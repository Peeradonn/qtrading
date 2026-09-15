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


class CausalVolumeUser:
    """Causal, but reads prices.volume and prices.extra — the checker must carry both into the perturbed pass."""
    name = "causal-volume"

    def signals(self, prices):
        s = prices.close.pct_change(24) * prices.volume.rolling(24).mean()
        return s + prices.extra["funding"].rolling(8).mean()

    def targets(self, t, s, state):
        return {}


def test_checker_keeps_volume_and_extra_panels_in_the_perturbed_pass():
    prices = random_panel()
    rng = np.random.default_rng(1)
    prices.volume = pd.DataFrame(rng.uniform(1, 2, prices.close.shape), index=prices.close.index, columns=prices.close.columns)
    prices.extra["funding"] = pd.DataFrame(rng.normal(0, 1e-4, prices.close.shape), index=prices.close.index,
                                           columns=prices.close.columns)
    assert_no_lookahead(CausalVolumeUser(), prices, at=100)
