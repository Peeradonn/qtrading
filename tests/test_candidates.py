"""Candidate families for a second bot. A second bot only helps if it wins when the core loses, so these exist
to be measured for correlation against the core, not to beat it."""
import math

import pandas as pd
import pytest

from qtrading.data.store import Prices
from qtrading.strategy import State
from qtrading.strategy.candidates import LowVolatility
from qtrading.strategy.momentum import MomentumParams


def ts(h):
    return pd.Timestamp("2026-09-01", tz="UTC") + pd.Timedelta(hours=h)


def panel(closes):
    n = len(next(iter(closes.values())))
    idx = pd.DatetimeIndex([ts(h) for h in range(n)], name="time")
    close = pd.DataFrame(closes, index=idx, dtype=float)
    return Prices(close=close, stale=pd.DataFrame(False, index=idx, columns=close.columns))


def state():
    return State(holdings={}, weights={}, cash=1.0, equity=1.0, peak_equity=1.0, memory={})


def wobbly(amplitude, n=400, start=100.0):
    """A price path that alternates up and down by `amplitude` each hour: volatility without drift."""
    return [start * math.exp(amplitude * (-1) ** i) for i in range(n)]


def test_low_volatility_ranks_the_calmest_asset_first():
    prices = panel({"CALM/USD": wobbly(0.002), "WILD/USD": wobbly(0.05), "MID/USD": wobbly(0.01)})
    params = MomentumParams(k=1, buffer_rank=1, min_age_h=0, vol_window_h=168, select_every_h=24)
    sig = LowVolatility(params).signals(prices)
    row = sig.iloc[-1]
    assert row[("score", "CALM/USD")] > row[("score", "MID/USD")] > row[("score", "WILD/USD")]
    assert set(LowVolatility(params).targets(ts(399), row, state())) == {"CALM/USD"}


def test_low_volatility_still_honours_eligibility():
    nan = float("nan")
    prices = panel({"CALM/USD": wobbly(0.002), "NEW/USD": [nan] * 380 + wobbly(0.001, n=20)})
    params = MomentumParams(k=2, buffer_rank=4, min_age_h=720, vol_window_h=168, select_every_h=24)
    row = LowVolatility(params).signals(prices).iloc[-1]
    assert pd.isna(row[("score", "NEW/USD")])            # too new, despite being the calmest
    assert not pd.isna(row[("score", "CALM/USD")])


def test_the_momentum_ranking_is_the_opposite_ordering_on_the_same_panel():
    """Sanity: the two families genuinely disagree, which is the point of testing one as a second bot."""
    from qtrading.strategy.momentum import Momentum
    rising_wild = [100 * math.exp(0.004 * i + 0.05 * (-1) ** i) for i in range(400)]
    prices = panel({"CALM/USD": wobbly(0.002), "WILD/USD": rising_wild})
    params = MomentumParams(k=1, buffer_rank=1, min_age_h=0, vol_window_h=168, select_every_h=24,
                            lookbacks_h=(72,), skip_h=0)
    assert set(Momentum(params).targets(ts(399), Momentum(params).signals(prices).iloc[-1], state())) == {"WILD/USD"}
    assert set(LowVolatility(params).targets(ts(399), LowVolatility(params).signals(prices).iloc[-1], state())) \
        == {"CALM/USD"}
