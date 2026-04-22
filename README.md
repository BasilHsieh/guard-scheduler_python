# Guard Scheduler Side Project

Lightweight monthly guard scheduling tool for a real-world court security use case.

This repository is intentionally small and interview-friendly:
- clear spec
- deterministic rule engine
- CSV/XLSX output
- no backend required
- GUI for non-technical users (Streamlit)

## Problem

Manual Excel scheduling takes about one hour per month and is easy to break when balancing:
- max consecutive work days
- post rotation
- weekend alternation
- monthly hours fairness

## What This MVP Does

- Generates a monthly schedule for 6 guards
- Fetches workday/holiday from Taiwan calendar API
- Applies 6 business rules
- Supports shift-change workflow (borrow shift + payback + auto-repair remaining days)
- Exports roster to CSV and Excel
- Produces a JSON validation report with fairness metrics

## Project Structure

- `app.py`: Streamlit UI
- `docs/SPEC_V1.md`: initial product + rule specification
- `docs/SPEC_V2.md`: current functional specification (latest)
- `shift_scheduler/`: scheduling engine and CLI
- `examples/input.sample.json`: sample input
- `outputs/`: generated files (ignored by git if you add `.gitignore`)

## Quick Start (UI for General Users)

```bash
cd /Users/basil/Desktop/projects/guard-scheduler-sideproject
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

In browser:
- choose year/month
- choose sample data or upload your own JSON
- system auto-fetches Taiwan calendar API to classify workday/holiday
- click "產生排班"
- download CSV / XLSX / JSON report

## CLI (Optional)

```bash
python3 -m shift_scheduler --input examples/input.sample.json --year 2026 --month 5
# fallback mode (if you want to force JSON holidays):
python3 -m shift_scheduler --input examples/input.sample.json --year 2026 --month 5 --use-input-holidays
```

CLI generated files:
- `outputs/schedule_2026_05.csv`
- `outputs/schedule_2026_05.xlsx`
- `outputs/report_2026_05.json`

## Input Contract

See `examples/input.sample.json`.

Important fields:
- `guards`: guard list (`id`, `name`)
- `holidays`: optional fallback list (`YYYY-MM-DD`) when not using API
- `carry_over`: previous-month state per guard (optional but recommended)

## Notes

- Rules `1-4` are treated as hard constraints.
- Rules `5-6` are optimized as fairness objectives.
- If a fully feasible schedule cannot be found, the CLI exits with an error.
