"""共用 HTTP 工具與 collector 抽象介面。

所有 collector 回傳統一格式:
    { series_key: { "YYYY-MM-DD": float, ... }, ... }
其中值為「原始」讀數(流量為當日淨額、部位為當日水位),
累計序列(foreign_cum / adl 等)與衍生值(adr_prem)由 build_handoff 計算。

守則:抓取失敗回傳空 dict 或跳過該日,呼叫端據此在 data_gaps 記錄,
      **絕不以假值填補**。
"""
from __future__ import annotations

import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import requests

log = logging.getLogger("chipflow.collectors")


@dataclass
class HttpConfig:
    min_interval_sec: float = 0.25
    timeout_sec: int = 25
    max_retries: int = 3
    user_agent: str = "Mozilla/5.0 (chipflow)"


class RateLimiter:
    """跨呼叫的簡易節流,對來源保持禮貌的請求間隔。"""

    def __init__(self, min_interval_sec: float):
        self.min_interval = min_interval_sec
        self._last = 0.0

    def wait(self) -> None:
        dt = time.monotonic() - self._last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last = time.monotonic()


class HttpClient:
    def __init__(self, cfg: HttpConfig):
        self.cfg = cfg
        self.limiter = RateLimiter(cfg.min_interval_sec)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": cfg.user_agent})

    def _request(self, method: str, url: str, **kw) -> requests.Response | None:
        last_exc: Exception | None = None
        for attempt in range(1, self.cfg.max_retries + 1):
            self.limiter.wait()
            try:
                r = self.session.request(
                    method, url, timeout=self.cfg.timeout_sec, **kw
                )
                r.raise_for_status()
                return r
            except Exception as e:  # noqa: BLE001
                last_exc = e
                log.warning("HTTP %s %s attempt %d/%d failed: %s",
                            method, url, attempt, self.cfg.max_retries, e)
                time.sleep(0.4 * attempt)
        log.error("HTTP %s %s gave up: %s", method, url, last_exc)
        return None

    def get_json(self, url: str) -> Any | None:
        r = self._request("GET", url)
        if r is None:
            return None
        try:
            return r.json()
        except ValueError:
            log.error("Non-JSON response from %s", url)
            return None

    def post_html(self, url: str, data: dict, referer: str) -> str | None:
        r = self._request("POST", url, data=data, headers={"Referer": referer})
        return None if r is None else r.text


def trading_day_candidates(start: date, end: date) -> list[date]:
    """回傳區間內的工作日(週一至週五)。實際交易日由各源回傳是否為空判定。"""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def to_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def num(x: Any) -> float | None:
    """把含千分位/百分比殘留的字串轉 float;失敗回 None。"""
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


@dataclass
class BaseCollector(ABC):
    """所有 collector 的抽象基底。"""

    http: HttpClient
    cfg: dict = field(default_factory=dict)

    @abstractmethod
    def collect(self, start: date, end: date) -> dict[str, dict[str, float]]:
        """回傳 { series_key: { iso_date: value } }。失敗維度可略過。"""
        raise NotImplementedError
