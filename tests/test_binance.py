"""BinanceSource against a fake HTTP getter. Rows mirror Binance's 12-field kline arrays exactly."""
import pandas as pd

from qtrading.data.binance import BinanceSource

H = 3_600_000                    # one hour in ms
T0 = 1_725_148_800_000           # 2024-09-01 00:00:00 UTC


def ts(ms):
    return pd.Timestamp(ms, unit="ms", tz="UTC")


def kline(open_ms, close):
    # [open_time, open, high, low, close, volume, close_time, quote_vol, trades, taker_base, taker_quote, ignore]
    return [open_ms, "1.0", "2.0", "0.5", str(close), "10.0", open_ms + H - 1, "100.0", 5, "4.0", "40.0", "0"]


class FakeHttp:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def __call__(self, url, params):
        self.calls.append((url, dict(params)))
        return self.pages.pop(0)


def test_bars_parse_ohlcv_as_floats_indexed_by_bar_close_time():
    http = FakeHttp([[kline(T0, 100.5)]])
    df = BinanceSource(http=http).bars("BTCUSDT", start=ts(T0 + H), end=ts(T0 + H))
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "quote_volume"]
    assert df.index[0] == pd.Timestamp("2024-09-01 01:00", tz="UTC")       # opened 00:00, closed 01:00
    assert df["close"].iloc[0] == 100.5
    assert df["close"].dtype == float


def test_bars_paginate_from_the_last_bar_and_stitch_without_gaps_or_duplicates():
    page1 = [kline(T0 + i * H, i) for i in range(3)]          # a full page of 3
    page2 = [kline(T0 + i * H, i) for i in range(3, 5)]       # short page -> stop
    http = FakeHttp([page1, page2])
    df = BinanceSource(http=http, page_limit=3).bars("BTCUSDT", start=ts(T0 + H), end=ts(T0 + 5 * H))
    assert list(df["close"]) == [0, 1, 2, 3, 4]
    assert http.calls[0][1]["startTime"] == T0                 # first wanted bar closes at 01:00 -> opens at 00:00
    assert http.calls[1][1]["startTime"] == T0 + 3 * H         # resume right after the last received bar


def test_bars_drop_anything_closing_after_end():
    http = FakeHttp([[kline(T0, 1), kline(T0 + H, 2), kline(T0 + 2 * H, 3)]])
    df = BinanceSource(http=http).bars("BTCUSDT", start=ts(T0 + H), end=ts(T0 + 2 * H))
    assert list(df["close"]) == [1, 2]                         # the bar closing at 03:00 is beyond end=02:00


def test_funding_rates_parse_rate_indexed_by_funding_time():
    rows = [{"symbol": "BTCUSDT", "fundingTime": T0, "fundingRate": "0.00010000", "markPrice": "58000.10"},
            {"symbol": "BTCUSDT", "fundingTime": T0 + 8 * H, "fundingRate": "-0.00005000", "markPrice": "58100.00"}]
    http = FakeHttp([rows])
    s = BinanceSource(http=http).funding_rates("BTCUSDT", start=ts(T0), end=ts(T0 + 8 * H))
    assert list(s.index) == [ts(T0), ts(T0 + 8 * H)]
    assert list(s) == [0.0001, -0.00005]
