"""YahooSource against a fake yfinance.download. The frame mirrors yfinance's MultiIndex (Price, Ticker) layout."""
import pandas as pd

from qtrading.data.yahoo import YahooSource


def yf_frame(ticker, rows):
    """rows: list of (local New York timestamp, close)."""
    idx = pd.DatetimeIndex([pd.Timestamp(t, tz="America/New_York") for t, _ in rows])
    cols = pd.MultiIndex.from_product([["Close", "High", "Low", "Open", "Volume"], [ticker]], names=["Price", "Ticker"])
    data = [[c, c + 1, c - 1, c - 0.5, 1000] for _, c in rows]
    return pd.DataFrame(data, index=idx, columns=cols)


class FakeDownload:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def __call__(self, ticker, **kwargs):
        self.calls.append((ticker, kwargs))
        return self.frame


def test_bars_take_close_and_index_by_bar_close_time_in_utc():
    dl = FakeDownload(yf_frame("NVDA", [("2026-09-11 09:30", 100.0), ("2026-09-11 10:30", 102.0)]))
    df = YahooSource(download=dl).bars("NVDA", start=pd.Timestamp("2026-09-11", tz="UTC"),
                                        end=pd.Timestamp("2026-09-12", tz="UTC"))
    # 09:30 EDT bar closes 10:30 EDT == 14:30 UTC
    assert list(df.index) == [pd.Timestamp("2026-09-11 14:30", tz="UTC"), pd.Timestamp("2026-09-11 15:30", tz="UTC")]
    assert list(df["close"]) == [100.0, 102.0]


def test_bars_return_empty_frame_when_yahoo_has_nothing():
    dl = FakeDownload(pd.DataFrame())
    df = YahooSource(download=dl).bars("WLFI-USD", start=pd.Timestamp("2026-09-11", tz="UTC"),
                                        end=pd.Timestamp("2026-09-12", tz="UTC"))
    assert len(df) == 0
    assert "close" in df.columns
