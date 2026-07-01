# 架構 — chipflow

## 資料流

```
                         ┌─────────────── config.yaml / .env ───────────────┐
                         ▼                                                    ▼
  ┌──────────────┐   ┌──────────────────────────────────────────┐    ┌──────────────┐
  │  scheduler   │──▶│                collectors                 │    │   storage    │
  │ GH Actions / │   │  twse.py   taifex.py   external.py        │◀──▶│ files / DB   │
  │ k8s CronJob  │   │  (BaseCollector: collect(start,end))      │    └──────────────┘
  └──────────────┘   └──────────────────────┬───────────────────┘
                                             │  {series: {iso_date: value}}
                                             ▼
                              ┌──────────────────────────┐
                              │  align.py                │  對齊台股交易日 → labels + 等長序列
                              └────────────┬─────────────┘
                                           ▼
                              ┌──────────────────────────┐
                              │  derive.py               │  summary_stats + signals(門檻自 config)
                              └────────────┬─────────────┘
                                           ▼
                              ┌──────────────────────────┐
                              │  build_handoff.py        │  組 handoff.json + 依 schema 驗證
                              └────────────┬─────────────┘
                                  handoff.json (契約)
                        ┌──────────────────┼───────────────────┐
                        ▼                  ▼                    ▼
              ┌──────────────┐   ┌──────────────────┐   ┌──────────────┐
              │  analyze.py  │   │   render.py      │   │  alert (P1)  │
              │ LLM + prompt │   │  HTML 面板        │   │ webhook/Slack│
              │ → 研判 md/json│   │                  │   └──────────────┘
              └──────────────┘   └──────────────────┘
```

## 模組邊界與介面

| 模組 | 職責 | 對外介面(穩定) |
|------|------|------|
| `collectors/base.py` | HTTP 工具(限速/重試/UA)、`BaseCollector` 抽象 | `BaseCollector.collect(start: date, end: date) -> dict[str, dict[str, float]]` |
| `collectors/twse.py` | TWSE 各報表 | `TwseCollector.collect(...)` |
| `collectors/taifex.py` | TAIFEX 期貨/選擇權 | `TaifexCollector.collect(...)` |
| `collectors/external.py` | Yahoo 外圍 + ADR 溢價 | `ExternalCollector.collect(...)` |
| `align.py` | 對齊交易日 | `align(sources: list[dict], master_key: str) -> dict` |
| `derive.py` | 統計與訊號 | `derive(aligned: dict, cfg) -> (summary_stats, signals)` |
| `build_handoff.py` | 組裝 + 驗證 | `build_handoff(aligned, derived, meta) -> dict` |
| `analyze.py` | LLM 研判 | `analyze(handoff: dict, prompt: str, cfg) -> dict` |
| `render.py` | 面板輸出 | `render(handoff: dict, out_path: str) -> None` |
| `storage.py` | 持久化 | `save/load(...)`(檔案預設,DB 為介面) |
| `cli.py` | 編排 | `build-handoff / backfill / run-daily / analyze / render` |

## 關鍵設計決策

1. **collector 回傳格式統一**為 `{series_key: {iso_date: value}}`,由 align 統一成序列;新增維度不影響下游。
2. **契約優先**:handoff.json 為唯一整合點,analyze/render/alert 都只依賴它,彼此解耦。
3. **交易日主軸**取自現貨源(BFI82U/FMTQIK)。美股與缺值以 null 對齊,前端 spanGaps 呈現。
4. **禁止杜撰**:抓取失敗→null + data_gaps 記錄,貫穿 collector→build→analyze。
5. **provider-agnostic LLM**:analyze 以介面隔離 Anthropic/OpenAI/本地,金鑰走 .env。

## 部署形態

- **GitHub Actions**:cron(對應台北盤後),產物存 artifact / 推分支 / 發告警。適合輕量、無自管基礎設施。
- **EKS CronJob**(ArgoCD 管理):容器化執行,產物寫既有 storage,整合現有 LGTM。適合已在跑 k8s 者。
- 兩者共用同一 image 與 CLI;擇一為單一事實來源。
