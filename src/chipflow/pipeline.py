"""對齊 + 衍生 + handoff 組裝。

align:   把多個 collector 輸出對齊到以台股交易日為主的 label 軸。
derive:  summary_stats + 規則式 signals(scaffold:部分已實作,其餘 TODO)。
build:   組出符合 schemas/handoff.schema.json 的 handoff dict 並驗證。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .fund_flow import fund_flow_regime


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
    """累計；中段缺日沿用前值。尚未出現任何有效日值前保持 null（不捏造 0）。"""
    out: list[float | None] = []
    run = 0.0
    has_value = False
    for v in daily:
        if v is None:
            out.append(round(run, 1) if has_value else None)
        else:
            has_value = True
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


def signals(series: dict[str, list], snapshot: dict, cfg: dict,
            flow: dict | None = None) -> list[dict]:
    th = cfg.get("signal_thresholds", {})
    out: list[dict] = []

    def last(k):
        v = [x for x in series.get(k, []) if x is not None]
        return v[-1] if v else None

    def prev(k, n: int = 5):
        v = [x for x in series.get(k, []) if x is not None]
        return v[-n] if len(v) >= n else (v[0] if v else None)

    # 資金風險狀態（多日轉折；入場/出場研判）
    if flow is not None:
        out.append({
            "indicator": "資金風險狀態",
            "reading": flow.get("regime_label", flow.get("stance", "")),
            "direction": flow.get("direction", "neutral"),
            "rationale": flow.get("summary", flow.get("action_hint", "")),
        })
        for tr in flow.get("triggers") or []:
            # 避免與下方累計水位重複：只收「轉折」類 indicator
            if "轉折" in tr.get("indicator", "") or "合計" in tr.get("indicator", ""):
                out.append({
                    "indicator": tr["indicator"],
                    "reading": tr["reading"],
                    "direction": tr["direction"],
                    "rationale": tr["rationale"],
                })

    # 外資現貨(累計水位；輔助，不主導進出場)
    fc = last("foreign_cum")
    if fc is not None:
        out.append({"indicator": "外資現貨累計", "reading": f"{fc:+.0f}億",
                    "direction": "bearish" if fc < 0 else "bullish",
                    "rationale": "區間累計水位（輔助）；進出場以「資金風險狀態」多日轉折為準"})

    # 外資台指期未平倉(水位)
    oi = last("fut_oi")
    if oi is not None:
        out.append({"indicator": "外資台指期", "reading": f"{oi:,}口",
                    "direction": "bearish" if oi < 0 else "bullish",
                    "rationale": "未平倉淨額水位；負=淨空。轉折見「外資台指期OI轉折」"})

    # 期現貨基差（正價差/逆價差）
    basis = last("basis")
    if basis is not None:
        direction = "bearish" if basis < -30 else ("bullish" if basis > 30 else "neutral")
        out.append({"indicator": "期現貨基差", "reading": f"{basis:+.0f}點",
                    "direction": direction,
                    "rationale": "台指期結算-加權指數；負=逆價差(市場偏悲觀)"})

    # 投信買賣超（累計）
    tc = last("trust_cum")
    if tc is not None:
        out.append({"indicator": "投信累計", "reading": f"{tc:+.0f}億",
                    "direction": "bullish" if tc > 0 else "bearish",
                    "rationale": "投信現貨累計買賣超；護盤/買基金力量"})

    # 自營商買賣超（累計）
    dc = last("dealer_cum")
    if dc is not None:
        out.append({"indicator": "自營商累計", "reading": f"{dc:+.0f}億",
                    "direction": "neutral",
                    "rationale": "含避險部位，方向參考意義低於外資/投信"})

    # 融資餘額
    fin = last("margin_fin")
    hw = th.get("margin_fin_high_watermark_yi", 2500)
    if fin is not None:
        out.append({"indicator": "融資餘額", "reading": f"{fin:,.0f}億",
                    "direction": "bearish" if fin >= hw else "neutral",
                    "rationale": f"散戶槓桿水位；>{hw}億過熱"})

    # 大盤融資維持率（擔保市值/融資金額；新倉基準166.7%）
    mm = last("margin_maint")
    mm5 = prev("margin_maint")
    if mm is not None:
        chg = (mm - mm5) if mm5 is not None else 0.0
        if mm < 160 or chg < -8:
            direction = "bearish"
        elif mm >= 175 and chg >= 0:
            direction = "bullish"
        else:
            direction = "neutral"
        out.append({"indicator": "融資維持率", "reading": f"{mm:.1f}%(近5日{chg:+.1f})",
                    "direction": direction,
                    "rationale": "全市場融資擔保市值/融資金額；<160%警戒、急降代表多殺多風險，>175%安全墊厚"})

    # 融券趨勢（千股；看方向而非絕對值）
    short_amt = last("margin_short")
    short5 = prev("margin_short")
    if short_amt is not None and short5 is not None:
        chg = short_amt - short5
        direction = "bullish" if chg > 5000 else ("bearish" if chg < -5000 else "neutral")
        out.append({"indicator": "融券餘額趨勢", "reading": f"{short_amt:,.0f}千股(近5日{chg:+,.0f})",
                    "direction": direction,
                    "rationale": "增加=空方增加/回補動能積累；急速減少=空頭棄守"})

    # 散戶小台淨倉
    rmtx = last("retail_mtx")
    if rmtx is not None:
        direction = "bullish" if rmtx > 5000 else ("bearish" if rmtx < -5000 else "neutral")
        out.append({"indicator": "散戶小台", "reading": f"{rmtx:,}口",
                    "direction": direction,
                    "rationale": "散戶小台淨多/淨空；與外資反向時視為反指標"})

    # 選擇權 P/C
    pcr = last("pcr")
    if pcr is not None:
        b, g = th.get("pcr_bearish", 150), th.get("pcr_bullish", 100)
        d = "neutral"
        if pcr >= b:
            d = "bearish"
        elif pcr <= g:
            d = "bullish"
        out.append({"indicator": "選擇權P/C", "reading": f"{pcr:.0f}%",
                    "direction": d, "rationale": f"未平倉比；>{b}悲觀/<{g}樂觀"})

    # VIX 恐慌指數
    vix = last("vix")
    if vix is not None:
        direction = "bearish" if vix >= 25 else ("bullish" if vix <= 15 else "neutral")
        out.append({"indicator": "VIX", "reading": f"{vix:.1f}",
                    "direction": direction,
                    "rationale": ">25恐慌/<15樂觀；影響外資風險偏好"})

    # SOX 費半（近5日變化）
    sox = last("sox")
    sox5 = prev("sox")
    if sox is not None and sox5 is not None and sox5 != 0:
        chg_pct = (sox - sox5) / sox5 * 100
        direction = "bearish" if chg_pct < -2 else ("bullish" if chg_pct > 2 else "neutral")
        out.append({"indicator": "SOX費半", "reading": f"{sox:,.0f}({chg_pct:+.1f}%近5日)",
                    "direction": direction,
                    "rationale": "費城半導體指數；台積電/半導體股領先指標"})

    # 台積電 ADR 溢價
    adr = last("adr_prem")
    if adr is not None:
        direction = "bearish" if adr < 0 else ("bullish" if adr > 3 else "neutral")
        out.append({"indicator": "台積電ADR溢價", "reading": f"{adr:+.1f}%",
                    "direction": direction,
                    "rationale": "TSM ADR vs 2330折溢價；負=隔日開低壓力"})

    # DXY 美元指數（近5日變化）
    dxy = last("dxy")
    dxy5 = prev("dxy")
    if dxy is not None and dxy5 is not None:
        chg = dxy - dxy5
        direction = "bearish" if chg > 0.5 else ("bullish" if chg < -0.5 else "neutral")
        out.append({"indicator": "DXY美元", "reading": f"{dxy:.1f}({chg:+.2f}近5日)",
                    "direction": direction,
                    "rationale": "強美元→外資匯出壓力；弱美元→資金回流新興市場"})

    # US 10Y 公債殖利率
    tnx = last("tnx")
    if tnx is not None:
        direction = "bearish" if tnx > 4.5 else ("bullish" if tnx < 3.8 else "neutral")
        out.append({"indicator": "US10Y殖利率", "reading": f"{tnx:.2f}%",
                    "direction": direction,
                    "rationale": ">4.5%壓縮估值/<3.8%有利風險資產"})

    # ADL 漲跌線廣度（近5日變化）
    adl = last("adl")
    adl5 = prev("adl")
    if adl is not None and adl5 is not None:
        chg = adl - adl5
        direction = "bullish" if chg > 200 else ("bearish" if chg < -200 else "neutral")
        out.append({"indicator": "ADL漲跌線", "reading": f"{adl:+,.0f}(近5日{chg:+,.0f})",
                    "direction": direction,
                    "rationale": "漲跌家數累計；與指數背離則警惕假突破"})

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
    "fut_settle", "basis",
    "retail_mtx", "margin_fin", "margin_short", "margin_maint", "sbl", "pcr", "pe", "pb", "yd",
    "sox", "ndx", "dxy", "tnx", "vix", "adr_prem", "otc", "fx", "adl",
]


def build_handoff(merged: dict, as_of: date, window_start: date,
                  cfg: dict, meta: dict, composition: dict | None = None) -> dict:
    dates = master_dates(merged)
    labels = [to_label(d) for d in dates]

    # 對齊各原始序列
    a = {k: align_series(merged, k, dates) for k in [
        "index", "volume", "foreign_daily", "trust_daily", "dealer_daily",
        "fut_oi", "fut_settle", "retail_mtx", "margin_fin", "margin_short", "margin_maint", "sbl", "pcr",
        "pe", "pb", "yd", "sox", "ndx", "otc", "dxy", "tnx", "vix",
        "tsm", "t2330", "usdtwd",
    ]}

    # 衍生
    series: dict[str, list] = {
        "index": a["index"], "volume": a["volume"],
        "foreign_cum": _cumsum(a["foreign_daily"]),
        "trust_cum": _cumsum(a["trust_daily"]),
        "dealer_cum": _cumsum(a["dealer_daily"]),
        "fut_oi": a["fut_oi"], "fut_settle": a["fut_settle"],
        "retail_mtx": a["retail_mtx"],
        "margin_fin": a["margin_fin"], "margin_short": a["margin_short"],
        "margin_maint": a["margin_maint"],
        "sbl": a["sbl"], "pcr": a["pcr"],
        "pe": a["pe"], "pb": a["pb"], "yd": a["yd"],
        "sox": a["sox"], "ndx": a["ndx"], "dxy": a["dxy"], "tnx": a["tnx"],
        "vix": a["vix"], "otc": a["otc"], "fx": a["usdtwd"],
    }
    # 期現貨基差 = 台指期結算價 - 加權指數收盤
    series["basis"] = [
        round(fs - idx, 0) if (fs is not None and idx is not None) else None
        for fs, idx in zip(a["fut_settle"], a["index"])
    ]
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

    # 三大法人資金風險狀態（多日轉折；入場/出場研判）
    flow = fund_flow_regime(
        foreign_daily=a["foreign_daily"],
        trust_daily=a["trust_daily"],
        dealer_daily=a["dealer_daily"],
        fut_oi=a["fut_oi"],
        cfg=cfg,
    )
    # 缺核心籌碼時，在 data_gaps 補註（series 維度名）
    if not any(x is not None for x in a["foreign_daily"]):
        if "foreign_cum" not in data_gaps:
            data_gaps.append("foreign_cum")
    if not any(x is not None for x in a["fut_oi"]):
        if "fut_oi" not in data_gaps:
            data_gaps.append("fut_oi")

    sigs = signals(series, {}, cfg, flow=flow)
    kl = cfg.get("key_levels", {})

    # thesis：以資金流向狀態為主軸 regime；其餘訊號作輔助格局
    aux_regime = regime_from_signals(
        [s for s in sigs if s.get("indicator") not in (
            "資金風險狀態", "外資現貨流向轉折", "外資台指期OI轉折", "三大法人現貨合計流向", "投信現貨流向"
        )]
    )
    thesis_regime = flow["regime_label"]
    if flow["stance"] == "neutral_watch" and aux_regime:
        thesis_regime = f"{flow['regime_label']}（輔助格局：{aux_regime}）"

    handoff = {
        "schema_version": "1.0",
        "report_type": "taiwan_equity_chip_flow_analysis",
        "purpose": "供 AI 接續分析用的自我描述資料包。含三大法人資金風險狀態（入場/出場研判，非下單）。",
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
        "fund_flow_regime": {
            "stance": flow["stance"],
            "action_hint": flow["action_hint"],
            "direction": flow["direction"],
            "regime_label": flow["regime_label"],
            "summary": flow["summary"],
            "triggers": flow["triggers"],
            "components": flow["components"],
            "data_complete": flow["data_complete"],
            "score": flow["score"],
        },
        "thesis": {
            "regime": thesis_regime,
            "core_insight": flow["summary"],
            "bull_case": (
                flow["action_hint"] if flow["stance"] == "bullish_entry"
                else "待外資現貨連續買超或近窗淨額翻正、且期貨空單收斂，才偏多方資金面。"
            ),
            "bear_case": (
                flow["action_hint"] if flow["stance"] == "bearish_exit"
                else "待外資現貨連續賣超或近窗淨額翻負、且期貨淨空加深，才偏空方風險面。"
            ),
            "net_read": (
                f"{flow['regime_label']}。{flow['action_hint']}"
                + ("" if flow["data_complete"] else "（核心維度有缺，勿當完整訊號）")
            ),
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
