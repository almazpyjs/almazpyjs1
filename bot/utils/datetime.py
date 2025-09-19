from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def parse_time(value: str) -> Optional[time]:
    """Parse HH:MM formatted time string."""
    try:
        hour_str, minute_str = value.split(":", maxsplit=1)
        hour = int(hour_str)
        minute = int(minute_str)
    except (ValueError, AttributeError):
        return None
    if 0 <= hour < 24 and 0 <= minute < 60:
        return time(hour=hour, minute=minute)
    return None


def parse_duration(value: str) -> Optional[int]:
    """Parse duration in minutes from text like '90' or '1h30m'."""
    value = value.strip().lower()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    minutes = 0
    number = ""
    for char in value:
        if char.isdigit():
            number += char
            continue
        if char in {"h", "ч"} and number:
            minutes += int(number) * 60
            number = ""
        elif char in {"m", "мин"} and number:
            minutes += int(number)
            number = ""
        else:
            return None
    if number:
        minutes += int(number)
    return minutes or None


def apply_timezone(date: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    if date.tzinfo is None:
        return date.replace(tzinfo=tz)
    return date.astimezone(tz)


def aware_utc(datetime_obj: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    if datetime_obj.tzinfo is None:
        datetime_obj = datetime_obj.replace(tzinfo=tz)
    return datetime_obj.astimezone(timezone.utc)


def validate_timezone(tz_name: str) -> bool:
    try:
        ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return False
    return True


def format_timedelta(minutes: int) -> str:
    delta = timedelta(minutes=minutes)
    total_minutes = int(delta.total_seconds() // 60)
    hours, mins = divmod(total_minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} ч")
    if mins or not parts:
        parts.append(f"{mins} мин")
    return " ".join(parts)


__all__ = [
    "parse_time",
    "parse_duration",
    "apply_timezone",
    "aware_utc",
    "validate_timezone",
    "format_timedelta",
]
