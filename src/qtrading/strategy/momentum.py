"""Long-only dual-momentum rotation. Every hypothesis in the research plan is a MomentumParams config.

signals: per asset, the mean over lookbacks of (return over L hours, skipping the latest skip_h) / (hourly vol * sqrt(L));
         optionally blended with the residual (BTC-beta-neutral) version, scaled by a volume-confirmation multiplier,
         and masked where perpetual funding says the trade is crowded. Plus each asset's vol and a banded market gate.
         Causal operations only.
targets: eligibility -> gate -> hysteresis -> weights -> exposure (vol target, drawdown brake) -> drift band.
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
    select_hour_utc: int | None = None          # ...or at this UTC hour each day (overrides select_every_h)
    select_hours_utc: tuple[int, ...] | None = None   # ...or at each of these UTC hours (overlapping tranches)
    weighting: str = "equal"                    # "equal" | "inverse_vol"
    gate: str = "none"                          # "none" | "own" | "market" | "both"
    gate_pair: str = "BTC/USD"                  # the market proxy: gate and residual beta are measured against it
    gate_ma_h: int = 480                        # 20-day moving average
    gate_band: float = 0.02                     # hysteresis band around the MA
    residual_weight: float = 0.0                # 0 = raw momentum; 1 = fully BTC-beta-neutral residual momentum
    beta_window_h: int = 720
    volume_confirm: bool = False                # scale score by short/long dollar-volume ratio (clipped)
    volume_short_h: int = 168
    volume_long_h: int = 720
    volume_clip: tuple[float, float] = (0.5, 1.5)
    funding_max: float | None = None            # drop assets whose mean funding over funding_window_h exceeds this
    funding_window_h: int = 72
    vol_target_daily: float | None = None       # e.g. 0.03; None = no scaling
    avg_corr: float = 0.7                       # constant-correlation model for portfolio vol
    dd_halve: float | None = None               # drawdown from peak at which exposure halves
    dd_flat: float | None = None                # drawdown from peak at which we go to cash
    dd_cooldown_h: int = 48                     # stay flat this long, then reset the peak and resume
    drift_band: float = 0.05                    # do not touch a holding within this of its target
    max_exposure: float = 1.0


def market_gate(close: pd.Series, ma_h: int, band: float) -> pd.Series:
    """1 = risk on, 0 = risk off. Turns on above MA*(1+band), off below MA*(1-band), holds in between.
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
        if p.select_hours_utc is not None:
            bits.append("h" + "+".join(str(h) for h in p.select_hours_utc))
        elif p.select_hour_utc is not None:
            bits.append(f"h{p.select_hour_utc}")
        elif p.select_every_h != 1:
            bits.append(f"s{p.select_every_h}")
        return ":".join(bits)

    # ---- signals ------------------------------------------------------------

    def signals(self, prices: Prices) -> pd.DataFrame:
        p = self.params
        all_pairs = list(prices.close.columns)
        cols = [c for c in all_pairs if p.pairs is None or c in p.pairs]
        close = prices.close[cols]

        # hourly log returns on live bars only: a carried-forward price is not a zero-return observation
        logret = np.log(close).diff().where(~prices.stale[cols])
        # min_periods: a stock has only ~35 live returns in a 168h window (7 bars x 5 days), so require W/6
        vol = logret.rolling(p.vol_window_h, min_periods=max(2, p.vol_window_h // 6)).std()

        raw = self._horizon_mean(lambda L: close.shift(p.skip_h) / close.shift(p.skip_h + L) - 1, vol)
        composite = raw
        if p.residual_weight > 0:
            if p.gate_pair not in cols:
                raise ValueError(f"residual momentum needs {p.gate_pair!r} in the universe")
            mkt = logret[p.gate_pair]
            w = max(24, p.beta_window_h // 4)
            beta = logret.rolling(p.beta_window_h, min_periods=w).cov(mkt).div(
                mkt.rolling(p.beta_window_h, min_periods=w).var(), axis=0)
            log_close = np.log(close)

            def residual_return(L):
                r = log_close.shift(p.skip_h) - log_close.shift(p.skip_h + L)
                return r.sub(beta.mul(r[p.gate_pair], axis=0))

            residual = self._horizon_mean(residual_return, vol)
            composite = (1 - p.residual_weight) * raw + p.residual_weight * residual
            composite[p.gate_pair] = raw[p.gate_pair]                      # the market itself keeps its raw score

        if p.volume_confirm and prices.volume is not None:
            dv = prices.volume[cols]
            ratio = dv.rolling(p.volume_short_h, min_periods=1).mean() / dv.rolling(p.volume_long_h, min_periods=1).mean()
            composite = composite * ratio.clip(*p.volume_clip).fillna(1.0)

        if p.funding_max is not None and "funding" in prices.extra:
            funding = prices.extra["funding"].reindex(index=close.index, columns=cols)
            crowded = funding.rolling(p.funding_window_h, min_periods=1).mean() > p.funding_max
            composite = composite.mask(crowded)

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

    def _horizon_mean(self, return_over, vol: pd.DataFrame) -> pd.DataFrame:
        scores = [return_over(L) / (vol * np.sqrt(L)) for L in self.params.lookbacks_h]
        return sum(scores) / len(scores)

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
        hours = p.select_hours_utc if p.select_hours_utc is not None else (
            (p.select_hour_utc,) if p.select_hour_utc is not None else None)
        if hours is not None:
            due = last is None or (t.hour in hours and t - last >= pd.Timedelta(hours=1))
        else:
            due = last is None or t - last >= pd.Timedelta(hours=p.select_every_h)
        if due:
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
