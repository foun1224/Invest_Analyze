"""TWSE(臺灣證券交易所)collector。

已實作(經驗證):BFI82U、FMTQIK、MI_MARGN、TWT93U、MI_INDEX、BWIBBU、T86。
端點/欄位細節見 docs/data_sources.md。
"""
from __future__ import annotations

import statistics
from datetime import date

from .base import BaseCollector, trading_day_candidates, to_iso, num

TWSE = "https://www.twse.com.tw/rwd/zh"


def _roc_to_iso(s: str) -> str | None:
    """民國 '115/06/30' -> '2026-06-30'。"""
    try:
        y, m, d = s.split("/")
        return f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"
    except Exception:  # noqa: BLE001
        return None


class TwseCollector(BaseCollector):
    def collect(self, start: date, end: date) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {
            k: {} for k in (
                "foreign_daily", "trust_daily", "dealer_daily",
                "index", "volume",
                "margin_fin", "margin_short", "sbl",
                "breadth_up", "breadth_dn",
                "pe", "pb", "yd",
            )
        }
        days = trading_day_candidates(start, end)

        # --- FMTQIK: index + volume (單次抓整月,先蒐集涵蓋的月份) ---
        months = sorted({(d.year, d.month) for d in days})
        for y, m in months:
            data = self.http.get_json(
                f"{TWSE}/afterTrading/FMTQIK?date={y}{m:02d}01&response=json")
            if not data or data.get("stat") != "OK":
                continue
            for row in data.get("data", []):
                iso = _roc_to_iso(row[0])
                if not iso:
                    continue
                idx = num(row[4])
                amt = num(row[2])
                if idx is not None:
                    out["index"][iso] = idx
                if amt is not None:
                    out["volume"][iso] = round(amt / 1e8, 1)  # 元 -> 億元

        # --- per-day endpoints ---
        for d in days:
            ymd = d.strftime("%Y%m%d")
            iso = to_iso(d)

            # BFI82U 三大法人現貨
            data = self.http.get_json(
                f"{TWSE}/fund/BFI82U?type=day&dayDate={ymd}&response=json")
            if data and data.get("stat") == "OK":
                rows = {r[0]: r for r in data["data"]}

                def net(name: str) -> float | None:
                    r = rows.get(name)
                    return None if r is None else num(r[3])
                f = net("外資及陸資(不含外資自營商)")
                t = net("投信")
                ds = net("自營商(自行買賣)")
                dh = net("自營商(避險)")
                if f is not None:
                    out["foreign_daily"][iso] = round(f / 1e8, 1)
                if t is not None:
                    out["trust_daily"][iso] = round(t / 1e8, 1)
                if ds is not None and dh is not None:
                    out["dealer_daily"][iso] = round((ds + dh) / 1e8, 1)

            # MI_MARGN 融資融券
            data = self.http.get_json(
                f"{TWSE}/marginTrading/MI_MARGN?date={ymd}&selectType=MS&response=json")
            if data and data.get("stat") == "OK":
                try:
                    rows = data["tables"][0]["data"]
                    fin = num(rows[2][5])
                    short = num(rows[1][5])
                    if fin is not None:
                        out["margin_fin"][iso] = round(fin / 1e5, 1)  # 仟元 -> 億元
                    if short is not None:
                        out["margin_short"][iso] = short
                except (KeyError, IndexError):
                    pass

            # TWT93U 借券賣出(逐檔加總)
            data = self.http.get_json(
                f"{TWSE}/marginTrading/TWT93U?date={ymd}&response=json")
            if data and data.get("stat") == "OK" and data.get("data"):
                total = 0.0
                for row in data["data"]:
                    v = num(row[12])
                    if v is not None:
                        total += v
                out["sbl"][iso] = round(total / 1e8, 1)  # 股 -> 億股

            # MI_INDEX 漲跌家數
            data = self.http.get_json(
                f"{TWSE}/afterTrading/MI_INDEX?date={ymd}&type=MS&response=json")
            if data and data.get("stat") == "OK":
                for tb in data.get("tables", []):
                    if str(tb.get("title", "")) == "漲跌證券數合計":
                        rows = {r[0]: r for r in tb["data"]}
                        try:
                            up = int(rows["上漲(漲停)"][2].split("(")[0].replace(",", ""))
                            dn = int(rows["下跌(跌停)"][2].split("(")[0].replace(",", ""))
                            out["breadth_up"][iso] = up
                            out["breadth_dn"][iso] = dn
                        except (KeyError, ValueError, IndexError):
                            pass
                        break

            # BWIBBU 估值中位數
            data = self.http.get_json(
                f"{TWSE}/afterTrading/BWIBBU_d?date={ymd}&selectType=ALL&response=json")
            if data and data.get("stat") == "OK":
                pe, pb, yd = [], [], []
                for r in data["data"]:
                    p, b, y = num(r[5]), num(r[6]), num(r[3])
                    if p and p > 0:
                        pe.append(p)
                    if b and b > 0:
                        pb.append(b)
                    if y is not None:
                        yd.append(y)
                if pe:
                    out["pe"][iso] = round(statistics.median(pe), 1)
                if pb:
                    out["pb"][iso] = round(statistics.median(pb), 2)
                if yd:
                    out["yd"][iso] = round(statistics.median(yd), 2)

        return out

    def get_composition(self, d: date, top_n: int = 6) -> dict | None:
        """T86:回傳指定日外資買/賣超前 N 檔(張)。供 build_handoff 附入。"""
        ymd = d.strftime("%Y%m%d")
        data = self.http.get_json(
            f"{TWSE}/fund/T86?date={ymd}&selectType=ALLBUT0999&response=json")
        if not data or data.get("stat") != "OK":
            return None
        fields = data["fields"]
        try:
            fi = next(i for i, f in enumerate(fields)
                      if "外陸資買賣超股數" in f or "外資買賣超股數" in f)
        except StopIteration:
            return None
        rows = []
        for r in data["data"]:
            v = num(r[fi])
            if v is not None:
                rows.append((r[1].strip(), int(v / 1e3)))  # 股 -> 張
        rows.sort(key=lambda x: x[1])
        return {
            "foreign_top_sells_zhang": rows[:top_n],
            "foreign_top_buys_zhang": rows[-top_n:][::-1],
        }
