from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class CreateEvent(StatesGroup):
    waiting_for_title = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_duration = State()
    waiting_for_custom_duration = State()
    waiting_for_reminder = State()


class SettingsState(StatesGroup):
    waiting_for_timezone = State()
    waiting_for_reminder_default = State()


__all__ = ["CreateEvent", "SettingsState"]
