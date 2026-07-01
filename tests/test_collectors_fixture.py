"""離線 collector 測試 — 用錄製 fixture，CI 不打外網。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


# ── helper ────────────────────────────────────────────────────────────────────

def _json_resp(filename: str) -> MagicMock:
    data = json.loads((FIXTURES / filename).read_text())
    m = MagicMock()
    m.json.return_value = data
    m.status_code = 200
    m.raise_for_status = MagicMock()
    return m


def _html_resp(filename: str) -> MagicMock:
    text = (FIXTURES / filename).read_text()
    m = MagicMock()
    m.text = text
    m.status_code = 200
    m.raise_for_status = MagicMock()
    return m


# ── TWSE BFI82U ───────────────────────────────────────────────────────────────

def test_bfi82u_foreign_net():
    from chipflow.collectors.twse import TwseCollector

    col = TwseCollector.__new__(TwseCollector)
    col.http = MagicMock()
    col.http.get_json.return_value = json.loads((FIXTURES / "bfi82u_20260630.json").read_text())

    result = col.collect(date(2026, 6, 30), date(2026, 6, 30))

    # 外資淨額 = 15,600,000,000 元 = 156.0 億
    assert "foreign_daily" in result
    val = result["foreign_daily"].get("2026-06-30")
    assert val is not None
    assert abs(val - 156.0) < 1.0, f"Expected ~156 億, got {val}"


def test_bfi82u_non_ok_stat():
    from chipflow.collectors.twse import TwseCollector

    col = TwseCollector.__new__(TwseCollector)
    col.http = MagicMock()
    col.http.get_json.return_value = {"stat": "NO DATA"}

    result = col.collect(date(2026, 6, 28), date(2026, 6, 28))

    # 非交易日 → 回傳空，不杜撰
    assert result.get("foreign_daily", {}) == {}


def test_fmtqik_index_close():
    from chipflow.collectors.twse import TwseCollector

    col = TwseCollector.__new__(TwseCollector)
    col.http = MagicMock()
    col.http.get_json.return_value = json.loads((FIXTURES / "fmtqik_202606.json").read_text())

    result = col.collect(date(2026, 6, 30), date(2026, 6, 30))

    assert "index" in result
    val = result["index"].get("2026-06-30")
    assert val is not None
    assert abs(val - 22520.30) < 1.0, f"Expected ~22520, got {val}"


# ── pipeline null-safety ──────────────────────────────────────────────────────

def test_pipeline_null_series_recorded_in_data_gaps():
    """來源全空 → series 全 null，data_gaps 有記錄，無假值。"""
    from chipflow import pipeline

    merged: dict = {
        "foreign_daily": {"2026-06-30": -5.1},
    }
    meta = {
        "conventions": {
            "amount_unit_default": "億元",
            "net_buy_sell_sign": "正=買超/淨多 負=賣超/淨空",
            "series_alignment": "台股交易日主軸",
        },
        "field_legend": {},
        "data_sources": [],
        "generated_at": "",
        "watch_list": [],
        "open_questions": [],
        "data_gaps_todo": [],
    }
    h = pipeline.build_handoff(
        merged, date(2026, 6, 30), date(2026, 5, 28), {}, meta
    )

    # sox 未提供 → 應在 data_gaps
    assert "sox" in h["data_gaps"]
    # sox series 全為 null
    assert all(v is None for v in h["series"]["sox"])
    # 不含捏造值
    assert all(v is None or isinstance(v, (int, float)) for v in h["series"]["sox"])
