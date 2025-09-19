from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.storage.memory import MemoryStorage

from .config import settings
from .database import Database, Event
from .handlers.main import router
from .middlewares.rate_limit import RateLimitMiddleware
from .services.reminders import ReminderService
from .utils.datetime import apply_timezone


async def send_reminder(bot: Bot, database: Database, event: Event) -> None:
    if event.telegram_id is None:
        return
    user = await database.get_user(event.telegram_id)
    tz_name = user["timezone"] if user else "UTC"
    start_local = apply_timezone(event.start_time, tz_name)
    text = (
        "⏰ Напоминание!\n"
        f"{event.title}\n"
        f"Начало: {start_local.strftime('%d.%m.%Y %H:%M')}"
    )
    try:
        await bot.send_message(event.telegram_id, text)
    except (TelegramBadRequest, TelegramForbiddenError):
        # Пользователь мог заблокировать бота – пропускаем напоминание
        pass


async def main() -> None:
    storage = MemoryStorage()
    bot = Bot(token=settings.bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=storage)
    database = Database(settings.database_path)
    await database.init_models()
    dp.include_router(router)
    dp.update.outer_middleware(RateLimitMiddleware())
    dp["database"] = database

    reminder_service = ReminderService(
        database=database,
        callback=lambda event: send_reminder(bot, database, event),
        interval_seconds=settings.reminder_interval_seconds,
    )
    reminder_service.start()

    try:
        await dp.start_polling(bot)
    finally:
        await reminder_service.stop()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
