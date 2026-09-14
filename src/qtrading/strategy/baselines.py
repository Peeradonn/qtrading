"""Reference strategies: what a naive competitor's book looks like."""
import pandas as pd

from ..data.store import Prices
from . import State, eligible_mask


class BuyAndHold:
    def __init__(self, pair: str):
        self.pair = pair
        self.name = f"hold:{pair}"

    def signals(self, prices: Prices) -> pd.DataFrame:
        return pd.DataFrame(0.0, index=prices.close.index, columns=prices.close.columns)

    def targets(self, t, signals_at_t, state: State) -> dict[str, float]:
        return {self.pair: 1.0}


class EqualWeight:
    """1/N across every eligible asset (optionally restricted to a list of pairs)."""

    def __init__(self, min_age_h: int = 720, pairs: list[str] | None = None, name: str = "eqw"):
        self.min_age_h = min_age_h
        self.pairs = None if pairs is None else set(pairs)
        self.name = name

    def signals(self, prices: Prices) -> pd.DataFrame:
        return eligible_mask(prices, self.min_age_h).astype(float)

    def targets(self, t, signals_at_t, state: State) -> dict[str, float]:
        chosen = [p for p, v in signals_at_t.items() if v > 0 and (self.pairs is None or p in self.pairs)]
        if not chosen:
            return {}
        return {p: 1.0 / len(chosen) for p in chosen}
