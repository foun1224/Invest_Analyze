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

        # 台指期(TX)每日結算價(區間抓)
        # 表格欄位: [0]契約 [1]到期月份 [2]開盤 [3]最高 [4]最低
        #           [5]最後成交價 [6]漲跌 [7]漲跌% [8]夜盤量 [9]日盤量
        #           [10]合計量 [11]結算價 [12]OI ...
        html_daily = self.http.post_html(
            FUT_DAILY_URL,
            {"queryStartDate": start.strftime("%Y/%m/%d"),
             "queryEndDate": end.strftime("%Y/%m/%d"),
             "commodity_id": "TX"},
            "https://www.taifex.com.tw/cht/3/futDailyMarket",
        )
        if html_daily:
            try:
                tabs = [t for t in pd.read_html(io.StringIO(html_daily)) if t.shape[1] >= 12]
                if tabs:
                    # 每日只取第一筆(近月合約)
                    row = tabs[0].iloc[0]
                    try:
                        v = float(str(row.iloc[11]).replace(",", ""))
                        if 10000 < v < 150000:
                            out["fut_settle"][end.isoformat()] = v
                    except (ValueError, TypeError):
                        pass
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
        """抓取指定日期台指期(TX)夜盤行情；使用 futDailyMarketExcel。
        表格欄位: [5]最後成交價 [8]*盤後交易時段成交量 [9]日盤量 [11]結算價
        """
        result: dict = {"date": d.isoformat(), "close": None, "volume": None,
                        "chg": None, "chg_pct": None}
        html = self.http.post_html(
            FUT_DAILY_URL,
            {"queryStartDate": d.strftime("%Y/%m/%d"),
             "queryEndDate": d.strftime("%Y/%m/%d"),
             "commodity_id": "TX"},
            "https://www.taifex.com.tw/cht/3/futDailyMarket",
        )
        if not html:
            return result
        try:
            tabs = [t for t in pd.read_html(io.StringIO(html)) if t.shape[1] >= 12]
            if not tabs:
                return result
            row = tabs[0].iloc[0]  # 近月合約首筆
            # 最後成交價 col[5]（夜盤結束後即為夜盤收盤）
            try:
                v = float(str(row.iloc[5]).replace(",", ""))
                if 10000 < v < 150000:
                    result["close"] = v
            except (ValueError, TypeError):
                pass
            # 夜盤成交量 col[8]
            try:
                vol = float(str(row.iloc[8]).replace(",", ""))
                if vol >= 0:
                    result["volume"] = int(vol)
            except (ValueError, TypeError):
                pass
        except Exception:  # noqa: BLE001
            pass
        return result
