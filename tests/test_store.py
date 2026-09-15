"""PriceStore: disk cache with incremental updates; hourly UTC grid; stale mask; no look-ahead."""
import pandas as pd

from qtrading.data.store import PriceStore
from qtrading.data.universe import Asset

BTC = Asset("BTC/USD", "BTC", "crypto", "binance", "BTCUSDT")
NVDA = Asset("NVDAB/USD", "NVDAB", "stock", "yahoo", "NVDA")


def ts(hours: float) -> pd.Timestamp:
    return pd.Timestamp("2026-09-01", tz="UTC") + pd.Timedelta(hours=hours)


def bars(points):
    """points: list of (hours offset of bar CLOSE time, close price)."""
    idx = pd.DatetimeIndex([ts(h) for h, _ in points], name="close_time")
    closes = [float(c) for _, c in points]
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1.0}, index=idx)


class FakeSource:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def bars(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        df = self.data[symbol]
        return df[(df.index >= start) & (df.index <= end)]


def make_store(tmp_path, binance=None, yahoo=None):
    return PriceStore(cache_dir=tmp_path, sources={"binance": binance, "yahoo": yahoo})


def test_cached_bars_are_reused_by_a_new_store_instance_without_refetching(tmp_path):
    data = {"BTCUSDT": bars([(h, 100 + h) for h in range(1, 6)])}
    first = FakeSource(data)
    make_store(tmp_path, binance=first).closes([BTC], ts(1), ts(5))
    second = FakeSource(data)
    prices = make_store(tmp_path, binance=second).closes([BTC], ts(1), ts(5))
    assert second.calls == []
    assert list(prices.close["BTC/USD"]) == [101, 102, 103, 104, 105]


def test_extending_the_range_fetches_only_the_missing_tail(tmp_path):
    src = FakeSource({"BTCUSDT": bars([(h, 100 + h) for h in range(1, 9)])})
    store = make_store(tmp_path, binance=src)
    store.closes([BTC], ts(1), ts(5))
    prices = store.closes([BTC], ts(1), ts(8))
    assert len(src.calls) == 2
    assert src.calls[1][1] == ts(6)                                  # resume one bar after the cached end
    assert list(prices.close["BTC/USD"]) == [101, 102, 103, 104, 105, 106, 107, 108]


def test_gaps_are_forward_filled_and_flagged_stale(tmp_path):
    src = FakeSource({"NVDA": bars([(1, 10), (2, 11), (3, 12), (6, 15), (7, 16)])})
    prices = make_store(tmp_path, yahoo=src).closes([NVDA], ts(1), ts(7))
    assert list(prices.close["NVDAB/USD"]) == [10, 11, 12, 12, 12, 15, 16]
    assert list(prices.stale["NVDAB/USD"]) == [False, False, False, True, True, False, False]


def test_off_grid_bar_lands_on_the_next_grid_hour_never_the_previous(tmp_path):
    # A stock bar closing at 01:30 is unknown at 01:00; it becomes usable at 02:00.
    src = FakeSource({"NVDA": bars([(1.5, 5.0)])})
    prices = make_store(tmp_path, yahoo=src).closes([NVDA], ts(1), ts(2))
    assert prices.close["NVDAB/USD"].isna().tolist() == [True, False]
    assert prices.close["NVDAB/USD"].iloc[1] == 5.0


def test_assets_share_one_hourly_index_with_nan_before_first_bar(tmp_path):
    b = FakeSource({"BTCUSDT": bars([(h, 100 + h) for h in range(1, 5)])})
    y = FakeSource({"NVDA": bars([(3, 10), (4, 11)])})
    prices = make_store(tmp_path, binance=b, yahoo=y).closes([BTC, NVDA], ts(1), ts(4))
    assert list(prices.close.index) == [ts(1), ts(2), ts(3), ts(4)]
    assert list(prices.close.columns) == ["BTC/USD", "NVDAB/USD"]
    assert prices.close["NVDAB/USD"].isna().tolist() == [True, True, False, False]
    assert prices.stale["NVDAB/USD"].tolist() == [True, True, False, False]


def test_volume_panel_carries_dollar_volume_per_grid_hour_and_zero_where_no_bar(tmp_path):
    idx = pd.DatetimeIndex([ts(1), ts(2), ts(4)], name="close_time")
    frame = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": [10.0, 10.0, 10.0], "volume": [5.0, 7.0, 9.0],
                          "quote_volume": [100.0, 200.0, 400.0]}, index=idx)
    src = FakeSource({"BTCUSDT": frame})
    prices = make_store(tmp_path, binance=src).closes([BTC], ts(1), ts(4))
    assert list(prices.volume["BTC/USD"]) == [100.0, 200.0, 0.0, 400.0]


def test_volume_panel_uses_shares_times_close_when_no_quote_volume(tmp_path):
    idx = pd.DatetimeIndex([ts(1), ts(2)], name="close_time")
    frame = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": [10.0, 20.0], "volume": [5.0, 7.0]}, index=idx)
    src = FakeSource({"NVDA": frame})
    prices = make_store(tmp_path, yahoo=src).closes([NVDA], ts(1), ts(2))
    assert list(prices.volume["NVDAB/USD"]) == [50.0, 140.0]


def test_funding_is_carried_forward_from_each_settlement_until_the_next(tmp_path):
    class FakeFunding:
        def funding_rates(self, symbol, start, end):
            return pd.Series([0.0001, -0.0002], index=pd.DatetimeIndex([ts(0), ts(8)]), name="funding_rate")

    store = make_store(tmp_path, binance=FakeFunding())
    f = store.funding([BTC], ts(0), ts(9))
    assert list(f["BTC/USD"]) == [0.0001] * 8 + [-0.0002] * 2
