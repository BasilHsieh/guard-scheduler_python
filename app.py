from __future__ import annotations

from datetime import date, datetime
import html
import json
from pathlib import Path
from typing import Any

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

RULE_TITLES: dict[int, str] = {
    1: "不超過連續 6 天上班",
    2: "同一哨點不連兩天",
    3: "假日星期交替",
    4: "假日哨點 F/G 交替",
    5: "每人月總時數差距 <= 12h",
    6: "每個哨點分配次數差距 <= 1",
}


def _inject_ui_theme() -> None:
    st.markdown(
        """
<style>
:root {
    --app-bg: #e5e7eb;
    --surface: #f8fafc;
    --panel: #f3f4f6;
    --card: #ffffff;
    --line: #d1d5db;
    --ink: #111827;
    --muted: #6b7280;
    --brand: #0f766e;
    --brand-soft: #d9f2ec;
    --danger: #b91c1c;
    --danger-soft: #fff1f2;
    --ok: #047857;
}

html, body, [class*="css"] {
    font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
}

.stApp {
    background: var(--app-bg);
}

.block-container {
    max-width: 1580px;
    padding-top: 0.9rem;
    padding-bottom: 1.6rem;
}

[data-testid="stSidebar"] {
    display: none;
}

.shell-topbar {
    border: 1px solid var(--line);
    border-radius: 12px;
    background: var(--card);
    padding: 0.7rem 1.05rem;
    margin-bottom: 0.85rem;
}

.shell-topbar .brand {
    margin: 0;
    color: var(--ink);
    font-size: 1.7rem;
    font-weight: 800;
    line-height: 1.1;
}

.shell-topbar .menu {
    margin-top: 0.22rem;
    color: var(--muted);
    font-size: 0.95rem;
}

.rail-card {
    border: 1px solid var(--line);
    border-radius: 14px;
    background: var(--panel);
    padding: 0.8rem 0.75rem;
    margin-bottom: 0.75rem;
}

.rail-brand {
    border: 1px solid #d5dae0;
    border-radius: 12px;
    background: var(--card);
    padding: 0.62rem 0.72rem;
}

.rail-brand .name {
    margin: 0;
    color: var(--ink);
    font-size: 1.05rem;
    font-weight: 800;
}

.rail-brand .sub {
    margin: 0.2rem 0 0 0;
    color: var(--muted);
    font-size: 0.78rem;
}

.nav-item {
    border: 1px solid transparent;
    border-radius: 10px;
    background: transparent;
    color: #374151;
    font-size: 0.92rem;
    padding: 0.5rem 0.58rem;
    margin-top: 0.34rem;
}

.nav-item.active {
    border-color: #cfd5dd;
    background: var(--card);
    color: #111827;
    font-weight: 700;
}

.main-header {
    border: 1px solid var(--line);
    border-radius: 14px;
    background: var(--surface);
    padding: 0.85rem 1rem;
    margin-bottom: 0.75rem;
}

.breadcrumbs {
    margin: 0;
    color: #6b7280;
    font-size: 0.8rem;
}

.page-title {
    margin: 0.25rem 0 0 0;
    color: #111827;
    font-size: 2.2rem;
    font-weight: 800;
    line-height: 1.1;
}

.page-subtitle {
    margin: 0.34rem 0 0 0;
    color: #4b5563;
    font-size: 1rem;
}

.kpi-strip {
    border: 1px solid var(--line);
    border-radius: 13px;
    background: var(--card);
    padding: 0.75rem 0.95rem;
    margin-bottom: 0.75rem;
}

.kpi-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.56rem;
}

.kpi {
    border: 1px solid #d5dbe3;
    border-radius: 10px;
    background: #f8fafc;
    padding: 0.55rem 0.62rem;
}

.kpi.ok {
    border-color: #9cd9c9;
    background: #ecfdf5;
}

.kpi.bad {
    border-color: #f2b6bb;
    background: #fff1f2;
}

.kpi .label {
    margin: 0;
    color: #6b7280;
    font-size: 0.78rem;
}

.kpi .value {
    margin: 0.18rem 0 0 0;
    color: #111827;
    font-size: 1.35rem;
    font-weight: 800;
}

.kpi .hint {
    margin: 0.2rem 0 0 0;
    color: #6b7280;
    font-size: 0.74rem;
}

.matrix-panel {
    border: 1px solid var(--line);
    border-radius: 13px;
    background: var(--card);
    overflow: hidden;
    margin-bottom: 0.8rem;
}

.matrix-header {
    border-bottom: 1px solid var(--line);
    padding: 0.75rem 0.95rem;
    background: #f9fafb;
}

.matrix-title {
    margin: 0;
    color: #111827;
    font-size: 1rem;
    font-weight: 700;
}

.legend-row {
    margin-top: 0.46rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.36rem;
}

.legend-chip {
    border-radius: 8px;
    border: 1px solid #d3dae3;
    background: #ffffff;
    color: #374151;
    font-size: 0.75rem;
    padding: 0.18rem 0.45rem;
}

.section-title {
    margin: 0.1rem 0 0.42rem 0;
    color: #111827;
    font-size: 1.02rem;
    font-weight: 800;
}

.rule-card {
    border: 1px solid #d5dbe4;
    border-radius: 10px;
    background: #ffffff;
    padding: 0.5rem 0.58rem;
    margin-bottom: 0.37rem;
}

.rule-card.pass {
    border-color: #9cdcc9;
    background: #f1fdf8;
}

.rule-card.fail {
    border-color: #f2b8bf;
    background: #fff4f5;
}

.rule-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.45rem;
}

.rule-name {
    margin: 0;
    color: #1f2937;
    font-size: 0.84rem;
    font-weight: 700;
}

.rule-badge {
    border-radius: 999px;
    padding: 0.1rem 0.45rem;
    font-size: 0.68rem;
    font-weight: 700;
}

.rule-card.pass .rule-badge {
    color: #065f46;
    border: 1px solid #8fdac0;
    background: #eafbf3;
}

.rule-card.fail .rule-badge {
    color: #991b1b;
    border: 1px solid #efb4bc;
    background: #fff0f2;
}

.rule-meta {
    margin: 0.22rem 0 0 0;
    color: #556070;
    font-size: 0.75rem;
}

.danger-card {
    border: 1px solid #f4bdc4;
    border-left: 5px solid var(--danger);
    border-radius: 12px;
    background: var(--danger-soft);
    padding: 0.65rem 0.8rem;
    margin-bottom: 0.52rem;
}

.danger-title {
    margin: 0;
    color: #7f1d1d;
    font-size: 0.94rem;
    font-weight: 800;
}

.danger-body {
    margin: 0.2rem 0 0 0;
    color: #7f1d1d;
    font-size: 0.84rem;
}

.empty-state {
    border: 1px dashed #bfc7d2;
    border-radius: 12px;
    padding: 0.95rem 1rem;
    background: #ffffffd8;
}

.empty-state h3 {
    margin: 0;
    color: #111827;
}

.empty-state p {
    margin: 0.28rem 0 0 0;
    color: #556070;
}

[data-testid="stDataFrame"] {
    border: 1px solid #d6dde5;
    border-radius: 10px;
}

.stButton button, .stDownloadButton button {
    border-radius: 10px;
}
</style>
""",
        unsafe_allow_html=True,
    )


def _render_shell_topbar() -> None:
    st.markdown(
        """
<section class="shell-topbar">
  <p class="brand">Security Scheduler</p>
  <p class="menu">Generate Schedule ・ Export ・ Rule Compliance</p>
</section>
""",
        unsafe_allow_html=True,
    )


def _render_left_navigation() -> None:
    st.markdown(
        """
<section class="rail-card">
  <div class="rail-brand">
    <p class="name">Guard Operations</p>
    <p class="sub">Scheduling Console</p>
  </div>
  <div class="nav-item">Dashboard</div>
  <div class="nav-item active">Schedule Matrix</div>
  <div class="nav-item">Swap Management</div>
  <div class="nav-item">Rules & Compliance</div>
  <div class="nav-item">Reports</div>
</section>
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


def _build_violations_table(
    report: Any, guard_name_by_id: dict[str, str]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for v in report.violations:
        rows.append(
            {
                "規則": f"規則 {v.rule}：{RULE_TITLES.get(v.rule, '未命名規則')}",
                "人員": "全體" if v.guard_id == "*" else guard_name_by_id.get(v.guard_id, v.guard_id),
                "日期": v.date if v.date else "整月統計",
                "說明": _friendly_violation_message(v.message),
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


def _build_hours_table(report: Any, guard_name_by_id: dict[str, str]) -> list[dict[str, str]]:
    if not report.hours_by_guard:
        return []
    avg_hours = sum(report.hours_by_guard.values()) / len(report.hours_by_guard)
    rows: list[dict[str, str]] = []
    for gid, hours in sorted(report.hours_by_guard.items(), key=lambda x: x[1], reverse=True):
        rows.append(
            {
                "人員": guard_name_by_id.get(gid, gid),
                "總工時": f"{hours}h",
                "與平均差距": f"{hours - avg_hours:+.1f}h",
            }
        )
    return rows


def _build_post_spread_table(report: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for post_id in sorted(report.post_spreads.keys()):
        spread = report.post_spreads[post_id]
        rows.append(
            {
                "哨點": post_id,
                "分配差距": str(spread),
                "狀態": "正常" if spread <= 1 else "超標",
            }
        )
    return rows


def _render_main_header() -> None:
    st.markdown(
        """
<section class="main-header">
  <p class="breadcrumbs">Scheduling &nbsp;›&nbsp; Interactive Matrix</p>
  <h2 class="page-title">Schedule Matrix</h2>
  <p class="page-subtitle">排班生成、規則檢查與調班修復都在同一頁完成。</p>
</section>
""",
        unsafe_allow_html=True,
    )


def _render_kpi_strip(
    officers: int,
    status_text: str,
    violations_count: int,
    hours_spread: int,
    max_post_spread: int,
) -> None:
    status_cls = "ok" if violations_count == 0 else "bad"
    st.markdown(
        f"""
<section class="kpi-strip">
  <div class="kpi-grid">
    <div class="kpi">
      <p class="label">總人數</p>
      <p class="value">{officers}</p>
      <p class="hint">本月排班參與人員</p>
    </div>
    <div class="kpi {status_cls}">
      <p class="label">排班狀態</p>
      <p class="value">{html.escape(status_text)}</p>
      <p class="hint">依六條規則檢查</p>
    </div>
    <div class="kpi {'ok' if hours_spread <= 12 else 'bad'}">
      <p class="label">工時差距</p>
      <p class="value">{hours_spread}h</p>
      <p class="hint">規則上限 12h</p>
    </div>
    <div class="kpi {'ok' if max_post_spread <= 1 else 'bad'}">
      <p class="label">哨點分配差距</p>
      <p class="value">{max_post_spread}</p>
      <p class="hint">規則上限 1</p>
    </div>
  </div>
</section>
""",
        unsafe_allow_html=True,
    )


def _render_matrix_header() -> None:
    legend_items = []
    for pid in ["A", "B", "C", "D", "E", "F", "G"]:
        legend_items.append(
            f'<span class="legend-chip">{pid}（{POSTS[pid].hours}h）</span>'
        )
    legend_html = "".join(legend_items)

    st.markdown(
        f"""
<div class="matrix-panel">
  <div class="matrix-header">
    <p class="matrix-title">Shift Legend</p>
    <div class="legend-row">{legend_html}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_rule_health_panel(report: Any) -> None:
    st.markdown('<p class="section-title">Rules & Compliance</p>', unsafe_allow_html=True)
    for audit in report.audits:
        status_class = "pass" if audit.passed else "fail"
        badge = "PASS" if audit.passed else "ALERT"
        st.markdown(
            f"""
<div class="rule-card {status_class}">
  <div class="rule-head">
    <p class="rule-name">R{audit.rule}. {html.escape(audit.name)}</p>
    <span class="rule-badge">{badge}</span>
  </div>
  <p class="rule-meta">{html.escape(audit.measured)}</p>
</div>
""",
            unsafe_allow_html=True,
        )


def _render_violation_cards(violations_rows: list[dict[str, str]]) -> None:
    st.markdown('<p class="section-title">Critical Rule Violations</p>', unsafe_allow_html=True)
    if not violations_rows:
        st.success("目前沒有違規，排班可直接使用。")
        return
    for row in violations_rows:
        st.markdown(
            f"""
<div class="danger-card">
  <p class="danger-title">{html.escape(row['規則'])}</p>
  <p class="danger-body">{html.escape(row['說明'])}（{html.escape(row['人員'])} / {html.escape(row['日期'])}）</p>
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
) -> None:
    schedule_obj = result["schedule"]
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

    if override_today_enabled:
        st.info(f"測試模式已啟用：今天視為 {today_iso}")

    st.caption(f"可調班日期：{editable_date_options[0]} ～ {editable_date_options[-1]}（今天以前鎖定）")

    borrow_date = st.selectbox(
        "借班日（原值班人臨時有事）",
        options=editable_date_options,
        key="swap_borrow_date",
    )
    borrow_map = day_assignments[borrow_date]
    requester_options = [gid for gid in guard_ids if borrow_map.get(gid) is not None]

    if not requester_options:
        st.info("這天沒有人有班可借，請換一天。")
        return

    requester = st.selectbox(
        "原值班人",
        options=requester_options,
        format_func=lambda gid: guard_name_by_id[gid],
        key="swap_requester",
    )
    requester_post = borrow_map.get(requester)
    substitute_options = [
        gid for gid in guard_ids if gid != requester and borrow_map.get(gid) is None
    ]
    if requester_post is not None:
        st.caption(f"借班內容：{guard_name_by_id[requester]} 在 {borrow_date} 的 {requester_post} 班")

    if not substitute_options:
        st.info("這組條件目前沒有可代班人，請換一天或換原值班人。")
        return

    substitute = st.selectbox(
        "代班人（借班日當天原本休息）",
        options=substitute_options,
        format_func=lambda gid: guard_name_by_id[gid],
        key="swap_substitute",
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

    payback_date = st.selectbox(
        "還班日（可早於或晚於借班日）",
        options=payback_candidates,
        key="swap_payback_date",
    )
    payback_post = day_assignments[payback_date].get(substitute)
    st.caption(
        f"還班內容：{payback_date} 的 {payback_post} 班，由 {guard_name_by_id[substitute]} 還給 {guard_name_by_id[requester]}"
    )

    if not st.button("套用調班並自動修復剩餘班表", type="primary", key="apply_shift_change"):
        return

    try:
        seed_for_adjust = int(seed_input) if seed_input.strip() else None
    except ValueError:
        st.error("隨機種子格式錯誤，請輸入整數或留空。")
        return

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
            "carry_over": carry_over,
            "adjustment_result": {
                "status": "success",
                "borrow_date": borrow_date,
                "payback_date": payback_date,
                "changed_cells": adjust_meta["changed_cells"],
                "message": adjustment_note,
            },
        }
        st.rerun()
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
        st.error(f"本次調班失敗：{exc}")
        if feasible_payback_dates:
            st.info("可行還班日建議：" + "、".join(feasible_payback_dates))
        else:
            st.info("此組借班條件目前找不到可行還班日，請改借班日或代班人。")


def main() -> None:
    st.set_page_config(
        page_title="保全排班工具",
        page_icon="📅",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _inject_ui_theme()
    _render_shell_topbar()

    now = datetime.now()
    system_today = now.date()

    left_col, main_col = st.columns([1.05, 4.25], gap="large")

    with left_col:
        _render_left_navigation()
        with st.container(border=True):
            st.markdown("**Generate Schedule**")
            c1, c2 = st.columns(2)
            year = c1.number_input("年份", min_value=2020, max_value=2100, value=now.year, step=1)
            month = c2.number_input("月份", min_value=1, max_value=12, value=now.month, step=1)
            source_mode = st.selectbox("輸入來源", options=["使用範例資料", "上傳 JSON"], index=0)
            uploaded = st.file_uploader(
                "上傳 JSON 檔案",
                type=["json"],
                accept_multiple_files=False,
                disabled=(source_mode != "上傳 JSON"),
            )
            run_clicked = st.button("產生排班", type="primary", use_container_width=True)

        with st.expander("Advanced Options", expanded=False):
            attempts = st.slider("求解嘗試次數", min_value=100, max_value=3000, value=500, step=100)
            seed_input = st.text_input("隨機種子（可留空）", value="")
            override_today_enabled = st.toggle("測試模式：自訂今天日期", value=False)
            if override_today_enabled:
                effective_today = st.date_input("測試用今天日期", value=system_today)
            else:
                effective_today = system_today

        with st.expander("Input JSON", expanded=False):
            st.code(SAMPLE_INPUT_PATH.read_text(encoding="utf-8"), language="json")

    if run_clicked:
        try:
            payload = _load_payload_from_ui(source_mode, uploaded)
            input_data = load_input_from_payload(payload)
            seed = int(seed_input) if seed_input.strip() else None
            try:
                cal = fetch_month_calendar(year=int(year), month=int(month))
            except CalendarAPIError as exc:
                raise ValueError(f"無法取得行事曆 API，請稍後重試：{exc}") from exc

            holidays = set(cal.holidays)
            day_types = cal.day_types
            calendar_note = f"API 已套用：放假日 {len(cal.holidays)} 天，上班日 {len(cal.workdays)} 天"

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
                "calendar_source": "taiwan_calendar_api",
                "solver_stats": {
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
                "carry_over": input_data.carry_over,
                "adjustment_result": None,
            }
        except InfeasibleScheduleError as exc:
            st.error(f"排班失敗：{exc}")
        except Exception as exc:
            st.error(f"資料格式或執行錯誤：{exc}")

    result = st.session_state.get("result")

    with main_col:
        _render_main_header()

        if not result:
            st.markdown(
                """
<section class="empty-state">
  <h3>還沒有班表結果</h3>
  <p>請在左側設定年月與輸入資料，按「產生排班」後就會顯示矩陣與違規卡片。</p>
</section>
""",
                unsafe_allow_html=True,
            )
            return

        report = result["report"]
        schedule_obj = result["schedule"]
        guard_name_by_id = {g.id: g.name for g in schedule_obj.guards}
        violations_count = len(report.violations)
        max_post_spread = max(report.post_spreads.values())
        status_text = "通過" if violations_count == 0 else "需調整"

        header_l, header_r = st.columns([2.0, 1.35], gap="large")
        with header_l:
            st.markdown(f"**作業月份：{schedule_obj.year}-{schedule_obj.month:02d}**")
            calendar_note = result.get("calendar_note")
            if isinstance(calendar_note, str) and calendar_note:
                st.info(calendar_note)
        with header_r:
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

        _render_kpi_strip(
            officers=len(schedule_obj.guards),
            status_text=status_text,
            violations_count=violations_count,
            hours_spread=report.hours_spread,
            max_post_spread=max_post_spread,
        )

        _render_matrix_header()
        st.dataframe(result["schedule_table"], use_container_width=True, hide_index=True)

        content_l, content_r = st.columns([2.15, 1.0], gap="large")
        with content_l:
            _render_violation_cards(result["violations_table"])
            with st.container(border=True):
                st.markdown("**Swap Management（借班 + 還班）**")
                st.caption("先借班、再還班，系統會自動修復剩餘班表。")
                _render_shift_change_section(
                    result=result,
                    attempts=int(attempts),
                    seed_input=seed_input,
                    effective_today=effective_today,
                    override_today_enabled=override_today_enabled,
                )

            with st.expander("查看完整違規表", expanded=False):
                if result["violations_table"]:
                    st.dataframe(result["violations_table"], use_container_width=True, hide_index=True)
                else:
                    st.write("無違規。")

        with content_r:
            _render_rule_health_panel(report)
            st.markdown('<p class="section-title">工時分布</p>', unsafe_allow_html=True)
            st.dataframe(
                _build_hours_table(report, guard_name_by_id),
                use_container_width=True,
                hide_index=True,
            )
            st.markdown('<p class="section-title">哨點均衡</p>', unsafe_allow_html=True)
            st.dataframe(
                _build_post_spread_table(report),
                use_container_width=True,
                hide_index=True,
            )

            with st.expander("稽核證據", expanded=False):
                st.dataframe(result["audit_table"], use_container_width=True, hide_index=True)
                for audit in report.audits:
                    with st.expander(f"規則 {audit.rule}：{audit.name}"):
                        st.write(f"門檻：`{audit.threshold}`")
                        st.write(f"實測：`{audit.measured}`")
                        st.json(audit.evidence)


if __name__ == "__main__":
    main()
