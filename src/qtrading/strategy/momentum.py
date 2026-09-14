"""Long-only dual-momentum rotation. Every hypothesis in the research plan is a MomentumParams config.

signals: per asset, the mean over lookbacks of (return over L hours, skipping the latest skip_h) / (hourly vol · √L);
         plus each asset's hourly vol and a banded market-regime gate. Causal operations only.
targets: eligibility → gate → hysteresis → weights → exposure (vol target, drawdown brake) → drift band.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..data.store import Prices
from . import State, eligible_mask

HOURS_PER_DAY = 24


@dataclass(frozen=True)
class MomentumParams:
    pairs: tuple[str, ...] | None = None        # restrict the selectable universe; None = every pair
    lookbacks_h: tuple[int, ...] = (24, 72, 168, 336)
    skip_h: int = 12                            # ignore the most recent hours (short-term reversal)
    vol_window_h: int = 168
    min_age_h: int = 720
    k: int = 6
    buffer_rank: int = 12                       # keep a holding while it ranks at or above this
    select_every_h: int = 1                     # re-rank/re-select this often; risk rules still run every decision
    weighting: str = "equal"                    # "equal" | "inverse_vol"
    gate: str = "none"                          # "none" | "own" | "market" | "both"
    gate_pair: str = "BTC/USD"
    gate_ma_h: int = 480                        # 20-day moving average
    gate_band: float = 0.02                     # hysteresis band around the MA
    vol_target_daily: float | None = None       # e.g. 0.03; None = no scaling
    avg_corr: float = 0.7                       # constant-correlation model for portfolio vol
    dd_halve: float | None = None               # drawdown from peak at which exposure halves
    dd_flat: float | None = None                # drawdown from peak at which we go to cash
    dd_cooldown_h: int = 48                     # stay flat this long, then reset the peak and resume
    drift_band: float = 0.05                    # don't touch a holding within this of its target
    max_exposure: float = 1.0


def market_gate(close: pd.Series, ma_h: int, band: float) -> pd.Series:
    """1 = risk on, 0 = risk off. Turns on above MA·(1+band), off below MA·(1−band), holds in between.
    Off while the MA is warming up."""
    ma = close.rolling(ma_h).mean()
    up = close > ma * (1 + band)
    down = close < ma * (1 - band)
    raw = pd.Series(np.where(up, 1.0, np.where(down, 0.0, np.nan)), index=close.index)
    return raw.ffill().fillna(0.0)


class Momentum:
    def __init__(self, params: MomentumParams = MomentumParams(), name: str | None = None):
        self.params = params
        self.name = name or self._default_name()

    def _default_name(self) -> str:
        p = self.params
        bits = ["mom", p.weighting[:2], f"k{p.k}", f"g:{p.gate}"]
        if p.vol_target_daily:
            bits.append(f"vt{p.vol_target_daily:g}")
        if p.dd_halve or p.dd_flat:
            bits.append(f"dd{p.dd_halve:g}/{p.dd_flat:g}")
        if p.select_every_h != 1:
            bits.append(f"s{p.select_every_h}")
        return ":".join(bits)

    # ---- signals ------------------------------------------------------------

    def signals(self, prices: Prices) -> pd.DataFrame:
        p = self.params
        all_pairs = list(prices.close.columns)
        cols = [c for c in all_pairs if p.pairs is None or c in p.pairs]
        close = prices.close[cols]

        vol = np.log(close).diff().rolling(p.vol_window_h).std()
        horizon_scores = []
        for L in p.lookbacks_h:
            ret = close.shift(p.skip_h) / close.shift(p.skip_h + L) - 1
            horizon_scores.append(ret / (vol * np.sqrt(L)))
        composite = sum(horizon_scores) / len(horizon_scores)
        composite = composite.replace([np.inf, -np.inf], np.nan)
        composite = composite.where(eligible_mask(prices, p.min_age_h)[cols])

        out = pd.concat({"score": composite.reindex(columns=all_pairs), "vol": vol.reindex(columns=all_pairs)}, axis=1)
        if p.gate_pair in prices.close.columns:
            out[("gate", "MARKET")] = market_gate(prices.close[p.gate_pair], p.gate_ma_h, p.gate_band)
        elif p.gate in ("market", "both"):
            raise ValueError(f"market gate needs {p.gate_pair!r} in the price panel")
        else:
            out[("gate", "MARKET")] = 1.0
        return out

    # ---- targets ------------------------------------------------------------

    def targets(self, t, s: pd.Series, state: State) -> dict[str, float]:
        p = self.params
        mem = state.memory

        # --- risk rules: every decision -------------------------------------
        if p.gate in ("market", "both") and s[("gate", "MARKET")] <= 0:
            return {}
        peak = max(mem.get("peak", 0.0), state.equity)
        mem["peak"] = peak
        drawdown = 1 - state.equity / peak if peak > 0 else 0.0
        flat_since = mem.get("flat_since")
        if flat_since is not None:
            if t - flat_since < pd.Timedelta(hours=p.dd_cooldown_h):
                return {}
            mem["flat_since"] = None                               # cooldown over: restart from here
            mem["peak"] = state.equity
            drawdown = 0.0
        elif p.dd_flat is not None and drawdown >= p.dd_flat:
            mem["flat_since"] = t
            return {}

        # --- selection: slow cadence ----------------------------------------
        last = mem.get("last_select")
        if last is None or t - last >= pd.Timedelta(hours=p.select_every_h):
            chosen = self._select(s, state)
            mem["selected"], mem["last_select"] = chosen, t
        else:
            chosen = [c for c in mem.get("selected", []) if not np.isnan(s["vol"].get(c, np.nan))]
        if not chosen:
            return {}

        total = len(chosen) / p.k                                  # unfilled slots stay in cash
        if p.weighting == "inverse_vol":
            inv = 1.0 / s["vol"].reindex(chosen)
            weights = inv / inv.sum() * total
        else:
            weights = pd.Series(1.0 / p.k, index=chosen)

        exposure = p.max_exposure
        if p.vol_target_daily:
            daily_vol = s["vol"].reindex(chosen) * np.sqrt(HOURS_PER_DAY)
            wv = weights * daily_vol
            port_vol = np.sqrt((1 - p.avg_corr) * (wv ** 2).sum() + p.avg_corr * wv.sum() ** 2)
            if port_vol > 0:
                exposure = min(exposure, p.vol_target_daily / port_vol)
        if p.dd_halve is not None and drawdown >= p.dd_halve:
            exposure *= 0.5
        weights = weights * exposure

        out = {}
        for pair, w in weights.items():
            current = state.weights.get(pair, 0.0)
            out[pair] = current if current > 0 and abs(w - current) < p.drift_band else float(w)
        return out

    def _select(self, s: pd.Series, state: State) -> list[str]:
        """Rank by score; keep current holdings while they stay inside the buffer; fill from the top."""
        p = self.params
        score = s["score"].dropna()
        if p.gate in ("own", "both"):
            score = score[score > 0]
        if score.empty:
            return []
        ranked = score.sort_values(ascending=False)
        rank = {pair: i + 1 for i, pair in enumerate(ranked.index)}
        chosen = [pair for pair in state.holdings if pair in rank and rank[pair] <= p.buffer_rank]
        for pair in ranked.index:
            if len(chosen) >= p.k:
                break
            if pair not in chosen:
                chosen.append(pair)
        return chosen
