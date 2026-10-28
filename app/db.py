from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite

from app.config import ScheduledStep

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    phone       TEXT,
    started_at  REAL NOT NULL,
    phone_at    REAL
);

-- Очередь отложенных сообщений живёт в БД, а не в памяти:
-- после перезапуска бота ничего не теряется.
CREATE TABLE IF NOT EXISTS scheduled_messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(user_id),
    step_id   TEXT NOT NULL,
    text      TEXT NOT NULL,
    send_at   REAL NOT NULL,
    status    TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | failed
    sent_at   REAL,
    error     TEXT,
    UNIQUE (user_id, step_id)
);
CREATE INDEX IF NOT EXISTS idx_sched_due ON scheduled_messages(status, send_at);
"""


@dataclass(frozen=True)
class DueMessage:
    id: int
    user_id: int
    step_id: str
    text: str


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    return phone[:5] + "•" * (len(phone) - 7) + phone[-2:] if len(phone) > 8 else "•••"


class Database:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    @classmethod
    async def connect(cls, path: str) -> "Database":
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.executescript(SCHEMA)
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self.conn.close()

    async def upsert_user(self, user_id: int, username: str | None, first_name: str | None, now: float) -> None:
        await self.conn.execute(
            """INSERT INTO users (user_id, username, first_name, started_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username = excluded.username, first_name = excluded.first_name""",
            (user_id, username, first_name, now),
        )
        await self.conn.commit()

    async def has_phone(self, user_id: int) -> bool:
        async with self.conn.execute("SELECT phone FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        return bool(row and row["phone"])

    async def register_phone(self, user_id: int, phone: str, steps: list[ScheduledStep], now: float) -> bool:
        """Сохраняет телефон и ставит цепочку в очередь. False — пользователь уже был зарегистрирован."""
        cur = await self.conn.execute(
            "UPDATE users SET phone = ?, phone_at = ? WHERE user_id = ? AND phone IS NULL",
            (phone, now, user_id),
        )
        if cur.rowcount == 0:
            await self.conn.commit()
            return False
        await self.conn.executemany(
            "INSERT OR IGNORE INTO scheduled_messages (user_id, step_id, text, send_at) VALUES (?, ?, ?, ?)",
            [(user_id, s.id, s.text, now + s.delay_seconds) for s in steps],
        )
        await self.conn.commit()
        return True

    async def fetch_due(self, now: float, limit: int = 50) -> list[DueMessage]:
        async with self.conn.execute(
            """SELECT id, user_id, step_id, text FROM scheduled_messages
               WHERE status = 'pending' AND send_at <= ? ORDER BY send_at LIMIT ?""",
            (now, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [DueMessage(r["id"], r["user_id"], r["step_id"], r["text"]) for r in rows]

    async def mark_sent(self, message_id: int, now: float) -> None:
        await self.conn.execute(
            "UPDATE scheduled_messages SET status = 'sent', sent_at = ? WHERE id = ?", (now, message_id)
        )
        await self.conn.commit()

    async def mark_failed(self, message_id: int, error: str) -> None:
        await self.conn.execute(
            "UPDATE scheduled_messages SET status = 'failed', error = ? WHERE id = ?", (error[:500], message_id)
        )
        await self.conn.commit()

    async def postpone(self, message_id: int, send_at: float) -> None:
        await self.conn.execute("UPDATE scheduled_messages SET send_at = ? WHERE id = ?", (send_at, message_id))
        await self.conn.commit()

    async def stats(self, steps: list[ScheduledStep], tz: str, now: float, days: int = 14) -> dict[str, Any]:
        zone = ZoneInfo(tz)

        async with self.conn.execute("SELECT COUNT(*) AS started, COUNT(phone) AS phone FROM users") as cur:
            row = await cur.fetchone()
        totals = {"started": row["started"], "phone": row["phone"]} if row else {"started": 0, "phone": 0}

        async with self.conn.execute(
            "SELECT step_id, status, COUNT(*) AS n FROM scheduled_messages GROUP BY step_id, status"
        ) as cur:
            by_step: dict[str, dict[str, int]] = {}
            for r in await cur.fetchall():
                by_step.setdefault(r["step_id"], {})[r["status"]] = r["n"]

        funnel = [
            {"id": "start", "label": "Нажали /start", "count": totals["started"]},
            {"id": "phone", "label": "Оставили телефон", "count": totals["phone"]},
        ] + [
            {"id": s.id, "label": f"Получили «{s.title}»", "count": by_step.get(s.id, {}).get("sent", 0)} for s in steps
        ]

        queue = {"pending": 0, "sent": 0, "failed": 0}
        for counts in by_step.values():
            for status, n in counts.items():
                queue[status] = queue.get(status, 0) + n

        # Динамика по дням в часовом поясе заказчика
        today = datetime.fromtimestamp(now, zone).date()
        first_day = today - timedelta(days=days - 1)
        since = datetime.combine(first_day, datetime.min.time(), zone).timestamp()
        daily = {(first_day + timedelta(d)).isoformat(): {"started": 0, "phone": 0} for d in range(days)}
        async with self.conn.execute(
            "SELECT started_at, phone_at FROM users WHERE started_at >= ? OR phone_at >= ?", (since, since)
        ) as cur:
            for r in await cur.fetchall():
                for key, ts in (("started", r["started_at"]), ("phone", r["phone_at"])):
                    if ts and ts >= since:
                        day = datetime.fromtimestamp(ts, zone).date().isoformat()
                        if day in daily:
                            daily[day][key] += 1

        async with self.conn.execute(
            """SELECT u.user_id, u.username, u.first_name, u.phone, u.started_at, u.phone_at,
                      (SELECT COUNT(*) FROM scheduled_messages m
                        WHERE m.user_id = u.user_id AND m.status = 'sent') AS sent
               FROM users u ORDER BY u.started_at DESC LIMIT 10"""
        ) as cur:
            recent = [
                {
                    "name": r["first_name"],
                    "username": r["username"],
                    "phone": mask_phone(r["phone"]),
                    "started_at": r["started_at"],
                    "phone_at": r["phone_at"],
                    "messages_sent": r["sent"],
                    "messages_total": len(steps) if r["phone"] else 0,
                }
                for r in await cur.fetchall()
            ]

        started = totals["started"]
        return {
            "generated_at": now,
            "timezone": tz,
            "totals": {
                **totals,
                "conversion": round(totals["phone"] / started * 100, 1) if started else 0.0,
            },
            "funnel": funnel,
            "queue": queue,
            "daily": [{"day": d, **v} for d, v in daily.items()],
            "recent": recent,
        }
