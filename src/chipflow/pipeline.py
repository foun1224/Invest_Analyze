"""對齊 + 衍生 + handoff 組裝。

align:   把多個 collector 輸出對齊到以台股交易日為主的 label 軸。
derive:  summary_stats + 規則式 signals(scaffold:部分已實作,其餘 TODO)。
build:   組出符合 schemas/handoff.schema.json 的 handoff dict 並驗證。
"""
from __future__ import annotations

from datetime import date
from typing import Any


# ---------------------------------------------------------------- align
def merge_sources(sources: list[dict[str, dict[str, float]]]) -> dict[str, dict[str, float]]:
    merged: dict[str, dict[str, float]] = {}
    for src in sources:
        for k, series in src.items():
            merged.setdefault(k, {}).update(series)
    return merged


def master_dates(merged: dict, master_key: str = "foreign_daily") -> list[str]:
    """交易日主軸:取 master_key 有值的日期(升冪)。BFI82U 定義交易日。"""
    return sorted(merged.get(master_key, {}).keys())


def to_label(iso: str) -> str:
    return f"{iso[5:7]}/{iso[8:10]}"


def align_series(merged: dict, key: str, dates: list[str]) -> list[float | None]:
    s = merged.get(key, {})
    return [s.get(d) for d in dates]


def _cumsum(daily: list[float | None]) -> list[float | None]:
    out, run = [], 0.0
    for v in daily:
        if v is None:
            out.append(round(run, 1))  # 缺日沿用前值,不新增
        else:
            run += v
            out.append(round(run, 1))
    return out


# ---------------------------------------------------------------- derive
def summary_stats(series: dict[str, list], keys: list[str]) -> dict[str, dict]:
    stats = {}
    for k in keys:
        v = [x for x in series.get(k, []) if x is not None]
        if not v:
            continue
        stats[k] = {"start": v[0], "end": v[-1], "change": round(v[-1] - v[0], 2),
                    "min": min(v), "max": max(v), "n": len(v)}
    return stats


def signals(series: dict[str, list], snapshot: dict, cfg: dict) -> list[dict]:
    """規則式訊號(scaffold)。

    已示範數則;其餘 15 項請依 SPEC P1-3 與 config.signal_thresholds 補齊,
    每則須含 indicator / reading / direction / rationale。
    """
    th = cfg.get("signal_thresholds", {})
    out: list[dict] = []

    def last(k):
        v = [x for x in series.get(k, []) if x is not None]
        return v[-1] if v else None

    # 外資現貨(累計)
    fc = last("foreign_cum")
    if fc is not None:
        out.append({"indicator": "外資現貨", "reading": f"累計{fc:+.0f}億",
                    "direction": "bearish" if fc < 0 else "bullish",
                    "rationale": "外資現貨累計買賣超方向"})
    # 外資台指期未平倉
    oi = last("fut_oi")
    if oi is not None:
        out.append({"indicator": "外資台指期", "reading": f"{oi:,}口",
                    "direction": "bearish" if oi < 0 else "bullish",
                    "rationale": "外資台指期未平倉多空淨額;負=淨空"})
    # 融資餘額過熱
    fin = last("margin_fin")
    hw = th.get("margin_fin_high_watermark_yi")
    if fin is not None and hw:
        out.append({"indicator": "融資餘額", "reading": f"{fin:,.0f}億",
                    "direction": "bearish" if fin >= hw else "neutral",
                    "rationale": f"散戶槓桿;>{hw}億視為過熱"})
    # 選擇權 P/C
    pcr = last("pcr")
    if pcr is not None:
        b, g = th.get("pcr_bearish", 150), th.get("pcr_bullish", 100)
        d = "neutral"
        if pcr >= b:
            d = "bearish"      # 賣權多 = 偏悲觀
        elif pcr <= g:
            d = "bullish"
        out.append({"indicator": "選擇權P/C", "reading": f"{pcr:.0f}%",
                    "direction": d, "rationale": f">{b} 悲觀 / <{g} 樂觀"})

    # TODO(agent): 補齊 投信 / 指數相對強度 / 費半SOX / ADR溢價 / 外資賣超組成 /
    #   櫃買 / 借券 / 散戶小台 / 融券 / 台幣 / 成交量 / ADL / 估值 / VIX 等其餘訊號。
    return out


def regime_from_signals(sigs: list[dict]) -> str:
    bull = sum(1 for s in sigs if "bull" in s["direction"])
    bear = sum(1 for s in sigs if "bear" in s["direction"])
    if abs(bull - bear) <= 1:
        return "多空對峙/區間震盪"
    return "偏多" if bull > bear else "偏空"


# ---------------------------------------------------------------- build
SERIES_KEYS = [
    "index", "volume", "foreign_cum", "trust_cum", "dealer_cum", "fut_oi",
    "retail_mtx", "margin_fin", "margin_short", "sbl", "pcr", "pe", "pb", "yd",
    "sox", "ndx", "dxy", "tnx", "vix", "adr_prem", "otc", "fx", "adl",
]


def build_handoff(merged: dict, as_of: date, window_start: date,
                  cfg: dict, meta: dict, composition: dict | None = None) -> dict:
    dates = master_dates(merged)
    labels = [to_label(d) for d in dates]

    # 對齊各原始序列
    a = {k: align_series(merged, k, dates) for k in [
        "index", "volume", "foreign_daily", "trust_daily", "dealer_daily",
        "fut_oi", "retail_mtx", "margin_fin", "margin_short", "sbl", "pcr",
        "pe", "pb", "yd", "sox", "ndx", "otc", "dxy", "tnx", "vix",
        "tsm", "t2330", "usdtwd",
    ]}

    # 衍生
    series: dict[str, list] = {
        "index": a["index"], "volume": a["volume"],
        "foreign_cum": _cumsum(a["foreign_daily"]),
        "trust_cum": _cumsum(a["trust_daily"]),
        "dealer_cum": _cumsum(a["dealer_daily"]),
        "fut_oi": a["fut_oi"], "retail_mtx": a["retail_mtx"],
        "margin_fin": a["margin_fin"], "margin_short": a["margin_short"],
        "sbl": a["sbl"], "pcr": a["pcr"],
        "pe": a["pe"], "pb": a["pb"], "yd": a["yd"],
        "sox": a["sox"], "ndx": a["ndx"], "dxy": a["dxy"], "tnx": a["tnx"],
        "vix": a["vix"], "otc": a["otc"], "fx": a["usdtwd"],
    }
    # ADR 溢價 = (tsm/5 * usdtwd)/2330 - 1
    series["adr_prem"] = [
        round(((t / 5) * fx / p - 1) * 100, 1)
        if (t is not None and p and fx is not None) else None
        for t, p, fx in zip(a["tsm"], a["t2330"], a["usdtwd"])
    ]
    # ADL = cumsum(up - dn)
    up = align_series(merged, "breadth_up", dates)
    dn = align_series(merged, "breadth_dn", dates)
    diff = [(u - d) if (u is not None and d is not None) else None for u, d in zip(up, dn)]
    series["adl"] = _cumsum(diff)

    # data_gaps:完全無值的維度(誠實記錄,不補假值)
    data_gaps = [k for k in SERIES_KEYS if not any(x is not None for x in series.get(k, []))]

    sigs = signals(series, {}, cfg)
    kl = cfg.get("key_levels", {})

    handoff = {
        "schema_version": "1.0",
        "report_type": "taiwan_equity_chip_flow_analysis",
        "purpose": "供 AI 接續分析用的自我描述資料包。",
        "as_of_date": as_of.isoformat(),
        "generated_at": meta.get("generated_at", ""),
        "language": "zh-Hant",
        "market_scope": "TWSE集中市場 + TAIFEX期貨/選擇權 + 美股外圍(Yahoo)",
        "analysis_window": {"start": window_start.isoformat(),
                            "end": as_of.isoformat(),
                            "trading_days": len(labels)},
        "conventions": meta["conventions"],
        "data_sources": meta["data_sources"],
        "field_legend": meta["field_legend"],
        "labels": labels,
        "series": {k: series.get(k) for k in SERIES_KEYS},
        "summary_stats": summary_stats(series, SERIES_KEYS),
        "signals": sigs,
        "thesis": {
            "regime": regime_from_signals(sigs),
            "core_insight": "(規則式骨架;由 analyze/LLM 依 signals 與 series 充實)",
            "bull_case": "(pending LLM)",
            "bear_case": "(pending LLM)",
            "net_read": "(pending LLM)",
        },
        "key_levels": {
            "range_low": kl.get("range_low", min([x for x in series["index"] if x] or [0])),
            "range_high": kl.get("range_high", max([x for x in series["index"] if x] or [0])),
            "supports": kl.get("supports", []),
            "resistances": kl.get("resistances", []),
            "notes": kl.get("notes", ""),
        },
        "watch_list": meta.get("watch_list", []),
        "open_questions": meta.get("open_questions", []),
        "data_gaps_todo": meta.get("data_gaps_todo", []),
        "data_gaps": data_gaps,
    }
    if composition:
        handoff["composition"] = composition
    return handoff


def validate(handoff: dict, schema_path: str) -> None:
    """依 JSON Schema 驗證;失敗拋例外。"""
    import json
    import jsonschema
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(handoff, schema)
