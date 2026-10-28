import time

from aiogram import F, Router, html
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from app.config import FunnelConfig, Settings
from app.db import Database

router = Router()
# Воронка работает только в личных сообщениях
router.message.filter(F.chat.type == "private")


def phone_keyboard(cfg: FunnelConfig) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=cfg.messages.phone_button, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def normalize_phone(phone: str) -> str:
    return phone if phone.startswith("+") else f"+{phone}"


@router.message(CommandStart())
async def on_start(message: Message, cfg: FunnelConfig, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.upsert_user(user.id, user.username, user.first_name, time.time())
    await message.answer(cfg.messages.greeting.format(name=html.quote(user.first_name or "друг")))

    if await db.has_phone(user.id):
        await message.answer(cfg.messages.already_registered, reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer(cfg.messages.phone_request, reply_markup=phone_keyboard(cfg))


@router.message(F.contact)
async def on_contact(message: Message, cfg: FunnelConfig, db: Database) -> None:
    user, contact = message.from_user, message.contact
    if user is None or contact is None:
        return
    # Через «Прикрепить → Контакт» можно отправить чужой номер — такие не принимаем
    if contact.user_id != user.id:
        await message.answer(cfg.messages.not_own_contact, reply_markup=phone_keyboard(cfg))
        return

    now = time.time()
    await db.upsert_user(user.id, user.username, user.first_name, now)
    registered = await db.register_phone(user.id, normalize_phone(contact.phone_number), cfg.schedule, now)
    text = cfg.messages.phone_received if registered else cfg.messages.already_registered
    await message.answer(text, reply_markup=ReplyKeyboardRemove())


@router.message(Command("stats"))
async def on_stats(message: Message, settings: Settings) -> None:
    user = message.from_user
    if user is None or (settings.admin_ids and user.id not in settings.admin_ids):
        return
    if settings.webapp_url is None:
        await message.answer("WEBAPP_URL не задан в .env — дашборду нужен HTTPS-адрес.")
        return
    button = InlineKeyboardButton(text="Открыть дашборд", web_app=WebAppInfo(url=str(settings.webapp_url)))
    await message.answer("📊 Статистика воронки", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]))


@router.message()
async def on_other(message: Message, cfg: FunnelConfig, db: Database) -> None:
    if message.from_user and not await db.has_phone(message.from_user.id):
        await message.answer(cfg.messages.remind_phone, reply_markup=phone_keyboard(cfg))
