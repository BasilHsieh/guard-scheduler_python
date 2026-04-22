from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .models import CarryOver, Guard, PostId


@dataclass(frozen=True)
class InputData:
    guards: list[Guard]
    holidays: set[str]
    carry_over: dict[str, CarryOver]


def _as_post_id(value: object) -> PostId | None:
    if value in {"A", "B", "C", "D", "E", "F", "G"}:
        return value  # type: ignore[return-value]
    return None


def _parse_guard(raw: object, idx: int) -> Guard:
    if isinstance(raw, str):
        gid = f"g{idx + 1}"
        return Guard(id=gid, name=raw)
    if isinstance(raw, dict):
        gid = str(raw.get("id", "")).strip()
        name = str(raw.get("name", "")).strip()
        if not gid or not name:
            raise ValueError(f"guards[{idx}] must have non-empty id/name")
        return Guard(id=gid, name=name)
    raise ValueError(f"guards[{idx}] must be string or object")


def _parse_carry_over(raw: object, guard_id: str) -> CarryOver:
    if raw is None:
        return CarryOver()
    if not isinstance(raw, dict):
        raise ValueError(f"carry_over.{guard_id} must be object")

    last_post = _as_post_id(raw.get("last_post"))
    last_holiday_post = _as_post_id(raw.get("last_holiday_post"))
    last_holiday_dow_raw = raw.get("last_holiday_dow")

    last_holiday_dow: int | None
    if last_holiday_dow_raw is None:
        last_holiday_dow = None
    else:
        last_holiday_dow = int(last_holiday_dow_raw)
        if last_holiday_dow not in {5, 6}:
            raise ValueError(
                f"carry_over.{guard_id}.last_holiday_dow must be 5 (Sat) or 6 (Sun)"
            )

    consecutive_days = int(raw.get("consecutive_days", 0))
    if consecutive_days < 0:
        raise ValueError(f"carry_over.{guard_id}.consecutive_days must be >= 0")

    return CarryOver(
        consecutive_days=consecutive_days,
        last_post=last_post,
        last_holiday_dow=last_holiday_dow,
        last_holiday_post=last_holiday_post,
    )


def load_input_from_payload(payload: dict[str, object]) -> InputData:
    guards_raw = payload.get("guards")
    if not isinstance(guards_raw, list) or len(guards_raw) == 0:
        raise ValueError("guards must be a non-empty list")

    guards = [_parse_guard(g, idx) for idx, g in enumerate(guards_raw)]
    guard_ids = [g.id for g in guards]
    if len(set(guard_ids)) != len(guard_ids):
        raise ValueError("guard ids must be unique")

    holidays_raw = payload.get("holidays", [])
    if not isinstance(holidays_raw, list):
        raise ValueError("holidays must be a list of YYYY-MM-DD")
    holidays = {str(x) for x in holidays_raw}

    carry_over_raw = payload.get("carry_over", {})
    if carry_over_raw is None:
        carry_over_raw = {}
    if not isinstance(carry_over_raw, dict):
        raise ValueError("carry_over must be an object")

    carry_over: dict[str, CarryOver] = {}
    for guard in guards:
        carry_over[guard.id] = _parse_carry_over(carry_over_raw.get(guard.id), guard.id)

    return InputData(guards=guards, holidays=holidays, carry_over=carry_over)


def load_input(path: str | Path) -> InputData:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input json root must be an object")
    return load_input_from_payload(payload)


def build_month_days(
    year: int,
    month: int,
    holidays: set[str] | None = None,
    day_types: dict[str, bool] | None = None,
) -> list[tuple[date, bool]]:
    first = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)

    holidays_set = holidays or set()
    days: list[tuple[date, bool]] = []
    current = first
    while current < next_month:
        ds = current.isoformat()
        if day_types is not None:
            is_holiday = day_types.get(ds, current.weekday() >= 5)
        else:
            is_weekend = current.weekday() >= 5
            is_holiday = is_weekend or ds in holidays_set
        days.append((current, is_holiday))
        current += timedelta(days=1)

    return days
