# AGENTS.md — 給接手實作的 AI Coding Agent

本檔是你的作業指南。**動工前先讀 `SPEC.md`(需求/驗收)、`ARCHITECTURE.md`(邊界)、`docs/data_sources.md`(實際端點)、`schemas/handoff.schema.json`(契約)。**

## 你的任務

把本 scaffold 補成可每日無人值守執行的管線。`collectors/` 已含經驗證可跑的程式碼;請沿用其模式擴充其餘 collector,並完成 align/derive/build_handoff/analyze/render/storage/cli 與排程。

## 守則(硬性)

1. **不杜撰資料**。任一維度抓取失敗 → 該序列填 `null` 並在 `handoff.data_gaps` 記錄。禁止插補/估算假值。這是本專案的第一原則。
2. **契約優先**。所有整合走 `handoff.json`;改欄位必須同步更新 `schemas/handoff.schema.json`、`schemas/handoff.example.json`、`prompts/analyst_handoff.md`、`render.py` 與測試。
3. **尊重來源**。對 TWSE/TAIFEX 保持請求間隔(config `http.min_interval_sec`,預設 0.2–0.3s)、重試與正確 UA/Referer。見 docs 的注意事項(尤其 TAIFEX 日期參數陷阱)。
4. **時區 Asia/Taipei**;交易日判定見 docs。
5. **冪等**:同日期重跑結果一致。
6. **設定外置**:門檻/標的/provider 不寫死,一律讀 config/env。
7. **每個 collector 附離線測試**(用錄製 fixture,勿在 CI 打外網)。

## 建議實作順序(對應 SPEC 分階段)

### Phase 1(P0)— 先讓核心 handoff.json 每日產出
1. `collectors/base.py`:HTTP helper 已備;確認限速/重試/逾時可用。
2. `collectors/twse.py`:BFI82U、FMTQIK 已實作;跑通 `collect`。
3. `collectors/external.py`:Yahoo 全序列 + ADR 溢價已實作;跑通。
4. `collectors/taifex.py`:futContractsDate(外資 TX、散戶小台)已實作;**務必用 `queryDate` 而非 Excel 端點**(見 docs)。
5. `align.py`:完成對齊(master = BFI82U 交易日)。
6. `derive.py`:先做 summary_stats;signals 可先給結構、門檻後補。
7. `build_handoff.py`:組裝 + 以 schema 驗證(用 `jsonschema`)。
8. `cli.py`:`build-handoff` / `backfill` 可跑。
9. `tests/`:BFI82U + Yahoo 的 fixture 測試。
> **Phase 1 Definition of Done**:`python -m chipflow.cli build-handoff --end <D> --window 32` 產出通過 schema 驗證的 handoff.json,核心序列數值與官網一致。

### Phase 2(P1)— 全自動每日研判
10. twse.py 補:MI_MARGN、TWT93U(借券加總)、MI_INDEX(ADL)、BWIBBU(中位數估值)、T86(個股)。
11. taifex.py 補:pcRatio(加重試/降級)。
12. derive.py:完成 18 項 signals,門檻讀 config。
13. `analyze.py`:讀 `prompts/analyst_handoff.md` + handoff.json → 呼叫 LLM → 產出當日研判(md+json),標出觸發訊號。provider 走介面。
14. `render.py`:由 handoff.json 產單檔 HTML 面板(可參考本專案既有面板設計)。
15. `.github/workflows/daily.yml` 與 `deploy/cronjob.yaml`:排程跑 `run-daily` 並保存產物。
16. 告警:關鍵訊號跨門檻發 webhook。
> **Phase 2 DoD**:排程每日自動輸出 handoff.json + 研判 + 面板,並在門檻事件發告警。

### Phase 3(P2)— 待接資料源 + Grafana + 回測
17. 依 `data_gaps_todo` 逐一新增 collector(每個都要有測試與 schema 欄位)。
18. Grafana 整合:把序列寫入 Prometheus/DB。
19. 回測:記錄每日研判 vs 隔日實際,輸出準確度報表。

## 驗收自查清單

- [ ] handoff.json 通過 `schemas/handoff.schema.json` 驗證
- [ ] 核心序列數值抽樣與 TWSE/TAIFEX 官網一致
- [ ] 任一源失敗時,序列為 null 且 data_gaps 有記錄(無假值)
- [ ] 同日期重跑結果一致(冪等)
- [ ] collectors 有離線 fixture 測試,CI 不打外網
- [ ] `run-daily` 端到端可跑並保存產物
- [ ] 修改 schema 時,範例/prompt/render/測試同步更新

## 常見陷阱(來自實測)

- **TAIFEX futContractsDate**:用 `POST queryDate=YYYY/MM/DD&doQuery=1`。若用 `futContractsDateExcel` 帶 queryStartDate/queryEndDate,端點會**忽略日期、回傳最新一天**(假時間序列)。務必驗證「不同日期回不同值」。
- **TAIFEX pcRatioExcel**:偶發回傳無表格,需重試/降級,勿讓其中斷整批。
- **TWSE 民國日期**:FMTQIK 的日期欄為民國(115/06/30),需轉換。
- **國定假日**:非交易日 API 回 `stat != 'OK'` 或空 data;跳過即可,勿補值。
- **Yahoo 美股日曆**:與台股不完全同步,對齊後以 null 呈現缺日。
