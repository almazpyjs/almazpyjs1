from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from ..database import Database, Event


ReminderCallback = Callable[[Event], Awaitable[None]]


@dataclass(slots=True)
class ReminderService:
    database: Database
    callback: ReminderCallback
    interval_seconds: int = 30

    _task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._runner())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _runner(self) -> None:
        while True:
            try:
                await self.dispatch_due()
            except Exception as exc:  # pragma: no cover - logging placeholder
                # Use print as placeholder for logging in this context
                print(f"Reminder dispatch failed: {exc}")
            await asyncio.sleep(self.interval_seconds)

    async def dispatch_due(self) -> None:
        now = datetime.now(timezone.utc)
        events = await self.database.get_due_reminders(now)
        if not events:
            return
        for event in events:
            await self.callback(event)
        await self.database.mark_reminded(event.id for event in events)


__all__ = ["ReminderService"]
