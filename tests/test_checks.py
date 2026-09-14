"""The look-ahead checker must pass a causal strategy and catch a leaky one."""
import numpy as np
import pandas as pd
import pytest

from qtrading.backtest.checks import assert_no_lookahead
from qtrading.data.store import Prices


def random_panel(n_hours=200, n_assets=3, seed=0) -> Prices:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n_hours, freq="1h", tz="UTC", name="time")
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n_hours, n_assets)), axis=0)),
                         index=idx, columns=[f"A{i}/USD" for i in range(n_assets)])
    return Prices(close=close, stale=pd.DataFrame(False, index=idx, columns=close.columns))


class CausalMomentum:
    name = "causal"

    def signals(self, prices):
        return prices.close.pct_change(24)

    def targets(self, t, s, state):
        return {}


class LeakyMomentum:
    name = "leaky"

    def signals(self, prices):
        return prices.close.pct_change(24).shift(-1)         # uses the next bar

    def targets(self, t, s, state):
        return {}


def test_causal_strategy_passes():
    assert_no_lookahead(CausalMomentum(), random_panel(), at=100)


def test_leaky_strategy_is_caught():
    with pytest.raises(AssertionError, match="look-ahead"):
        assert_no_lookahead(LeakyMomentum(), random_panel(), at=100)
