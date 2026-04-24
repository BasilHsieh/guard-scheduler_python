# 保全排班工具 Technical Specification

## 1. 文件目的

本文件描述目前系統的技術設計與行為，作為開發、維護與測試依據。

## 2. 系統邊界與元件

### 2.1 Runtime 形態

- 本機 Web App（Streamlit）
- Python 排班核心
- 檔案匯出（CSV / XLSX / JSON）

### 2.2 核心模組

- `app.py`：UI 流程與使用者互動
- `shift_scheduler/calendar_api.py`：台灣行事曆 API client
- `shift_scheduler/solver.py`：排班與調班修復求解器
- `shift_scheduler/validate.py`：違規檢查與稽核證據
- `shift_scheduler/exporters.py`：匯出器
- `shift_scheduler/io.py`：輸入 payload 解析與日期工具

## 3. 外部依賴

- 台灣行事曆 API：`https://api.pin-yi.me/taiwan-calendar/{year}/{month}`
- 主要第三方庫：
  - `streamlit`
  - `openpyxl`

## 4. 資料模型

### 4.1 Domain Types

- `Guard`：`id`, `name`
- `PostId`：`A~G`
- `Post`：`id`, `post_type`, `hours`
- `CarryOver`：跨月狀態
- `DaySchedule`：`date`, `is_holiday`, `assignments`
- `Schedule`：整月排班

### 4.2 規則輸出模型

- `Violation`：單筆違規
- `RuleAudit`：單條規則的門檻、實測值、證據
- `ValidationSummary`：違規、稽核、工時與分配指標彙總

### 4.3 調班模型

- `ShiftChangeRequest`
  - `borrow_date`
  - `requester_guard_id`
  - `substitute_guard_id`
  - `payback_date`

## 5. 日型判定策略

### 5.1 UI 路徑

- 產生排班時先呼叫 calendar API
- 以 `isHoliday` 組出 `day_types: dict[date_str, bool]`
- `True`：假日（F/G）
- `False`：上班日（A~E）

### 5.2 CLI 路徑

- 預設走 calendar API
- `--use-input-holidays` 可改用輸入 JSON 的 `holidays`

## 6. 排班演算法

### 6.1 每月排班

1. 先依月需求計算配額目標（targets）
2. 逐日為需求崗位尋找可行人員
3. 使用回溯搜尋當日最佳組合
4. 多次嘗試（randomized restarts）挑選最佳整月結果

### 6.2 限制與目標

- 硬限制：規則 1~4（若違反則候選不可用）
- 目標：降低工時差距與哨點分配差距

## 7. 調班與自動修復

### 7.1 前置驗證

- 借班/還班日期皆存在且不同日
- requester / substitute 合法且不同人
- 借班日：requester 有班、substitute 休息
- 還班日：requester 休息、substitute 有班
- 借還班工時一致（10h 或 12h）

### 7.2 修復流程

1. 將借班日與還班日交換結果設為固定
2. 以兩日期較早者作為修復起點
3. 起點之前保持不變
4. 起點到月底重新求解
5. 在合規前提下最小化變更格數

### 7.3 失敗處理

- 若無可行解，拋出 `InfeasibleScheduleError`
- UI 轉換為中文錯誤訊息
- UI 再進一步計算可行還班日建議

## 8. UI 規則

### 8.1 可編輯日期

- 只允許「今天與未來」日期
- 「今天以前」不可調班

### 8.2 測試模式

- 左側設定區可開啟「自訂今天日期」
- 只影響可編輯日期過濾，不影響系統時間

### 8.3 畫面資訊架構（目前版）

- 版型採單頁工作台（非 tabs）
- 上方：產品工具列與頁面標題（Schedule Matrix）
- 左欄：操作設定（年月、輸入來源、進階參數）
- 中欄：班表矩陣與違規卡片（Critical Rule Violations）
- 右欄：規則健康、工時分布、哨點均衡
- 調班區塊置於矩陣與違規資訊下方，並即時回饋本次結果

### 8.4 班表矩陣互動

- 班表矩陣使用 Streamlit 原生 `st.dataframe`
- 開啟 cell selection：`on_select="rerun"` + `selection_mode="single-cell"`
- 使用者點擊「有班」格子後：
  - 解析成 `selected_shift_cell = {guard_id, date}`
  - 由 `st.dialog("調班精靈")` 開啟調班流程
- 使用者點擊「休」格或無效格時：
  - 不進入調班
  - 清除既有選取狀態
- 關閉彈窗或取消選取時：
  - 需同步清空 dataframe selection state
  - 避免同一格在下一次 rerun 又自動開啟彈窗
- 舊版曾用 query param (`pick`) 承接點擊事件；目前僅保留相容性恢復邏輯，不作為主要互動路徑

## 9. 匯出規格

- CSV：人員 x 日期班別
- XLSX：`Schedule` + `Summary` sheet
- JSON：
  - `solver_stats`
  - `validation.violations`
  - `validation.audits`
  - 調班後可含 `adjustment` metadata

## 10. 啟動與執行

### 10.1 UI

- `start.command` 或 `streamlit run app.py`
- 8501 佔用時，`start.command` 會自動遞增可用 port

### 10.2 CLI

- `python3 -m shift_scheduler --input ... --year ... --month ...`

## 11. 測試策略

### 11.1 基本驗證

- 產生單月排班成功
- 規則檢查可輸出
- 匯出檔案可生成

### 11.2 調班驗證

- 可行案例：調班成功且 violations=0
- 不可行案例：回傳清楚錯誤與候選建議
- 還班日可早於借班日（同月、未發生日期）
- 點擊矩陣格子時，不應改變網址或出現瀏覽器導頁式刷新
- 關閉調班彈窗後，不應因舊 selection state 再次自動開啟

## 12. 需求對照（PRD → Tech）

- PRD「月排班」→ `generate_schedule`
- PRD「規則證據」→ `validate_schedule` + `audits`
- PRD「調班與修復」→ `adjust_schedule_for_shift_change`
- PRD「同月、未發生限制」→ UI 日期過濾 + solver 驗證
- PRD「無解可說明」→ `InfeasibleScheduleError` + UI 建議日期
