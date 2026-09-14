"""Strategy contract. A strategy is two pure functions — no I/O, no clocks, no side effects — so the
backtester and the live engine run the identical code.

  signals(prices)                 -> DataFrame (hourly grid × pair) computed with causal operations only
  targets(t, signals_at_t, state) -> {pair: weight}  the decision at one time step; weights sum to <= 1
"""
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from ..data.store import Prices


@dataclass
class State:
    holdings: dict[str, float]    # pair -> quantity currently held (non-zero only)
    weights: dict[str, float]     # pair -> fraction of equity currently held
    cash: float
    equity: float
    peak_equity: float            # highest equity seen at a decision time (engine-observed)
    memory: dict = field(default_factory=dict)   # strategy-owned scratch, carried unchanged between decisions


class Strategy(Protocol):
    name: str

    def signals(self, prices: Prices) -> pd.DataFrame: ...

    def targets(self, t: pd.Timestamp, signals_at_t: pd.Series, state: State) -> dict[str, float]: ...


def eligible_mask(prices: Prices, min_age_h: int) -> pd.DataFrame:
    """True where an asset can be selected: it has a live (non-stale) price now, and either it already had a
    price at the panel's first bar or it listed at least ``min_age_h`` hours ago."""
    has_price = prices.close.notna().to_numpy()
    any_valid = has_price.any(axis=0)
    first = has_price.argmax(axis=0)                                   # row of the first valid price
    rows = np.arange(len(prices.close))[:, None]
    aged = (rows - first[None, :] >= min_age_h) | (first[None, :] == 0)
    ok = has_price & ~prices.stale.to_numpy() & aged & any_valid[None, :]
    return pd.DataFrame(ok, index=prices.close.index, columns=prices.close.columns)
