from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Iterable, Literal
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..database import Database, Event
from ..keyboards.main import (
    CALENDAR_DISABLED_CALLBACK,
    CALENDAR_IGNORE_CALLBACK,
    CalendarData,
    calendar_keyboard,
    available_time_options,
    duration_keyboard,
    event_actions_keyboard,
    events_keyboard,
    main_menu,
    reminder_keyboard,
    settings_keyboard,
    time_keyboard,
)
from ..states import CreateEvent, SettingsState
from ..utils.datetime import (
    apply_timezone,
    aware_utc,
    format_timedelta,
    parse_duration,
    parse_time,
    validate_timezone,
)


router = Router()


def _format_event(event: Event, tz_name: str) -> str:
    start_local = apply_timezone(event.start_time, tz_name)
    end_local = apply_timezone(event.end_time, tz_name)
    reminder_text = "без напоминания" if event.remind_before == 0 else f"за {event.remind_before} мин"
    status_text = (
        "🟢 Напоминание запланировано" if not event.reminded else "✅ Напоминание отправлено"
    )
    return (
        f"📌 <b>{event.title}</b>\n"
        f"🗓 {start_local.strftime('%d.%m.%Y')} {start_local.strftime('%H:%M')} — {end_local.strftime('%H:%M')}\n"
        f"⏱ {format_timedelta(event.duration_minutes)}\n"
        f"🔔 Напоминание: {reminder_text}\n"
        f"{status_text}"
    )


def _events_overview(
    events: Iterable[Event], tz_name: str, empty_text: str
) -> str:
    lines = []
    for idx, event in enumerate(events, start=1):
        start_local = apply_timezone(event.start_time, tz_name)
        lines.append(
            f"{idx}. {start_local.strftime('%d.%m %H:%M')} — {event.title}"
        )
    return "\n".join(lines) if lines else empty_text


def _build_events_keyboard(
    events: Iterable[Event], view: str
) -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    for event in events:
        keyboard.button(text=event.title[:32], callback_data=f"event:{event.id}:view")
    if events:
        keyboard.adjust(1)
    keyboard.attach(events_keyboard(view))
    keyboard.button(text="Назад", callback_data="menu:root")
    keyboard.adjust(1)
    return keyboard


EventView = Literal["active", "history"]

EVENT_HEADERS: dict[EventView, str] = {
    "active": "Активные напоминания:",
    "history": "Прошедшие напоминания:",
}

EVENT_EMPTY_TEXT: dict[EventView, str] = {
    "active": "Пока нет активных напоминаний.",
    "history": "Прошедшие напоминания пока отсутствуют.",
}


async def _get_user_timezone(database: Database, telegram_id: int) -> str:
    user = await database.get_user(telegram_id)
    return user["timezone"] if user else "UTC"


async def _events_payload(
    database: Database, telegram_id: int, view: EventView
) -> tuple[str, list[Event], str]:
    tz_name = await _get_user_timezone(database, telegram_id)
    events = await database.list_events(telegram_id, reminded=view == "history")
    body = _events_overview(events, tz_name, EVENT_EMPTY_TEXT[view])
    text = f"{EVENT_HEADERS[view]}\n{body}"
    return text, events, tz_name


async def _send_next_event(
    target: Message | CallbackQuery, database: Database
) -> None:
    user_id = target.from_user.id if isinstance(target, Message) else target.from_user.id
    event = await database.get_next_event(user_id)
    if event:
        tz_name = await _get_user_timezone(database, user_id)
        text = "Ближайшее событие:\n" + _format_event(event, tz_name)
        markup = event_actions_keyboard(event.id).as_markup()
    else:
        text = "Ближайших событий нет. Создайте новое напоминание."
        markup = main_menu().as_markup()
    if isinstance(target, Message):
        await target.answer(text, reply_markup=markup)
    else:
        await target.message.edit_text(text, reply_markup=markup)


def _export_json_payload(events: Iterable[Event], tz_name: str) -> str:
    return json.dumps(
        [
            {
                "id": event.id,
                "title": event.title,
                "start": apply_timezone(event.start_time, tz_name).isoformat(),
                "duration": event.duration_minutes,
                "remind_before": event.remind_before,
            }
            for event in events
        ],
        ensure_ascii=False,
        indent=2,
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, database: Database) -> None:
    await state.clear()
    await database.ensure_user(message.from_user.id)
    text = (
        "👋 Привет! Я календарь-бот. Помогу планировать события, напоминать о них и делать экспорт."\
        "\nИспользуйте кнопки меню ниже или команды: /new, /events, /next, /export, /settings."
    )
    await message.answer(text, reply_markup=main_menu().as_markup())


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CreateEvent.waiting_for_title)
    await message.answer(
        "Давайте создадим событие. Напишите название (это поле можно ввести полностью вручную)."
    )


@router.message(Command("events"))
async def cmd_events(message: Message, database: Database) -> None:
    text, events, _ = await _events_payload(database, message.from_user.id, "active")
    await message.answer(
        text, reply_markup=_build_events_keyboard(events, "active").as_markup()
    )


@router.message(Command("next"))
async def cmd_next(message: Message, database: Database) -> None:
    await _send_next_event(message, database)


@router.message(Command("export"))
async def cmd_export(message: Message, database: Database) -> None:
    events = await database.list_events(message.from_user.id, reminded=False)
    if not events:
        await message.answer("Нет событий для экспорта.")
        return
    tz_name = await _get_user_timezone(database, message.from_user.id)
    overview = _events_overview(events, tz_name, EVENT_EMPTY_TEXT["active"])
    keyboard = InlineKeyboardBuilder()
    keyboard.attach(events_keyboard("active"))
    keyboard.button(text="Назад", callback_data="menu:root")
    keyboard.adjust(1)
    await message.answer(
        overview + "\n\nВыберите формат экспорта:",
        reply_markup=keyboard.as_markup(),
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, database: Database) -> None:
    user = await database.get_user(message.from_user.id)
    tz_name = user["timezone"] if user else "UTC"
    default_reminder = int(user["reminder_default"]) if user else 15
    text = (
        f"Текущий часовой пояс: <b>{tz_name}</b>\n"
        f"Напоминание по умолчанию: {default_reminder} минут\n\n"
        "Выберите часовой пояс или напоминание по умолчанию:"
    )
    await message.answer(
        text, reply_markup=settings_keyboard(default_reminder).as_markup()
    )


@router.callback_query(F.data == "menu:create")
async def menu_create(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CreateEvent.waiting_for_title)
    await callback.message.answer("Напишите название события.")
    await callback.answer()


@router.callback_query(F.data == "menu:list")
async def menu_list(callback: CallbackQuery, database: Database) -> None:
    text, events, _ = await _events_payload(database, callback.from_user.id, "active")
    await callback.message.edit_text(
        text, reply_markup=_build_events_keyboard(events, "active").as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "menu:next")
async def menu_next(callback: CallbackQuery, database: Database) -> None:
    await _send_next_event(callback, database)
    await callback.answer()


@router.callback_query(F.data == "menu:export")
async def menu_export(callback: CallbackQuery, database: Database) -> None:
    events = await database.list_events(callback.from_user.id, reminded=False)
    if not events:
        await callback.answer("Нет событий для экспорта", show_alert=True)
        return
    tz_name = await _get_user_timezone(database, callback.from_user.id)
    overview = _events_overview(events, tz_name, EVENT_EMPTY_TEXT["active"])
    keyboard = InlineKeyboardBuilder()
    keyboard.attach(events_keyboard("active"))
    keyboard.button(text="Назад", callback_data="menu:root")
    keyboard.adjust(1)
    await callback.message.edit_text(
        overview + "\n\nВыберите формат экспорта:",
        reply_markup=keyboard.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:settings")
async def menu_settings(callback: CallbackQuery, database: Database) -> None:
    user = await database.get_user(callback.from_user.id)
    tz_name = user["timezone"] if user else "UTC"
    default_reminder = int(user["reminder_default"]) if user else 15
    text = (
        f"Настройки пользователя\n"
        f"Часовой пояс: <b>{tz_name}</b>\n"
        f"Напоминание по умолчанию: {default_reminder} минут\n\n"
        "Выберите часовой пояс или напоминание по умолчанию:"
    )
    await callback.message.edit_text(
        text, reply_markup=settings_keyboard(default_reminder).as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "menu:root")
async def menu_root(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Главное меню", reply_markup=main_menu().as_markup())
    await callback.answer()


@router.message(CreateEvent.waiting_for_title)
async def process_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым.")
        return
    await state.update_data(title=title)
    await state.set_state(CreateEvent.waiting_for_date)
    today = date.today()
    await message.answer(
        "Выберите дату:", reply_markup=calendar_keyboard(today).as_markup()
    )


@router.callback_query(CreateEvent.waiting_for_date, F.data == "calendar_today")
async def calendar_today(
    callback: CallbackQuery, state: FSMContext, database: Database
) -> None:
    today = date.today()
    await state.update_data(date=today.isoformat())
    await state.set_state(CreateEvent.waiting_for_time)
    await callback.message.edit_reply_markup(calendar_keyboard(today).as_markup())
    await prompt_time(callback, today, database)
    await callback.answer("Дата выбрана")


@router.callback_query(CreateEvent.waiting_for_date, F.data.startswith("calendar_prev"))
async def calendar_prev(callback: CallbackQuery, state: FSMContext) -> None:
    data = CalendarData.unpack(callback.data)
    target = date(year=data.year, month=data.month, day=1)
    min_month = date.today().replace(day=1)
    alert_text = None
    if target < min_month:
        target = date.today()
        alert_text = "Прошедшие месяцы недоступны"
    await callback.message.edit_reply_markup(calendar_keyboard(target).as_markup())
    await callback.answer(alert_text, show_alert=alert_text is not None)


@router.callback_query(CreateEvent.waiting_for_date, F.data.startswith("calendar_next"))
async def calendar_next(callback: CallbackQuery, state: FSMContext) -> None:
    data = CalendarData.unpack(callback.data)
    target = date(year=data.year, month=data.month, day=1)
    await callback.message.edit_reply_markup(calendar_keyboard(target).as_markup())
    await callback.answer()


@router.callback_query(CreateEvent.waiting_for_date, F.data.startswith("calendar:"))
async def calendar_select(
    callback: CallbackQuery, state: FSMContext, database: Database
) -> None:
    data = CalendarData.unpack(callback.data)
    chosen_date = date(year=data.year, month=data.month, day=data.day or 1)
    if chosen_date < date.today():
        target = chosen_date.replace(day=1)
        today = date.today().replace(day=1)
        if target < today:
            target = date.today()
        await callback.message.edit_reply_markup(
            calendar_keyboard(target).as_markup()
        )
        await callback.answer("Нельзя выбрать прошедшую дату", show_alert=True)
        return
    await state.update_data(date=chosen_date.isoformat())
    await state.set_state(CreateEvent.waiting_for_time)
    await prompt_time(callback, chosen_date, database)
    await callback.answer()


@router.callback_query(F.data == CALENDAR_IGNORE_CALLBACK)
@router.callback_query(F.data == "noop")
async def calendar_ignore(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == CALENDAR_DISABLED_CALLBACK)
async def calendar_disabled(callback: CallbackQuery) -> None:
    await callback.answer("Нельзя выбрать прошедшую дату", show_alert=True)


@router.callback_query(CreateEvent.waiting_for_time, F.data.startswith("time:"))
async def time_selected(
    callback: CallbackQuery, state: FSMContext, database: Database
) -> None:
    value = callback.data.split(":", maxsplit=1)[1]
    if value == "custom":
        await callback.message.answer("Введите время в формате ЧЧ:ММ")
        await callback.answer()
        return
    result = parse_time(value)
    if result is None:
        await callback.answer("Неверное время", show_alert=True)
        return
    data = await state.get_data()
    date_str = data.get("date")
    if not date_str:
        await callback.answer("Сначала выберите дату", show_alert=True)
        return
    selected_date = date.fromisoformat(date_str)
    is_valid, error = await _validate_time_selection(
        database, callback.from_user.id, selected_date, result
    )
    if not is_valid:
        await callback.answer(error or "Нельзя выбрать прошедшее время", show_alert=True)
        return
    await state.update_data(time=result.strftime("%H:%M"))
    await state.set_state(CreateEvent.waiting_for_duration)
    await callback.message.answer(
        "Выберите продолжительность:", reply_markup=duration_keyboard().as_markup()
    )
    await callback.answer()


@router.message(CreateEvent.waiting_for_time)
async def custom_time(message: Message, state: FSMContext, database: Database) -> None:
    result = parse_time(message.text or "")
    if result is None:
        await message.answer("Не удалось распознать время, используйте формат ЧЧ:ММ")
        return
    data = await state.get_data()
    date_str = data.get("date")
    if not date_str:
        await message.answer("Сначала выберите дату с помощью календаря")
        return
    selected_date = date.fromisoformat(date_str)
    is_valid, error = await _validate_time_selection(
        database, message.from_user.id, selected_date, result
    )
    if not is_valid:
        await message.answer(error or "Нельзя выбрать прошедшее время. Попробуйте снова.")
        return
    await state.update_data(time=result.strftime("%H:%M"))
    await state.set_state(CreateEvent.waiting_for_duration)
    await message.answer(
        "Выберите продолжительность:", reply_markup=duration_keyboard().as_markup()
    )


@router.callback_query(CreateEvent.waiting_for_duration, F.data.startswith("duration:"))
async def duration_selected(callback: CallbackQuery, state: FSMContext, database: Database) -> None:
    value = callback.data.split(":", maxsplit=1)[1]
    if value == "custom":
        await state.set_state(CreateEvent.waiting_for_custom_duration)
        await callback.message.answer("Введите длительность (например, 90 или 1h30m)")
        await callback.answer()
        return
    minutes = int(value)
    await state.update_data(duration=str(minutes))
    await state.set_state(CreateEvent.waiting_for_reminder)
    await prompt_reminder(callback, database)
    await callback.answer()


@router.message(CreateEvent.waiting_for_custom_duration)
async def custom_duration(message: Message, state: FSMContext, database: Database) -> None:
    value = parse_duration(message.text or "")
    if value is None or value <= 0:
        await message.answer("Не удалось распознать длительность. Попробуйте ещё раз.")
        return
    await state.update_data(duration=str(value))
    await state.set_state(CreateEvent.waiting_for_reminder)
    await prompt_reminder(message, database)


async def prompt_time(
    event_source: Message | CallbackQuery, selected_date: date, database: Database
) -> None:
    user_id = (
        event_source.from_user.id
        if isinstance(event_source, Message)
        else event_source.from_user.id
    )
    tz_name = await _get_user_timezone(database, user_id)
    options = available_time_options(selected_date, tz_name)
    markup = time_keyboard(selected_date, tz_name, options).as_markup()
    if options:
        text = "Выберите время:"
    else:
        text = (
            "Свободных быстрых вариантов на выбранный день нет. "
            "Нажмите «Свое время» и укажите его вручную."
        )
    if isinstance(event_source, Message):
        await event_source.answer(text, reply_markup=markup)
    else:
        await event_source.message.answer(text, reply_markup=markup)


async def _validate_time_selection(
    database: Database,
    telegram_id: int,
    selected_date: date,
    selected_time: time,
) -> tuple[bool, str | None]:
    tz_name = await _get_user_timezone(database, telegram_id)
    now_local = datetime.now(ZoneInfo(tz_name))
    today_local = now_local.date()
    if selected_date < today_local:
        return False, "Нельзя выбрать прошедшее время"
    if selected_date == today_local:
        current_time = now_local.time().replace(second=0, microsecond=0)
        if selected_time <= current_time:
            return (
                False,
                "Это время уже прошло. Выберите более поздний вариант.",
            )
    return True, None


async def prompt_reminder(event_source: Message | CallbackQuery, database: Database) -> None:
    default_reminder = 15
    user = await database.get_user(event_source.from_user.id)
    if user:
        default_reminder = int(user["reminder_default"])
    markup = reminder_keyboard(default_reminder).as_markup()
    if isinstance(event_source, Message):
        await event_source.answer("Выберите напоминание:", reply_markup=markup)
    else:
        await event_source.message.answer("Выберите напоминание:", reply_markup=markup)


@router.callback_query(CreateEvent.waiting_for_reminder, F.data.startswith("reminder:"))
async def reminder_selected(callback: CallbackQuery, state: FSMContext, database: Database) -> None:
    value = callback.data.split(":", maxsplit=1)[1]
    user = await database.get_user(callback.from_user.id)
    default_reminder = int(user["reminder_default"]) if user else 15
    if value == "default":
        minutes = default_reminder
    else:
        minutes = int(value)
    data = await state.get_data()
    await finish_event_creation(callback, state, minutes, data, database)


async def finish_event_creation(
    callback: CallbackQuery,
    state: FSMContext,
    reminder_minutes: int,
    data: dict,
    database: Database,
) -> None:
    title = data.get("title")
    date_str = data.get("date")
    time_str = data.get("time")
    duration_str = data.get("duration")
    if not all([title, date_str, time_str, duration_str]):
        await callback.answer("Не хватает данных. Попробуйте снова.", show_alert=True)
        await state.clear()
        return
    user = await database.get_user(callback.from_user.id)
    tz_name = user["timezone"] if user else "UTC"
    start_datetime = datetime.fromisoformat(f"{date_str}T{time_str}")
    start_utc = aware_utc(start_datetime, tz_name)
    duration_minutes = int(duration_str)
    await database.add_event(
        callback.from_user.id,
        title=title,
        start_time=start_utc,
        duration_minutes=duration_minutes,
        remind_before=reminder_minutes,
    )
    await state.clear()
    start_local = apply_timezone(start_utc, tz_name)
    summary = (
        f"Событие сохранено!\n{title}"
        f"\nДата: {start_local.strftime('%d.%m.%Y %H:%M')}"
        f"\nДлительность: {format_timedelta(duration_minutes)}"
        f"\nНапоминание: {'без напоминания' if reminder_minutes == 0 else f'за {reminder_minutes} минут'}"
    )
    await callback.message.answer(summary, reply_markup=main_menu().as_markup())
    await callback.answer("Запись создана")


@router.callback_query(F.data.startswith("event:"))
async def event_actions(callback: CallbackQuery, database: Database) -> None:
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer()
        return
    _, event_id_str, action = parts[:3]
    event_id = int(event_id_str)
    if action == "view":
        event = await database.get_event(callback.from_user.id, event_id)
        if not event:
            await callback.answer("Событие не найдено", show_alert=True)
            return
        user = await database.get_user(callback.from_user.id)
        tz_name = user["timezone"] if user else "UTC"
        await callback.message.edit_text(
            _format_event(event, tz_name),
            reply_markup=event_actions_keyboard(event.id).as_markup(),
        )
        await callback.answer()
    elif action == "delete":
        await database.delete_event(callback.from_user.id, event_id)
        await callback.message.edit_text(
            "Событие удалено.", reply_markup=main_menu().as_markup()
        )
        await callback.answer("Удалено")


@router.callback_query(F.data.startswith("events:"))
async def events_control(callback: CallbackQuery, database: Database) -> None:
    parts = callback.data.split(":")
    command = parts[1]
    if command == "view":
        view = parts[2] if len(parts) > 2 else "active"
        text, events, _ = await _events_payload(database, callback.from_user.id, view)
        await callback.message.edit_text(
            text, reply_markup=_build_events_keyboard(events, view).as_markup()
        )
        await callback.answer()
        return
    view = parts[2] if len(parts) > 2 else "active"
    text, events, tz_name = await _events_payload(
        database, callback.from_user.id, view
    )
    if command == "refresh":
        try:
            await callback.message.edit_text(
                text, reply_markup=_build_events_keyboard(events, view).as_markup()
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
        await callback.answer("Обновлено")
    elif command in {"export_txt", "export_json"}:
        if not events:
            await callback.answer("Нет данных", show_alert=True)
            return
        if command == "export_txt":
            await callback.message.answer(text)
        else:
            payload = _export_json_payload(events, tz_name)
            await callback.message.answer_document(
                BufferedInputFile(payload.encode("utf-8"), filename="events.json"),
                caption="Экспорт JSON",
            )
        await callback.answer()


@router.callback_query(F.data.startswith("tz:"))
async def timezone_change(callback: CallbackQuery, state: FSMContext, database: Database) -> None:
    value = callback.data.split(":", maxsplit=1)[1]
    if value == "custom":
        await state.set_state(SettingsState.waiting_for_timezone)
        await callback.message.answer("Введите название часового пояса, например Europe/Moscow")
        await callback.answer()
        return
    await database.update_user(callback.from_user.id, timezone_name=value)
    await callback.answer("Часовой пояс обновлён")


@router.message(SettingsState.waiting_for_timezone)
async def timezone_custom(message: Message, state: FSMContext, database: Database) -> None:
    tz_name = (message.text or "").strip()
    if not validate_timezone(tz_name):
        await message.answer("Не удалось распознать часовой пояс. Пример: Europe/Moscow")
        return
    await database.update_user(message.from_user.id, timezone_name=tz_name)
    await state.clear()
    await message.answer(f"Часовой пояс обновлён на {tz_name}", reply_markup=main_menu().as_markup())


@router.callback_query(F.data.startswith("settings_reminder:"))
async def settings_reminder(callback: CallbackQuery, database: Database) -> None:
    value = int(callback.data.split(":", maxsplit=1)[1])
    await database.update_user(callback.from_user.id, reminder_default=value)
    await callback.answer("Значение сохранено")


__all__ = ["router"]
