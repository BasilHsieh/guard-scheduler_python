from __future__ import annotations

from datetime import datetime
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


def _build_violations_table(report: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for v in report.violations:
        rows.append(
            {
                "規則": str(v.rule),
                "人員": v.guard_id,
                "日期": v.date,
                "說明": v.message,
            }
        )
    return rows


def _build_audit_table(report: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for a in report.audits:
        rows.append(
            {
                "規則": f"{a.rule}. {a.name}",
                "門檻": a.threshold,
                "實測值": a.measured,
                "結果": "通過" if a.passed else "未通過",
            }
        )
    return rows


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


def main() -> None:
    st.set_page_config(
        page_title="保全排班工具",
        page_icon="📅",
        layout="wide",
    )
    st.title("保全排班工具")
    st.caption("給一般使用者：上傳資料、按一下產生、直接下載 Excel/CSV。")

    now = datetime.now()
    system_today = now.date()
    with st.sidebar:
        st.header("排班設定")
        year = st.number_input("年份", min_value=2020, max_value=2100, value=now.year, step=1)
        month = st.number_input("月份", min_value=1, max_value=12, value=now.month, step=1)
        attempts = st.slider("求解嘗試次數", min_value=100, max_value=3000, value=500, step=100)
        seed_input = st.text_input("隨機種子（可留空）", value="")

        st.divider()
        override_today_enabled = st.toggle("測試模式：自訂今天日期", value=False)
        if override_today_enabled:
            selected_today = st.date_input("測試用今天日期", value=system_today)
            effective_today = selected_today
        else:
            effective_today = system_today

        st.divider()
        source_mode = st.radio("輸入來源", ["使用範例資料", "上傳 JSON"], index=0)
        uploaded = st.file_uploader(
            "上傳輸入檔",
            type=["json"],
            accept_multiple_files=False,
            disabled=(source_mode != "上傳 JSON"),
        )
        run_clicked = st.button("產生排班", type="primary", use_container_width=True)

    with st.expander("輸入格式說明（JSON）"):
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
            calendar_source = "taiwan_calendar_api"
            calendar_note = (
                f"API 已套用：放假日 {len(cal.holidays)} 天，上班日 {len(cal.workdays)} 天"
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

            report_payload = {
                "month": {"year": int(year), "month": int(month)},
                "calendar_source": calendar_source,
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
                "violations_table": _build_violations_table(report),
                "audit_table": _build_audit_table(report),
                "csv_bytes": export_csv_bytes(schedule),
                "xlsx_bytes": export_xlsx_bytes(schedule, report),
                "report_bytes": json.dumps(
                    report_payload, ensure_ascii=False, indent=2
                ).encode("utf-8"),
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
    if not result:
        st.info("尚未產生排班。請在左側設定後點擊「產生排班」。")
        return

    report = result["report"]
    violations_count = len(report.violations)
    max_post_spread = max(report.post_spreads.values())
    status_text = "通過" if violations_count == 0 else "需調整"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("狀態", status_text)
    c2.metric("違規數", violations_count)
    c3.metric("工時差距", report.hours_spread)
    c4.metric("最大哨點差距", max_post_spread)

    calendar_note = result.get("calendar_note")
    if isinstance(calendar_note, str) and calendar_note:
        if "失敗" in calendar_note:
            st.warning(calendar_note)
        else:
            st.info(calendar_note)

    st.subheader("排班結果")
    st.dataframe(result["schedule_table"], use_container_width=True, hide_index=True)

    st.subheader("規則檢查")
    if violations_count == 0:
        st.success("本月排班無違規。")
    else:
        st.dataframe(result["violations_table"], use_container_width=True, hide_index=True)

    st.subheader("規則稽核證據")
    st.dataframe(result["audit_table"], use_container_width=True, hide_index=True)
    for audit in report.audits:
        status = "PASS" if audit.passed else "FAIL"
        with st.expander(f"[{status}] 規則 {audit.rule}：{audit.name}"):
            st.write(f"門檻：`{audit.threshold}`")
            st.write(f"實測值：`{audit.measured}`")
            st.json(audit.evidence)

    st.subheader("調班（借班＋還班）")
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
    else:
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
        else:
            requester = st.selectbox(
                "原值班人",
                options=requester_options,
                format_func=lambda gid: guard_name_by_id[gid],
                key="swap_requester",
            )
            requester_post = borrow_map.get(requester)
            substitute_options = [
                gid
                for gid in guard_ids
                if gid != requester and borrow_map.get(gid) is None
            ]
            if requester_post is not None:
                st.caption(
                    f"借班內容：{guard_name_by_id[requester]} 在 {borrow_date} 的 {requester_post} 班"
                )

            if not substitute_options:
                st.info("這組條件目前沒有可代班人，請換一天或換原值班人。")
            else:
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
                    st.info(
                        "這組條件目前沒有可還班日期。請換借班日、原值班人或代班人。"
                    )
                else:
                    payback_date = st.selectbox(
                        "還班日（可早於或晚於借班日）",
                        options=payback_candidates,
                        key="swap_payback_date",
                    )
                    payback_post = day_assignments[payback_date].get(substitute)
                    st.caption(
                        f"還班內容：{payback_date} 的 {payback_post} 班，"
                        f"由 {guard_name_by_id[substitute]} 還給 {guard_name_by_id[requester]}"
                    )

                    if st.button("套用調班並自動修復剩餘班表", type="secondary", key="apply_shift_change"):
                        try:
                            seed_for_adjust = int(seed_input) if seed_input.strip() else None
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
                            adjusted_report = validate_schedule(
                                adjusted_schedule,
                                carry_over=carry_over,
                            )
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
                                f"調班完成：借班 {borrow_date}、還班 {payback_date}，"
                                f"系統自動調整 {adjust_meta['changed_cells']} 格"
                            )
                            st.session_state["result"] = {
                                "schedule": adjusted_schedule,
                                "report": adjusted_report,
                                "schedule_table": _build_schedule_table(adjusted_schedule),
                                "violations_table": _build_violations_table(adjusted_report),
                                "audit_table": _build_audit_table(adjusted_report),
                                "csv_bytes": export_csv_bytes(adjusted_schedule),
                                "xlsx_bytes": export_xlsx_bytes(adjusted_schedule, adjusted_report),
                                "report_bytes": json.dumps(
                                    report_payload, ensure_ascii=False, indent=2
                                ).encode("utf-8"),
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
                        except ValueError:
                            st.error("隨機種子格式錯誤，請輸入整數或留空。")
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
                                st.info(
                                    "可行還班日建議："
                                    + "、".join(feasible_payback_dates)
                                )
                            else:
                                st.info("此組借班條件目前找不到可行還班日，請改借班日或代班人。")

    adjustment_result = result.get("adjustment_result")
    if isinstance(adjustment_result, dict):
        msg = str(adjustment_result.get("message", "")).strip()
        if adjustment_result.get("status") == "success" and msg:
            st.success(f"本次調班成功：{msg}")

    st.subheader("下載")
    col1, col2, col3 = st.columns(3)
    col1.download_button(
        label="下載 CSV",
        data=result["csv_bytes"],
        file_name=f"{result['file_stem']}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    col2.download_button(
        label="下載 Excel",
        data=result["xlsx_bytes"],
        file_name=f"{result['file_stem']}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    col3.download_button(
        label="下載驗證報告 JSON",
        data=result["report_bytes"],
        file_name=f"report_{result['file_stem'].replace('schedule_', '')}.json",
        mime="application/json",
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
