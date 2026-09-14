"""Yahoo Finance via yfinance (no key) — used for the US-stock underlyings of Roostoo's tokenized stocks.

yfinance labels intraday bars by their START time in the exchange's timezone; we re-index by CLOSE time in UTC.
"""
import pandas as pd

BAR_COLUMNS = ["open", "high", "low", "close", "volume"]
_RENAME = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


def _download(ticker: str, **kwargs):
    import yfinance as yf
    return yf.download(ticker, progress=False, auto_adjust=True, **kwargs)


def _empty_bars() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=float) for c in BAR_COLUMNS},
                        index=pd.DatetimeIndex([], tz="UTC", name="close_time"))


class YahooSource:
    def __init__(self, download=_download, interval: str = "1h"):
        self._download = download
        self._interval = interval
        self._step = pd.Timedelta(interval)

    def bars(self, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        raw = self._download(ticker, start=start.strftime("%Y-%m-%d"),
                             end=(end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), interval=self._interval)
        if raw is None or len(raw) == 0:
            return _empty_bars()
        if isinstance(raw.columns, pd.MultiIndex):
            raw = raw.droplevel(1, axis=1)                 # drop the Ticker level
        out = raw.rename(columns=_RENAME)[BAR_COLUMNS].astype(float)
        idx = pd.DatetimeIndex(out.index)
        idx = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
        out.index = idx + self._step
        out.index.name = "close_time"
        out = out[(out.index >= start) & (out.index <= end)]
        return out[~out.index.duplicated(keep="last")].sort_index()
