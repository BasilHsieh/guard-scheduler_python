from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

PostId = Literal["A", "B", "C", "D", "E", "F", "G"]
PostType = Literal["weekday", "holiday"]


@dataclass(frozen=True)
class Post:
    id: PostId
    post_type: PostType
    hours: int


@dataclass(frozen=True)
class Guard:
    id: str
    name: str


@dataclass(frozen=True)
class CarryOver:
    consecutive_days: int = 0
    last_post: PostId | None = None
    last_holiday_dow: int | None = None
    last_holiday_post: PostId | None = None


@dataclass
class DaySchedule:
    date: date
    is_holiday: bool
    assignments: dict[str, PostId | None]


@dataclass
class Schedule:
    year: int
    month: int
    guards: list[Guard]
    days: list[DaySchedule]


@dataclass
class RuntimeState:
    consecutive_days: int
    last_post: PostId | None
    last_holiday_dow: int | None
    last_holiday_post: PostId | None
    total_hours: int = 0
    post_counts: dict[PostId, int] = field(
        default_factory=lambda: {pid: 0 for pid in ALL_POST_IDS}
    )


ALL_POST_IDS: tuple[PostId, ...] = ("A", "B", "C", "D", "E", "F", "G")
WEEKDAY_POSTS: tuple[PostId, ...] = ("A", "B", "C", "D", "E")
HOLIDAY_POSTS: tuple[PostId, ...] = ("F", "G")

POSTS: dict[PostId, Post] = {
    "A": Post("A", "weekday", 10),
    "B": Post("B", "weekday", 10),
    "C": Post("C", "weekday", 10),
    "D": Post("D", "weekday", 12),
    "E": Post("E", "weekday", 12),
    "F": Post("F", "holiday", 12),
    "G": Post("G", "holiday", 12),
}

