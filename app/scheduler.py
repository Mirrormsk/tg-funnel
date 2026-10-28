import asyncio
import logging
import time
from typing import Protocol

from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from app.db import Database

log = logging.getLogger(__name__)


class MessageSender(Protocol):
    async def send_message(self, chat_id: int, text: str) -> object: ...


class Scheduler:
    """Раз в секунду забирает из БД сообщения, у которых наступило время, и отправляет их."""

    def __init__(self, bot: MessageSender, db: Database, poll_interval: float = 1.0):
        self.bot = bot
        self.db = db
        self.poll_interval = poll_interval

    async def run(self) -> None:
        log.info("Планировщик запущен")
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("Ошибка планировщика")
            await asyncio.sleep(self.poll_interval)

    async def tick(self, now: float | None = None) -> int:
        sent = 0
        for msg in await self.db.fetch_due(now or time.time()):
            try:
                await self.bot.send_message(msg.user_id, msg.text)
            except TelegramRetryAfter as e:
                # Упёрлись в лимиты Telegram — переносим, а не теряем
                await self.db.postpone(msg.id, time.time() + e.retry_after)
                log.warning("Rate limit, перенос сообщения %s на %s с", msg.id, e.retry_after)
                continue
            except TelegramAPIError as e:
                # Например, пользователь заблокировал бота — повторять бессмысленно
                await self.db.mark_failed(msg.id, str(e))
                log.warning("Не доставлено %s → %s: %s", msg.step_id, msg.user_id, e)
                continue
            await self.db.mark_sent(msg.id, time.time())
            log.info("Отправлено %s → %s", msg.step_id, msg.user_id)
            sent += 1
        return sent
