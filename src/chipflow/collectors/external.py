"""外圍 collector(Yahoo Finance):SOX / Nasdaq / TSMC-ADR / 2330 / OTC / DXY / US10Y / VIX / USDTWD。

回傳各序列(iso_date -> close)。台積電 ADR 溢價與其他衍生值由 build_handoff 計算
(需 tsm / t2330 / usdtwd 三者)。細節見 docs/data_sources.md。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from .base import BaseCollector

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"

DEFAULT_SYMBOLS = {
    "sox": "^SOX", "ndx": "^IXIC", "tsm": "TSM", "t2330": "2330.TW",
    "otc": "^TWOII", "dxy": "DX-Y.NYB", "tnx": "^TNX", "vix": "^VIX",
    "usdtwd": "USDTWD=X",
}


def _range_str(start: date, end: date) -> str:
    days = (end - start).days
    if days <= 35:
        return "2mo"
    if days <= 65:
        return "3mo"
    return "6mo"


class ExternalCollector(BaseCollector):
    def collect(self, start: date, end: date) -> dict[str, dict[str, float]]:
        symbols = self.cfg.get("external_symbols", DEFAULT_SYMBOLS)
        rng = _range_str(start, end)
        out: dict[str, dict[str, float]] = {}
        for key, sym in symbols.items():
            data = self.http.get_json(CHART.format(sym=sym.replace("^", "%5E"), rng=rng))
            series: dict[str, float] = {}
            try:
                res = data["chart"]["result"][0]
                ts = res["timestamp"]
                closes = res["indicators"]["quote"][0]["close"]
                for t, c in zip(ts, closes):
                    if c is None:
                        continue
                    iso = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
                    if start.isoformat() <= iso <= end.isoformat():
                        series[iso] = round(float(c), 3)
            except (TypeError, KeyError, IndexError):
                series = {}  # 降級:留白,由 data_gaps 記錄
            out[key] = series
        return out
