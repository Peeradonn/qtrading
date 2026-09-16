"""Candidate families for a second bot.

The core and its risk-on twin share one signal, so running both is leverage rather than diversification. A second
bot earns its place only if it wins in fortnights where the core loses — which is a question about correlation,
not about returns. These families exist to be measured for that.

They reuse the core's portfolio machinery (eligibility, hysteresis, weighting, exposure, drift band) and change
only what is ranked, so any difference in results comes from the signal and nothing else.
"""
import pandas as pd

from ..data.store import Prices
from .momentum import Momentum


class LowVolatility(Momentum):
    """Hold the calmest eligible assets rather than the strongest.

    The low-volatility anomaly is long documented in equities; whether it survives in crypto is exactly what the
    study measures. Aimed at the composite score rather than at the return threshold.
    """

    def __init__(self, params=None, name: str | None = None):
        super().__init__(params or Momentum().params, name=name or "lowvol")

    def signals(self, prices: Prices) -> pd.DataFrame:
        out = super().signals(prices)
        vol, score = out["vol"], out["score"]
        # rank ascending by volatility, keeping the eligibility mask momentum already applied
        ranked = (-vol).where(score.notna())
        for pair in ranked.columns:
            out[("score", pair)] = ranked[pair]
        return out
