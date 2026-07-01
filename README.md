# chipflow — 台股籌碼面每日自動分析管線

> 每日盤後自動收集台股多維度籌碼資料 → 產出自我描述的 `handoff.json` → 交由 AI Agent 產生當日研判 → 輸出面板/告警。
>
> 本 repo 為 **agent-ready scaffold**:核心 collector 已內含經驗證可跑的程式碼,其餘模組為清楚的骨架 + TODO,供後續 AI coding agent 接手完成。**開工前先讀 [`AGENTS.md`](./AGENTS.md) 與 [`SPEC.md`](./SPEC.md)。**

## 這個系統做什麼

把「人工每天到 TWSE / TAIFEX / Yahoo 抓 11+ 種籌碼資料、手動判讀」的流程,變成:

```
scheduler(每日盤後)
  → collectors(TWSE/TAIFEX/Yahoo)
  → align(對齊交易日)
  → derive(衍生訊號/統計)
  → build_handoff(產出 handoff.json,符合 schemas/handoff.schema.json)
  → analyze(LLM 依 prompts/analyst_handoff.md 產出當日研判)
  → render/alert(HTML 面板 + Grafana + 告警)
```

## 快速開始

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/config.example.yaml config/config.yaml
cp .env.example .env            # 填入 LLM 金鑰等

# 抓單日 + 產出 handoff.json(不含 LLM)
python -m chipflow.cli build-handoff --end 2026-06-30 --window 32

# 回補一段區間
python -m chipflow.cli backfill --start 2026-05-15 --end 2026-06-30

# 完整每日流程(collect → handoff → analyze → render)
python -m chipflow.cli run-daily --date 2026-06-30
```

## 專案結構

```
chipflow/
├── SPEC.md                     系統規格(需求 P0/P1/P2、驗收條件、Non-Goals、分階段)
├── ARCHITECTURE.md             架構、資料流、模組邊界
├── AGENTS.md                   給 AI coding agent 的接手指南(任務拆解 + 守則)
├── docs/data_sources.md        ★ 已驗證的實際 API 端點/參數/回傳結構(省下重新逆向的功夫)
├── schemas/
│   ├── handoff.schema.json      handoff 格式的正式 JSON Schema (draft-07)
│   └── handoff.example.json     實際範例(2026-06-30)
├── prompts/analyst_handoff.md  AI 接手分析的 prompt 樣板
├── config/config.example.yaml  標的/日期政策/告警門檻/資料源設定
├── src/chipflow/
│   ├── collectors/             base + twse/taifex/external(★含可跑程式碼)
│   ├── align.py                對齊交易日
│   ├── derive.py               衍生訊號 + summary_stats
│   ├── build_handoff.py        組出 handoff.json
│   ├── analyze.py              LLM 分析步驟(provider-agnostic 骨架)
│   ├── render.py               輸出 HTML 面板
│   ├── storage.py              持久化(檔案/DB 介面)
│   └── cli.py                  進入點
├── .github/workflows/daily.yml GitHub Actions 排程
├── deploy/cronjob.yaml         Kubernetes CronJob(EKS/ArgoCD)
├── Dockerfile
└── tests/
```

## 授權與免責

資料僅供研究,非投資建議。請遵守各資料源(TWSE/TAIFEX/Yahoo)之使用條款與合理存取頻率。
