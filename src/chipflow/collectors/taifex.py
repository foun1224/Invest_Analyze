"""TAIFEX(臺灣期貨交易所)collector。

已實作(經驗證):futContractsDate(外資台指期未平倉、散戶小台)、pcRatio。
★ 務必用 queryDate 途徑;futContractsDateExcel 帶區間會忽略日期只回最新一天。
細節見 docs/data_sources.md。
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd

from .base import BaseCollector, trading_day_candidates, to_iso

FUT_URL = "https://www.taifex.com.tw/cht/3/futContractsDate"
FUT_DAILY_URL = "https://www.taifex.com.tw/cht/3/futDailyMarketExcel"
NIGHT_URL = "https://www.taifex.com.tw/cht/3/afterHoursFutDailyMarketExcel"
PCR_URL = "https://www.taifex.com.tw/cht/3/pcRatioExcel"


def _parse_contract_table(html: str) -> pd.DataFrame | None:
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:  # noqa: BLE001
        return None
    for t in tables:
        if t.shape[1] >= 15 and t.shape[0] > 5:
            return t
    return None


class TaifexCollector(BaseCollector):
    def collect(self, start: date, end: date) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {
            "fut_oi": {}, "fut_trade_net": {}, "retail_mtx": {}, "pcr": {},
            "fut_settle": {},
        }
        for d in trading_day_candidates(start, end):
            iso = to_iso(d)
            html = self.http.post_html(
                FUT_URL, {"queryDate": d.strftime("%Y/%m/%d"), "doQuery": "1"}, FUT_URL)
            if not html:
                continue
            t = _parse_contract_table(html)
            if t is None:
                continue
            c1 = t.iloc[:, 1].astype(str).str.strip()
            c2 = t.iloc[:, 2].astype(str).str.strip()

            # 外資台指期(TX)
            m = (c1 == "臺股期貨") & (c2 == "外資")
            if m.any():
                i = t.index[m][0]
                try:
                    out["fut_oi"][iso] = int(t.iloc[i, 13])       # 未平倉多空淨額 口
                    out["fut_trade_net"][iso] = int(t.iloc[i, 7])  # 當日交易淨 口
                except (ValueError, TypeError):
                    pass

            # 散戶小台 = -(自營+投信+外資 之小型臺指未平倉淨額)
            mm = (c1 == "小型臺指期貨")
            if mm.sum() >= 3:
                sub = t[mm]
                sub2 = c2[mm]
                法人 = 0
                ok = True
                for who in ("自營商", "投信", "外資"):
                    rr = sub[sub2 == who]
                    if len(rr):
                        try:
                            法人 += int(rr.iloc[0, 13])
                        except (ValueError, TypeError):
                            ok = False
                    else:
                        ok = False
                if ok:
                    out["retail_mtx"][iso] = -法人

        # 台指期(TX)每日結算價(區間;近月合約=每日首筆)
        html_daily = self.http.post_html(
            FUT_DAILY_URL,
            {"queryStartDate": start.strftime("%Y/%m/%d"),
             "queryEndDate": end.strftime("%Y/%m/%d"),
             "commodity_id": "TX"},
            "https://www.taifex.com.tw/cht/3/futDailyMarket",
        )
        if html_daily:
            try:
                tabs = [t for t in pd.read_html(io.StringIO(html_daily)) if t.shape[1] >= 8]
                if tabs:
                    for _, row in tabs[0].iterrows():
                        try:
                            raw = str(row.iloc[0]).strip()
                            if "/" not in raw:
                                continue
                            parts = raw.split("/")
                            if len(parts) != 3:
                                continue
                            y, m2, d2 = int(parts[0]), int(parts[1]), int(parts[2])
                            if y < 200:
                                y += 1911
                            iso = f"{y:04d}-{m2:02d}-{d2:02d}"
                            if iso in out["fut_settle"]:
                                continue  # 保留近月(每日首筆)
                            # 結算價優先 col 10;備用 col 6(收盤)
                            settle = None
                            for ci in (10, 6):
                                if ci < len(row):
                                    try:
                                        v = float(str(row.iloc[ci]).replace(",", ""))
                                        if 10000 < v < 150000:
                                            settle = v
                                            break
                                    except (ValueError, TypeError):
                                        pass
                            if settle:
                                out["fut_settle"][iso] = settle
                        except Exception:  # noqa: BLE001
                            continue
            except Exception:  # noqa: BLE001
                pass  # 降級:fut_settle 留白

        # 選擇權 P/C 未平倉比(單次抓區間;端點偶發不穩 -> 降級留白)
        html = self.http.post_html(
            PCR_URL,
            {"queryStartDate": start.strftime("%Y/%m/%d"),
             "queryEndDate": end.strftime("%Y/%m/%d")},
            "https://www.taifex.com.tw/cht/3/pcRatio",
        )
        if html:
            try:
                tabs = [x for x in pd.read_html(io.StringIO(html)) if x.shape[1] >= 7]
                if tabs:
                    for _, row in tabs[0].iterrows():
                        try:
                            y, m2, d2 = str(row.iloc[0]).split("/")
                            iso = f"{int(y):04d}-{int(m2):02d}-{int(d2):02d}"
                            out["pcr"][iso] = float(row.iloc[6])  # 未平倉比率
                        except Exception:  # noqa: BLE001
                            continue
            except Exception:  # noqa: BLE001
                pass  # 降級:pcr 留白,由 data_gaps 記錄

        return out

    def collect_night(self, d: date) -> dict:
        """抓取指定日期台指期(TX)夜盤行情；結果為單筆 dict，非時間序列。"""
        result: dict = {"date": d.isoformat(), "close": None, "volume": None,
                        "chg": None, "chg_pct": None}
        html = self.http.post_html(
            NIGHT_URL,
            {"queryStartDate": d.strftime("%Y/%m/%d"),
             "queryEndDate": d.strftime("%Y/%m/%d"),
             "commodity_id": "TX"},
            "https://www.taifex.com.tw/cht/3/afterHoursFutDailyMarket",
        )
        if not html:
            return result
        try:
            tabs = [t for t in pd.read_html(io.StringIO(html)) if t.shape[1] >= 6]
            if not tabs:
                return result
            for _, row in tabs[0].iterrows():
                settle = None
                for ci in (10, 6):
                    if ci < len(row):
                        try:
                            v = float(str(row.iloc[ci]).replace(",", ""))
                            if 10000 < v < 150000:
                                settle = v
                                break
                        except (ValueError, TypeError):
                            pass
                if settle:
                    result["close"] = settle
                    for vi in (9, 8):
                        if vi < len(row):
                            try:
                                vol = float(str(row.iloc[vi]).replace(",", ""))
                                if vol > 0:
                                    result["volume"] = int(vol)
                                    break
                            except (ValueError, TypeError):
                                pass
                    break  # 取近月(首筆)
        except Exception:  # noqa: BLE001
            pass
        return result
