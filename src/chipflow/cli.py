"""chipflow CLI 編排進入點。

子命令:
  build-handoff --end YYYY-MM-DD [--window N]   收集 → 對齊 → 產出 handoff.json
  backfill --start ... --end ...                同上,以起訖日界定區間
  run-daily --date YYYY-MM-DD                   完整流程:handoff → analyze → render
  analyze --handoff path                        對既有 handoff.json 產出研判
  render  --handoff path                        對既有 handoff.json 產出 HTML

用法:python -m chipflow.cli <cmd> [args]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone

try:
    import yaml
except ImportError:
    yaml = None

from .collectors import HttpClient, HttpConfig, TwseCollector, TaifexCollector, ExternalCollector
from . import pipeline, meta as meta_mod, storage as storage_mod, analyze as analyze_mod, render as render_mod

log = logging.getLogger("chipflow")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA_PATH = os.path.join(REPO_ROOT, "schemas", "handoff.schema.json")
PROMPT_PATH = os.path.join(REPO_ROOT, "prompts", "analyst_handoff.md")


def load_config(path: str | None) -> dict:
    path = path or os.path.join(REPO_ROOT, "config", "config.yaml")
    if not os.path.exists(path):
        path = os.path.join(REPO_ROOT, "config", "config.example.yaml")
    if yaml is None:
        raise RuntimeError("pip install PyYAML")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _window_start(end: date, trading_days: int) -> date:
    # 粗估:交易日約為日曆日的 5/7;多抓緩衝以確保涵蓋。
    return end - timedelta(days=int(trading_days * 1.7) + 7)


def _http(cfg: dict, source: str = "default") -> HttpClient:
    h = cfg.get("http", {})
    # TAIFEX 對連續 POST 較敏感，用較長間隔避免 429
    interval = h.get("taifex_min_interval_sec" if source == "taifex" else "min_interval_sec", 0.25)
    return HttpClient(HttpConfig(
        min_interval_sec=interval,
        timeout_sec=h.get("timeout_sec", 25),
        max_retries=h.get("max_retries", 3),
        user_agent=h.get("user_agent", "Mozilla/5.0 (chipflow)"),
    ))


def do_build(start: date, end: date, cfg: dict) -> dict:
    http = _http(cfg)
    sources_cfg = cfg.get("sources", {})
    collector_cfg = {"external_symbols": cfg.get("external_symbols")}

    outputs = []
    composition = None
    if sources_cfg.get("twse", True):
        tw = TwseCollector(http=http, cfg=collector_cfg)
        outputs.append(tw.collect(start, end))
        composition = tw.get_composition(end)
    if sources_cfg.get("taifex", True):
        http_taifex = _http(cfg, source="taifex")
        outputs.append(TaifexCollector(http=http_taifex, cfg=collector_cfg).collect(start, end))
    if sources_cfg.get("external", True):
        outputs.append(ExternalCollector(http=http, cfg=collector_cfg).collect(start, end))

    merged = pipeline.merge_sources(outputs)
    generated_at = datetime.now(timezone(timedelta(hours=8))).isoformat()
    meta = meta_mod.build_meta(generated_at)
    handoff = pipeline.build_handoff(merged, end, start, cfg, meta, composition)

    try:
        pipeline.validate(handoff, SCHEMA_PATH)
        log.info("handoff 通過 schema 驗證")
    except Exception as e:  # noqa: BLE001
        log.error("schema 驗證失敗:%s", e)
    if handoff.get("data_gaps"):
        log.warning("缺漏維度(以 null 呈現):%s", handoff["data_gaps"])
    return handoff


def cmd_build_handoff(args, cfg):
    end = parse_date(args.end)
    window = args.window or cfg.get("window", {}).get("trading_days", 32)
    start = _window_start(end, window)
    handoff = do_build(start, end, cfg)
    st = storage_mod.FileStorage(cfg.get("output", {}).get("dir", "./out"))
    p = st.save_json(f"handoff_{end.isoformat()}.json", handoff)
    print(f"handoff -> {p}  ({handoff['analysis_window']['trading_days']} 交易日)")


def cmd_backfill(args, cfg):
    start, end = parse_date(args.start), parse_date(args.end)
    handoff = do_build(start, end, cfg)
    st = storage_mod.FileStorage(cfg.get("output", {}).get("dir", "./out"))
    p = st.save_json(f"handoff_{start.isoformat()}_{end.isoformat()}.json", handoff)
    print(f"handoff -> {p}")


def cmd_run_daily(args, cfg):
    end = parse_date(args.date)
    window = cfg.get("window", {}).get("trading_days", 32)
    start = _window_start(end, window)
    handoff = do_build(start, end, cfg)
    st = storage_mod.FileStorage(cfg.get("output", {}).get("dir", "./out"))
    st.save_json(f"handoff_{end.isoformat()}.json", handoff)

    with open(PROMPT_PATH, encoding="utf-8") as f:
        prompt = f.read()

    analysis_md = ""
    try:
        result = analyze_mod.analyze(handoff, prompt, cfg)
        analysis_md = result.get("analysis_md", "")
        st.save_text(f"analysis_{end.isoformat()}.md", analysis_md)
        st.save_json(f"analysis_{end.isoformat()}.json", result)
    except Exception as exc:
        log.warning("analyze 跳過（%s）；面板仍會產出", exc)
        analysis_md = f"（分析未執行：{exc}）"

    if cfg.get("output", {}).get("render_html", True):
        out = os.path.join(cfg.get("output", {}).get("dir", "./out"),
                           f"panel_{end.isoformat()}.html")
        render_mod.render(handoff, out, analysis_md=analysis_md)
    print(f"run-daily 完成:{end.isoformat()}")
    # TODO(agent, P1): 依 signals 與 alert.webhook_url 發送告警。


def cmd_analyze(args, cfg):
    st = storage_mod.FileStorage(os.path.dirname(args.handoff) or ".")
    handoff = st.load_json(os.path.basename(args.handoff))
    with open(PROMPT_PATH, encoding="utf-8") as f:
        prompt = f.read()
    result = analyze_mod.analyze(handoff, prompt, cfg)
    print(result["analysis_md"])


def cmd_render(args, cfg):
    import json
    with open(args.handoff, encoding="utf-8") as f:
        handoff = json.load(f)
    out = args.out or args.handoff.replace(".json", ".html")
    render_mod.render(handoff, out)
    print(f"panel -> {out}")


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="chipflow")
    p.add_argument("--config", help="config.yaml 路徑")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build-handoff"); b.add_argument("--end", required=True); b.add_argument("--window", type=int)
    bf = sub.add_parser("backfill"); bf.add_argument("--start", required=True); bf.add_argument("--end", required=True)
    rd = sub.add_parser("run-daily"); rd.add_argument("--date", required=True)
    an = sub.add_parser("analyze"); an.add_argument("--handoff", required=True)
    rn = sub.add_parser("render"); rn.add_argument("--handoff", required=True); rn.add_argument("--out")

    args = p.parse_args(argv)
    cfg = load_config(args.config)
    {"build-handoff": cmd_build_handoff, "backfill": cmd_backfill,
     "run-daily": cmd_run_daily, "analyze": cmd_analyze, "render": cmd_render}[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
