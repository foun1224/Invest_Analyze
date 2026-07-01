# 系統規格書 — chipflow 台股籌碼面每日自動分析管線

版本 0.1 · 狀態:草案 · 目標讀者:接手實作的工程師 / AI coding agent

---

## 1. 問題陳述

單一分析者每天盤後需手動至 TWSE、TAIFEX、Yahoo 抓取 11+ 種籌碼資料(三大法人現貨/期貨、選擇權 P/C、融資融券、借券、散戶部位、估值、外圍指數、匯率、廣度),再人工對齊、判讀、產出研判。此流程耗時、易漏、不可重現、且無法在無人值守下延續。本系統將其自動化,並以標準化的 `handoff.json` 讓 AI Agent 能無縫接續分析。

## 2. 目標(Goals)

1. **可重現**:給定日期,任何人/機器都能重建當日完整資料包(bit-for-bit 對齊 schema)。
2. **無人值守**:每日盤後自動執行 collect → handoff → analyze → 輸出,無需手動。
3. **AI 可接手**:輸出符合 `handoff.schema.json` 的自我描述資料包,含單位/正負號慣例、來源、時效、衍生訊號與待解問題。
4. **可觀測 + 告警**:關鍵訊號跨門檻時發出告警(例:外資期貨空單單日暴增、融資異常、SOX 跌破均線)。
5. **可擴充**:新增資料維度(見 §9 data gaps)只需實作一個 collector,不動核心流程。

## 3. 非目標(Non-Goals)

1. **不做投資決策/下單**:僅產出分析,不連接券商 API、不自動交易。(合規 + 責任邊界)
2. **不做 tick/盤中即時**:日頻(盤後)即可,盤中即時另案。(複雜度與資料源限制)
3. **不自建資料庫叢集**:v1 用檔案(JSON/parquet)+ 既有 DB 介面即可,不引入新資料庫基礎設施。
4. **不重寫前端框架**:面板沿用現有單檔 HTML + Chart.js(見 `render.py`),不導入 SPA。
5. **不涵蓋個股基本面選股**:專注大盤/籌碼面資金流,個股財報選股另案。

## 4. 需求(Requirements)

### P0 — Must Have(缺這些系統不成立)

| ID | 需求 | 驗收條件(Given/When/Then) |
|----|------|------|
| P0-1 | TWSE collector:三大法人現貨(BFI82U)、加權指數+量(FMTQIK) | Given 交易日 D,When 呼叫 collect,Then 回傳外資/投信/自營淨額(億元)與指數收盤/成交量,數值與 TWSE 網站一致 |
| P0-2 | TAIFEX collector:外資台指期未平倉、散戶小台 | Given D,When collect,Then 回傳外資 TX 未平倉多空淨額(口)與散戶小台淨額,且不同日期回不同值(避免端點回傳最新值的陷阱,見 docs) |
| P0-3 | External collector:SOX/Nasdaq/TSMC-ADR/2330/DXY/US10Y/VIX/USDTWD(Yahoo) | Given 區間,When collect,Then 回傳各序列日資料;ADR 溢價依 `(TSM/5*USDTWD)/2330-1` 計算 |
| P0-4 | Align:對齊至以台股交易日為主的 label 軸,缺值以 null | Given 各源不同交易日曆,When align,Then 產出等長序列,美股/缺值以 null 補齊 |
| P0-5 | build_handoff:組出符合 schema 的 handoff.json | Given 對齊後資料,When build,Then 產物通過 `handoff.schema.json` 驗證,含所有必填欄位 |
| P0-6 | CLI:`build-handoff` / `backfill` / `run-daily` | Given 參數,When 執行,Then 產出對應檔案並回報成功/失敗與缺漏維度 |
| P0-7 | 合理存取:對 TWSE/TAIFEX 加上請求間隔與重試,設定 User-Agent 與 Referer | When 連續抓取,Then 每請求間隔 ≥ 設定值、失敗重試,不對來源造成濫用 |
| P0-8 | 不杜撰資料:任一維度抓取失敗須標為 null 並記錄於 `data_gaps`,禁止填補假值 | Given 某源失敗,When build,Then 該序列為 null 且 handoff.data_gaps 註記,絕不出現捏造數字 |

### P1 — Should Have(重要但非上線必需)

| ID | 需求 | 驗收條件 |
|----|------|------|
| P1-1 | 更多 TWSE 維度:融資融券(MI_MARGN)、借券賣出(TWT93U 加總)、廣度 ADL(MI_INDEX)、估值中位數(BWIBBU)、三大法人個股(T86) | 各維度數值與網站一致;借券為逐檔加總、估值為中位數 |
| P1-2 | 選擇權 P/C(TAIFEX pcRatio),含端點抽風時的重試/降級 | 端點失敗時序列降級為 null 並記錄,不中斷流程 |
| P1-3 | derive:自動計算 summary_stats 與 signals(方向 bull/bear/neutral + 依據),門檻由 config 驅動 | Given 序列,When derive,Then 產出 18 項訊號結構,門檻可由 config 調整 |
| P1-4 | analyze:讀 prompt + handoff.json,呼叫 LLM(provider-agnostic),輸出當日研判 md/json | Given handoff.json + prompt,When analyze,Then 產出研判並附觸發訊號;支援 Anthropic/OpenAI/本地 |
| P1-5 | render:產出單檔 HTML 面板(沿用現有設計) | Given handoff.json,When render,Then 產出可離線開啟的 HTML |
| P1-6 | 排程:GitHub Actions cron(Asia/Taipei 盤後)+ k8s CronJob | 兩種排程皆可執行 run-daily 並保存產物 |
| P1-7 | 告警:關鍵訊號跨門檻時發送(webhook/Slack) | 外資期貨空單單日變化 > 門檻等事件觸發通知 |

### P2 — Future(v1 先設計、不實作)

- 待接資料源(見 `handoff.data_gaps_todo`):高股息 ETF 資金流、M1B/M2、大額交易人、Taiwan VIX、券資比/外資持股比率/當沖比重、月營收年增。
- Grafana 資料源整合(把 handoff 序列寫入 Prometheus/DB 供 Grafana 讀取)。
- 多市場擴充(TPEx 櫃買三大法人、美股其他領先指標)。
- 研判品質回測(記錄每日研判 vs 隔日實際,評估準確度)。

## 5. 資料契約

唯一對外契約為 `schemas/handoff.schema.json`(draft-07)。範例見 `schemas/handoff.example.json`。所有模組以此為準;**修改 schema 需同步更新驗證、範例、prompt 與 render**。關鍵不變量:

- 單位:金額預設億元(=1e8 TWD);期貨口數;正負號 正=買超/淨多、負=賣超/淨空。
- 對齊:所有序列等長,對齊 `labels`(台股交易日 MM/DD)。
- 時效:`as_of_date` 必填;消費端須據此判斷是否需抓新資料。

## 6. 非功能需求

- **時區**:一律 Asia/Taipei;交易日判定排除週末(國定假日由「抓取回傳為空即跳過」處理,見 docs)。
- **冪等**:同一日期重跑產生相同結果;產物以日期命名可覆寫。
- **可測**:collectors 以錄製的 fixture 做離線測試(見 `tests/`)。
- **可觀測**:結構化 log(每源成功/失敗/耗時);退出碼反映結果。
- **設定外置**:標的、門檻、間隔、LLM provider 皆由 `config.yaml` + `.env` 控制,不寫死。

## 7. 里程碑 / 分階段

- **Phase 1(P0)**:BFI82U + FMTQIK + Yahoo + align + build_handoff + CLI + schema 驗證。→ 能每日產出核心 handoff.json。
- **Phase 2(P1)**:補齊 TWSE/TAIFEX 其餘維度 + derive 訊號 + analyze(LLM) + render + 排程 + 告警。→ 全自動每日研判。
- **Phase 3(P2)**:待接資料源 + Grafana + 回測。

## 8. 開放問題(Open Questions)

- **[infra]** 產物存放:純檔案(S3/artifact)還是寫入既有 MySQL/時序 DB?影響 storage.py 與 Grafana 整合路徑。
- **[infra]** 排程平台:GitHub Actions 還是 EKS CronJob 為主?(兩者皆附,擇一為 SoT)
- **[llm]** LLM provider 與成本上限?是否需將 handoff 壓縮/摘要以控 token?
- **[data]** TAIFEX pcRatio 端點不穩定,是否改用單日 `futContractsDate` 途徑或加快取?
- **[data]** 估值採「全體上市中位數」為 proxy;是否需改抓市值加權指數本益比(台積電主導)?來源待確認。
- **[alert]** 告警門檻的初始值與收斂方式(先觀察 N 日分佈再定)?

## 9. 待接資料源(P2 明細)

見 `handoff.example.json` 之 `data_gaps_todo`。每項應實作為獨立 collector,遵守 §5 契約與 §6 非功能需求。
