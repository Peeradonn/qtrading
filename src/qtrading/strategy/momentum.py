"""Long-only dual-momentum rotation. Every hypothesis in the research plan is a MomentumParams config.

signals: per asset, the mean over lookbacks of (return over L hours, skipping the latest skip_h) / (hourly vol * sqrt(L));
         optionally blended with the residual (BTC-beta-neutral) version, scaled by a volume-confirmation multiplier,
         and masked where perpetual funding says the trade is crowded. Plus each asset's vol and a banded market gate.
         Causal operations only.
targets: eligibility -> gate -> hysteresis -> weights -> exposure (vol target, drawdown brake) -> sleeve -> hedge
         -> drift band.
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
    vol_window_h: int = 168                     # trailing window, and the warm-up floor for either model
    vol_model: str = "trailing"                 # "trailing" | "ewma"
    ewma_lambda: float = 0.99                   # RiskMetrics decay on hourly squared returns (~3-day half-life)
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
    vol_target_on: str = "total"                # "total" | "downside": size the book on downside deviation only
    min_exposure: float = 0.0                   # floor on the exposure scalar once anything is selected
    avg_corr: float = 0.7                       # constant-correlation model for portfolio vol
    dd_halve: float | None = None               # drawdown from peak at which exposure halves
    dd_flat: float | None = None                # drawdown from peak at which we go to cash
    dd_cooldown_h: int = 48                     # stay flat this long, then reset the peak and resume
    drift_band: float = 0.05                    # do not touch a holding within this of its target
    max_exposure: float = 1.0
    sleeve: tuple[str, ...] = ()                # pairs held by rule rather than by rank (e.g. gold); never selected
    sleeve_mode: str = "cash"                   # "cash": the sleeve takes the idle cash the vol target leaves;
                                                #   "book": one more inverse-vol position, uncorrelated with the book
    sleeve_fraction: float = 1.0                # cash mode: share of the idle cash placed in the sleeve
    hedge_pair: str | None = None               # short this pair against the long book (needs a venue that shorts)
    hedge_ratio: float = 0.0                    # short notional as a fraction of the long notional
    max_gross: float = 1.0                      # longs + |shorts| as a fraction of equity (the rules' 1x)
    short_k: int = 0                            # short this many names from the bottom of the ranking (0 = long-only)
    short_share: float = 0.5                    # share of gross exposure in the short leg when it is full
    short_buffer_rank: int = 12                 # keep a short while it ranks within this many from the bottom
    short_negative_only: bool = False           # short only names whose score is negative
    gross_guard: float = 1.0                    # a book with shorts whose realised gross drifts past this is
                                                #   rebalanced to target at once, drift band or not


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
        if p.vol_model != "trailing":
            bits.append(f"{p.vol_model}{p.ewma_lambda:g}")
        if p.vol_target_daily:
            bits.append(f"vt{p.vol_target_daily:g}" + ("d" if p.vol_target_on == "downside" else ""))
        if p.min_exposure:
            bits.append(f"floor{p.min_exposure:g}")
        if p.dd_halve or p.dd_flat:
            bits.append(f"dd{p.dd_halve:g}/{p.dd_flat:g}")
        if p.select_hours_utc is not None:
            bits.append("h" + "+".join(str(h) for h in p.select_hours_utc))
        elif p.select_hour_utc is not None:
            bits.append(f"h{p.select_hour_utc}")
        elif p.select_every_h != 1:
            bits.append(f"s{p.select_every_h}")
        if p.sleeve:
            bits.append("sl:" + "+".join(q.split("/")[0] for q in p.sleeve) + f":{p.sleeve_mode}{p.sleeve_fraction:g}")
        if p.hedge_pair and p.hedge_ratio:
            bits.append(f"hg:{p.hedge_pair.split('/')[0]}{p.hedge_ratio:g}")
        if p.short_k:
            bits.append(f"ls{p.short_share:g}" + ("n" if p.short_negative_only else ""))
        return ":".join(bits)

    # ---- signals ------------------------------------------------------------

    def signals(self, prices: Prices) -> pd.DataFrame:
        p = self.params
        all_pairs = list(prices.close.columns)
        cols = [c for c in all_pairs if p.pairs is None or c in p.pairs]
        close = prices.close[cols]
        missing = [q for q in p.sleeve if q not in cols]
        if missing:
            raise ValueError(f"sleeve pairs must be in the selectable universe: {missing}")

        # hourly log returns on live bars only: a carried-forward price is not a zero-return observation
        # ...and a research panel that treats an asset as tradable on carried-forward prices (Roostoo's stock
        # tokens price around the clock; our underlying history does not) passes the true live-bar mask in extra
        live = prices.extra.get("live_bars") if prices.extra else None
        if live is not None:
            live_mask = live.reindex(index=close.index, columns=cols).fillna(False).astype(bool)
        else:
            live_mask = ~prices.stale[cols]
        logret = np.log(close).diff().where(live_mask)
        # min_periods: a stock has only ~35 live returns in a 168h window (7 bars x 5 days), so require W/6
        warmup = max(2, p.vol_window_h // 6)
        if p.vol_model == "ewma":
            # exponentially weighted variance of squared returns (RiskMetrics). Chosen over the trailing window on
            # forecast error alone -- see the volatility experiment in the design doc.
            vol = np.sqrt((logret ** 2).ewm(alpha=1 - p.ewma_lambda, min_periods=warmup).mean())
        else:
            vol = logret.rolling(p.vol_window_h, min_periods=warmup).std()

        # downside deviation on the same clock, scaled by sqrt(2) so symmetric returns give the total vol back
        neg = logret.clip(upper=0.0)
        if p.vol_model == "ewma":
            dvol = np.sqrt(2.0 * (neg ** 2).ewm(alpha=1 - p.ewma_lambda, min_periods=warmup).mean())
        else:
            dvol = np.sqrt(2.0 * (neg ** 2).rolling(p.vol_window_h, min_periods=warmup).mean())

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
        if p.sleeve:
            composite[list(p.sleeve)] = np.nan                                 # held by rule, never by rank

        out = pd.concat({"score": composite.reindex(columns=all_pairs), "vol": vol.reindex(columns=all_pairs),
                         "dvol": dvol.reindex(columns=all_pairs)}, axis=1)
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
            mem["selected_short"] = self._select_shorts(s, state, chosen) if p.short_k else []
        else:
            chosen = [c for c in mem.get("selected", []) if not np.isnan(s["vol"].get(c, np.nan))]
        shorts = [c for c in mem.get("selected_short", []) if not np.isnan(s["vol"].get(c, np.nan))] if p.short_k else []
        # --- weights and exposure -------------------------------------------
        sleeve = [q for q in p.sleeve if not np.isnan(s["vol"].get(q, np.nan))]   # needs a live vol to be held
        in_book = sleeve if p.sleeve_mode == "book" else []
        book = chosen + in_book
        weights = pd.Series(dtype=float)
        if book:
            slots = p.k + len(in_book)
            total = len(book) / slots                              # unfilled slots stay in cash
            if p.weighting == "inverse_vol":
                inv = 1.0 / s["vol"].reindex(book)
                weights = inv / inv.sum() * total
            else:
                weights = pd.Series(1.0 / slots, index=book)

            if shorts:                                             # the short leg: the bottom of the same ranking
                fill = len(shorts) / p.short_k                     # unfilled short slots leave that gross to the longs
                if p.weighting == "inverse_vol":
                    inv_s = 1.0 / s["vol"].reindex(shorts)
                    short_w = inv_s / inv_s.sum()
                else:
                    short_w = pd.Series(1.0 / len(shorts), index=shorts)
                weights = pd.concat([weights * (1 - p.short_share * fill), -short_w * p.short_share * fill])

            exposure = p.max_exposure
            if p.vol_target_daily:
                sizing_vol = s["dvol"] if p.vol_target_on == "downside" and "dvol" in s else s["vol"]
                wv = weights * sizing_vol.reindex(book).fillna(s["vol"].reindex(book)) * np.sqrt(HOURS_PER_DAY)
                core_wv = wv.reindex(chosen + shorts)              # constant correlation inside the crypto book; signed
                                                                   # weights, so a short nets against the longs...
                var = (1 - p.avg_corr) * (core_wv ** 2).sum() + p.avg_corr * core_wv.sum() ** 2
                var += (wv.reindex(in_book) ** 2).sum()            # ...and the sleeve uncorrelated with it
                port_vol = np.sqrt(var)
                if port_vol > 0:
                    exposure = min(exposure, p.vol_target_daily / port_vol)
            if p.dd_halve is not None and drawdown >= p.dd_halve:
                exposure *= 0.5
            exposure = max(exposure, min(p.min_exposure, p.max_exposure))
            weights = weights * exposure

        if sleeve and p.sleeve_mode == "cash":                     # idle cash is held in the sleeve, not in USD
            idle = max(0.0, 1.0 - float(weights.sum())) * p.sleeve_fraction
            extra = pd.Series(idle / len(sleeve), index=sleeve)
            weights = extra if weights.empty else pd.concat([weights, extra])
        if weights.empty:
            return {}

        if p.hedge_pair and p.hedge_ratio > 0 and not np.isnan(s["vol"].get(p.hedge_pair, np.nan)):
            short = p.hedge_ratio * weights[weights > 0].sum()          # sized off the long notional
            weights[p.hedge_pair] = weights.get(p.hedge_pair, 0.0) - short   # nets against a long in the same pair
            gross = weights.abs().sum()
            if gross > p.max_gross:                                    # the 1x rule: scale the whole book
                weights = weights * (p.max_gross / gross)

        # the engine sets force_rebalance for one cycle when the active-days pace is at risk
        band = 0.0 if mem.pop("force_rebalance", False) else p.drift_band
        if (p.short_k or p.hedge_ratio) and sum(abs(w) for w in state.weights.values()) > p.gross_guard:
            band = 0.0                              # realised gross has drifted past the cap: back to target now
        out = {}
        for pair, w in weights.items():
            current = state.weights.get(pair, 0.0)
            out[pair] = current if current != 0 and abs(w - current) < band else float(w)
        return out

    def _select(self, s: pd.Series, state: State) -> list[str]:
        """Rank by score; keep current holdings while they stay inside the buffer; fill from the top."""
        p = self.params
        score = s["score"].drop(labels=[q for q in p.sleeve if q in s["score"].index]).dropna()
        if p.gate in ("own", "both"):
            score = score[score > 0]
        if score.empty:
            return []
        ranked = score.sort_values(ascending=False)
        rank = {pair: i + 1 for i, pair in enumerate(ranked.index)}
        chosen = [pair for pair, q in state.holdings.items() if q > 0 and pair in rank and rank[pair] <= p.buffer_rank]
        for pair in ranked.index:
            if len(chosen) >= p.k:
                break
            if pair not in chosen:
                chosen.append(pair)
        return chosen

    def _select_shorts(self, s: pd.Series, state: State, longs: list[str]) -> list[str]:
        """The mirror image: rank from the bottom; keep a current short while it stays inside the bottom buffer."""
        p = self.params
        score = s["score"].drop(labels=[q for q in list(p.sleeve) + longs if q in s["score"].index]).dropna()
        if p.short_negative_only:
            score = score[score < 0]
        if score.empty:
            return []
        ranked = score.sort_values(ascending=True)
        rank = {pair: i + 1 for i, pair in enumerate(ranked.index)}
        chosen = [pair for pair, q in state.holdings.items() if q < 0 and pair in rank and rank[pair] <= p.short_buffer_rank]
        for pair in ranked.index:
            if len(chosen) >= p.short_k:
                break
            if pair not in chosen:
                chosen.append(pair)
        return chosen[:p.short_k]
