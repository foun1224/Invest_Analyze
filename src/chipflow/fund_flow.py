"""三大法人資金流向轉折 → 風險狀態（偏多入場／偏空出場／中性觀望）。

純函式、無 I/O。看多日淨額與期貨 OI 變化，不單看區間累計正負號。
門檻全讀 config.signal_thresholds；缺核心序列 → data_insufficient，不捏造。
"""
from __future__ import annotations

from typing import Any


# stance 代碼 → 人可讀
STANCE_LABELS = {
    "bullish_entry": "偏多／入場可考慮",
    "bearish_exit": "偏空／出場警戒",
    "neutral_watch": "中性／觀望",
    "data_insufficient": "資料不足／觀望",
}

ACTION_HINTS = {
    "bullish_entry": "資金開始轉向多頭，可考慮分批入場（研判非下單保證）",
    "bearish_exit": "風險轉空，出場警戒（研判非下單保證）",
    "neutral_watch": "訊號混雜或未達轉折門檻，觀望",
    "data_insufficient": "核心籌碼維度缺值，狀態不可假裝完整",
}


def _non_null(vals: list[float | None]) -> list[float]:
    return [float(v) for v in vals if v is not None]


def _window_sum(vals: list[float | None], n: int) -> float | None:
    """近 n 筆非 null 日值合計；不足一半視作資料不夠。"""
    nn = _non_null(vals)
    if not nn:
        return None
    need = max(1, (n + 1) // 2)
    if len(nn) < need:
        return None
    take = nn[-n:] if len(nn) >= n else nn
    return round(sum(take), 2)


def _prior_window_sum(vals: list[float | None], n: int) -> float | None:
    """對照窗：近 n 筆之前的 n 筆合計。"""
    nn = _non_null(vals)
    if len(nn) < n + 1:
        return None
    if len(nn) >= 2 * n:
        prior = nn[-(2 * n) : -n]
    else:
        prior = nn[:-n]
    if not prior:
        return None
    return round(sum(prior), 2)


def _end_streak(vals: list[float | None]) -> tuple[int, int]:
    """末端連續同號買賣超：(sign +1/-1/0, 連續天數)。0 日跳過。"""
    nn = _non_null(vals)
    if not nn:
        return 0, 0
    # 跳過末端剛好為 0
    i = len(nn) - 1
    while i >= 0 and nn[i] == 0:
        i -= 1
    if i < 0:
        return 0, 0
    sign = 1 if nn[i] > 0 else -1
    count = 0
    while i >= 0:
        v = nn[i]
        if v == 0:
            i -= 1
            continue
        if (v > 0 and sign > 0) or (v < 0 and sign < 0):
            count += 1
            i -= 1
        else:
            break
    return sign, count


def _th(cfg: dict) -> dict[str, Any]:
    raw = cfg.get("signal_thresholds") or {}
    return {
        "flow_window_days": int(raw.get("flow_window_days", 5)),
        "consecutive_days": int(raw.get("consecutive_days", 3)),
        "foreign_fut_oi_daily_spike": float(raw.get("foreign_fut_oi_daily_spike", 6000)),
        "foreign_fut_oi_multi_day_deepen": float(
            raw.get("foreign_fut_oi_multi_day_deepen", 10000)
        ),
        "fut_oi_multi_window_days": int(raw.get("fut_oi_multi_window_days", 5)),
    }


def _assess_spot(
    daily: list[float | None],
    *,
    window: int,
    consecutive_days: int,
    label: str,
) -> dict[str, Any] | None:
    """現貨日淨額轉折。None = 該序列完全無資料。"""
    nn = _non_null(daily)
    if not nn:
        return None

    recent = _window_sum(daily, window)
    prior = _prior_window_sum(daily, window)
    sign, streak = _end_streak(daily)

    direction = "neutral"
    reasons: list[str] = []

    # 多日淨額翻號 = 轉折（主邏輯；非僅看累計水位）
    if recent is not None and prior is not None:
        if prior < 0 and recent > 0:
            direction = "bullish"
            reasons.append(f"近{window}日淨額由負翻正({prior:+.1f}→{recent:+.1f}億)")
        elif prior > 0 and recent < 0:
            direction = "bearish"
            reasons.append(f"近{window}日淨額由正翻負({prior:+.1f}→{recent:+.1f}億)")

    # 連續買賣超強化／獨立觸發
    if sign > 0 and streak >= consecutive_days:
        if direction != "bearish":
            direction = "bullish"
        reasons.append(f"連續{streak}日買超")
    elif sign < 0 and streak >= consecutive_days:
        if direction != "bullish":
            direction = "bearish"
        reasons.append(f"連續{streak}日賣超")

    # 尚未觸發轉折時，以近窗淨額方向作弱訊號
    if direction == "neutral" and recent is not None:
        if recent > 0:
            direction = "bullish"
            reasons.append(f"近{window}日淨買{recent:+.1f}億")
        elif recent < 0:
            direction = "bearish"
            reasons.append(f"近{window}日淨賣{recent:+.1f}億")
        else:
            reasons.append(f"近{window}日淨額接近零")

    if not reasons:
        reasons.append("現貨流向可讀但無明顯偏向")

    reading_parts = []
    if recent is not None:
        reading_parts.append(f"近{window}日{recent:+.1f}億")
    if streak:
        reading_parts.append(f"連{streak}日{'買' if sign > 0 else '賣'}")
    reading = "；".join(reading_parts) if reading_parts else "—"

    return {
        "indicator": label,
        "reading": reading,
        "direction": direction,
        "rationale": "；".join(reasons) + "（趨勢轉折，非單日）",
        "recent_net": recent,
        "prior_net": prior,
        "streak_sign": sign,
        "streak_days": streak,
    }


def _zip_sum(
    *series: list[float | None],
) -> list[float | None]:
    """逐日加總；當日任一缺值則該日為 null（不捏造）。"""
    if not series:
        return []
    n = max(len(s) for s in series)
    out: list[float | None] = []
    for i in range(n):
        day_vals = []
        missing = False
        for s in series:
            if i >= len(s) or s[i] is None:
                missing = True
                break
            day_vals.append(float(s[i]))
        out.append(None if missing else round(sum(day_vals), 2))
    return out


def _assess_fut_oi(
    fut_oi: list[float | None],
    *,
    daily_spike: float,
    multi_threshold: float,
    multi_window: int,
) -> dict[str, Any] | None:
    nn = _non_null(fut_oi)
    if len(nn) < 2:
        return None if not nn else {
            "indicator": "外資台指期OI轉折",
            "reading": f"{nn[-1]:,.0f}口",
            "direction": "neutral",
            "rationale": "期貨序列不足兩日，無法判讀轉折",
            "last_oi": nn[-1],
            "daily_chg": None,
            "multi_chg": None,
        }

    last = nn[-1]
    prev = nn[-2]
    daily_chg = last - prev
    multi_chg: float | None = None
    if len(nn) > multi_window:
        multi_chg = last - nn[-(multi_window + 1)]
    elif len(nn) >= 2:
        multi_chg = last - nn[0]

    direction = "neutral"
    reasons: list[str] = []

    # 淨空加深（OI 更負）→ 偏空；回補／加多（OI 上升）→ 偏多
    if daily_chg <= -daily_spike:
        direction = "bearish"
        reasons.append(f"單日淨空加深{daily_chg:+,.0f}口(≥門檻{daily_spike:,.0f})")
    elif multi_chg is not None and multi_chg <= -multi_threshold:
        direction = "bearish"
        reasons.append(
            f"近{multi_window}日淨空加深{multi_chg:+,.0f}口(≥門檻{multi_threshold:,.0f})"
        )
    elif daily_chg >= daily_spike:
        direction = "bullish"
        reasons.append(f"單日空單回補/加多{daily_chg:+,.0f}口(≥門檻{daily_spike:,.0f})")
    elif multi_chg is not None and multi_chg >= multi_threshold:
        direction = "bullish"
        reasons.append(
            f"近{multi_window}日空單收斂{multi_chg:+,.0f}口(≥門檻{multi_threshold:,.0f})"
        )
    else:
        reasons.append(
            f"期貨OI變化未跨門檻(日{daily_chg:+,.0f}"
            + (f"/多日{multi_chg:+,.0f}" if multi_chg is not None else "")
            + ")"
        )

    reading = f"{last:,.0f}口(日{daily_chg:+,.0f}"
    if multi_chg is not None:
        reading += f"/近{multi_window}日{multi_chg:+,.0f}"
    reading += ")"

    return {
        "indicator": "外資台指期OI轉折",
        "reading": reading,
        "direction": direction,
        "rationale": "；".join(reasons) + "；負=淨空、加深=出場側風險",
        "last_oi": last,
        "daily_chg": daily_chg,
        "multi_chg": multi_chg,
    }


def _score_direction(direction: str) -> int:
    if direction == "bullish":
        return 1
    if direction == "bearish":
        return -1
    return 0


def fund_flow_regime(
    foreign_daily: list[float | None],
    trust_daily: list[float | None],
    dealer_daily: list[float | None],
    fut_oi: list[float | None],
    cfg: dict | None = None,
) -> dict[str, Any]:
    """由對齊後日序列推導資金風險狀態。

    Parameters
    ----------
    foreign_daily / trust_daily / dealer_daily
        現貨日買賣超(億元)，與交易日軸等長；缺值 null。
    fut_oi
        外資台指期未平倉淨額(口)。
    cfg
        含 signal_thresholds 的設定 dict。

    Returns
    -------
    dict
        stance, action_hint, direction, triggers, summary, components,
        data_complete, regime_label
    """
    cfg = cfg or {}
    t = _th(cfg)
    w = t["flow_window_days"]
    cons = t["consecutive_days"]

    foreign = _assess_spot(
        foreign_daily, window=w, consecutive_days=cons, label="外資現貨流向轉折"
    )
    trust = _assess_spot(
        trust_daily, window=w, consecutive_days=cons, label="投信現貨流向"
    )
    # 三大法人合計（外資+投信+自營）；當日缺任一則該日 null
    inst_daily = _zip_sum(foreign_daily, trust_daily, dealer_daily)
    # 若自營全缺但外資+投信有值，降級為外資+投信
    if not _non_null(inst_daily):
        inst_daily = _zip_sum(foreign_daily, trust_daily)
    institutional = _assess_spot(
        inst_daily,
        window=w,
        consecutive_days=cons,
        label="三大法人現貨合計流向",
    )
    futures = _assess_fut_oi(
        fut_oi,
        daily_spike=t["foreign_fut_oi_daily_spike"],
        multi_threshold=t["foreign_fut_oi_multi_day_deepen"],
        multi_window=t["fut_oi_multi_window_days"],
    )

    components: dict[str, Any] = {
        "foreign_spot": foreign,
        "trust_spot": trust,
        "institutional_spot": institutional,
        "foreign_futures_oi": futures,
    }

    # 核心：外資現貨 + 期貨 OI；至少要有一個可讀，否則資料不足
    core_present = foreign is not None or futures is not None
    if not core_present:
        stance = "data_insufficient"
        return {
            "stance": stance,
            "action_hint": ACTION_HINTS[stance],
            "direction": "neutral",
            "regime_label": STANCE_LABELS[stance],
            "triggers": [],
            "summary": "外資現貨與台指期 OI 皆無有效序列，無法推導資金風險狀態。",
            "components": components,
            "data_complete": False,
            "score": 0,
        }

    # 加權：外資現貨×2、期貨×2、三大法人合計×1、投信×1（輔助）
    score = 0
    weights = [
        (foreign, 2),
        (futures, 2),
        (institutional, 1),
        (trust, 1),
    ]
    for comp, weight in weights:
        if comp is None:
            continue
        score += weight * _score_direction(comp["direction"])

    # 觸發清單：僅納入有方向的成分（供 handoff.signals 與研判）
    triggers: list[dict[str, Any]] = []
    for comp in (foreign, futures, institutional, trust):
        if comp is None:
            continue
        triggers.append(
            {
                "indicator": comp["indicator"],
                "reading": comp["reading"],
                "direction": comp["direction"],
                "rationale": comp["rationale"],
            }
        )

    data_complete = foreign is not None and futures is not None

    # 聚合：|score| 夠大才給進出場側；否則觀望
    # 權重總和理論 max ≈ 6；門檻 3 ≈ 至少一個核心轉多/空且有輔助同向
    if score >= 3:
        stance = "bullish_entry"
    elif score <= -3:
        stance = "bearish_exit"
    else:
        stance = "neutral_watch"

    # 資料不完整時不得假裝完整：降為觀望並標註（若本可進出場仍保留方向但 data_complete=False）
    if not data_complete and stance != "neutral_watch":
        # 仍輸出方向側 stance，但 summary 會標缺漏；acceptance 要求狀態不得假裝完整
        pass

    direction = {
        "bullish_entry": "bullish",
        "bearish_exit": "bearish",
        "neutral_watch": "neutral",
        "data_insufficient": "neutral",
    }[stance]

    # 摘要：趨勢描述，不給偽精確頂底日
    parts = [STANCE_LABELS[stance]]
    if foreign is not None:
        parts.append(f"外資現貨{foreign['direction']}({foreign['reading']})")
    else:
        parts.append("外資現貨缺值")
    if futures is not None:
        parts.append(f"期貨OI{futures['direction']}({futures['reading']})")
    else:
        parts.append("期貨OI缺值")
    if institutional is not None:
        parts.append(f"三大法人合計{institutional['direction']}({institutional['reading']})")
    if not data_complete:
        parts.append("核心維度有缺，解讀需打折")

    summary = "。".join(parts) + "。看多日流向轉折，非單日淨額。"

    return {
        "stance": stance,
        "action_hint": ACTION_HINTS[stance],
        "direction": direction,
        "regime_label": STANCE_LABELS[stance],
        "triggers": triggers,
        "summary": summary,
        "components": {
            k: (
                None
                if v is None
                else {
                    "direction": v["direction"],
                    "reading": v["reading"],
                    "rationale": v["rationale"],
                    **{
                        kk: v[kk]
                        for kk in (
                            "recent_net",
                            "prior_net",
                            "streak_days",
                            "last_oi",
                            "daily_chg",
                            "multi_chg",
                        )
                        if kk in v
                    },
                }
            )
            for k, v in components.items()
        },
        "data_complete": data_complete,
        "score": score,
    }
