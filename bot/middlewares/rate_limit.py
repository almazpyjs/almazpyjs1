from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any, Callable, Dict, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, limit_per_user: float = 0.5) -> None:
        super().__init__()
        self.limit_per_user = limit_per_user
        self._user_timestamps: Dict[int, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            telegram_id = event.from_user.id
            async with self._lock:
                now = time.monotonic()
                if now - self._user_timestamps[telegram_id] < self.limit_per_user:
                    return
                self._user_timestamps[telegram_id] = now
        return await handler(event, data)


__all__ = ["RateLimitMiddleware"]
