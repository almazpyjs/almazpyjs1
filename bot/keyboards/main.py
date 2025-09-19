from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import calendar

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


@dataclass(slots=True)
class CalendarData:
    action: str
    year: int
    month: int
    day: int | None = None

    def pack(self) -> str:
        parts = [self.action, str(self.year), str(self.month)]
        if self.day is not None:
            parts.append(str(self.day))
        return ":".join(parts)

    @classmethod
    def unpack(cls, data: str) -> "CalendarData":
        action, year, month, *rest = data.split(":")
        day = int(rest[0]) if rest else None
        return cls(action=action, year=int(year), month=int(month), day=day)


def main_menu() -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Создать событие", callback_data="menu:create")
    keyboard.button(text="Мои события", callback_data="menu:list")
    keyboard.button(text="Экспорт", callback_data="menu:export")
    keyboard.button(text="Настройки", callback_data="menu:settings")
    keyboard.adjust(2)
    return keyboard


def timezone_keyboard() -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="UTC", callback_data="tz:UTC")
    keyboard.button(text="Европа/Москва", callback_data="tz:Europe/Moscow")
    keyboard.button(text="Азия/Алматы", callback_data="tz:Asia/Almaty")
    keyboard.button(text="Свой вариант", callback_data="tz:custom")
    keyboard.adjust(2)
    return keyboard


def reminder_default_keyboard(current: int) -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    for minutes in (5, 10, 15, 30, 60, 120):
        label = f"За {minutes} мин"
        if minutes == current:
            label = "✅ " + label
        keyboard.button(text=label, callback_data=f"settings_reminder:{minutes}")
    keyboard.button(text="Отключить", callback_data="settings_reminder:0")
    keyboard.adjust(2)
    return keyboard


def settings_keyboard(current: int) -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.attach(timezone_keyboard())
    keyboard.attach(reminder_default_keyboard(current))
    keyboard.row(InlineKeyboardButton(text="Назад", callback_data="menu:root"))
    return keyboard


def calendar_keyboard(target_date: date) -> InlineKeyboardBuilder:
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(target_date.year, target_date.month)
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text=target_date.strftime("%B %Y"), callback_data="noop"),
    )
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.row(*[InlineKeyboardButton(text=day, callback_data="noop") for day in week_days])
    for week in month_days:
        buttons = []
        for day in week:
            if day == 0:
                buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                data = CalendarData("calendar", target_date.year, target_date.month, day).pack()
                buttons.append(InlineKeyboardButton(text=str(day), callback_data=data))
        keyboard.row(*buttons)
    prev_month = (target_date.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (target_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    keyboard.row(
        InlineKeyboardButton(
            text="<", callback_data=CalendarData("calendar_prev", prev_month.year, prev_month.month).pack()
        ),
        InlineKeyboardButton(text="Сегодня", callback_data="calendar_today"),
        InlineKeyboardButton(
            text=">", callback_data=CalendarData("calendar_next", next_month.year, next_month.month).pack()
        ),
    )
    return keyboard


def time_keyboard() -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    for value in ("08:00", "10:00", "13:00", "15:00", "18:00", "21:00"):
        keyboard.button(text=value, callback_data=f"time:{value}")
    keyboard.button(text="Свое время", callback_data="time:custom")
    keyboard.adjust(3)
    return keyboard


def duration_keyboard() -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    options = [
        ("30 минут", "30"),
        ("1 час", "60"),
        ("2 часа", "120"),
        ("Кастом", "custom"),
    ]
    for text, value in options:
        keyboard.button(text=text, callback_data=f"duration:{value}")
    keyboard.adjust(2)
    return keyboard


def reminder_keyboard(default_minutes: int) -> InlineKeyboardBuilder:
    options = [0, 5, 10, 15, 30, 60, 120]
    keyboard = InlineKeyboardBuilder()
    for minutes in options:
        label = "Без напоминания" if minutes == 0 else f"За {minutes} мин"
        if minutes == default_minutes:
            label = "✅ " + label
        keyboard.button(text=label, callback_data=f"reminder:{minutes}")
    keyboard.adjust(2)
    keyboard.button(text="Использовать по умолчанию", callback_data="reminder:default")
    return keyboard


def events_keyboard() -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Обновить", callback_data="events:refresh")
    keyboard.button(text="Экспорт TXT", callback_data="events:export_txt")
    keyboard.button(text="Экспорт JSON", callback_data="events:export_json")
    keyboard.adjust(2)
    return keyboard


def event_actions_keyboard(event_id: int) -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Удалить", callback_data=f"event:{event_id}:delete")
    keyboard.button(text="Назад", callback_data="menu:list")
    keyboard.adjust(2)
    return keyboard


__all__ = [
    "CalendarData",
    "main_menu",
    "timezone_keyboard",
    "reminder_default_keyboard",
    "settings_keyboard",
    "calendar_keyboard",
    "time_keyboard",
    "duration_keyboard",
    "reminder_keyboard",
    "events_keyboard",
    "event_actions_keyboard",
]
