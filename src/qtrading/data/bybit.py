"""Bybit public market data (no API key): spot klines for tokenised equities (xStocks).

Roostoo's stock pairs are tokenised equities that price around the clock (verified 2026-09-17: live spreads and
moving prints seven hours after the US close, within ~0.2% of Bybit's quotes). Bybit publishes free 24/7 hourly
history for the names it lists, which is the only history of that instrument class we have; our Yahoo data is the
underlying share and stops at the US close. Bybit returns pages newest-first, so this paginates backwards.
"""
import time

import pandas as pd

from .binance import BAR_COLUMNS, _empty_bars, _http_get

KLINE_URL = "https://api.bybit.com/v5/market/kline"
KLINE_COLUMNS = ["start_time", "open", "high", "low", "close", "volume", "quote_volume"]


class BybitSource:
    def __init__(self, http=_http_get, url: str = KLINE_URL, interval: str = "1h", page_limit: int = 1000,
                 pause_s: float = 0.15, sleep=time.sleep):
        self._http = http
        self._url = url
        self._step = pd.Timedelta(interval)
        self._interval = str(int(self._step.total_seconds() // 60))     # Bybit spot intervals are minutes: "60"
        self._page_limit = page_limit
        self._pause_s = pause_s
        self._sleep = sleep

    def bars(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """OHLCV bars whose close time lies in [start, end], indexed by close time (UTC)."""
        step_ms = int(self._step.total_seconds() * 1000)
        first_open_ms = int(start.timestamp() * 1000) - step_ms
        rows, cursor = [], int(end.timestamp() * 1000)
        while cursor >= first_open_ms:
            page = self._http(self._url, {"category": "spot", "symbol": symbol, "interval": self._interval,
                                          "start": first_open_ms, "end": cursor, "limit": self._page_limit})
            page = page["result"]["list"]
            if not page:
                break
            rows.extend(page)
            cursor = min(int(r[0]) for r in page) - 1
            if len(page) < self._page_limit:
                break
            self._sleep(self._pause_s)
        if not rows:
            return _empty_bars()
        raw = pd.DataFrame(rows, columns=KLINE_COLUMNS)
        out = raw[BAR_COLUMNS].astype(float)
        out.index = pd.to_datetime(raw["start_time"].astype("int64"), unit="ms", utc=True) + self._step
        out.index.name = "close_time"
        out = out[(out.index >= start) & (out.index <= end)]
        return out[~out.index.duplicated(keep="last")].sort_index()
