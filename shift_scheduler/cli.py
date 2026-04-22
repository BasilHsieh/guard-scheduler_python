from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .calendar_api import CalendarAPIError, fetch_month_calendar
from .exporters import export_csv, export_xlsx
from .io import load_input
from .solver import InfeasibleScheduleError, SolverConfig, generate_schedule
from .validate import validate_schedule


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guard schedule generator")
    parser.add_argument("--input", required=True, help="input json path")
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--month", type=int, default=datetime.now().month)
    parser.add_argument("--out-dir", default="outputs")
    parser.add_argument("--attempts", type=int, default=300)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--use-input-holidays",
        action="store_true",
        help="use holidays from input JSON instead of Taiwan calendar API",
    )
    parser.add_argument(
        "--no-xlsx",
        action="store_true",
        help="skip xlsx export",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    payload = load_input(args.input)
    holidays = set(payload.holidays)
    day_types: dict[str, bool] | None = None
    calendar_source = "input_json"
    if args.use_input_holidays:
        calendar_source = "input_json"
        print("[INFO] using holidays from input JSON")
    else:
        try:
            cal = fetch_month_calendar(year=args.year, month=args.month)
        except CalendarAPIError as exc:
            print(f"[ERROR] calendar API failed: {exc}")
            return 2
        day_types = cal.day_types
        holidays = set(cal.holidays)
        calendar_source = "taiwan_calendar_api"
        print(
            f"[INFO] calendar API loaded: holidays={len(cal.holidays)}, workdays={len(cal.workdays)}"
        )

    config = SolverConfig(attempts=args.attempts, seed=args.seed)
    try:
        schedule, solve_stats = generate_schedule(
            year=args.year,
            month=args.month,
            guards=payload.guards,
            holidays=holidays,
            day_types=day_types,
            carry_over=payload.carry_over,
            config=config,
        )
    except InfeasibleScheduleError as exc:
        print(f"[ERROR] {exc}")
        return 2

    report = validate_schedule(schedule, carry_over=payload.carry_over)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    y, m = args.year, args.month
    csv_path = export_csv(schedule, out_dir / f"schedule_{y}_{m:02d}.csv")

    xlsx_path: Path | None = None
    if not args.no_xlsx:
        xlsx_path = export_xlsx(schedule, report, out_dir / f"schedule_{y}_{m:02d}.xlsx")

    report_path = out_dir / f"report_{y}_{m:02d}.json"
    report_path.write_text(
        json.dumps(
            {
                "month": {"year": y, "month": m},
                "calendar_source": calendar_source,
                "solver_stats": {
                    "hours_spread": solve_stats.hours_spread,
                    "post_spreads": solve_stats.post_spreads,
                },
                "validation": report.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[OK] CSV  : {csv_path}")
    if xlsx_path is not None:
        print(f"[OK] XLSX : {xlsx_path}")
    print(f"[OK] Report: {report_path}")
    print(f"[INFO] violations={len(report.violations)}")
    print(f"[INFO] hours_spread={report.hours_spread}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
