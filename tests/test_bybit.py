"""BybitSource against a fake HTTP getter. Rows mirror Bybit's v5 spot kline arrays: newest first, all strings."""
import pandas as pd

from qtrading.data.bybit import BybitSource

H = 3_600_000                    # one hour in ms
T0 = 1_751_241_600_000           # 2025-06-30 00:00:00 UTC


def ts(ms):
    return pd.Timestamp(ms, unit="ms", tz="UTC")


def kline(start_ms, close):
    # [startTime, open, high, low, close, volume, turnover]
    return [str(start_ms), "1.0", "2.0", "0.5", str(close), "10.0", "1000.0"]


def envelope(rows):
    return {"retCode": 0, "retMsg": "OK", "result": {"category": "spot", "symbol": "NVDAXUSDT", "list": rows}}


class FakeHttp:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def __call__(self, url, params):
        self.calls.append((url, dict(params)))
        return self.pages.pop(0)


def test_bars_parse_bybit_klines_as_floats_indexed_by_close_time():
    http = FakeHttp([envelope([kline(T0, 216.5)])])
    df = BybitSource(http=http).bars("NVDAXUSDT", start=ts(T0 + H), end=ts(T0 + H))
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "quote_volume"]
    assert df.index[0] == pd.Timestamp("2025-06-30 01:00", tz="UTC")       # opened 00:00, closed 01:00
    assert df["close"].iloc[0] == 216.5 and df["quote_volume"].iloc[0] == 1000.0
    assert http.calls[0][1]["category"] == "spot" and http.calls[0][1]["interval"] == "60"


def test_bars_page_backwards_from_the_end_and_stitch_in_order():
    newest = [kline(T0 + i * H, i) for i in (4, 3, 2)]          # a full page of 3, newest first
    older = [kline(T0 + i * H, i) for i in (1, 0)]              # short page -> stop
    http = FakeHttp([envelope(newest), envelope(older)])
    df = BybitSource(http=http, page_limit=3).bars("NVDAXUSDT", start=ts(T0 + H), end=ts(T0 + 5 * H))
    assert list(df["close"]) == [0, 1, 2, 3, 4]
    assert df.index[0] == ts(T0 + H) and df.index[-1] == ts(T0 + 5 * H)
    assert http.calls[1][1]["end"] == T0 + 2 * H - 1                  # the next page ends before the oldest bar seen


def test_empty_response_gives_an_empty_frame():
    df = BybitSource(http=FakeHttp([envelope([])])).bars("NVDAXUSDT", start=ts(T0), end=ts(T0 + H))
    assert df.empty and list(df.columns) == ["open", "high", "low", "close", "volume", "quote_volume"]
