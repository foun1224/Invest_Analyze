"""三大法人資金流向轉折 → 風險狀態：離線合成序列驅動 shipped 函式。

不 mock fund_flow_regime；不複製第二套規則互比。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from chipflow.fund_flow import fund_flow_regime
from chipflow import pipeline

# 與 config.example 對齊的固定門檻（測試可重現，非硬編碼期望 stance 的旁路規則）
CFG = {
    "signal_thresholds": {
        "flow_window_days": 5,
        "consecutive_days": 3,
        "foreign_fut_oi_daily_spike": 6000,
        "foreign_fut_oi_multi_day_deepen": 10000,
        "fut_oi_multi_window_days": 5,
    }
}

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "schemas" / "handoff.schema.json"


def _meta() -> dict:
    return {
        "conventions": {
            "amount_unit_default": "億元",
            "net_buy_sell_sign": "正=買",
            "series_alignment": "labels",
        },
        "field_legend": {},
        "data_sources": [],
        "generated_at": "test",
        "watch_list": [],
        "open_questions": [],
        "data_gaps_todo": [],
    }


def test_bullish_entry_when_foreign_spot_turns_from_sell_to_buy_and_futures_cover():
    """外資現貨：前5日賣超、近5日買超；期貨：明顯回補 → 偏多／入場。"""
    # 10 日：前半賣、後半買（近5日合計 +50、前5日合計 -50）
    foreign = [-10.0, -10.0, -10.0, -10.0, -10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    trust = [2.0] * 10
    dealer = [0.0] * 10
    # OI 從 -80000 回補到 -50000（多日 +30000 ≥ 10000；末日日變 +8000 ≥ 6000）
    fut = [-80000, -78000, -75000, -70000, -65000, -62000, -60000, -58000, -58000, -50000]

    r = fund_flow_regime(foreign, trust, dealer, fut, CFG)

    assert r["stance"] == "bullish_entry"
    assert r["direction"] == "bullish"
    assert "入場" in r["regime_label"] or "偏多" in r["regime_label"]
    assert r["data_complete"] is True
    assert r["score"] >= 3

    fs = r["components"]["foreign_spot"]
    assert fs is not None
    assert fs["direction"] == "bullish"
    assert fs["recent_net"] is not None and fs["recent_net"] > 0
    assert fs["prior_net"] is not None and fs["prior_net"] < 0

    fo = r["components"]["foreign_futures_oi"]
    assert fo is not None
    assert fo["direction"] == "bullish"
    assert fo["daily_chg"] is not None and fo["daily_chg"] >= 6000

    # 觸發清單可機器讀
    inds = {t["indicator"] for t in r["triggers"]}
    assert "外資現貨流向轉折" in inds
    assert "外資台指期OI轉折" in inds


def test_bearish_exit_when_foreign_spot_turns_sell_and_futures_deepen_short():
    """外資現貨翻賣 + 期貨淨空加深 → 偏空／出場警戒。"""
    foreign = [10.0, 10.0, 10.0, 10.0, 10.0, -10.0, -10.0, -10.0, -10.0, -10.0]
    trust = [1.0] * 10
    dealer = [0.0] * 10
    # 淨空加深：-50k → -70k；末日 -8000
    fut = [-50000, -52000, -55000, -58000, -60000, -62000, -64000, -65000, -62000, -70000]

    r = fund_flow_regime(foreign, trust, dealer, fut, CFG)

    assert r["stance"] == "bearish_exit"
    assert r["direction"] == "bearish"
    assert "出場" in r["regime_label"] or "偏空" in r["regime_label"]
    assert r["score"] <= -3

    fs = r["components"]["foreign_spot"]
    assert fs["direction"] == "bearish"
    assert fs["recent_net"] < 0
    assert fs["prior_net"] > 0

    fo = r["components"]["foreign_futures_oi"]
    assert fo["direction"] == "bearish"
    assert fo["daily_chg"] is not None and fo["daily_chg"] <= -6000


def test_neutral_when_signals_mixed():
    """現貨偏多但期貨大幅加空 → 混雜 → 中性／觀望。"""
    foreign = [-5.0, -5.0, -5.0, -5.0, -5.0, 8.0, 8.0, 8.0, 8.0, 8.0]
    trust = [3.0] * 10
    dealer = [1.0] * 10
    # 期貨單日大加深空單
    fut = [-40000, -40000, -40000, -40000, -40000, -40000, -40000, -40000, -40000, -50000]

    r = fund_flow_regime(foreign, trust, dealer, fut, CFG)

    assert r["stance"] == "neutral_watch"
    assert r["direction"] == "neutral"
    assert "觀望" in r["regime_label"] or "中性" in r["regime_label"]
    # 成分方向應對立
    assert r["components"]["foreign_spot"]["direction"] == "bullish"
    assert r["components"]["foreign_futures_oi"]["direction"] == "bearish"


def test_data_insufficient_when_core_series_missing_no_fabricated_values():
    """外資與期貨皆無值 → data_insufficient；不捏造數字。"""
    r = fund_flow_regime(
        [None, None, None],
        [None, None, None],
        [None, None, None],
        [None, None, None],
        CFG,
    )
    assert r["stance"] == "data_insufficient"
    assert r["data_complete"] is False
    assert r["triggers"] == []
    assert r["components"]["foreign_spot"] is None
    assert r["components"]["foreign_futures_oi"] is None
    assert "無法" in r["summary"] or "缺" in r["summary"]


def test_partial_core_marks_data_incomplete():
    """僅有外資現貨、無期貨 → 仍可給方向，但 data_complete=False。"""
    foreign = [-10.0] * 5 + [10.0] * 5
    r = fund_flow_regime(foreign, [1.0] * 10, [0.0] * 10, [None] * 10, CFG)
    assert r["data_complete"] is False
    assert r["components"]["foreign_spot"] is not None
    assert r["components"]["foreign_futures_oi"] is None
    # 不可為 data_insufficient（有核心現貨可讀）
    assert r["stance"] != "data_insufficient"


def test_build_handoff_includes_fund_flow_regime_and_passes_schema():
    """最小 merged → handoff 含 fund_flow_regime，通過 schema；缺維度 data_gaps。"""
    # 10 個交易日：外資賣→買、期貨回補 → 期望 bullish 側
    dates = [f"2026-06-{d:02d}" for d in range(16, 26)]
    foreign = [-10.0, -10.0, -10.0, -10.0, -10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    fut = [-80000, -78000, -75000, -70000, -65000, -62000, -60000, -58000, -58000, -50000]
    merged = {
        "foreign_daily": dict(zip(dates, foreign)),
        "trust_daily": {d: 2.0 for d in dates},
        "dealer_daily": {d: 0.0 for d in dates},
        "fut_oi": dict(zip(dates, fut)),
        "index": {d: 22000.0 + i for i, d in enumerate(dates)},
        "volume": {d: 3000.0 for d in dates},
    }
    h = pipeline.build_handoff(
        merged, date(2026, 6, 25), date(2026, 6, 16), CFG, _meta()
    )

    assert "fund_flow_regime" in h
    fr = h["fund_flow_regime"]
    assert fr["stance"] == "bullish_entry"
    assert fr["direction"] == "bullish"
    assert "入場" in h["thesis"]["net_read"] or "偏多" in h["thesis"]["regime"]
    assert any(s["indicator"] == "資金風險狀態" for s in h["signals"])
    # 未提供的外圍序列 → data_gaps，且 series 全 null
    assert "sox" in h["data_gaps"]
    assert all(x is None for x in h["series"]["sox"])

    pipeline.validate(h, str(SCHEMA))


def test_build_handoff_gap_when_no_foreign_or_fut():
    """foreign_daily / fut 全 null → data_gaps + series 全 null，不捏造 0；無假 bullish 訊號。"""
    # master 軸仍需日期 key；值為 None 表示抓取失敗
    h = pipeline.build_handoff(
        {
            "foreign_daily": {"2026-06-30": None},
            "index": {"2026-06-30": 22000.0},
        },
        date(2026, 6, 30),
        date(2026, 6, 1),
        CFG,
        _meta(),
    )
    fr = h["fund_flow_regime"]
    assert fr["stance"] == "data_insufficient"
    assert fr["data_complete"] is False

    assert "foreign_cum" in h["data_gaps"]
    assert "fut_oi" in h["data_gaps"]
    assert all(x is None for x in h["series"]["foreign_cum"]), (
        f"foreign_cum must be all-null when missing, got {h['series']['foreign_cum']}"
    )
    assert all(x is None for x in h["series"]["fut_oi"])
    assert all(x is None for x in h["series"]["trust_cum"])
    assert all(x is None for x in h["series"]["dealer_cum"])

    # 不得出現「外資現貨累計 +0億」這類由假 0 衍生的訊號
    for s in h["signals"]:
        if s["indicator"] == "外資現貨累計":
            raise AssertionError(f"fabricated foreign_cum signal: {s}")
        if "累計" in s["indicator"] and s.get("reading", "").startswith("+0"):
            raise AssertionError(f"fabricated zero cumulative signal: {s}")

    pipeline.validate(h, str(SCHEMA))


def test_thresholds_come_from_config_not_hardcoded_spike():
    """提高期貨單日門檻後，同樣日變不再觸發期貨偏空。"""
    foreign = [0.0] * 10  # 現貨中性
    trust = [0.0] * 10
    dealer = [0.0] * 10
    fut = [-50000] * 9 + [-56000]  # 日變 -6000

    low = fund_flow_regime(foreign, trust, dealer, fut, {
        "signal_thresholds": {
            "flow_window_days": 5,
            "consecutive_days": 3,
            "foreign_fut_oi_daily_spike": 6000,
            "foreign_fut_oi_multi_day_deepen": 999999,
            "fut_oi_multi_window_days": 5,
        }
    })
    high = fund_flow_regime(foreign, trust, dealer, fut, {
        "signal_thresholds": {
            "flow_window_days": 5,
            "consecutive_days": 3,
            "foreign_fut_oi_daily_spike": 20000,
            "foreign_fut_oi_multi_day_deepen": 999999,
            "fut_oi_multi_window_days": 5,
        }
    })
    assert low["components"]["foreign_futures_oi"]["direction"] == "bearish"
    assert high["components"]["foreign_futures_oi"]["direction"] == "neutral"
