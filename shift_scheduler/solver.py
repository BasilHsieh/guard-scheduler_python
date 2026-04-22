from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import random
from typing import Any

from .io import build_month_days
from .models import (
    ALL_POST_IDS,
    HOLIDAY_POSTS,
    POSTS,
    WEEKDAY_POSTS,
    CarryOver,
    DaySchedule,
    Guard,
    PostId,
    RuntimeState,
    Schedule,
)


class InfeasibleScheduleError(RuntimeError):
    pass


@dataclass(frozen=True)
class SolverConfig:
    attempts: int = 300
    max_consecutive_days: int = 6
    seed: int | None = None


@dataclass(frozen=True)
class SolveStats:
    hours_spread: int
    post_spreads: dict[PostId, int]


@dataclass
class _AttemptResult:
    schedule: Schedule
    stats: SolveStats
    objective: tuple[int, ...]
    changed_cells: int = 0


def _required_posts(is_holiday: bool) -> tuple[PostId, ...]:
    return HOLIDAY_POSTS if is_holiday else WEEKDAY_POSTS


def _initial_state(carry_over: CarryOver) -> RuntimeState:
    return RuntimeState(
        consecutive_days=carry_over.consecutive_days,
        last_post=carry_over.last_post,
        last_holiday_dow=carry_over.last_holiday_dow,
        last_holiday_post=carry_over.last_holiday_post,
    )


def _build_targets(
    month_days: list[tuple[date, bool]],
    guards: list[Guard],
    rng: random.Random,
) -> dict[str, dict[PostId, int]]:
    n = len(guards)
    targets: dict[str, dict[PostId, int]] = {
        g.id: {pid: 0 for pid in ALL_POST_IDS} for g in guards
    }

    post_totals = {pid: 0 for pid in ALL_POST_IDS}
    for _, is_holiday in month_days:
        for pid in _required_posts(is_holiday):
            post_totals[pid] += 1

    projected_hours = {g.id: 0 for g in guards}
    for pid in ALL_POST_IDS:
        base = post_totals[pid] // n
        for g in guards:
            targets[g.id][pid] = base
            projected_hours[g.id] += base * POSTS[pid].hours

        extras = post_totals[pid] % n
        if extras == 0:
            continue
        order = sorted(
            guards,
            key=lambda g: (projected_hours[g.id], rng.random()),
        )
        for g in order[:extras]:
            targets[g.id][pid] += 1
            projected_hours[g.id] += POSTS[pid].hours

    return targets


def _is_guard_valid_for_post(
    state: RuntimeState,
    post_id: PostId,
    dow: int,
    max_consecutive_days: int,
) -> bool:
    if state.consecutive_days >= max_consecutive_days:
        return False
    if state.last_post == post_id:
        return False

    if post_id in HOLIDAY_POSTS:
        if state.last_holiday_dow is not None and state.last_holiday_dow == dow:
            return False
        if state.last_holiday_post == post_id:
            return False

    return True


def _score_candidate(
    guard_id: str,
    post_id: PostId,
    states: dict[str, RuntimeState],
    targets: dict[str, dict[PostId, int]],
    avg_hours: float,
    rng: random.Random,
) -> float:
    state = states[guard_id]
    target = targets[guard_id][post_id]
    done = state.post_counts[post_id]
    deficit = target - done
    hour_gap = avg_hours - state.total_hours
    streak_penalty = state.consecutive_days

    return (
        deficit * 9.0
        + hour_gap * 0.8
        - streak_penalty * 0.7
        + rng.random() * 0.05
    )


def _apply_day_to_states(
    day_date: date,
    assignments: dict[str, PostId | None],
    states: dict[str, RuntimeState],
) -> None:
    for gid, st in states.items():
        pid = assignments.get(gid)
        if pid is None:
            st.consecutive_days = 0
            st.last_post = None
            continue

        st.consecutive_days += 1
        st.last_post = pid
        st.total_hours += POSTS[pid].hours
        st.post_counts[pid] += 1
        if pid in HOLIDAY_POSTS:
            st.last_holiday_dow = day_date.weekday()
            st.last_holiday_post = pid


def _solve_single_day(
    required_posts: tuple[PostId, ...],
    day_date: date,
    states: dict[str, RuntimeState],
    targets: dict[str, dict[PostId, int]],
    max_consecutive_days: int,
    rng: random.Random,
    fixed_assignments: dict[str, PostId | None] | None = None,
    baseline_assignments: dict[str, PostId | None] | None = None,
) -> dict[str, PostId] | None:
    fixed = fixed_assignments or {}
    baseline = baseline_assignments or {}
    dow = day_date.weekday()
    avg_hours = sum(s.total_hours for s in states.values()) / len(states)
    best_total = float("-inf")
    best_assignment: dict[str, PostId] | None = None

    fixed_working = {gid: pid for gid, pid in fixed.items() if pid is not None}
    required_set = set(required_posts)
    if any(pid not in required_set for pid in fixed_working.values()):
        return None
    if len(set(fixed_working.values())) != len(fixed_working):
        return None
    for gid, pid in fixed_working.items():
        st = states.get(gid)
        if st is None:
            return None
        if not _is_guard_valid_for_post(st, pid, dow, max_consecutive_days):
            return None

    blocked_guards = set(fixed.keys())
    used_guards_initial = set(fixed_working.keys())
    remaining_posts = [p for p in required_posts if p not in set(fixed_working.values())]

    def choose_next_post(
        remaining: list[PostId], used_guards: set[str]
    ) -> tuple[PostId, list[str]]:
        options: list[tuple[int, PostId, list[str]]] = []
        for pid in remaining:
            candidates = [
                gid
                for gid, st in states.items()
                if gid not in used_guards
                and gid not in blocked_guards
                and _is_guard_valid_for_post(st, pid, dow, max_consecutive_days)
            ]
            options.append((len(candidates), pid, candidates))
        options.sort(key=lambda x: x[0])
        return options[0][1], options[0][2]

    def backtrack(
        remaining_posts: list[PostId],
        used_guards: set[str],
        current: dict[str, PostId],
        score_total: float,
    ) -> None:
        nonlocal best_total, best_assignment
        if not remaining_posts:
            if score_total > best_total:
                best_total = score_total
                best_assignment = dict(current)
            return

        pid, candidates = choose_next_post(remaining_posts, used_guards)
        if not candidates:
            return

        scored = sorted(
            candidates,
            key=lambda gid: _score_candidate(gid, pid, states, targets, avg_hours, rng),
            reverse=True,
        )
        next_remaining = [p for p in remaining_posts if p != pid]
        for gid in scored:
            s = _score_candidate(gid, pid, states, targets, avg_hours, rng)
            if baseline.get(gid) == pid:
                s += 1.2
            used_guards.add(gid)
            current[gid] = pid
            backtrack(next_remaining, used_guards, current, score_total + s)
            current.pop(gid)
            used_guards.remove(gid)

    fixed_score = 0.0
    for gid, pid in fixed_working.items():
        fixed_score += _score_candidate(gid, pid, states, targets, avg_hours, rng)
        if baseline.get(gid) == pid:
            fixed_score += 1.2

    backtrack(remaining_posts, used_guards_initial, dict(fixed_working), fixed_score)
    return best_assignment


def _post_spreads(states: dict[str, RuntimeState]) -> dict[PostId, int]:
    out: dict[PostId, int] = {}
    for pid in ALL_POST_IDS:
        vals = [st.post_counts[pid] for st in states.values()]
        out[pid] = max(vals) - min(vals)
    return out


def _evaluate_attempt(states: dict[str, RuntimeState]) -> SolveStats:
    hours = [st.total_hours for st in states.values()]
    spread = max(hours) - min(hours)
    return SolveStats(hours_spread=spread, post_spreads=_post_spreads(states))


def _objective(stats: SolveStats) -> tuple[int, int, int, int]:
    hours_excess = max(0, stats.hours_spread - 12)
    max_post_spread = max(stats.post_spreads.values())
    post_excess = sum(max(0, v - 1) for v in stats.post_spreads.values())
    post_sum = sum(stats.post_spreads.values())
    return (hours_excess, post_excess, stats.hours_spread, post_sum)


def _run_one_attempt(
    year: int,
    month: int,
    guards: list[Guard],
    holidays: set[str],
    day_types: dict[str, bool] | None,
    carry_over: dict[str, CarryOver],
    cfg: SolverConfig,
    rng: random.Random,
) -> _AttemptResult | None:
    month_days = build_month_days(year, month, holidays=holidays, day_types=day_types)
    targets = _build_targets(month_days, guards, rng)
    states = {g.id: _initial_state(carry_over.get(g.id, CarryOver())) for g in guards}
    guard_ids = [g.id for g in guards]

    days_out: list[DaySchedule] = []
    for day_date, is_holiday in month_days:
        required = _required_posts(is_holiday)
        chosen = _solve_single_day(
            required_posts=required,
            day_date=day_date,
            states=states,
            targets=targets,
            max_consecutive_days=cfg.max_consecutive_days,
            rng=rng,
        )
        if chosen is None:
            return None

        assignments: dict[str, PostId | None] = {gid: None for gid in guard_ids}
        for gid, pid in chosen.items():
            assignments[gid] = pid

        _apply_day_to_states(day_date, assignments, states)

        days_out.append(
            DaySchedule(date=day_date, is_holiday=is_holiday, assignments=assignments)
        )

    schedule = Schedule(year=year, month=month, guards=guards, days=days_out)
    stats = _evaluate_attempt(states)
    return _AttemptResult(schedule=schedule, stats=stats, objective=_objective(stats))


def generate_schedule(
    year: int,
    month: int,
    guards: list[Guard],
    holidays: set[str],
    day_types: dict[str, bool] | None,
    carry_over: dict[str, CarryOver],
    config: SolverConfig | None = None,
) -> tuple[Schedule, SolveStats]:
    cfg = config or SolverConfig()
    seed = cfg.seed if cfg.seed is not None else random.randint(1, 10**9)

    best: _AttemptResult | None = None
    for i in range(cfg.attempts):
        rng = random.Random(seed + i)
        attempt = _run_one_attempt(
            year=year,
            month=month,
            guards=guards,
            holidays=holidays,
            day_types=day_types,
            carry_over=carry_over,
            cfg=cfg,
            rng=rng,
        )
        if attempt is None:
            continue
        if best is None or attempt.objective < best.objective:
            best = attempt
        if best is not None and best.objective[0] == 0 and best.objective[1] == 0:
            break

    if best is None:
        raise InfeasibleScheduleError(
            "No feasible schedule found. Try adding carry_over or increasing attempts."
        )

    return best.schedule, best.stats


@dataclass(frozen=True)
class ShiftChangeRequest:
    borrow_date: str
    requester_guard_id: str
    substitute_guard_id: str
    payback_date: str


def _run_one_repair_attempt(
    schedule: Schedule,
    carry_over: dict[str, CarryOver],
    start_date: date,
    fixed_by_date: dict[str, dict[str, PostId | None]],
    cfg: SolverConfig,
    rng: random.Random,
) -> _AttemptResult | None:
    month_days = [(d.date, d.is_holiday) for d in schedule.days]
    guards = schedule.guards
    targets = _build_targets(month_days, guards, rng)
    states = {g.id: _initial_state(carry_over.get(g.id, CarryOver())) for g in guards}
    guard_ids = [g.id for g in guards]
    existing_by_date = {d.date.isoformat(): dict(d.assignments) for d in schedule.days}

    days_out: list[DaySchedule] = []
    for day_date, is_holiday in month_days:
        ds = day_date.isoformat()
        if day_date < start_date:
            assignments = dict(existing_by_date[ds])
        else:
            required = _required_posts(is_holiday)
            fixed_day = fixed_by_date.get(ds)
            baseline_day = existing_by_date.get(ds)
            chosen = _solve_single_day(
                required_posts=required,
                day_date=day_date,
                states=states,
                targets=targets,
                max_consecutive_days=cfg.max_consecutive_days,
                rng=rng,
                fixed_assignments=fixed_day,
                baseline_assignments=baseline_day,
            )
            if chosen is None:
                return None

            assignments = {gid: None for gid in guard_ids}
            if fixed_day:
                for gid, pid in fixed_day.items():
                    assignments[gid] = pid
            for gid, pid in chosen.items():
                assignments[gid] = pid

        _apply_day_to_states(day_date, assignments, states)
        days_out.append(
            DaySchedule(date=day_date, is_holiday=is_holiday, assignments=assignments)
        )

    changed_cells = 0
    for day in days_out:
        if day.date < start_date:
            continue
        ds = day.date.isoformat()
        before = existing_by_date[ds]
        for gid in guard_ids:
            if before[gid] != day.assignments[gid]:
                changed_cells += 1

    schedule_out = Schedule(
        year=schedule.year,
        month=schedule.month,
        guards=guards,
        days=days_out,
    )
    stats = _evaluate_attempt(states)
    hours_excess, post_excess, _, post_sum = _objective(stats)
    objective = (hours_excess, post_excess, changed_cells, stats.hours_spread, post_sum)
    return _AttemptResult(
        schedule=schedule_out,
        stats=stats,
        objective=objective,
        changed_cells=changed_cells,
    )


def adjust_schedule_for_shift_change(
    schedule: Schedule,
    carry_over: dict[str, CarryOver],
    request: ShiftChangeRequest,
    config: SolverConfig | None = None,
) -> tuple[Schedule, SolveStats, dict[str, Any]]:
    cfg = config or SolverConfig()
    guard_ids = {g.id for g in schedule.guards}
    if request.requester_guard_id not in guard_ids:
        raise InfeasibleScheduleError("Requester guard id not found in schedule")
    if request.substitute_guard_id not in guard_ids:
        raise InfeasibleScheduleError("Substitute guard id not found in schedule")
    if request.requester_guard_id == request.substitute_guard_id:
        raise InfeasibleScheduleError("Requester and substitute must be different guards")

    day_by_date = {d.date.isoformat(): d for d in schedule.days}
    if request.borrow_date not in day_by_date:
        raise InfeasibleScheduleError("Borrow date is out of this month")
    if request.payback_date not in day_by_date:
        raise InfeasibleScheduleError("Payback date is out of this month")
    if request.payback_date == request.borrow_date:
        raise InfeasibleScheduleError("Borrow date and payback date cannot be the same day")

    requester = request.requester_guard_id
    substitute = request.substitute_guard_id
    borrow_day = day_by_date[request.borrow_date]
    payback_day = day_by_date[request.payback_date]
    borrow_assignments = dict(borrow_day.assignments)
    payback_assignments = dict(payback_day.assignments)

    borrowed_post = borrow_assignments.get(requester)
    if borrowed_post is None:
        raise InfeasibleScheduleError("Requester has no shift on borrow date")
    if borrow_assignments.get(substitute) is not None:
        raise InfeasibleScheduleError("Substitute is not off on borrow date")

    payback_post = payback_assignments.get(substitute)
    if payback_post is None:
        raise InfeasibleScheduleError("Substitute has no shift on payback date")
    if payback_assignments.get(requester) is not None:
        raise InfeasibleScheduleError("Requester must be off on payback date")
    if POSTS[borrowed_post].hours != POSTS[payback_post].hours:
        raise InfeasibleScheduleError(
            "借班與還班必須是同工時（10h 對 10h、12h 對 12h）"
        )

    borrow_fixed = dict(borrow_assignments)
    borrow_fixed[requester] = None
    borrow_fixed[substitute] = borrowed_post

    payback_fixed = dict(payback_assignments)
    payback_fixed[requester] = payback_post
    payback_fixed[substitute] = None

    fixed_by_date = {
        request.borrow_date: borrow_fixed,
        request.payback_date: payback_fixed,
    }
    start_date = min(
        date.fromisoformat(request.borrow_date),
        date.fromisoformat(request.payback_date),
    )

    seed = cfg.seed if cfg.seed is not None else random.randint(1, 10**9)
    best: _AttemptResult | None = None
    for i in range(cfg.attempts):
        rng = random.Random(seed + i)
        attempt = _run_one_repair_attempt(
            schedule=schedule,
            carry_over=carry_over,
            start_date=start_date,
            fixed_by_date=fixed_by_date,
            cfg=cfg,
            rng=rng,
        )
        if attempt is None:
            continue
        if best is None or attempt.objective < best.objective:
            best = attempt
        if best is not None and best.objective[0] == 0 and best.objective[1] == 0:
            break

    if best is None:
        raise InfeasibleScheduleError(
            "目前這組借班/還班條件無法修復成符合規則的班表"
        )

    changed_dates = sorted(
        {
            day.date.isoformat()
            for day, old in zip(best.schedule.days, schedule.days)
            if day.assignments != old.assignments and day.date >= start_date
        }
    )
    meta: dict[str, Any] = {
        "borrow_date": request.borrow_date,
        "payback_date": request.payback_date,
        "requester_guard_id": requester,
        "substitute_guard_id": substitute,
        "borrowed_post": borrowed_post,
        "payback_post": payback_post,
        "changed_cells": best.changed_cells,
        "changed_dates": changed_dates,
    }
    return best.schedule, best.stats, meta
