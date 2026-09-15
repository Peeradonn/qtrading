"""Guards that every strategy must pass before its backtest numbers are believed."""
import numpy as np

from ..data.store import Prices
from ..strategy import Strategy


def assert_no_lookahead(strategy: Strategy, prices: Prices, at: int, seed: int = 0, scale: float = 0.2) -> None:
    """Perturb every price after row ``at``; signals up to and including ``at`` must be unchanged."""
    base = strategy.signals(prices)
    rng = np.random.default_rng(seed)
    close = prices.close.copy()
    future = close.iloc[at + 1:]
    close.iloc[at + 1:] = future.to_numpy() * np.exp(rng.normal(0.0, scale, size=future.shape))
    perturbed = strategy.signals(Prices(close=close, stale=prices.stale, volume=prices.volume, extra=prices.extra))
    a = base.iloc[:at + 1].to_numpy(dtype=float)
    b = perturbed.iloc[:at + 1].to_numpy(dtype=float)
    if not np.allclose(a, b, equal_nan=True):
        raise AssertionError(f"look-ahead detected in strategy {strategy.name!r}: "
                             f"signals up to row {at} changed when prices after it were perturbed")
