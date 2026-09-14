"""Binance public market data (no API key). Spot klines for prices, futures funding rates as a positioning signal."""
import time

import pandas as pd
import requests

SPOT_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
FUTURES_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"

KLINE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
                 "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]
BAR_COLUMNS = ["open", "high", "low", "close", "volume", "quote_volume"]


TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}


def _is_transient(e: Exception) -> bool:
    if isinstance(e, requests.HTTPError):
        resp = getattr(e, "response", None)
        return resp is not None and getattr(resp, "status_code", 0) in TRANSIENT_STATUS
    return isinstance(e, (requests.ConnectionError, requests.Timeout))


def with_retries(get, attempts: int = 5, backoff_s: float = 1.0, sleep=time.sleep):
    """Wrap a ``get(url, params)`` callable: retry transient failures with exponential backoff,
    re-raise permanent ones (4xx other than 408/429) immediately."""
    def wrapped(url, params):
        for i in range(attempts):
            try:
                return get(url, params)
            except requests.RequestException as e:
                if not _is_transient(e) or i == attempts - 1:
                    raise
                sleep(backoff_s * 2 ** i)
    return wrapped


def _raw_get(url: str, params: dict):
    resp = requests.get(url, params=params, timeout=(10, 30))     # (connect, read) seconds
    resp.raise_for_status()
    return resp.json()


_http_get = with_retries(_raw_get)


def _empty_bars() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=float) for c in BAR_COLUMNS},
                        index=pd.DatetimeIndex([], tz="UTC", name="close_time"))


class BinanceSource:
    def __init__(self, http=_http_get, spot_url: str = SPOT_KLINES_URL, futures_url: str = FUTURES_FUNDING_URL,
                 interval: str = "1h", page_limit: int = 1000, pause_s: float = 0.15, sleep=time.sleep):
        self._http = http
        self._spot_url = spot_url
        self._futures_url = futures_url
        self._interval = interval
        self._step = pd.Timedelta(interval)
        self._page_limit = page_limit
        self._pause_s = pause_s
        self._sleep = sleep

    def bars(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """OHLCV bars whose close time lies in [start, end], indexed by close time (UTC)."""
        step_ms = int(self._step.total_seconds() * 1000)
        first_open_ms = int(start.timestamp() * 1000) - step_ms
        rows = self._paginate(self._spot_url, {"symbol": symbol, "interval": self._interval},
                              first_open_ms, int(end.timestamp() * 1000), time_of=lambda r: r[0], step_ms=step_ms)
        if not rows:
            return _empty_bars()
        raw = pd.DataFrame(rows, columns=KLINE_COLUMNS)
        out = raw[BAR_COLUMNS].astype(float)
        out.index = pd.to_datetime(raw["open_time"].astype("int64"), unit="ms", utc=True) + self._step
        out.index.name = "close_time"
        out = out[(out.index >= start) & (out.index <= end)]
        return out[~out.index.duplicated(keep="last")].sort_index()

    def funding_rates(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
        """Perpetual funding rate (fraction per 8h settlement) indexed by funding time (UTC)."""
        rows = self._paginate(self._futures_url, {"symbol": symbol}, int(start.timestamp() * 1000),
                              int(end.timestamp() * 1000), time_of=lambda r: int(r["fundingTime"]), step_ms=1)
        idx = pd.to_datetime([int(r["fundingTime"]) for r in rows], unit="ms", utc=True)
        s = pd.Series([float(r["fundingRate"]) for r in rows], index=idx, name="funding_rate", dtype=float)
        s = s[(s.index >= start) & (s.index <= end)]
        return s[~s.index.duplicated(keep="last")].sort_index()

    def _paginate(self, url, base_params, start_ms, end_ms, time_of, step_ms):
        out, cursor = [], start_ms
        while cursor <= end_ms:
            rows = self._http(url, {**base_params, "startTime": cursor, "endTime": end_ms, "limit": self._page_limit})
            if not rows:
                break
            out.extend(rows)
            cursor = time_of(rows[-1]) + step_ms
            if len(rows) < self._page_limit:
                break
            self._sleep(self._pause_s)
        return out
