"""Bounded, numeric five-field cron schedules using local wall-clock time."""

import calendar
import re
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo


def _field(text, low, high):
    values = set()
    for part in text.split(","):
        if not re.fullmatch(r"(?:\*|[0-9]+(?:-[0-9]+)?)(?:/[0-9]+)?", part):
            raise ValueError("Cron accepts numbers, *, lists, ascending ranges and steps only.")
        base, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if not 1 <= step <= high - low + 1:
            raise ValueError("Cron step is outside the field's range.")
        if base == "*":
            start, end = low, high
        elif "-" in base:
            start, end = map(int, base.split("-"))
        else:
            start = int(base)
            end = high if step_text else start
        if not low <= start <= end <= high:
            raise ValueError("Cron value or range is outside the field's bounds.")
        values.update(range(start, end + 1, step))
    return frozenset(values)


@lru_cache(maxsize=256)
def parse_cron(expression):
    if len(expression) > 256 or len(parts := expression.split()) != 5:
        raise ValueError("Use five cron fields: minute hour day-of-month month day-of-week.")
    fields = tuple(_field(part, *bounds) for part, bounds in
                   zip(parts, [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]))
    # Sunday has two accepted numeric spellings.
    fields = (*fields[:4], frozenset(v % 7 for v in fields[4]))
    unrestricted = (fields[2] == frozenset(range(1, 32)), fields[4] == frozenset(range(7)))
    if unrestricted[1] and not any(
        day <= calendar.monthrange(2000, month)[1] for month in fields[3] for day in fields[2]
    ):
        raise ValueError("Cron has no possible calendar date.")
    return fields, unrestricted


def expression_for(schedule):
    trigger = schedule["trigger"]
    if trigger == "manual":
        return None
    if trigger == "cron":
        return schedule["cron"]
    hour, minute = map(int, schedule["time"].split(":"))
    weekdays = ",".join(str((day + 1) % 7) for day in schedule["weekdays"]) if trigger == "weekly" else "*"
    return f"{minute} {hour} * * {weekdays}"


@lru_cache(maxsize=128)
def day_occurrences(expression, zone_name, day):
    fields, (any_dom, any_dow) = parse_cron(expression)
    minutes, hours, days, months, weekdays = fields
    if day.month not in months:
        return ()
    dom, dow = day.day in days, (day.weekday() + 1) % 7 in weekdays
    matches = (dom and dow) if any_dom or any_dow else (dom or dow)
    if not matches:
        return ()
    zone = ZoneInfo(zone_name)
    result = []
    for hour in sorted(hours):
        for minute in sorted(minutes):
            wall = datetime.combine(day, time(hour, minute))
            due = wall.replace(tzinfo=zone, fold=0).astimezone(timezone.utc)
            # Skip nonexistent times; use only the first occurrence of repeated times.
            if due.astimezone(zone).replace(tzinfo=None) == wall:
                result.append(due)
    return tuple(sorted(result))


def latest_due(schedule, instant):
    expression = expression_for(schedule)
    if expression is None:
        return None
    occurrences = day_occurrences(expression, schedule["timezone"], instant.astimezone(ZoneInfo(schedule["timezone"])).date())
    return next((due for due in reversed(occurrences) if due <= instant), None)


def upcoming(schedule, instant=None, count=5):
    instant = instant or datetime.now(timezone.utc)
    expression = expression_for(schedule)
    if expression is None:
        return []
    zone = ZoneInfo(schedule["timezone"])
    first = instant.astimezone(zone).date()
    result = []
    # Eight years includes the leap-day gap across non-leap century years.
    for offset in range(8 * 366 + 1):
        day = first + timedelta(days=offset)
        for due in day_occurrences(expression, schedule["timezone"], day):
            if due > instant:
                result.append({"utc": due.isoformat(), "local": due.astimezone(zone).isoformat()})
                if len(result) == count:
                    return result
    return result
