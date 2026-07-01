"""煙霧測試 + 骨架。CI 不打外網;真實 collector 測試請用錄製 fixture。"""
from datetime import date

from chipflow import pipeline


def test_cumsum_handles_nulls():
    assert pipeline._cumsum([1.0, None, 2.0]) == [1.0, 1.0, 3.0]


def test_master_dates_from_foreign():
    merged = {"foreign_daily": {"2026-06-30": 1.0, "2026-06-29": 2.0}}
    assert pipeline.master_dates(merged) == ["2026-06-29", "2026-06-30"]


def test_to_label():
    assert pipeline.to_label("2026-06-30") == "06/30"


def test_data_gaps_recorded_when_series_empty():
    # 全空來源 → 應在 data_gaps 記錄,且不出現假值
    merged = {"foreign_daily": {"2026-06-30": -5.1}}
    meta = {"conventions": {"amount_unit_default": "億元", "net_buy_sell_sign": "x",
                            "series_alignment": "x"},
            "field_legend": {}, "data_sources": [], "generated_at": "",
            "watch_list": [], "open_questions": [], "data_gaps_todo": []}
    h = pipeline.build_handoff(merged, date(2026, 6, 30), date(2026, 5, 15), {}, meta)
    assert "sox" in h["data_gaps"]           # 未提供 → 記錄於 gaps
    assert all(x is None for x in h["series"]["sox"])  # 無假值

# TODO(agent): 加入 collector fixture 測試(錄製 TWSE/TAIFEX/Yahoo 回應離線驗證)。
