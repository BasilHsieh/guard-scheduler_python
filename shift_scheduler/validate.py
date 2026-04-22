from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import (
    ALL_POST_IDS,
    HOLIDAY_POSTS,
    POSTS,
    CarryOver,
    PostId,
    Schedule,
)


@dataclass(frozen=True)
class Violation:
    rule: int
    guard_id: str
    date: str
    message: str


@dataclass(frozen=True)
class RuleAudit:
    rule: int
    name: str
    threshold: str
    measured: str
    passed: bool
    evidence: dict[str, Any]


@dataclass(frozen=True)
class ValidationSummary:
    violations: list[Violation]
    audits: list[RuleAudit]
    hours_by_guard: dict[str, int]
    post_counts_by_guard: dict[str, dict[PostId, int]]
    hours_spread: int
    post_spreads: dict[PostId, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "violations": [asdict(v) for v in self.violations],
            "audits": [asdict(a) for a in self.audits],
            "hours_by_guard": self.hours_by_guard,
            "post_counts_by_guard": self.post_counts_by_guard,
            "hours_spread": self.hours_spread,
            "post_spreads": self.post_spreads,
        }


def validate_schedule(
    schedule: Schedule, carry_over: dict[str, CarryOver] | None = None
) -> ValidationSummary:
    carry_over = carry_over or {}
    guard_ids = [g.id for g in schedule.guards]
    guard_names = {g.id: g.name for g in schedule.guards}

    violations: list[Violation] = []
    rule1_events: list[dict[str, Any]] = []
    rule2_events: list[dict[str, Any]] = []
    rule3_events: list[dict[str, Any]] = []
    rule4_events: list[dict[str, Any]] = []

    hours_by_guard = {gid: 0 for gid in guard_ids}
    post_counts_by_guard: dict[str, dict[PostId, int]] = {
        gid: {pid: 0 for pid in ALL_POST_IDS} for gid in guard_ids
    }

    streak = {gid: carry_over.get(gid, CarryOver()).consecutive_days for gid in guard_ids}
    max_consecutive_by_guard = dict(streak)
    month_streak = {gid: 0 for gid in guard_ids}
    month_streak_start: dict[str, str | None] = {gid: None for gid in guard_ids}
    longest_streak_in_month_by_guard: dict[str, dict[str, Any]] = {
        gid: {"start": "", "end": "", "length": 0} for gid in guard_ids
    }

    prev_post = {gid: carry_over.get(gid, CarryOver()).last_post for gid in guard_ids}
    rule2_checks_by_guard = {gid: 0 for gid in guard_ids}
    rule2_repeats_by_guard = {gid: 0 for gid in guard_ids}

    last_holiday_dow = {
        gid: carry_over.get(gid, CarryOver()).last_holiday_dow for gid in guard_ids
    }
    last_holiday_post = {
        gid: carry_over.get(gid, CarryOver()).last_holiday_post for gid in guard_ids
    }
    rule3_checks_by_guard = {gid: 0 for gid in guard_ids}
    rule3_repeats_by_guard = {gid: 0 for gid in guard_ids}
    rule4_checks_by_guard = {gid: 0 for gid in guard_ids}
    rule4_repeats_by_guard = {gid: 0 for gid in guard_ids}
    holiday_week_sequence_by_guard = {gid: [] for gid in guard_ids}
    holiday_post_sequence_by_guard = {gid: [] for gid in guard_ids}
    dow_map = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for day in schedule.days:
        dow = day.date.weekday()
        day_iso = day.date.isoformat()
        for gid in guard_ids:
            post = day.assignments[gid]
            if post is None:
                streak[gid] = 0
                month_streak[gid] = 0
                month_streak_start[gid] = None
                prev_post[gid] = None
                continue

            streak[gid] += 1
            if streak[gid] > max_consecutive_by_guard[gid]:
                max_consecutive_by_guard[gid] = streak[gid]

            if month_streak[gid] == 0:
                month_streak_start[gid] = day_iso
            month_streak[gid] += 1
            if month_streak[gid] > longest_streak_in_month_by_guard[gid]["length"]:
                longest_streak_in_month_by_guard[gid] = {
                    "start": month_streak_start[gid] or day_iso,
                    "end": day_iso,
                    "length": month_streak[gid],
                }

            if streak[gid] > 6:
                rule1_events.append(
                    {
                        "guard_id": gid,
                        "guard_name": guard_names[gid],
                        "date": day_iso,
                        "consecutive_days": streak[gid],
                    }
                )
                violations.append(
                    Violation(
                        rule=1,
                        guard_id=gid,
                        date=day_iso,
                        message=f"consecutive work days = {streak[gid]} (> 6)",
                    )
                )

            if prev_post[gid] is not None:
                rule2_checks_by_guard[gid] += 1
            if prev_post[gid] == post:
                rule2_repeats_by_guard[gid] += 1
                rule2_events.append(
                    {
                        "guard_id": gid,
                        "guard_name": guard_names[gid],
                        "date": day_iso,
                        "post": post,
                    }
                )
                violations.append(
                    Violation(
                        rule=2,
                        guard_id=gid,
                        date=day_iso,
                        message=f"same post repeated on consecutive days: {post}",
                    )
                )

            if post in HOLIDAY_POSTS:
                holiday_week_sequence_by_guard[gid].append(dow_map[dow])
                holiday_post_sequence_by_guard[gid].append(post)

                if last_holiday_dow[gid] is not None and last_holiday_dow[gid] == dow:
                    rule3_checks_by_guard[gid] += 1
                    rule3_repeats_by_guard[gid] += 1
                    rule3_events.append(
                        {
                            "guard_id": gid,
                            "guard_name": guard_names[gid],
                            "date": day_iso,
                            "week_day": dow_map[dow],
                        }
                    )
                    violations.append(
                        Violation(
                            rule=3,
                            guard_id=gid,
                            date=day_iso,
                            message="holiday weekday did not alternate (Sat/Sun)",
                        )
                    )
                elif last_holiday_dow[gid] is not None:
                    rule3_checks_by_guard[gid] += 1
                if (
                    last_holiday_post[gid] is not None
                    and last_holiday_post[gid] == post
                ):
                    rule4_checks_by_guard[gid] += 1
                    rule4_repeats_by_guard[gid] += 1
                    rule4_events.append(
                        {
                            "guard_id": gid,
                            "guard_name": guard_names[gid],
                            "date": day_iso,
                            "post": post,
                        }
                    )
                    violations.append(
                        Violation(
                            rule=4,
                            guard_id=gid,
                            date=day_iso,
                            message=f"holiday post did not alternate: {post}",
                        )
                    )
                elif last_holiday_post[gid] is not None:
                    rule4_checks_by_guard[gid] += 1
                last_holiday_dow[gid] = dow
                last_holiday_post[gid] = post

            prev_post[gid] = post
            hours_by_guard[gid] += POSTS[post].hours
            post_counts_by_guard[gid][post] += 1

    hours = list(hours_by_guard.values())
    hours_spread = max(hours) - min(hours)
    if hours_spread > 12:
        violations.append(
            Violation(
                rule=5,
                guard_id="*",
                date="",
                message=f"hours spread = {hours_spread} (> 12)",
            )
        )

    post_spreads: dict[PostId, int] = {}
    for pid in ALL_POST_IDS:
        vals = [post_counts_by_guard[gid][pid] for gid in guard_ids]
        spread = max(vals) - min(vals)
        post_spreads[pid] = spread
        if spread > 1:
            violations.append(
                Violation(
                    rule=6,
                    guard_id="*",
                    date="",
                    message=f"post {pid} spread = {spread} (> 1)",
                )
            )

    violation_counts_by_rule = {idx: 0 for idx in range(1, 7)}
    for v in violations:
        violation_counts_by_rule[v.rule] += 1

    hours_max = max(hours)
    hours_min = min(hours)
    hours_max_guards = [
        {"guard_id": gid, "guard_name": guard_names[gid], "hours": h}
        for gid, h in hours_by_guard.items()
        if h == hours_max
    ]
    hours_min_guards = [
        {"guard_id": gid, "guard_name": guard_names[gid], "hours": h}
        for gid, h in hours_by_guard.items()
        if h == hours_min
    ]

    audits: list[RuleAudit] = [
        RuleAudit(
            rule=1,
            name="不超過連續 6 天上班",
            threshold="每人連續上班不可超過 6 天",
            measured=f"本月最長連續上班 {max(max_consecutive_by_guard.values())} 天",
            passed=violation_counts_by_rule[1] == 0,
            evidence={
                "per_guard_max_consecutive_days": max_consecutive_by_guard,
                "per_guard_longest_streak_in_month": longest_streak_in_month_by_guard,
                "violation_events": rule1_events,
            },
        ),
        RuleAudit(
            rule=2,
            name="同一哨點不連兩天",
            threshold="同一人相鄰兩個上班日不可排同一哨點",
            measured=(
                f"連續同哨點 {sum(rule2_repeats_by_guard.values())} 次，"
                f"共檢查 {sum(rule2_checks_by_guard.values())} 組相鄰上班日"
            ),
            passed=violation_counts_by_rule[2] == 0,
            evidence={
                "checks_by_guard": rule2_checks_by_guard,
                "repeats_by_guard": rule2_repeats_by_guard,
                "violation_events": rule2_events,
            },
        ),
        RuleAudit(
            rule=3,
            name="假日星期交替",
            threshold="同一人假日班需六日交替（不可連續兩個六或兩個日）",
            measured=(
                f"假日星期未交替 {sum(rule3_repeats_by_guard.values())} 次，"
                f"共檢查 {sum(rule3_checks_by_guard.values())} 次假日銜接"
            ),
            passed=violation_counts_by_rule[3] == 0,
            evidence={
                "holiday_weekday_sequence_by_guard": holiday_week_sequence_by_guard,
                "checks_by_guard": rule3_checks_by_guard,
                "repeats_by_guard": rule3_repeats_by_guard,
                "violation_events": rule3_events,
            },
        ),
        RuleAudit(
            rule=4,
            name="假日哨點 F/G 交替",
            threshold="同一人假日哨點需 F/G 交替",
            measured=(
                f"假日哨點未交替 {sum(rule4_repeats_by_guard.values())} 次，"
                f"共檢查 {sum(rule4_checks_by_guard.values())} 次假日銜接"
            ),
            passed=violation_counts_by_rule[4] == 0,
            evidence={
                "holiday_post_sequence_by_guard": holiday_post_sequence_by_guard,
                "checks_by_guard": rule4_checks_by_guard,
                "repeats_by_guard": rule4_repeats_by_guard,
                "violation_events": rule4_events,
            },
        ),
        RuleAudit(
            rule=5,
            name="每人月總時數差距 <= 12h",
            threshold="全員月工時最高與最低差距不可超過 12 小時",
            measured=f"工時差距 {hours_spread} 小時（最高 {hours_max}、最低 {hours_min}）",
            passed=violation_counts_by_rule[5] == 0,
            evidence={
                "hours_by_guard": hours_by_guard,
                "max_hours_guards": hours_max_guards,
                "min_hours_guards": hours_min_guards,
            },
        ),
        RuleAudit(
            rule=6,
            name="每個哨點分配次數差距 <= 1",
            threshold="每個哨點在人員間分配差距不可超過 1 班",
            measured=f"最大哨點分配差距 {max(post_spreads.values())} 班",
            passed=violation_counts_by_rule[6] == 0,
            evidence={
                "post_spreads": post_spreads,
                "post_counts_by_guard": post_counts_by_guard,
            },
        ),
    ]

    return ValidationSummary(
        violations=violations,
        audits=audits,
        hours_by_guard=hours_by_guard,
        post_counts_by_guard=post_counts_by_guard,
        hours_spread=hours_spread,
        post_spreads=post_spreads,
    )
