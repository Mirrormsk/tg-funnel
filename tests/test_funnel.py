from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from app.config import FunnelConfig
from app.db import Database
from app.scheduler import Scheduler


class FakeBot:
    def __init__(self, blocked: frozenset[int] = frozenset(), rate_limited: bool = False) -> None:
        self.sent: list[tuple[int, str]] = []
        self.blocked = blocked
        self.rate_limited = rate_limited

    async def send_message(self, chat_id: int, text: str) -> None:
        method = SendMessage(chat_id=chat_id, text=text)
        if chat_id in self.blocked:
            raise TelegramForbiddenError(method, "bot was blocked by the user")
        if self.rate_limited:
            raise TelegramRetryAfter(method, "Too Many Requests", retry_after=30)
        self.sent.append((chat_id, text))


async def test_messages_go_out_on_schedule(db: Database, cfg: FunnelConfig) -> None:
    await db.upsert_user(1, "ivan", "Иван", now=1000)
    assert await db.register_phone(1, "+79990001122", cfg.schedule, now=1000)

    bot = FakeBot()
    sched = Scheduler(bot, db)
    assert await sched.tick(now=1005) == 0  # рано
    assert await sched.tick(now=1010) == 1  # +10 сек
    assert await sched.tick(now=1030) == 0
    assert await sched.tick(now=1060) == 1  # +1 мин
    assert [text for _, text in bot.sent] == [s.text for s in cfg.schedule]
    assert await sched.tick(now=5000) == 0  # повторно не шлём


async def test_queue_survives_restart(db: Database, cfg: FunnelConfig) -> None:
    await db.upsert_user(1, None, "Иван", now=1000)
    await db.register_phone(1, "+79990001122", cfg.schedule, now=1000)
    # «Перезапуск»: новый планировщик поверх той же БД отправляет всё просроченное
    assert await Scheduler(FakeBot(), db).tick(now=9999) == len(cfg.schedule)


async def test_repeat_phone_does_not_duplicate_chain(db: Database, cfg: FunnelConfig) -> None:
    await db.upsert_user(1, None, "Иван", now=1000)
    assert await db.register_phone(1, "+79990001122", cfg.schedule, now=1000)
    assert not await db.register_phone(1, "+79990001122", cfg.schedule, now=1100)
    stats = await db.stats(cfg.schedule, "Europe/Moscow", now=1200)
    assert stats["queue"]["pending"] == len(cfg.schedule)


async def test_blocked_user_marked_failed(db: Database, cfg: FunnelConfig) -> None:
    await db.upsert_user(2, None, "Петр", now=1000)
    await db.register_phone(2, "+79990003344", cfg.schedule, now=1000)
    await Scheduler(FakeBot(blocked=frozenset({2})), db).tick(now=2000)
    stats = await db.stats(cfg.schedule, "Europe/Moscow", now=2000)
    assert stats["queue"] == {"pending": 0, "sent": 0, "failed": 2}


async def test_rate_limit_postpones_instead_of_dropping(db: Database, cfg: FunnelConfig) -> None:
    await db.upsert_user(3, None, "Олег", now=1000)
    await db.register_phone(3, "+79990005566", cfg.schedule, now=1000)
    assert await Scheduler(FakeBot(rate_limited=True), db).tick(now=2000) == 0
    stats = await db.stats(cfg.schedule, "Europe/Moscow", now=2000)
    assert stats["queue"]["pending"] == len(cfg.schedule)


async def test_stats(db: Database, cfg: FunnelConfig) -> None:
    now = 1_760_000_000
    for uid in range(1, 5):
        await db.upsert_user(uid, f"user{uid}", f"User{uid}", now=now)
    await db.register_phone(1, "+79991234567", cfg.schedule, now=now)
    await db.register_phone(2, "+79997654321", cfg.schedule, now=now)
    await Scheduler(FakeBot(), db).tick(now=now + 15)

    s = await db.stats(cfg.schedule, "Europe/Moscow", now=now + 20)
    assert s["totals"] == {"started": 4, "phone": 2, "conversion": 50.0}
    assert [f["count"] for f in s["funnel"]] == [4, 2, 2, 0]
    assert s["daily"][-1] == {"day": s["daily"][-1]["day"], "started": 4, "phone": 2}
    assert len(s["daily"]) == 14
    phones = {u["phone"] for u in s["recent"]}
    assert "+79991234567" not in phones  # телефоны в дашборде маскируются
    assert "+7999•••••67" in phones
