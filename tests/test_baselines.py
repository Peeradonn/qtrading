"""Baseline strategies and the shared eligibility rule."""
import numpy as np
import pandas as pd

from qtrading.data.store import Prices
from qtrading.strategy import State, eligible_mask
from qtrading.strategy.baselines import BuyAndHold, EqualWeight


def ts(h):
    return pd.Timestamp("2026-09-01", tz="UTC") + pd.Timedelta(hours=h)


def panel(closes, stale=None):
    n = len(next(iter(closes.values())))
    idx = pd.DatetimeIndex([ts(h) for h in range(n)], name="time")
    close = pd.DataFrame(closes, index=idx, dtype=float)
    st = pd.DataFrame(stale or {p: [False] * n for p in closes}, index=idx, dtype=bool)
    return Prices(close=close, stale=st)


def state():
    return State(holdings={}, weights={}, cash=1.0, equity=1.0, peak_equity=1.0)


def test_eligible_requires_min_age_since_first_bar_and_a_live_price():
    nan = np.nan
    prices = panel({"A/USD": [1, 1, 1, 1, 1, 1], "B/USD": [nan, nan, 1, 1, 1, 1]},
                   stale={"A/USD": [False] * 6, "B/USD": [True, True, False, False, True, False]})
    e = eligible_mask(prices, min_age_h=2)
    assert list(e["A/USD"]) == [True, True, True, True, True, True]
    assert list(e["B/USD"]) == [False, False, False, False, False, True]   # listed at h2 -> aged at h4, but h4 is stale


def test_equal_weight_splits_across_eligible_assets_only():
    nan = np.nan
    prices = panel({"A/USD": [1, 1, 1], "B/USD": [1, 1, 1], "C/USD": [nan, nan, nan]})
    strat = EqualWeight(min_age_h=0)
    sig = strat.signals(prices)
    assert strat.targets(ts(2), sig.iloc[2], state()) == {"A/USD": 0.5, "B/USD": 0.5}


def test_buy_and_hold_targets_one_asset_fully():
    prices = panel({"BTC/USD": [1, 1], "ETH/USD": [1, 1]})
    strat = BuyAndHold("BTC/USD")
    sig = strat.signals(prices)
    assert strat.targets(ts(1), sig.iloc[1], state()) == {"BTC/USD": 1.0}
