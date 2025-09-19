from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator, Iterable, Optional

import aiosqlite


@dataclass(slots=True)
class Event:
    id: int
    user_id: int
    title: str
    start_time: datetime
    duration_minutes: int
    remind_before: int
    remind_at: datetime
    reminded: bool
    telegram_id: int | None = None

    @property
    def end_time(self) -> datetime:
        return self.start_time + timedelta(minutes=self.duration_minutes)


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._lock:
            db = await aiosqlite.connect(self._path)
            try:
                db.row_factory = aiosqlite.Row
                await db.execute("PRAGMA foreign_keys = ON")
                yield db
            finally:
                await db.close()

    async def init_models(self) -> None:
        async with self.connect() as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL UNIQUE,
                    timezone TEXT NOT NULL DEFAULT 'UTC',
                    reminder_default INTEGER NOT NULL DEFAULT 15,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    remind_before INTEGER NOT NULL,
                    remind_at TEXT NOT NULL,
                    reminded INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            await db.commit()

    async def ensure_user(self, telegram_id: int) -> int:
        async with self.connect() as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (telegram_id, created_at) VALUES (?, ?)",
                (telegram_id, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()
            async with db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("Failed to create user")
                return int(row[0])

    async def get_user(self, telegram_id: int) -> Optional[aiosqlite.Row]:
        async with self.connect() as db:
            async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                return await cursor.fetchone()

    async def update_user(self, telegram_id: int, *, timezone_name: Optional[str] = None, reminder_default: Optional[int] = None) -> None:
        fields = []
        values: list[object] = []
        if timezone_name is not None:
            fields.append("timezone = ?")
            values.append(timezone_name)
        if reminder_default is not None:
            fields.append("reminder_default = ?")
            values.append(reminder_default)
        if not fields:
            return
        values.append(telegram_id)
        async with self.connect() as db:
            await db.execute(f"UPDATE users SET {', '.join(fields)} WHERE telegram_id = ?", values)
            await db.commit()

    async def add_event(
        self,
        telegram_id: int,
        title: str,
        start_time: datetime,
        duration_minutes: int,
        remind_before: int,
    ) -> int:
        if start_time.tzinfo is None:
            raise ValueError("start_time must be timezone-aware")
        start_time = start_time.astimezone(timezone.utc)
        remind_at = start_time - timedelta(minutes=remind_before)
        user_id = await self.ensure_user(telegram_id)
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO events (user_id, title, start_time, duration_minutes, remind_before, remind_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    title,
                    start_time.isoformat(),
                    duration_minutes,
                    remind_before,
                    remind_at.isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()
            return cursor.lastrowid

    async def list_events(
        self, telegram_id: int, *, reminded: Optional[bool] = None
    ) -> list[Event]:
        async with self.connect() as db:
            conditions = ["u.telegram_id = ?"]
            values: list[object] = [telegram_id]
            if reminded is not None:
                conditions.append("e.reminded = ?")
                values.append(1 if reminded else 0)
            query = (
                " "
                """
                SELECT e.*, u.telegram_id as telegram_id FROM events e
                JOIN users u ON u.id = e.user_id
                WHERE {conditions}
                ORDER BY e.start_time ASC
                """
            ).format(conditions=" AND ".join(conditions))
            async with db.execute(query, values) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def get_next_event(self, telegram_id: int) -> Optional[Event]:
        async with self.connect() as db:
            now_iso = datetime.now(timezone.utc).isoformat()
            query = """
                SELECT e.*, u.telegram_id as telegram_id FROM events e
                JOIN users u ON u.id = e.user_id
                WHERE u.telegram_id = ? AND e.reminded = 0 AND e.start_time >= ?
                ORDER BY e.start_time ASC
                LIMIT 1
            """
            async with db.execute(query, (telegram_id, now_iso)) as cursor:
                row = await cursor.fetchone()
        return self._row_to_event(row) if row else None

    async def get_event(self, telegram_id: int, event_id: int) -> Optional[Event]:
        async with self.connect() as db:
            query = """
                SELECT e.*, u.telegram_id as telegram_id FROM events e
                JOIN users u ON u.id = e.user_id
                WHERE u.telegram_id = ? AND e.id = ?
            """
            async with db.execute(query, (telegram_id, event_id)) as cursor:
                row = await cursor.fetchone()
        return self._row_to_event(row) if row else None

    async def delete_event(self, telegram_id: int, event_id: int) -> None:
        async with self.connect() as db:
            query = """
                DELETE FROM events
                WHERE id = (
                    SELECT e.id FROM events e
                    JOIN users u ON u.id = e.user_id
                    WHERE u.telegram_id = ? AND e.id = ?
                )
            """
            await db.execute(query, (telegram_id, event_id))
            await db.commit()

    async def get_due_reminders(self, now: datetime) -> list[Event]:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        async with self.connect() as db:
            query = """
                SELECT e.*, u.telegram_id as telegram_id FROM events e
                JOIN users u ON u.id = e.user_id
                WHERE e.reminded = 0 AND e.remind_at <= ?
            """
            async with db.execute(query, (now.astimezone(timezone.utc).isoformat(),)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def mark_reminded(self, event_ids: Iterable[int]) -> None:
        ids = list(event_ids)
        if not ids:
            return
        placeholders = ", ".join("?" for _ in ids)
        async with self.connect() as db:
            await db.execute(f"UPDATE events SET reminded = 1 WHERE id IN ({placeholders})", ids)
            await db.commit()

    def _row_to_event(self, row: aiosqlite.Row) -> Event:
        keys = row.keys()
        telegram_id = None
        if "telegram_id" in keys and row["telegram_id"] is not None:
            telegram_id = int(row["telegram_id"])
        return Event(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            title=str(row["title"]),
            start_time=datetime.fromisoformat(row["start_time"]).replace(tzinfo=timezone.utc),
            duration_minutes=int(row["duration_minutes"]),
            remind_before=int(row["remind_before"]),
            remind_at=datetime.fromisoformat(row["remind_at"]).replace(tzinfo=timezone.utc),
            reminded=bool(row["reminded"]),
            telegram_id=telegram_id,
        )


__all__ = ["Database", "Event"]
