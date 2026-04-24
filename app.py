from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime
import html
import json
from pathlib import Path
import secrets
from typing import Any

import pandas as pd
import streamlit as st

from shift_scheduler.calendar_api import CalendarAPIError, fetch_month_calendar
from shift_scheduler.exporters import export_csv_bytes, export_xlsx_bytes
from shift_scheduler.io import load_input_from_payload
from shift_scheduler.models import POSTS
from shift_scheduler.solver import (
    InfeasibleScheduleError,
    ShiftChangeRequest,
    SolverConfig,
    adjust_schedule_for_shift_change,
    generate_schedule,
)
from shift_scheduler.validate import validate_schedule


ROOT_DIR = Path(__file__).resolve().parent
SAMPLE_INPUT_PATH = ROOT_DIR / "examples" / "input.sample.json"
APP_BUILD = "2026-04-24-clickfix-9"
RESULT_SNAPSHOT_LIMIT = 12
RESULT_SNAPSHOT_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
MATRIX_WIDGET_KEY = "schedule_matrix_grid"

POST_CELL_THEME: dict[str, tuple[str, str]] = {
    "A": ("#dcecef", "#0f4a55"),
    "B": ("#d8e3f0", "#1a3e6e"),
    "C": ("#dfdcef", "#2f2b6b"),
    "D": ("#f4e2c8", "#734a0f"),
    "E": ("#efd3be", "#6b3312"),
    "F": ("#f0cfc9", "#7a1f16"),
    "G": ("#c9e3d4", "#0f4a2e"),
}

RULE_TITLES: dict[int, str] = {
    1: "不超過連續 6 天上班",
    2: "同一哨點不連兩天",
    3: "假日星期交替",
    4: "假日哨點 F/G 交替",
    5: "每人月總時數差距 <= 12h",
    6: "每個哨點分配次數差距 <= 1",
}

RULE_FIXES: dict[int, str] = {
    1: "把其中一天改休息或改由其他人代班。",
    2: "把其中一天改排到不同哨點。",
    3: "調整下一次假日班到不同星期（六/日交替）。",
    4: "把下一次假日哨點改成另一個（F/G 交替）。",
    5: "把高工時人員的班次換給低工時人員。",
    6: "把該哨點改分配給次數較少的人員。",
}


def _inject_ui_theme() -> None:
    st.markdown(
        """
<style>
:root,
[data-theme="light"] {
  --bg-app: #f3f1ec;
  --bg-surface: #ffffff;
  --bg-panel: #faf8f3;
  --bg-inset: #efeae0;
  --bg-hover: #f5f2ea;

  --ink-1: #1a1714;
  --ink-2: #3d3833;
  --ink-3: #6b645b;
  --ink-4: #9a9389;
  --ink-5: #c4beb3;

  --line-strong: #cfc8bb;
  --line: #e2ddd1;

  --accent: #1f5f4a;
  --accent-soft: #d9ebe3;
  --accent-ink: #0f3a2c;

  --ok: #1f6b4f;
  --ok-soft: #dbeee2;
  --warn: #8a5a1e;
  --danger: #9c2d27;
  --danger-soft: #f6d9d6;
  --danger-line: #d99a96;

  --holiday-bg: #f7ecd3;
  --holiday-ink: #7a5a1c;

  --post-A-bg: #dcecef;
  --post-A-ink: #0f4a55;
  --post-B-bg: #d8e3f0;
  --post-B-ink: #1a3e6e;
  --post-C-bg: #dfdcef;
  --post-C-ink: #2f2b6b;
  --post-D-bg: #f4e2c8;
  --post-D-ink: #734a0f;
  --post-E-bg: #efd3be;
  --post-E-ink: #6b3312;
  --post-F-bg: #f0cfc9;
  --post-F-ink: #7a1f16;
  --post-G-bg: #c9e3d4;
  --post-G-ink: #0f4a2e;
}

html, body, [class*="css"] {
  font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", system-ui, sans-serif;
}

.stApp {
  background: var(--bg-app);
}

.block-container {
  max-width: 1640px;
  padding-top: 0.65rem;
  padding-bottom: 2rem;
}

[data-testid="stSidebar"] {
  display: none;
}

.mono {
  font-family: "JetBrains Mono", "SF Mono", Menlo, monospace;
}

.topbar {
  max-width: 1640px;
  margin: 0 auto 0.7rem auto;
  padding: 0.25rem 0.15rem;
  display: flex;
  align-items: center;
  gap: 18px;
}

.topbar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-right: 14px;
  border-right: 1px solid var(--line);
}

.topbar-logo {
  width: 30px;
  height: 30px;
  border-radius: 7px;
  background: var(--ink-1);
  color: var(--bg-surface);
  display: grid;
  place-items: center;
  font-size: 14px;
  font-weight: 800;
}

.topbar-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--ink-1);
}

.topbar-title .sub {
  display: block;
  margin-top: 1px;
  color: var(--ink-3);
  font-size: 11px;
  font-weight: 500;
}

.topbar-links {
  display: flex;
  gap: 10px;
  color: var(--ink-3);
  font-size: 13px;
}

.topbar-links span {
  padding: 0.32rem 0.5rem;
  border-radius: 8px;
}

.topbar-links span.active {
  background: var(--bg-surface);
  border: 1px solid var(--line);
  color: var(--ink-1);
  font-weight: 600;
}

.left-nav {
  background: var(--bg-surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 0.78rem;
  margin-bottom: 0.8rem;
}

.left-nav-head {
  border: 1px solid var(--line);
  background: var(--bg-panel);
  border-radius: 10px;
  padding: 0.58rem 0.62rem;
  margin-bottom: 0.62rem;
}

.left-nav-head .main {
  margin: 0;
  color: var(--ink-1);
  font-size: 14px;
  font-weight: 800;
}

.left-nav-head .sub {
  margin: 0.18rem 0 0 0;
  color: var(--ink-3);
  font-size: 11px;
}

.left-nav-item {
  margin-top: 0.22rem;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 0.42rem 0.5rem;
  font-size: 13px;
  color: var(--ink-3);
}

.left-nav-item.active {
  background: var(--bg-panel);
  border-color: var(--line);
  color: var(--ink-1);
  font-weight: 700;
}

.status-banner {
  background: var(--bg-surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 16px 20px;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 20px;
  align-items: center;
  margin-bottom: 0.82rem;
}

.status-mark {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  font-size: 24px;
  font-weight: 800;
  border: 1.5px solid;
}

.status-mark.ok {
  background: var(--ok-soft);
  color: var(--ok);
  border-color: var(--ok);
}

.status-mark.bad {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: var(--danger);
}

.status-text .headline {
  font-size: 22px;
  font-weight: 800;
  color: var(--ink-1);
}

.status-text .headline .accent-ok {
  color: var(--ok);
}

.status-text .headline .accent-bad {
  color: var(--danger);
}

.status-text .sub {
  margin-top: 4px;
  font-size: 13px;
  color: var(--ink-3);
}

.status-kpis {
  display: flex;
  gap: 20px;
  padding-left: 18px;
  border-left: 1px solid var(--line);
}

.status-kpi {
  text-align: right;
}

.status-kpi .label {
  font-size: 11px;
  color: var(--ink-3);
}

.status-kpi .val {
  margin-top: 2px;
  font-family: "JetBrains Mono", "SF Mono", Menlo, monospace;
  font-size: 20px;
  font-weight: 700;
  color: var(--ink-1);
}

.status-kpi.warn .val {
  color: var(--warn);
}

.status-kpi.bad .val {
  color: var(--danger);
}

.main-card {
  background: var(--bg-surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
  margin-bottom: 0.84rem;
}

.main-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-panel);
}

.main-card-header h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--ink-1);
}

.legend-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.legend-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid var(--line);
  background: var(--bg-surface);
}

.legend-chip .dot {
  width: 9px;
  height: 9px;
  border-radius: 3px;
}

.legend-chip .label {
  color: var(--ink-2);
}

.legend-chip .hours {
  font-family: "JetBrains Mono", "SF Mono", Menlo, monospace;
  color: var(--ink-4);
  font-size: 10px;
}

.matrix-wrap {
  overflow-x: auto;
  padding: 4px 0;
}

.matrix {
  border-collapse: separate;
  border-spacing: 0;
  width: 100%;
  min-width: 1100px;
  font-size: 12px;
}

.matrix th, .matrix td {
  border-bottom: 1px solid var(--line);
  border-right: 1px solid var(--line);
  text-align: center;
  padding: 0;
  background: var(--bg-surface);
}

.matrix thead th {
  background: var(--bg-panel);
  font-weight: 600;
  color: var(--ink-3);
  padding: 6px 4px;
  font-size: 11px;
  line-height: 1.2;
}

.matrix thead th.holiday {
  background: var(--holiday-bg);
  color: var(--holiday-ink);
}

.matrix thead th .dom {
  font-family: "JetBrains Mono", "SF Mono", Menlo, monospace;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink-1);
  display: block;
}

.matrix thead th.holiday .dom {
  color: var(--holiday-ink);
}

.matrix thead th .dow {
  font-size: 10px;
  opacity: 0.75;
  display: block;
  margin-top: 1px;
}

.matrix .row-header {
  text-align: left;
  padding: 8px 12px;
  font-weight: 600;
  color: var(--ink-1);
  background: var(--bg-surface);
  width: 88px;
  min-width: 88px;
  max-width: 88px;
  border-right: 1px solid var(--line-strong);
}

.matrix td.holiday-col {
  background: var(--holiday-bg);
}

.matrix td.cell {
  width: 38px;
  min-width: 38px;
  max-width: 38px;
  height: 36px;
  position: relative;
}

.matrix td.cell.has-link {
  cursor: pointer;
}

.matrix td.cell.has-link:hover .cell-inner {
  outline: 2px solid var(--ink-1);
  outline-offset: -2px;
}

.matrix td.cell.selected .cell-inner {
  outline: 2.5px solid var(--accent);
  outline-offset: -2px;
}

.matrix td.cell .cell-form {
  width: 100%;
  height: 100%;
  margin: 0;
}

.matrix td.cell .cell-btn {
  all: unset;
  width: 100%;
  height: 100%;
  cursor: pointer;
  display: block;
}

.matrix td.cell .cell-btn:focus-visible .cell-inner {
  outline: 2px solid var(--ink-1);
  outline-offset: -2px;
}

.matrix td.cell .cell-inner {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  font-family: "JetBrains Mono", "SF Mono", Menlo, monospace;
  font-weight: 700;
  font-size: 13px;
}

.matrix td.cell.off .cell-inner {
  color: var(--ink-5);
}

.matrix td.cell.post-A .cell-inner { background: var(--post-A-bg); color: var(--post-A-ink); }
.matrix td.cell.post-B .cell-inner { background: var(--post-B-bg); color: var(--post-B-ink); }
.matrix td.cell.post-C .cell-inner { background: var(--post-C-bg); color: var(--post-C-ink); }
.matrix td.cell.post-D .cell-inner { background: var(--post-D-bg); color: var(--post-D-ink); }
.matrix td.cell.post-E .cell-inner { background: var(--post-E-bg); color: var(--post-E-ink); }
.matrix td.cell.post-F .cell-inner { background: var(--post-F-bg); color: var(--post-F-ink); }
.matrix td.cell.post-G .cell-inner { background: var(--post-G-bg); color: var(--post-G-ink); }

.matrix td.cell.violation .cell-inner {
  box-shadow: inset 0 0 0 2px var(--danger);
}

.matrix td.cell.violation::after {
  content: "!";
  position: absolute;
  top: 2px;
  right: 3px;
  width: 13px;
  height: 13px;
  border-radius: 999px;
  background: var(--danger);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  display: grid;
  place-items: center;
}

.matrix-row-summary {
  padding: 6px 10px;
  text-align: right;
  background: var(--bg-panel);
  font-family: "JetBrains Mono", "SF Mono", Menlo, monospace;
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-3);
  min-width: 70px;
}

.matrix tr:last-child td {
  border-bottom: none;
}

.matrix th:last-child, .matrix td:last-child {
  border-right: none;
}

.section-title {
  margin: 0.1rem 0 0.42rem 0;
  color: var(--ink-1);
  font-size: 1.02rem;
  font-weight: 800;
}

.danger-card {
  border: 1px solid var(--danger-line);
  border-left: 4px solid var(--danger);
  background: var(--danger-soft);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
}

.danger-card .head {
  margin: 0;
  color: var(--danger);
  font-size: 12px;
  font-weight: 800;
}

.danger-card .msg {
  margin: 3px 0 0 0;
  color: var(--ink-1);
  font-size: 13px;
}

.danger-card .fix {
  margin: 6px 0 0 0;
  color: var(--ink-3);
  font-size: 11px;
}

.audit-row {
  display: grid;
  grid-template-columns: 18px 1fr auto;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg-panel);
  padding: 8px 10px;
  margin-bottom: 6px;
}

.audit-row.fail {
  border-color: var(--danger-line);
  background: var(--danger-soft);
}

.audit-row .dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--ok);
}

.audit-row.fail .dot {
  background: var(--danger);
}

.audit-row .name {
  margin: 0;
  font-size: 12px;
  font-weight: 700;
  color: var(--ink-1);
}

.audit-row .meas {
  margin: 2px 0 0 0;
  font-size: 11px;
  color: var(--ink-3);
}

.audit-row .badge {
  font-family: "JetBrains Mono", "SF Mono", Menlo, monospace;
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  padding: 2px 6px;
}

.audit-row.pass .badge {
  background: var(--ok-soft);
  color: var(--ok);
}

.audit-row.fail .badge {
  background: var(--danger);
  color: #fff;
}

.hours-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.hours-row {
  display: grid;
  grid-template-columns: 52px 1fr auto;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.hours-row .name {
  color: var(--ink-2);
  font-weight: 600;
}

.hours-row .bar {
  position: relative;
  height: 8px;
  background: var(--bg-inset);
  border-radius: 99px;
  overflow: hidden;
}

.hours-row .fill {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: var(--ink-3);
  border-radius: 99px;
}

.hours-row.max .fill { background: var(--warn); }
.hours-row.min .fill { background: var(--accent); }

.hours-row .val {
  font-family: "JetBrains Mono", "SF Mono", Menlo, monospace;
  font-size: 11px;
  color: var(--ink-2);
  font-weight: 600;
}

.hours-summary {
  display: flex;
  justify-content: space-between;
  padding-top: 9px;
  margin-top: 8px;
  border-top: 1px dashed var(--line);
  font-size: 11px;
  color: var(--ink-3);
}

.hours-summary .val {
  font-family: "JetBrains Mono", "SF Mono", Menlo, monospace;
  color: var(--ink-1);
  font-weight: 700;
}

.empty-state {
  border: 1px dashed #c8c0b5;
  border-radius: 12px;
  padding: 14px;
  background: #fffdfa;
}

.empty-state h3 {
  margin: 0;
  color: var(--ink-1);
}

.empty-state p {
  margin: 0.3rem 0 0 0;
  color: var(--ink-3);
}

.stButton button,
.stDownloadButton button {
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--bg-surface);
  color: var(--ink-1);
  font-weight: 600;
}

.stButton button[kind="primary"] {
  background: var(--ink-1);
  color: var(--bg-surface);
  border-color: var(--ink-1);
}

[data-baseweb="input"] > div,
[data-baseweb="select"] > div {
  border-color: var(--line) !important;
  background: var(--bg-surface);
}

[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: var(--line) !important;
  background: var(--bg-surface);
  border-radius: 14px !important;
}

.stTabs [data-baseweb="tab-list"] {
  gap: 2px;
  background: var(--bg-panel);
  padding: 0.55rem 0.7rem 0 0.7rem;
  border-bottom: 1px solid var(--line);
}

.stTabs [data-baseweb="tab"] {
  border-radius: 0;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--ink-3);
  font-size: 12px;
  font-weight: 600;
  background: transparent;
}

.stTabs [aria-selected="true"] {
  color: var(--ink-1) !important;
  border-bottom-color: var(--ink-1) !important;
}

[data-testid="stDataFrame"] {
  border: 1px solid var(--line);
  border-radius: 10px;
}
</style>
""",
        unsafe_allow_html=True,
    )


def _render_topbar() -> None:
    st.markdown(
        f"""
<div class="topbar">
  <div class="topbar-brand">
    <div class="topbar-logo">保</div>
    <div class="topbar-title">
      保全排班工具
      <span class="sub">Security Scheduler · Handoff Style · BUILD: {APP_BUILD}</span>
    </div>
  </div>
  <div class="topbar-links">
    <span class="active">Schedule Matrix</span>
    <span>Swap Management</span>
    <span>Rules & Compliance</span>
    <span>Export</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_left_navigation() -> None:
    st.markdown(
        """
<div class="left-nav">
  <div class="left-nav-head">
    <p class="main">Guard Operations</p>
    <p class="sub">Scheduling Console</p>
  </div>
  <div class="left-nav-item">Dashboard</div>
  <div class="left-nav-item active">Schedule Matrix</div>
  <div class="left-nav-item">Swap Management</div>
  <div class="left-nav-item">Rules & Compliance</div>
  <div class="left-nav-item">Reports</div>
</div>
""",
        unsafe_allow_html=True,
    )


def _load_payload_from_ui(mode: str, uploaded_file: Any) -> dict[str, object]:
    if mode == "使用範例資料":
        return json.loads(SAMPLE_INPUT_PATH.read_text(encoding="utf-8"))
    if uploaded_file is None:
        raise ValueError("請先上傳 JSON 檔案")
    raw = uploaded_file.getvalue().decode("utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("JSON 根層必須是 object")
    return payload


def _build_schedule_table(schedule: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for guard in schedule.guards:
        row: dict[str, str] = {"人員": guard.name}
        for day in schedule.days:
            key = f"{day.date.month:02d}-{day.date.day:02d}"
            row[key] = day.assignments[guard.id] or "休"
        rows.append(row)
    return rows


def _post_text(post: str | None) -> str:
    return post if post is not None else "休"


def _build_impact_preview_payload(
    base_schedule: Any,
    adjusted_schedule: Any,
    base_report: Any,
    adjusted_report: Any,
    guard_name_by_id: dict[str, str],
) -> dict[str, Any]:
    changed_cells: list[dict[str, str]] = []
    changed_dates: set[str] = set()
    guard_changed_count: dict[str, int] = {}

    for old_day, new_day in zip(base_schedule.days, adjusted_schedule.days):
        ds = old_day.date.isoformat()
        for gid, before_post in old_day.assignments.items():
            after_post = new_day.assignments.get(gid)
            if before_post == after_post:
                continue
            changed_dates.add(ds)
            guard_changed_count[gid] = guard_changed_count.get(gid, 0) + 1
            changed_cells.append(
                {
                    "日期": ds,
                    "人員": guard_name_by_id.get(gid, gid),
                    "調整": f"{_post_text(before_post)} → {_post_text(after_post)}",
                }
            )

    def _violation_key(v: Any) -> tuple[int, str, str, str]:
        return (int(v.rule), str(v.guard_id), str(v.date or ""), str(v.message))

    def _violation_to_row(v: Any) -> dict[str, str]:
        guard_label = "全體" if v.guard_id == "*" else guard_name_by_id.get(v.guard_id, v.guard_id)
        return {
            "規則": f"規則 {v.rule}",
            "人員": guard_label,
            "日期": v.date or "整月統計",
            "說明": _friendly_violation_message(v.message),
        }

    base_by_key = {_violation_key(v): v for v in base_report.violations}
    adjusted_by_key = {_violation_key(v): v for v in adjusted_report.violations}
    resolved_keys = sorted(set(base_by_key) - set(adjusted_by_key))
    new_keys = sorted(set(adjusted_by_key) - set(base_by_key))

    hour_changes: list[dict[str, str]] = []
    for guard_id, guard_name in guard_name_by_id.items():
        before_h = int(base_report.hours_by_guard.get(guard_id, 0))
        after_h = int(adjusted_report.hours_by_guard.get(guard_id, 0))
        if before_h == after_h:
            continue
        hour_changes.append(
            {
                "人員": guard_name,
                "原工時": f"{before_h}h",
                "新工時": f"{after_h}h",
                "差值": f"{after_h - before_h:+}h",
            }
        )

    impacted_guards = sorted(
        [
            {"人員": guard_name_by_id.get(gid, gid), "調整格數": changed_count}
            for gid, changed_count in guard_changed_count.items()
        ],
        key=lambda x: (-int(x["調整格數"]), x["人員"]),
    )

    return {
        "changed_cells": changed_cells,
        "changed_dates": sorted(changed_dates),
        "impacted_guards": impacted_guards,
        "resolved_violations": [_violation_to_row(base_by_key[k]) for k in resolved_keys],
        "new_violations": [_violation_to_row(adjusted_by_key[k]) for k in new_keys],
        "hour_changes": hour_changes,
    }


def _friendly_violation_message(message: str) -> str:
    if message.startswith("consecutive work days ="):
        days = message.split("=", maxsplit=1)[1].split("(", maxsplit=1)[0].strip()
        return f"連續上班 {days} 天，超過 6 天上限。"
    if message.startswith("same post repeated on consecutive days:"):
        post = message.rsplit(":", maxsplit=1)[-1].strip()
        return f"相鄰兩個上班日都排到同一哨點 {post}。"
    if message == "holiday weekday did not alternate (Sat/Sun)":
        return "假日班沒有做到六日交替。"
    if message.startswith("holiday post did not alternate:"):
        post = message.rsplit(":", maxsplit=1)[-1].strip()
        return f"假日哨點沒有交替，連續排到 {post}。"
    if message.startswith("hours spread ="):
        spread = message.split("=", maxsplit=1)[1].split("(", maxsplit=1)[0].strip()
        return f"本月工時落差 {spread} 小時，超過 12 小時。"
    if message.startswith("post ") and " spread =" in message:
        post = message.split("post ", maxsplit=1)[1].split(" spread", maxsplit=1)[0].strip()
        spread = message.split("=", maxsplit=1)[1].split("(", maxsplit=1)[0].strip()
        return f"哨點 {post} 的分配差距是 {spread}，超過 1。"
    return message


def _build_violations_table(report: Any, guard_name_by_id: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for v in report.violations:
        rows.append(
            {
                "規則": f"規則 {v.rule}：{RULE_TITLES.get(v.rule, '未命名規則')}",
                "人員": "全體" if v.guard_id == "*" else guard_name_by_id.get(v.guard_id, v.guard_id),
                "日期": v.date if v.date else "整月統計",
                "說明": _friendly_violation_message(v.message),
                "建議": RULE_FIXES.get(v.rule, "請調整該班次後再重新檢查。"),
                "rule_id": v.rule,
                "guard_id": v.guard_id,
            }
        )
    return rows


def _build_audit_table(report: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for a in report.audits:
        rows.append(
            {
                "規則": f"規則 {a.rule}：{a.name}",
                "門檻": a.threshold,
                "實測值": a.measured,
                "結果": "通過" if a.passed else "未通過",
            }
        )
    return rows


def _render_status_banner(
    violations_count: int,
    hours_spread: int,
    max_post_spread: int,
    officers: int,
) -> None:
    ok = violations_count == 0 and hours_spread <= 12 and max_post_spread <= 1
    mark_cls = "ok" if ok else "bad"
    headline = (
        '班表檢查 <span class="accent-ok">通過</span> · 可以公告'
        if ok
        else f'班表 <span class="accent-bad">需要調整</span> · 有 {violations_count} 筆違規'
    )
    sub = (
        f"六條規則全部通過，{officers} 位人員本月排班已完成。"
        if ok
        else "點擊下方違規卡片查看位置與建議解法，再使用調班精靈修復。"
    )
    st.markdown(
        f"""
<div class="status-banner">
  <div class="status-mark {mark_cls}">{'✓' if ok else '!'}</div>
  <div class="status-text">
    <div class="headline">{headline}</div>
    <div class="sub">{html.escape(sub)}</div>
  </div>
  <div class="status-kpis">
    <div class="status-kpi">
      <div class="label">人員</div>
      <div class="val">{officers}</div>
    </div>
    <div class="status-kpi {'bad' if hours_spread > 12 else ('warn' if hours_spread > 8 else '')}">
      <div class="label">工時差距</div>
      <div class="val">{hours_spread}h</div>
    </div>
    <div class="status-kpi {'bad' if max_post_spread > 1 else ''}">
      <div class="label">哨點差距</div>
      <div class="val">{max_post_spread}</div>
    </div>
    <div class="status-kpi {'bad' if violations_count else ''}">
      <div class="label">違規</div>
      <div class="val">{violations_count}</div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _clear_selected_cell_state() -> None:
    st.session_state.pop("selected_shift_cell", None)
    st.session_state["reset_matrix_selection"] = True
    token = _read_pick_query_token()
    if token:
        st.session_state["last_consumed_pick_token"] = token


def _save_result_snapshot(result: dict[str, Any]) -> str:
    key = secrets.token_urlsafe(9)
    RESULT_SNAPSHOT_CACHE[key] = result
    RESULT_SNAPSHOT_CACHE.move_to_end(key)
    while len(RESULT_SNAPSHOT_CACHE) > RESULT_SNAPSHOT_LIMIT:
        RESULT_SNAPSHOT_CACHE.popitem(last=False)
    st.session_state["result_snapshot_key"] = key
    return key


def _selection_token(guard_id: str, date_iso: str, post: str, solver_seed: int, nonce: int) -> str:
    return f"{guard_id}__{date_iso}__{post}__{solver_seed}__{nonce}"


def _parse_selection_token(token: str) -> dict[str, Any] | None:
    parts = token.split("__")
    if len(parts) < 2:
        return None
    guard_id, date_iso = parts[0], parts[1]
    if not guard_id or not date_iso:
        return None

    post_hint: str | None = None
    seed_hint: int | None = None
    if len(parts) >= 3:
        p3 = parts[2]
        if p3 in POSTS:
            post_hint = p3
    if len(parts) >= 4:
        try:
            seed_hint = int(parts[3])
        except ValueError:
            seed_hint = None

    return {
        "guard_id": guard_id,
        "date_iso": date_iso,
        "post_hint": post_hint,
        "seed_hint": seed_hint,
    }


def _consume_selection_query(schedule: Any) -> None:
    token = _read_pick_query_token()
    if not token:
        return

    parsed = _parse_selection_token(token)
    if parsed is None:
        if "pick" in st.query_params:
            del st.query_params["pick"]
        return
    guard_id = str(parsed["guard_id"])
    date_iso = str(parsed["date_iso"])

    day_map = {d.date.isoformat(): d for d in schedule.days}
    day = day_map.get(date_iso)
    if day is None:
        if "pick" in st.query_params:
            del st.query_params["pick"]
        return
    if day.assignments.get(guard_id) is None:
        if "pick" in st.query_params:
            del st.query_params["pick"]
        return

    new_cell = {"guard_id": guard_id, "date": date_iso}
    st.session_state["selected_shift_cell"] = new_cell
    # Any fresh pick token means the user just clicked a shift cell.
    # Always open the wizard, even when clicking the same cell repeatedly.
    st.session_state["last_consumed_pick_token"] = token
    st.session_state["swap_dialog_open"] = True
    if "pick" in st.query_params:
        del st.query_params["pick"]


def _read_pick_query_token() -> str:
    raw = st.query_params.get("pick")
    if isinstance(raw, list):
        return str(raw[0]) if raw else ""
    return str(raw or "")


def _read_result_snapshot_key() -> str:
    raw = st.query_params.get("rk")
    if isinstance(raw, list):
        return str(raw[0]) if raw else ""
    return str(raw or "")


def _try_restore_result_from_snapshot() -> bool:
    snapshot_key = _read_result_snapshot_key()
    if not snapshot_key:
        return False
    cached = RESULT_SNAPSHOT_CACHE.get(snapshot_key)
    if not isinstance(cached, dict):
        return False
    st.session_state["result"] = cached
    st.session_state["result_snapshot_key"] = snapshot_key
    return True


def _resolve_selected_cell(schedule: Any) -> dict[str, str] | None:
    raw = st.session_state.get("selected_shift_cell")
    if not isinstance(raw, dict):
        return None

    guard_id = str(raw.get("guard_id", ""))
    date_iso = str(raw.get("date", ""))
    if not guard_id or not date_iso:
        return None

    day_map = {d.date.isoformat(): d for d in schedule.days}
    if date_iso not in day_map:
        return None
    day = day_map[date_iso]
    post = day.assignments.get(guard_id)
    if post is None:
        return None
    guard_map = {g.id: g.name for g in schedule.guards}
    if guard_id not in guard_map:
        return None

    return {
        "guard_id": guard_id,
        "guard_name": guard_map[guard_id],
        "date": date_iso,
        "post": post,
    }


def _matrix_day_label(day: Any) -> str:
    dow_map = ["一", "二", "三", "四", "五", "六", "日"]
    return f"{day.date.day:02d}({dow_map[day.date.weekday()]})"


def _build_matrix_dataframe(
    schedule: Any,
    report: Any,
    hours_by_guard: dict[str, int],
    selected_cell: dict[str, str] | None,
) -> tuple[pd.DataFrame, pd.io.formats.style.Styler, dict[str, str], list[str]]:
    day_columns: list[str] = []
    date_by_column: dict[str, str] = {}
    holiday_columns: set[str] = set()
    for day in schedule.days:
        column_label = _matrix_day_label(day)
        day_columns.append(column_label)
        date_by_column[column_label] = day.date.isoformat()
        if day.is_holiday:
            holiday_columns.add(column_label)

    row_guard_ids: list[str] = []
    row_labels: list[str] = []
    rows: list[dict[str, str]] = []
    style_rows: list[dict[str, str]] = []
    violation_cells = {
        (v.guard_id, str(v.date))
        for v in report.violations
        if v.guard_id != "*" and v.date
    }

    for guard in schedule.guards:
        row_guard_ids.append(guard.id)
        row_labels.append(guard.name)
        row: dict[str, str] = {}
        style_row: dict[str, str] = {}
        for day in schedule.days:
            column_label = _matrix_day_label(day)
            date_iso = day.date.isoformat()
            post = day.assignments.get(guard.id)
            value = post or "休"
            row[column_label] = value

            css: list[str] = [
                "text-align: center",
                "font-family: 'JetBrains Mono', 'SF Mono', Menlo, monospace",
                "font-weight: 700",
            ]
            if post is None:
                css.append("background-color: #faf8f3")
                css.append("color: #b4aca2")
                if column_label in holiday_columns:
                    css.append("background-color: #f7ecd3")
                    css.append("color: #7a5a1c")
            else:
                bg, ink = POST_CELL_THEME[post]
                css.append(f"background-color: {bg}")
                css.append(f"color: {ink}")
            if (guard.id, date_iso) in violation_cells:
                css.append("box-shadow: inset 0 0 0 2px #9c2d27")
            if (
                selected_cell is not None
                and selected_cell.get("guard_id") == guard.id
                and selected_cell.get("date") == date_iso
            ):
                css.append("outline: 2px solid #1f5f4a")
                css.append("outline-offset: -2px")
            style_row[column_label] = "; ".join(css)

        row["月工時"] = f"{hours_by_guard.get(guard.id, 0)}h"
        style_row["月工時"] = (
            "text-align: center; font-family: 'JetBrains Mono', 'SF Mono', Menlo, monospace; "
            "font-weight: 700; background-color: #f4f1ea; color: #1a1714"
        )
        rows.append(row)
        style_rows.append(style_row)

    df = pd.DataFrame(rows, index=row_labels)
    style_df = pd.DataFrame(style_rows, index=row_labels)
    styler = df.style.apply(lambda _: style_df, axis=None)
    styler = styler.set_table_styles(
        [
            {
                "selector": "th",
                "props": "background-color: #faf8f3; color: #6b645b; font-weight: 700;",
            },
            {
                "selector": "th.col_heading",
                "props": "font-size: 11px; text-align: center;",
            },
            {
                "selector": "th.row_heading",
                "props": "background-color: #ffffff; color: #1a1714; font-weight: 700;",
            },
        ]
    )
    return df, styler, date_by_column, row_guard_ids


def _matrix_selection_default(
    schedule: Any, selected_cell: dict[str, str] | None
) -> dict[str, dict[str, list[tuple[int, str]] | list[int] | list[str]]] | None:
    if selected_cell is None:
        return None

    guard_lookup = {g.id: idx for idx, g in enumerate(schedule.guards)}
    row_idx = guard_lookup.get(str(selected_cell.get("guard_id", "")))
    date_iso = str(selected_cell.get("date", ""))
    if row_idx is None or not date_iso:
        return None

    for day in schedule.days:
        if day.date.isoformat() == date_iso:
            return {"selection": {"rows": [], "columns": [], "cells": [(row_idx, _matrix_day_label(day))]}}
    return None


def _consume_matrix_selection(
    schedule: Any,
    matrix_event: Any,
    date_by_column: dict[str, str],
    row_guard_ids: list[str],
) -> None:
    if matrix_event is None:
        return

    selection = matrix_event.get("selection", {}) if isinstance(matrix_event, dict) else getattr(matrix_event, "selection", {})
    cells = selection.get("cells", []) if isinstance(selection, dict) else []
    if not cells:
        return

    cell = cells[0]
    if not isinstance(cell, (list, tuple)) or len(cell) != 2:
        return

    row_idx, column_name = cell
    if not isinstance(row_idx, int) or not isinstance(column_name, str):
        return
    if row_idx < 0 or row_idx >= len(row_guard_ids):
        return

    date_iso = date_by_column.get(column_name)
    if not date_iso:
        _clear_selected_cell_state()
        st.session_state["swap_dialog_open"] = False
        return

    guard_id = row_guard_ids[row_idx]
    day_map = {d.date.isoformat(): d for d in schedule.days}
    day = day_map.get(date_iso)
    if day is None:
        return

    if day.assignments.get(guard_id) is None:
        _clear_selected_cell_state()
        st.session_state["swap_dialog_open"] = False
        return

    st.session_state["selected_shift_cell"] = {"guard_id": guard_id, "date": date_iso}
    st.session_state["swap_dialog_open"] = True


def _build_matrix_html(
    schedule: Any,
    report: Any,
    hours_by_guard: dict[str, int],
    selected_cell: dict[str, str] | None,
    solver_seed: int,
    result_snapshot_key: str | None,
    pick_nonce: int,
) -> str:
    dow_map = ["一", "二", "三", "四", "五", "六", "日"]
    violation_cells = {
        (v.guard_id, v.date)
        for v in report.violations
        if v.guard_id != "*" and v.date
    }

    header_cells: list[str] = []
    for day in schedule.days:
        d_cls = "holiday" if day.is_holiday else ""
        dom = day.date.day
        dow = dow_map[day.date.weekday()]
        header_cells.append(
            f'<th class="{d_cls}"><span class="dom">{dom}</span><span class="dow">{dow}</span></th>'
        )

    body_rows: list[str] = []
    for guard in schedule.guards:
        row_cells = [f'<td class="row-header">{html.escape(guard.name)}</td>']
        for day in schedule.days:
            day_iso = day.date.isoformat()
            post = day.assignments[guard.id]
            classes = ["cell"]
            is_selected = (
                selected_cell is not None
                and selected_cell.get("guard_id") == guard.id
                and selected_cell.get("date") == day_iso
            )
            if is_selected:
                classes.append("selected")
            if post:
                classes.append(f"post-{post}")
            else:
                classes.append("off")
            if day.is_holiday:
                classes.append("holiday-col")
            if (guard.id, day_iso) in violation_cells:
                classes.append("violation")
            if post is None:
                row_cells.append(
                    f'<td class="{" ".join(classes)}"><div class="cell-inner">·</div></td>'
                )
            else:
                classes.append("has-link")
                token = _selection_token(guard.id, day_iso, post, solver_seed, pick_nonce)
                rk_hidden = (
                    f'<input type="hidden" name="rk" value="{html.escape(result_snapshot_key)}" />'
                    if result_snapshot_key
                    else ""
                )
                row_cells.append(
                    f'<td class="{" ".join(classes)}">'
                    '<form class="cell-form" method="get">'
                    f'<input type="hidden" name="pick" value="{html.escape(token)}" />'
                    f"{rk_hidden}"
                    '<button class="cell-btn" type="submit">'
                    f'<div class="cell-inner">{post}</div>'
                    "</button>"
                    "</form>"
                    "</td>"
                )

        row_cells.append(f'<td class="matrix-row-summary">{hours_by_guard.get(guard.id, 0)}h</td>')
        body_rows.append("<tr>" + "".join(row_cells) + "</tr>")

    legend_chips: list[str] = []
    for pid in ["A", "B", "C", "D", "E", "F", "G"]:
        legend_chips.append(
            (
                '<span class="legend-chip">'
                f'<span class="dot" style="background: var(--post-{pid}-bg)"></span>'
                f'<span class="label">{pid}</span>'
                f'<span class="hours">{POSTS[pid].hours}h</span>'
                "</span>"
            )
        )

    return (
        '<div class="main-card">'
        '<div class="main-card-header">'
        f'<h2>班表矩陣 · {schedule.year}-{schedule.month:02d}</h2>'
        f'<div class="legend-inline">{"".join(legend_chips)}</div>'
        "</div>"
        '<div class="matrix-wrap">'
        '<table class="matrix">'
        "<thead><tr>"
        '<th class="row-header" style="background: var(--bg-panel)">人員</th>'
        f'{"".join(header_cells)}'
        '<th class="matrix-row-summary">月工時</th>'
        "</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        "</div>"
        "</div>"
    )


def _render_violation_cards(violations: list[dict[str, Any]]) -> None:
    if not violations:
        st.success("目前沒有違規，班表可直接使用。")
        return
    for row in violations:
        st.markdown(
            f"""
<div class="danger-card">
  <p class="head">{html.escape(row["規則"])} · {html.escape(row["人員"])} · {html.escape(row["日期"])}</p>
  <p class="msg">{html.escape(row["說明"])}</p>
  <p class="fix"><strong>建議：</strong>{html.escape(row["建議"])}</p>
</div>
""",
            unsafe_allow_html=True,
        )


def _render_audit_rows(report: Any) -> None:
    for audit in report.audits:
        cls = "pass" if audit.passed else "fail"
        badge = "PASS" if audit.passed else "ALERT"
        st.markdown(
            f"""
<div class="audit-row {cls}">
  <span class="dot"></span>
  <div>
    <p class="name">R{audit.rule} {html.escape(audit.name)}</p>
    <p class="meas">{html.escape(audit.measured)}</p>
  </div>
  <span class="badge">{badge}</span>
</div>
""",
            unsafe_allow_html=True,
        )


def _render_hours_distribution(schedule_obj: Any, report: Any) -> None:
    vals = list(report.hours_by_guard.values())
    if not vals:
        st.write("無資料")
        return
    min_v = min(vals)
    max_v = max(vals)
    avg_v = sum(vals) / len(vals)
    spread = max_v - min_v
    denom = max(max_v - min_v, 1)

    bars: list[str] = []
    for guard in schedule_obj.guards:
        h = report.hours_by_guard.get(guard.id, 0)
        width = int(((h - min_v) / denom) * 85) + 15
        width = min(max(width, 15), 100)
        cls = "max" if h == max_v else ("min" if h == min_v else "")
        bars.append(
            f"""
<div class="hours-row {cls}">
  <span class="name">{html.escape(guard.name)}</span>
  <div class="bar"><div class="fill" style="width:{width}%"></div></div>
  <span class="val">{h}h</span>
</div>
"""
        )

    st.markdown(
        f"""
<div class="hours-list">
  {"".join(bars)}
</div>
<div class="hours-summary">
  <span>平均 <span class="val">{avg_v:.0f}h</span></span>
  <span>差距 <span class="val">{spread}h</span></span>
</div>
""",
        unsafe_allow_html=True,
    )


def _suggest_feasible_payback_dates(
    schedule_obj: Any,
    carry_over: dict[str, Any],
    borrow_date: str,
    requester: str,
    substitute: str,
    payback_candidates: list[str],
    attempts: int,
    seed: int | None,
    limit: int = 5,
) -> list[str]:
    feasible: list[str] = []
    base_seed = seed if seed is not None else 20260423
    per_try_attempts = max(200, min(1200, attempts))

    for idx, candidate_date in enumerate(payback_candidates):
        try:
            adjust_schedule_for_shift_change(
                schedule=schedule_obj,
                carry_over=carry_over,
                request=ShiftChangeRequest(
                    borrow_date=borrow_date,
                    requester_guard_id=requester,
                    substitute_guard_id=substitute,
                    payback_date=candidate_date,
                ),
                config=SolverConfig(attempts=per_try_attempts, seed=base_seed + idx),
            )
            feasible.append(candidate_date)
            if len(feasible) >= limit:
                break
        except InfeasibleScheduleError:
            continue

    return feasible


def _render_shift_change_section(
    result: dict[str, Any],
    attempts: int,
    seed_input: str,
    effective_today: date,
    override_today_enabled: bool,
    selected_cell: dict[str, str] | None,
) -> None:
    schedule_obj = result["schedule"]
    base_report = result["report"]
    carry_over = result.get("carry_over", {})
    guard_name_by_id = {g.id: g.name for g in schedule_obj.guards}
    guard_ids = [g.id for g in schedule_obj.guards]
    day_assignments = {d.date.isoformat(): d.assignments for d in schedule_obj.days}
    date_options = [d.date.isoformat() for d in schedule_obj.days]
    today_iso = effective_today.isoformat()
    editable_date_options = [ds for ds in date_options if ds >= today_iso]

    if not editable_date_options:
        st.info("本月已無可調整日期（只允許修改今天與未來日期）。")
        return

    if selected_cell is None:
        st.info("請先在上方班表矩陣點一格有班的格子（今天或未來）再開始調班。")
        return

    if override_today_enabled:
        st.info(f"測試模式已啟用：今天視為 {today_iso}")
    st.caption(f"可調班日期：{editable_date_options[0]} ～ {editable_date_options[-1]}（今天以前鎖定）")

    borrow_date = selected_cell["date"]
    requester = selected_cell["guard_id"]
    requester_post = selected_cell["post"]
    if borrow_date not in editable_date_options:
        st.warning("目前選到的是今天以前的日期，不能調班。請改點今天或未來的格子。")
        return
    if borrow_date not in day_assignments:
        st.warning("選取格子不在當前月份，請重新點選。")
        return

    borrow_map = day_assignments[borrow_date]
    if borrow_map.get(requester) is None:
        st.warning("這格目前不是值班狀態，請改點有班的格子。")
        return

    selected_token = f"{requester}__{borrow_date}"
    if st.session_state.get("swap_selection_token") != selected_token:
        st.session_state["swap_selection_token"] = selected_token
        for k in [
            "swap_substitute_radio",
            "swap_payback_radio",
            "swap_preview_key",
            "swap_preview_payload",
        ]:
            st.session_state.pop(k, None)

    info_left, info_right = st.columns([4, 1])
    with info_left:
        st.markdown(
            (
                f"**借班格已選取**：{guard_name_by_id[requester]} "
                f"在 `{borrow_date}` 的 `{requester_post}` 班（{POSTS[requester_post].hours}h）"
            )
        )
    with info_right:
        if st.button("取消選取", key="clear_selected_cell"):
            _clear_selected_cell_state()
            st.session_state["swap_dialog_open"] = False
            st.rerun()

    substitute_options = [gid for gid in guard_ids if gid != requester and borrow_map.get(gid) is None]
    if not substitute_options:
        st.info("這組條件目前沒有可代班人，請換一天或換原值班人。")
        return

    substitute = st.radio(
        "代班人候選（借班日當天原本休息）",
        options=substitute_options,
        format_func=lambda gid: guard_name_by_id[gid],
        key="swap_substitute_radio",
    )

    requester_hours = POSTS[requester_post].hours if requester_post is not None else None
    payback_candidates: list[str] = []
    for ds in editable_date_options:
        if ds == borrow_date:
            continue
        if day_assignments[ds].get(requester) is not None:
            continue
        substitute_post = day_assignments[ds].get(substitute)
        if substitute_post is None:
            continue
        if requester_hours is None:
            continue
        if POSTS[substitute_post].hours != requester_hours:
            continue
        payback_candidates.append(ds)

    if not payback_candidates:
        st.info("這組條件目前沒有可還班日期。請換借班日、原值班人或代班人。")
        return

    payback_date = st.radio(
        "合法還班日候選（可早於或晚於借班日）",
        options=payback_candidates,
        format_func=lambda ds: (
            f"{ds}｜{day_assignments[ds].get(substitute)} 班｜"
            f"{POSTS[day_assignments[ds].get(substitute)].hours}h"
        ),
        key="swap_payback_radio",
    )
    payback_post = day_assignments[payback_date].get(substitute)
    st.caption(
        f"還班內容：{payback_date} 的 {payback_post} 班，由 {guard_name_by_id[substitute]} 還給 {guard_name_by_id[requester]}"
    )

    try:
        seed_for_adjust = int(seed_input) if seed_input.strip() else None
    except ValueError:
        st.error("隨機種子格式錯誤，請輸入整數或留空。")
        return

    preview_key = "|".join(
        [
            borrow_date,
            requester,
            substitute,
            payback_date,
            str(int(attempts)),
            str(seed_for_adjust),
        ]
    )
    if st.session_state.get("swap_preview_key") != preview_key:
        try:
            adjusted_schedule, adjusted_stats, adjust_meta = adjust_schedule_for_shift_change(
                schedule=schedule_obj,
                carry_over=carry_over,
                request=ShiftChangeRequest(
                    borrow_date=borrow_date,
                    requester_guard_id=requester,
                    substitute_guard_id=substitute,
                    payback_date=payback_date,
                ),
                config=SolverConfig(attempts=int(attempts), seed=seed_for_adjust),
            )
            adjusted_report = validate_schedule(adjusted_schedule, carry_over=carry_over)
            impact_preview = _build_impact_preview_payload(
                base_schedule=schedule_obj,
                adjusted_schedule=adjusted_schedule,
                base_report=base_report,
                adjusted_report=adjusted_report,
                guard_name_by_id=guard_name_by_id,
            )
            st.session_state["swap_preview_key"] = preview_key
            st.session_state["swap_preview_payload"] = {
                "status": "success",
                "schedule": adjusted_schedule,
                "stats": adjusted_stats,
                "meta": adjust_meta,
                "report": adjusted_report,
                "impact": impact_preview,
            }
        except InfeasibleScheduleError as exc:
            feasible_payback_dates = _suggest_feasible_payback_dates(
                schedule_obj=schedule_obj,
                carry_over=carry_over,
                borrow_date=borrow_date,
                requester=requester,
                substitute=substitute,
                payback_candidates=payback_candidates,
                attempts=int(attempts),
                seed=seed_for_adjust,
                limit=5,
            )
            st.session_state["swap_preview_key"] = preview_key
            st.session_state["swap_preview_payload"] = {
                "status": "failed",
                "error": str(exc),
                "suggestions": feasible_payback_dates,
            }

    preview = st.session_state.get("swap_preview_payload")
    if not isinstance(preview, dict):
        st.info("請先選擇代班人與還班日。")
        return

    if preview.get("status") != "success":
        st.error(f"預覽失敗：{preview.get('error', '未知錯誤')}")
        suggestions = preview.get("suggestions", [])
        if suggestions:
            st.info("可行還班日建議：" + "、".join(suggestions))
        return

    adjusted_schedule = preview["schedule"]
    adjusted_stats = preview["stats"]
    adjust_meta = preview["meta"]
    adjusted_report = preview["report"]
    impact_preview = preview.get("impact", {})

    st.markdown("**送出前影響預覽**")
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("預計調整格數", adjust_meta["changed_cells"])
    p2.metric("影響日期數", len(adjust_meta.get("changed_dates", [])))
    p3.metric("違規數", f"{len(base_report.violations)} → {len(adjusted_report.violations)}")
    p4.metric("工時差距", f"{base_report.hours_spread}h → {adjusted_report.hours_spread}h")

    changed_dates = adjust_meta.get("changed_dates", [])
    if changed_dates:
        sample = "、".join(changed_dates[:8])
        suffix = "…" if len(changed_dates) > 8 else ""
        st.caption(f"影響日期：{sample}{suffix}")

    impacted_guards = impact_preview.get("impacted_guards", []) if isinstance(impact_preview, dict) else []
    if impacted_guards:
        preview_guards = "、".join(
            [f"{row['人員']}（{row['調整格數']} 格）" for row in impacted_guards[:4]]
        )
        if len(impacted_guards) > 4:
            preview_guards += "…"
        st.caption(f"主要受影響人員：{preview_guards}")

    new_violations = impact_preview.get("new_violations", []) if isinstance(impact_preview, dict) else []
    resolved_violations = (
        impact_preview.get("resolved_violations", []) if isinstance(impact_preview, dict) else []
    )
    if new_violations:
        st.warning(f"此調班會新增 {len(new_violations)} 筆違規。送出前請確認。")
    if resolved_violations:
        st.success(f"此調班會消除 {len(resolved_violations)} 筆既有違規。")

    with st.expander("影響明細（送出前）", expanded=False):
        changed_cells = impact_preview.get("changed_cells", []) if isinstance(impact_preview, dict) else []
        if changed_cells:
            st.markdown("**班格變更（最多顯示 30 筆）**")
            st.dataframe(changed_cells[:30], hide_index=True, use_container_width=True)
        else:
            st.write("沒有偵測到班格變化。")

        hour_changes = impact_preview.get("hour_changes", []) if isinstance(impact_preview, dict) else []
        if hour_changes:
            st.markdown("**工時變化**")
            st.dataframe(hour_changes, hide_index=True, use_container_width=True)

        if resolved_violations:
            st.markdown("**會被修復的違規**")
            st.dataframe(resolved_violations, hide_index=True, use_container_width=True)

        if new_violations:
            st.markdown("**可能新增的違規**")
            st.dataframe(new_violations, hide_index=True, use_container_width=True)

    if not st.button("確認送出調班請求", type="primary", key="apply_shift_change"):
        return

    adjusted_guard_map = {g.id: g.name for g in adjusted_schedule.guards}
    report_payload = {
        "month": {"year": adjusted_schedule.year, "month": adjusted_schedule.month},
        "calendar_source": "taiwan_calendar_api",
        "solver_stats": {
            "hours_spread": adjusted_stats.hours_spread,
            "post_spreads": adjusted_stats.post_spreads,
        },
        "adjustment": adjust_meta,
        "validation": adjusted_report.to_dict(),
    }

    adjustment_note = (
        f"調班完成：借班 {borrow_date}、還班 {payback_date}，系統自動調整 {adjust_meta['changed_cells']} 格"
    )
    st.session_state["result"] = {
        "schedule": adjusted_schedule,
        "report": adjusted_report,
        "schedule_table": _build_schedule_table(adjusted_schedule),
        "violations_table": _build_violations_table(adjusted_report, adjusted_guard_map),
        "audit_table": _build_audit_table(adjusted_report),
        "csv_bytes": export_csv_bytes(adjusted_schedule),
        "xlsx_bytes": export_xlsx_bytes(adjusted_schedule, adjusted_report),
        "report_bytes": json.dumps(report_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        "file_stem": f"schedule_{adjusted_schedule.year}_{adjusted_schedule.month:02d}",
        "calendar_note": result["calendar_note"],
        "calendar_fallback": bool(result.get("calendar_fallback", False)),
        "solver_seed": int(result.get("solver_seed", 0)),
        "carry_over": carry_over,
        "adjustment_result": {
            "status": "success",
            "borrow_date": borrow_date,
            "payback_date": payback_date,
            "changed_cells": adjust_meta["changed_cells"],
            "message": adjustment_note,
        },
    }
    _save_result_snapshot(st.session_state["result"])
    _clear_selected_cell_state()
    st.session_state["swap_dialog_open"] = False
    for k in ["swap_substitute_radio", "swap_payback_radio", "swap_preview_key", "swap_preview_payload"]:
        st.session_state.pop(k, None)
    st.rerun()


@st.dialog("調班精靈", width="large", dismissible=False)
def _shift_change_dialog_body(
    result: dict[str, Any],
    attempts: int,
    seed_input: str,
    effective_today: date,
    override_today_enabled: bool,
    selected_cell: dict[str, str] | None,
) -> None:
    _render_shift_change_section(
        result=result,
        attempts=attempts,
        seed_input=seed_input,
        effective_today=effective_today,
        override_today_enabled=override_today_enabled,
        selected_cell=selected_cell,
    )
    if st.button("關閉", key="close_swap_dialog_button"):
        _clear_selected_cell_state()
        st.session_state["swap_dialog_open"] = False
        st.rerun()


def _show_shift_change_dialog(
    result: dict[str, Any],
    attempts: int,
    seed_input: str,
    effective_today: date,
    override_today_enabled: bool,
    selected_cell: dict[str, str] | None,
) -> None:
    _shift_change_dialog_body(
        result=result,
        attempts=attempts,
        seed_input=seed_input,
        effective_today=effective_today,
        override_today_enabled=override_today_enabled,
        selected_cell=selected_cell,
    )


def _generate_and_store_result(
    year: int,
    month: int,
    source_mode: str,
    uploaded: Any,
    attempts: int,
    seed_input: str,
    preserve_consumed_pick: bool = False,
    forced_seed: int | None = None,
) -> None:
    pick_token = _read_pick_query_token()
    if pick_token:
        st.session_state.pop("selected_shift_cell", None)
        if preserve_consumed_pick:
            st.session_state["last_consumed_pick_token"] = pick_token
        else:
            st.session_state.pop("last_consumed_pick_token", None)
    else:
        _clear_selected_cell_state()
    st.session_state["swap_dialog_open"] = False
    for k in [
        "swap_selection_token",
        "swap_substitute_radio",
        "swap_payback_radio",
        "swap_preview_key",
        "swap_preview_payload",
    ]:
        st.session_state.pop(k, None)

    payload = _load_payload_from_ui(source_mode, uploaded)
    input_data = load_input_from_payload(payload)
    if forced_seed is not None:
        seed = int(forced_seed)
    elif seed_input.strip():
        seed = int(seed_input)
    else:
        # Keep runs reproducible even when user leaves seed empty.
        seed = secrets.randbelow(2_147_483_647)

    calendar_source = "taiwan_calendar_api"
    calendar_fallback = False
    try:
        cal = fetch_month_calendar(year=int(year), month=int(month))
        holidays = set(cal.holidays)
        day_types = cal.day_types
        calendar_note = f"API 已套用：放假日 {len(cal.holidays)} 天，上班日 {len(cal.workdays)} 天"
    except CalendarAPIError as exc:
        # Fallback keeps the app usable if API is temporarily unavailable.
        holidays = set(input_data.holidays)
        day_types = None
        calendar_source = "fallback_weekend_plus_input_holidays"
        calendar_fallback = True
        calendar_note = (
            "行事曆 API 暫時不可用，已改用備援日曆（週六日視為放假日，並套用輸入檔 holidays）。"
            f" 原因：{exc}"
        )

    schedule, solver_stats = generate_schedule(
        year=int(year),
        month=int(month),
        guards=input_data.guards,
        holidays=holidays,
        day_types=day_types,
        carry_over=input_data.carry_over,
        config=SolverConfig(attempts=int(attempts), seed=seed),
    )
    report = validate_schedule(schedule, carry_over=input_data.carry_over)
    guard_name_by_id = {g.id: g.name for g in schedule.guards}

    report_payload = {
        "month": {"year": int(year), "month": int(month)},
        "calendar_source": calendar_source,
        "solver_stats": {
            "seed": seed,
            "hours_spread": solver_stats.hours_spread,
            "post_spreads": solver_stats.post_spreads,
        },
        "validation": report.to_dict(),
    }

    st.session_state["result"] = {
        "schedule": schedule,
        "report": report,
        "schedule_table": _build_schedule_table(schedule),
        "violations_table": _build_violations_table(report, guard_name_by_id),
        "audit_table": _build_audit_table(report),
        "csv_bytes": export_csv_bytes(schedule),
        "xlsx_bytes": export_xlsx_bytes(schedule, report),
        "report_bytes": json.dumps(report_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        "file_stem": f"schedule_{int(year)}_{int(month):02d}",
        "calendar_note": calendar_note,
        "calendar_fallback": calendar_fallback,
        "solver_seed": seed,
        "carry_over": input_data.carry_over,
        "adjustment_result": None,
    }
    _save_result_snapshot(st.session_state["result"])


def main() -> None:
    st.set_page_config(
        page_title="保全排班工具",
        page_icon="📅",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _inject_ui_theme()
    _render_topbar()

    now = datetime.now()
    system_today = now.date()

    shell_left, shell_main = st.columns([1.12, 4], gap="large")

    with shell_left:
        _render_left_navigation()

        with st.container(border=True):
            st.markdown('<p class="panel-title">產生班表 <span class="hint">自動求解</span></p>', unsafe_allow_html=True)
            ycol, mcol = st.columns(2)
            year = ycol.number_input("年份", min_value=2020, max_value=2100, value=now.year, step=1, key="ui_year")
            month = mcol.number_input("月份", min_value=1, max_value=12, value=now.month, step=1, key="ui_month")
            source_mode = st.selectbox("輸入來源", options=["使用範例資料", "上傳 JSON"], index=0, key="ui_source")
            uploaded = st.file_uploader(
                "上傳 JSON 檔案",
                type=["json"],
                accept_multiple_files=False,
                disabled=(source_mode != "上傳 JSON"),
                key="ui_upload",
            )
            run_clicked = st.button("產生排班", type="primary", use_container_width=True)

        with st.container(border=True):
            st.markdown('<p class="panel-title">進階參數 <span class="hint">保留全部功能</span></p>', unsafe_allow_html=True)
            attempts = st.slider("求解嘗試次數", min_value=100, max_value=3000, value=500, step=100, key="ui_attempts")
            seed_input = st.text_input("隨機種子（可留空）", value="", key="ui_seed")
            override_today_enabled = st.toggle("測試模式：自訂今天日期", value=False, key="ui_override_today")
            if override_today_enabled:
                effective_today = st.date_input("測試用今天日期", value=system_today, key="ui_today")
            else:
                effective_today = system_today

        with st.expander("輸入格式說明（JSON）", expanded=False):
            st.code(SAMPLE_INPUT_PATH.read_text(encoding="utf-8"), language="json")

    if run_clicked:
        existing_pick = _read_pick_query_token()
        if existing_pick:
            st.session_state["last_consumed_pick_token"] = existing_pick
            st.session_state.pop("selected_shift_cell", None)
            st.session_state["swap_dialog_open"] = False
        try:
            _generate_and_store_result(
                year=int(year),
                month=int(month),
                source_mode=source_mode,
                uploaded=uploaded,
                attempts=int(attempts),
                seed_input=seed_input,
                preserve_consumed_pick=bool(existing_pick),
                forced_seed=None,
            )
        except CalendarAPIError as exc:
            st.error(f"無法取得行事曆 API，請稍後重試：{exc}")
        except InfeasibleScheduleError as exc:
            st.error(f"排班失敗：{exc}")
        except Exception as exc:
            st.error(f"資料格式或執行錯誤：{exc}")

    result = st.session_state.get("result")
    if result is None:
        _try_restore_result_from_snapshot()
        result = st.session_state.get("result")
    pick_token = _read_pick_query_token()
    if result is None and pick_token:
        parsed_pick = _parse_selection_token(pick_token)
        auto_year, auto_month = int(year), int(month)
        forced_seed_from_pick: int | None = None
        if parsed_pick is not None:
            picked_date = str(parsed_pick["date_iso"])
            seed_hint = parsed_pick.get("seed_hint")
            if isinstance(seed_hint, int):
                forced_seed_from_pick = seed_hint
            try:
                picked = date.fromisoformat(picked_date)
                auto_year, auto_month = picked.year, picked.month
            except ValueError:
                pass

        auto_source = source_mode
        auto_uploaded = uploaded
        used_sample_fallback = False
        if auto_source == "上傳 JSON" and auto_uploaded is None:
            auto_source = "使用範例資料"
            used_sample_fallback = True

        try:
            _generate_and_store_result(
                year=auto_year,
                month=auto_month,
                source_mode=auto_source,
                uploaded=auto_uploaded,
                attempts=int(attempts),
                seed_input=seed_input,
                preserve_consumed_pick=False,
                forced_seed=forced_seed_from_pick,
            )
            result = st.session_state.get("result")
            if used_sample_fallback:
                st.warning("點擊事件已收到，但原上傳檔未保留；暫以範例資料恢復班表。")
        except Exception as exc:
            st.error(f"偵測到班表點擊，但自動恢復失敗：{exc}")

    with shell_main:
        if not result:
            st.markdown(
                """
<div class="empty-state">
  <h3>尚未產生班表</h3>
  <p>請在左側設定年月與輸入資料，按「產生排班」後即可看到矩陣、違規卡片與調班精靈。</p>
</div>
""",
                unsafe_allow_html=True,
            )
            return

        schedule_obj = result["schedule"]
        report = result["report"]
        violations_count = len(report.violations)
        max_post_spread = max(report.post_spreads.values())
        officers = len(schedule_obj.guards)
        _consume_selection_query(schedule_obj)
        selected_cell = _resolve_selected_cell(schedule_obj)
        if st.session_state.pop("reset_matrix_selection", False):
            st.session_state.pop(MATRIX_WIDGET_KEY, None)

        top_l, top_r = st.columns([1.8, 1.2], gap="large")
        with top_l:
            st.markdown(f'**作業月份：<span class="mono">{schedule_obj.year}-{schedule_obj.month:02d}</span>**', unsafe_allow_html=True)
            calendar_note = result.get("calendar_note")
            if isinstance(calendar_note, str) and calendar_note:
                if bool(result.get("calendar_fallback")):
                    st.warning(calendar_note)
                else:
                    st.info(calendar_note)
        with top_r:
            b1, b2, b3 = st.columns(3)
            b1.download_button(
                label="CSV",
                data=result["csv_bytes"],
                file_name=f"{result['file_stem']}.csv",
                mime="text/csv",
                use_container_width=True,
            )
            b2.download_button(
                label="Excel",
                data=result["xlsx_bytes"],
                file_name=f"{result['file_stem']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            b3.download_button(
                label="JSON",
                data=result["report_bytes"],
                file_name=f"report_{result['file_stem'].replace('schedule_', '')}.json",
                mime="application/json",
                use_container_width=True,
            )

        adjustment_result = result.get("adjustment_result")
        if isinstance(adjustment_result, dict):
            msg = str(adjustment_result.get("message", "")).strip()
            if adjustment_result.get("status") == "success" and msg:
                st.success(f"本次調班成功：{msg}")

        _render_status_banner(
            violations_count=violations_count,
            hours_spread=report.hours_spread,
            max_post_spread=max_post_spread,
            officers=officers,
        )

        matrix_df, matrix_styler, date_by_column, row_guard_ids = _build_matrix_dataframe(
            schedule=schedule_obj,
            report=report,
            hours_by_guard=report.hours_by_guard,
            selected_cell=selected_cell,
        )
        day_column_config = {
            col: st.column_config.TextColumn(col, width="small")
            for col in matrix_df.columns
            if col != "月工時"
        }
        day_column_config["月工時"] = st.column_config.TextColumn("月工時", width="small")

        with st.container(border=True):
            st.markdown(
                f"""
<div class="main-card-header" style="margin:-1rem -1rem 0.75rem -1rem; border-bottom:1px solid var(--line);">
  <h2>班表矩陣 · {schedule_obj.year}-{schedule_obj.month:02d}</h2>
  <div class="legend-inline">
    <span class="legend-chip"><span class="dot" style="background:#dcecef"></span><span class="label">A</span><span class="hours">10h</span></span>
    <span class="legend-chip"><span class="dot" style="background:#d8e3f0"></span><span class="label">B</span><span class="hours">10h</span></span>
    <span class="legend-chip"><span class="dot" style="background:#dfdcef"></span><span class="label">C</span><span class="hours">10h</span></span>
    <span class="legend-chip"><span class="dot" style="background:#f4e2c8"></span><span class="label">D</span><span class="hours">12h</span></span>
    <span class="legend-chip"><span class="dot" style="background:#efd3be"></span><span class="label">E</span><span class="hours">12h</span></span>
    <span class="legend-chip"><span class="dot" style="background:#f0cfc9"></span><span class="label">F</span><span class="hours">12h</span></span>
    <span class="legend-chip"><span class="dot" style="background:#c9e3d4"></span><span class="label">G</span><span class="hours">12h</span></span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
            matrix_event = st.dataframe(
                matrix_styler,
                key=MATRIX_WIDGET_KEY,
                use_container_width=True,
                hide_index=False,
                on_select="rerun",
                selection_mode="single-cell",
                selection_default=_matrix_selection_default(schedule_obj, selected_cell),
                row_height=38,
                column_config=day_column_config,
            )
        _consume_matrix_selection(schedule_obj, matrix_event, date_by_column, row_guard_ids)
        selected_cell = _resolve_selected_cell(schedule_obj)
        st.caption("點班表中的班別格子即可開啟調班精靈（同頁操作）。")
        if selected_cell is not None:
            st.caption(
                f"目前已選取：{selected_cell['guard_name']}｜{selected_cell['date']}｜{selected_cell['post']} 班"
            )
        else:
            st.session_state["swap_dialog_open"] = False

        if st.session_state.get("swap_dialog_open") and selected_cell is not None:
            _show_shift_change_dialog(
                result=result,
                attempts=int(attempts),
                seed_input=seed_input,
                effective_today=effective_today,
                override_today_enabled=override_today_enabled,
                selected_cell=selected_cell,
            )

        bottom_l, bottom_r = st.columns([1.2, 1], gap="large")
        with bottom_l:
            v_tab, a_tab = st.tabs(["違規清單", "六條規則稽核"])
            with v_tab:
                _render_violation_cards(result["violations_table"])
            with a_tab:
                _render_audit_rows(report)

            with st.expander("查看完整稽核證據", expanded=False):
                st.dataframe(result["audit_table"], hide_index=True, use_container_width=True)
                for audit in report.audits:
                    with st.expander(f"規則 {audit.rule}：{audit.name}"):
                        st.write(f"門檻：`{audit.threshold}`")
                        st.write(f"實測：`{audit.measured}`")
                        st.json(audit.evidence)

        with bottom_r:
            with st.container(border=True):
                st.markdown('<p class="section-title">調班精靈</p>', unsafe_allow_html=True)
                if selected_cell is None:
                    st.caption("請先點班表格子，再在彈窗裡完成調班。")
                else:
                    st.caption(
                        f"已選取：{selected_cell['guard_name']}｜{selected_cell['date']}｜{selected_cell['post']} 班"
                    )
                    if st.button("開啟調班精靈", type="primary", use_container_width=True, key="open_swap_dialog"):
                        st.session_state["swap_dialog_open"] = True
                        st.rerun()

            with st.container(border=True):
                st.markdown('<p class="section-title">月工時分布</p>', unsafe_allow_html=True)
                _render_hours_distribution(schedule_obj, report)

            with st.expander("完整班表資料（表格）", expanded=False):
                st.dataframe(result["schedule_table"], use_container_width=True, hide_index=True)
            with st.expander("完整違規資料（表格）", expanded=False):
                visible_rows = [
                    {
                        "規則": r["規則"],
                        "人員": r["人員"],
                        "日期": r["日期"],
                        "說明": r["說明"],
                        "建議": r["建議"],
                    }
                    for r in result["violations_table"]
                ]
                if visible_rows:
                    st.dataframe(visible_rows, hide_index=True, use_container_width=True)
                else:
                    st.write("無違規。")


if __name__ == "__main__":
    main()
