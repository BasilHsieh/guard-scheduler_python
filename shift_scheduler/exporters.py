from __future__ import annotations

import csv
from io import BytesIO, StringIO
from pathlib import Path

from .models import ALL_POST_IDS, Schedule
from .validate import ValidationSummary


def _schedule_rows(schedule: Schedule) -> list[list[str]]:
    rows: list[list[str]] = []
    dates = [d.date.isoformat() for d in schedule.days]
    rows.append(["guard_id", "guard_name", *dates])
    for guard in schedule.guards:
        row = [guard.id, guard.name]
        for day in schedule.days:
            row.append(day.assignments[guard.id] or "")
        rows.append(row)
    return rows


def export_csv_bytes(schedule: Schedule) -> bytes:
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    for row in _schedule_rows(schedule):
        writer.writerow(row)
    return stream.getvalue().encode("utf-8-sig")


def export_csv(schedule: Schedule, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        for row in _schedule_rows(schedule):
            writer.writerow(row)

    return path


def _build_workbook(
    schedule: Schedule,
    report: ValidationSummary,
) -> object:
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "openpyxl is required for XLSX export. Install requirements.txt first."
        ) from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "Schedule"

    for row in _schedule_rows(schedule):
        ws.append(row)

    summary = wb.create_sheet("Summary")
    summary.append(["guard_id", "guard_name", "hours", *ALL_POST_IDS])
    for guard in schedule.guards:
        gid = guard.id
        counts = report.post_counts_by_guard[gid]
        summary.append(
            [
                gid,
                guard.name,
                report.hours_by_guard[gid],
                *[counts[pid] for pid in ALL_POST_IDS],
            ]
        )

    summary.append([])
    summary.append(["metric", "value"])
    summary.append(["hours_spread", report.hours_spread])
    for pid, spread in report.post_spreads.items():
        summary.append([f"post_spread_{pid}", spread])
    summary.append(["violations", len(report.violations)])

    return wb


def export_xlsx_bytes(
    schedule: Schedule,
    report: ValidationSummary,
) -> bytes:
    wb = _build_workbook(schedule, report)
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def export_xlsx(
    schedule: Schedule,
    report: ValidationSummary,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    wb = _build_workbook(schedule, report)
    wb.save(path)
    return path
