from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_BASE_URL = "https://api.pin-yi.me/taiwan-calendar"


class CalendarAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class CalendarMonthData:
    day_types: dict[str, bool]
    holidays: set[str]
    workdays: set[str]


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise ValueError(f"invalid isHoliday value: {value!r}")


def _normalize_date(row: dict[str, object]) -> str:
    raw_date = row.get("date")
    if isinstance(raw_date, str):
        stripped = raw_date.strip()
        if len(stripped) == 8 and stripped.isdigit():
            return f"{stripped[0:4]}-{stripped[4:6]}-{stripped[6:8]}"
        if len(stripped) == 10 and stripped.count("-") == 2:
            datetime.strptime(stripped, "%Y-%m-%d")
            return stripped

    raw_fmt = row.get("date_format")
    if isinstance(raw_fmt, str):
        parsed = datetime.strptime(raw_fmt.strip(), "%Y/%m/%d").date()
        return parsed.isoformat()

    raise ValueError(f"missing date/date_format in row: {row}")


def fetch_month_calendar(
    year: int,
    month: int,
    timeout_sec: float = 10.0,
) -> CalendarMonthData:
    url = f"{API_BASE_URL}/{year}/{month:02d}"
    req = Request(
        url=url,
        headers={
            "Accept": "application/json",
            "User-Agent": "guard-scheduler-sideproject/0.1",
        },
        method="GET",
    )

    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
    except HTTPError as exc:
        raise CalendarAPIError(f"calendar API HTTP error: {exc.code}") from exc
    except URLError as exc:
        raise CalendarAPIError(f"calendar API connection error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise CalendarAPIError("calendar API timeout") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # pragma: no cover
        raise CalendarAPIError("calendar API returned invalid JSON") from exc

    if not isinstance(payload, list):
        raise CalendarAPIError("calendar API payload must be an array")

    day_types: dict[str, bool] = {}
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            raise CalendarAPIError(f"calendar row[{idx}] must be an object")
        ds = _normalize_date(item)
        is_holiday = _parse_bool(item.get("isHoliday"))
        day_types[ds] = is_holiday

    if not day_types:
        raise CalendarAPIError("calendar API returned empty data")

    holidays = {d for d, is_holiday in day_types.items() if is_holiday}
    workdays = {d for d, is_holiday in day_types.items() if not is_holiday}
    return CalendarMonthData(day_types=day_types, holidays=holidays, workdays=workdays)

