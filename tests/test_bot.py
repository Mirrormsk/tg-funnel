"""Хендлеры вызываются напрямую: им нужны только from_user, contact и answer()."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove

from app import bot
from app.config import FunnelConfig, Settings
from app.db import Database

USER = SimpleNamespace(id=1, username="ivan", first_name="<Иван>")


def make_message(contact: SimpleNamespace | None = None) -> Any:
    return SimpleNamespace(from_user=USER, contact=contact, answer=AsyncMock())


def replies(message: Any) -> list[str]:
    return [c.args[0] for c in message.answer.await_args_list]


async def test_start_greets_and_asks_phone(db: Database, cfg: FunnelConfig) -> None:
    msg = make_message()
    await bot.on_start(msg, cfg, db)

    greeting, request = replies(msg)
    assert "&lt;Иван&gt;" in greeting  # имя экранировано для HTML
    assert request == cfg.messages.phone_request
    keyboard = msg.answer.await_args.kwargs["reply_markup"]
    assert isinstance(keyboard, ReplyKeyboardMarkup)
    assert keyboard.keyboard[0][0].request_contact


async def test_own_contact_registers_and_schedules(db: Database, cfg: FunnelConfig) -> None:
    msg = make_message(contact=SimpleNamespace(user_id=USER.id, phone_number="79991234567"))
    await bot.on_contact(msg, cfg, db)

    assert replies(msg) == [cfg.messages.phone_received]
    assert isinstance(msg.answer.await_args.kwargs["reply_markup"], ReplyKeyboardRemove)
    assert await db.has_phone(USER.id)
    stats = await db.stats(cfg.schedule, "Europe/Moscow", now=0)
    assert stats["queue"]["pending"] == len(cfg.schedule)


async def test_foreign_contact_rejected(db: Database, cfg: FunnelConfig) -> None:
    msg = make_message(contact=SimpleNamespace(user_id=999, phone_number="+70000000000"))
    await bot.on_contact(msg, cfg, db)

    assert replies(msg) == [cfg.messages.not_own_contact]
    assert not await db.has_phone(USER.id)


async def test_start_after_registration(db: Database, cfg: FunnelConfig) -> None:
    await db.upsert_user(USER.id, None, "Иван", now=0)
    await db.register_phone(USER.id, "+79991234567", cfg.schedule, now=0)
    msg = make_message()
    await bot.on_start(msg, cfg, db)
    assert replies(msg)[-1] == cfg.messages.already_registered


@pytest.mark.parametrize(("admins", "answered"), [(frozenset(), False), ({1}, True), ({2}, False)])
async def test_stats_command_access(admins: frozenset[int], answered: bool) -> None:
    settings = Settings(bot_token="1:x", webapp_url="https://demo.example", admin_ids=frozenset(admins))
    msg = make_message()
    await bot.on_stats(msg, settings)
    assert msg.answer.await_count == int(answered)


def test_normalize_phone() -> None:
    assert bot.normalize_phone("79991234567") == "+79991234567"
    assert bot.normalize_phone("+79991234567") == "+79991234567"
