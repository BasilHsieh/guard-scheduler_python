# Guard Scheduler Side Project

輕量排班工具（本機執行），目標是把每月人工排班從約 1 小時縮短到幾分鐘，並保留可稽核的規則證據。

## 核心能力

- 單月自動排班（6 位人員、平日/假日不同哨點）
- 以台灣行事曆 API 判斷上班日與放假日
- 六條規則檢查 + 稽核證據
- 調班流程（借班 + 還班 + 自動修復剩餘班表）
- 匯出 CSV / Excel / JSON 報告

## 文件索引

- [產品 PRD](docs/PRD.md)
- [技術規格 TECH SPEC](docs/TECH_SPEC.md)
- [開發日誌 DEVLOG](docs/DEVLOG.md)
- [舊版整合規格（歷史）](docs/SPEC_V2.md)

## 本機啟動（建議）

### 方式 1：雙擊啟動（Mac）

直接雙擊 `start.command`。

- 會自動建立/使用 `.venv`
- 會安裝依賴（若尚未安裝）
- 會啟動 Streamlit
- 若 `8501` 被占用，會自動換可用 port，終端會顯示實際網址

### 方式 2：手動啟動

```bash
cd /Users/basil/Desktop/projects/guard-scheduler-sideproject
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## 使用流程（一般使用者）

1. 選擇年份與月份
2. 選擇範例資料或上傳 JSON
3. 點 `產生排班`
4. 查看矩陣、規則狀態、違規卡片
5. 需要時做調班（借班+還班）並套用自動修復
6. 下載 CSV / Excel / JSON

## CLI（可選）

```bash
python3 -m shift_scheduler --input examples/input.sample.json --year 2026 --month 5
```

若要強制使用輸入檔內的 `holidays`（不走 API）：

```bash
python3 -m shift_scheduler --input examples/input.sample.json --year 2026 --month 5 --use-input-holidays
```

## 重要限制（目前）

- 只支援單月排班
- 調班只支援同月內借還班
- 只能修改「今天與未來」日期
- 借班與還班需同工時（10h/12h）
