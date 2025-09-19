from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(slots=True)
class Settings:
    bot_token: str
    database_path: Path = Path("calendar.db")
    reminder_interval_seconds: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN")
        if not token:
            raise RuntimeError("BOT_TOKEN environment variable must be set")
        db_path = Path(os.getenv("DATABASE_PATH", "calendar.db"))
        interval = int(os.getenv("REMINDER_INTERVAL", "30"))
        return cls(bot_token=token, database_path=db_path, reminder_interval_seconds=interval)


settings = Settings.from_env()
