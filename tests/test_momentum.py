"""Momentum family: signal arithmetic, the banded market gate, and each targets() rule in isolation."""
import math

import numpy as np
import pandas as pd
import pytest

from qtrading.data.store import Prices
from qtrading.strategy import State
from qtrading.strategy.momentum import Momentum, MomentumParams, market_gate


def ts(h):
    return pd.Timestamp("2026-09-01", tz="UTC") + pd.Timedelta(hours=h)


def panel(closes):
    n = len(next(iter(closes.values())))
    idx = pd.DatetimeIndex([ts(h) for h in range(n)], name="time")
    close = pd.DataFrame(closes, index=idx, dtype=float)
    return Prices(close=close, stale=pd.DataFrame(False, index=idx, columns=close.columns))


def sig_row(scores: dict, vols: dict | None = None, gate: float = 1.0) -> pd.Series:
    """A signals row as targets() receives it: MultiIndex (field, pair)."""
    vols = vols or {p: 0.01 for p in scores}
    data = {("score", p): v for p, v in scores.items()}
    data.update({("vol", p): v for p, v in vols.items()})
    data[("gate", "MARKET")] = gate
    return pd.Series(data)


def state(holdings=None, weights=None, equity=1.0, peak=1.0, memory=None):
    return State(holdings=holdings or {}, weights=weights or {}, cash=0.0, equity=equity, peak_equity=peak,
                 memory=memory if memory is not None else {})


# --- signals -----------------------------------------------------------------

# close = [100, 102, 101, 104, 103]; hourly log returns = [.019803, -.009852, .029265, -.009662]
# at t=4 with vol_window=3: sample std of the last three = 0.022530
# lookback 1: r = 103/104-1 = -0.009615 -> score = -0.009615 / 0.022530          = -0.42677
# lookback 2: r = 103/101-1 = +0.019802 -> score =  0.019802 / (0.022530*sqrt(2)) =  0.62151
# composite = mean = 0.09737
def test_composite_is_the_mean_of_vol_adjusted_horizon_returns():
    prices = panel({"A/USD": [100, 102, 101, 104, 103]})
    strat = Momentum(MomentumParams(lookbacks_h=(1, 2), skip_h=0, vol_window_h=3, min_age_h=0, gate_ma_h=2))
    score = strat.signals(prices)[("score", "A/USD")]
    assert score.iloc[4] == pytest.approx(0.09737, rel=1e-3)
    assert math.isnan(score.iloc[1])                       # 2-hour lookback not yet available


# skip 1 hour, lookback 2 at t=4: r = close[3]/close[1]-1 = 104/102-1 = 0.019608 -> 0.019608/(0.022530*sqrt(2)) = 0.61539
def test_skip_recent_hours_excludes_the_latest_bars_from_the_return():
    prices = panel({"A/USD": [100, 102, 101, 104, 103]})
    strat = Momentum(MomentumParams(lookbacks_h=(2,), skip_h=1, vol_window_h=3, min_age_h=0, gate_ma_h=2))
    assert strat.signals(prices)[("score", "A/USD")].iloc[4] == pytest.approx(0.61539, rel=1e-3)


def test_signals_carry_vol_and_market_gate_fields():
    prices = panel({"BTC/USD": [100, 102, 101, 104, 103], "A/USD": [50, 51, 52, 53, 54]})
    sig = Momentum(MomentumParams(lookbacks_h=(1,), skip_h=0, vol_window_h=3, min_age_h=0, gate_ma_h=2)).signals(prices)
    assert ("vol", "A/USD") in sig.columns
    assert ("gate", "MARKET") in sig.columns


def test_market_gate_without_its_pair_in_the_panel_is_an_error():
    prices = panel({"A/USD": [50, 51, 52, 53, 54]})
    with pytest.raises(ValueError, match="BTC/USD"):
        Momentum(MomentumParams(gate="market", min_age_h=0)).signals(prices)


# MA(2) with a 10% band: px 100,100,100,125,112,105,80,95 -> MA nan,100,100,112.5,118.5,108.5,92.5,87.5
# t3: 125 > 123.75 -> on; t4,t5 inside band -> stay on; t6: 80 < 83.25 -> off; t7 inside band -> stay off
def test_market_gate_switches_only_outside_the_band_and_is_off_during_warmup():
    px = pd.Series([100, 100, 100, 125, 112, 105, 80, 95], dtype=float)
    assert list(market_gate(px, ma_h=2, band=0.10)) == [0, 0, 0, 1, 1, 1, 0, 0]


# --- targets -----------------------------------------------------------------

def test_top_k_equal_weight_leaves_unfilled_slots_in_cash():
    strat = Momentum(MomentumParams(k=3, buffer_rank=6, weighting="equal"))
    t = strat.targets(ts(0), sig_row({"A": 3.0, "B": 2.0, "C": 1.0, "D": 0.5}), state())
    assert t == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3), "C": pytest.approx(1 / 3)}


def test_hysteresis_keeps_a_holding_inside_the_buffer_and_drops_one_outside():
    scores = {f"A{i:02d}": 16 - i for i in range(1, 16)}            # A01 best ... A15 worst
    strat = Momentum(MomentumParams(k=6, buffer_rank=12))
    t = strat.targets(ts(0), sig_row(scores), state(holdings={"A09": 1.0, "A13": 1.0}))
    assert set(t) == {"A09", "A01", "A02", "A03", "A04", "A05"}


def test_own_gate_excludes_negative_scores_even_inside_top_k():
    strat = Momentum(MomentumParams(k=3, gate="own"))
    t = strat.targets(ts(0), sig_row({"A": 2.0, "B": 1.0, "C": -0.5, "D": -1.0}), state())
    assert t == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3)}


def test_market_gate_off_means_all_cash():
    strat = Momentum(MomentumParams(k=2, gate="market"))
    assert strat.targets(ts(0), sig_row({"A": 2.0, "B": 1.0}, gate=0.0), state()) == {}
    assert strat.targets(ts(0), sig_row({"A": 2.0, "B": 1.0}, gate=1.0), state()) != {}


def test_inverse_vol_weights_are_proportional_to_one_over_vol():
    strat = Momentum(MomentumParams(k=3, weighting="inverse_vol"))
    t = strat.targets(ts(0), sig_row({"A": 3.0, "B": 2.0, "C": 1.0}, vols={"A": 1.0, "B": 2.0, "C": 4.0}), state())
    assert t == {"A": pytest.approx(4 / 7), "B": pytest.approx(2 / 7), "C": pytest.approx(1 / 7)}


# two assets, equal weight, daily vol 4% each (hourly = 0.04/sqrt(24)), correlation 1 -> portfolio vol 4%;
# target 2% -> exposure 0.5 -> 0.25 each
def test_vol_target_scales_exposure_down():
    hv = 0.04 / math.sqrt(24)
    strat = Momentum(MomentumParams(k=2, vol_target_daily=0.02, avg_corr=1.0))
    t = strat.targets(ts(0), sig_row({"A": 2.0, "B": 1.0}, vols={"A": hv, "B": hv}), state())
    assert t == {"A": pytest.approx(0.25), "B": pytest.approx(0.25)}


def test_drawdown_brake_halves_then_flattens():
    strat = Momentum(MomentumParams(k=2, dd_halve=0.05, dd_flat=0.08))
    row = sig_row({"A": 2.0, "B": 1.0})
    mem = {}
    assert strat.targets(ts(0), row, state(equity=1.00, memory=mem)) == {"A": pytest.approx(0.5), "B": pytest.approx(0.5)}
    assert strat.targets(ts(1), row, state(equity=0.97, memory=mem)) == {"A": pytest.approx(0.5), "B": pytest.approx(0.5)}
    assert strat.targets(ts(2), row, state(equity=0.94, memory=mem)) == {"A": pytest.approx(0.25), "B": pytest.approx(0.25)}
    assert strat.targets(ts(3), row, state(equity=0.91, memory=mem)) == {}


def test_drawdown_brake_resumes_after_cooldown_with_the_peak_reset():
    strat = Momentum(MomentumParams(k=2, dd_halve=0.05, dd_flat=0.08, dd_cooldown_h=48))
    row = sig_row({"A": 2.0, "B": 1.0})
    mem = {}
    strat.targets(ts(0), row, state(equity=1.00, memory=mem))
    assert strat.targets(ts(1), row, state(equity=0.91, memory=mem)) == {}          # flat
    assert strat.targets(ts(25), row, state(equity=0.91, memory=mem)) == {}         # still cooling off
    assert strat.targets(ts(49), row, state(equity=0.91, memory=mem)) == {"A": pytest.approx(0.5), "B": pytest.approx(0.5)}
    # peak was reset to 0.91 on resume: 0.85 is a 6.6% drawdown from it -> halved, not flat
    assert strat.targets(ts(50), row, state(equity=0.85, memory=mem)) == {"A": pytest.approx(0.25), "B": pytest.approx(0.25)}


def test_selection_is_held_between_selection_times_even_if_ranks_change():
    strat = Momentum(MomentumParams(k=2, buffer_rank=2, select_every_h=24))
    mem = {}
    first = strat.targets(ts(0), sig_row({"A": 3.0, "B": 2.0, "C": 1.0, "D": 0.5}), state(memory=mem))
    assert set(first) == {"A", "B"}
    # an hour later C and D lead by a mile and A, B have fallen far outside the buffer — still held
    later = strat.targets(ts(1), sig_row({"A": 0.1, "B": 0.2, "C": 9.0, "D": 8.0}),
                          state(holdings={"A": 1.0, "B": 1.0}, weights={"A": 0.5, "B": 0.5}, memory=mem))
    assert set(later) == {"A", "B"}


def test_selection_is_redone_at_the_next_selection_time():
    strat = Momentum(MomentumParams(k=2, buffer_rank=2, select_every_h=24))
    mem = {}
    strat.targets(ts(0), sig_row({"A": 3.0, "B": 2.0, "C": 1.0, "D": 0.5}), state(memory=mem))
    redo = strat.targets(ts(24), sig_row({"A": 0.1, "B": 0.2, "C": 9.0, "D": 8.0}),
                         state(holdings={"A": 1.0, "B": 1.0}, weights={"A": 0.5, "B": 0.5}, memory=mem))
    assert set(redo) == {"C", "D"}


def test_drift_band_keeps_a_holding_within_band_of_target():
    strat = Momentum(MomentumParams(k=2, drift_band=0.05))
    t = strat.targets(ts(0), sig_row({"A": 2.0, "B": 1.0}),
                      state(holdings={"A": 1.0, "B": 1.0}, weights={"A": 0.48, "B": 0.40}))
    assert t == {"A": pytest.approx(0.48), "B": pytest.approx(0.5)}


# --- families 4-7: residual momentum, funding crowding, volume confirmation, stocks & gold -------------

def panel2(closes, stale=None, volume=None, extra=None):
    n = len(next(iter(closes.values())))
    idx = pd.DatetimeIndex([ts(h) for h in range(n)], name="time")
    close = pd.DataFrame(closes, index=idx, dtype=float)
    st = pd.DataFrame(stale or {p: [False] * n for p in closes}, index=idx, dtype=bool)
    vol = None if volume is None else pd.DataFrame(volume, index=idx, dtype=float)
    return Prices(close=close, stale=st, volume=vol, extra=extra or {})


LONG = dict(lookbacks_h=(168,), skip_h=0, vol_window_h=168, min_age_h=0, gate_ma_h=2)


# live closes 100 -> 110 -> 99 -> 105 with a stale hour after each; live log returns .09531, -.10536, .05884
# -> sample std 0.10690. A naive rolling std over all 6 hourly returns (three of them zero) would be 0.0797.
def test_vol_is_measured_on_live_bars_only():
    prices = panel2({"A/USD": [100, 100, 110, 110, 99, 99, 105]},
                    stale={"A/USD": [False, True, False, True, False, True, False]})
    strat = Momentum(MomentumParams(lookbacks_h=(1,), skip_h=0, vol_window_h=6, min_age_h=0))
    assert strat.signals(prices)[("vol", "A/USD")].iloc[6] == pytest.approx(0.10690, rel=1e-3)


def test_selection_at_a_fixed_utc_hour_and_on_the_first_call():
    strat = Momentum(MomentumParams(k=2, buffer_rank=2, select_hour_utc=15))
    mem = {}
    assert set(strat.targets(ts(3), sig_row({"A": 3.0, "B": 2.0, "C": 1.0}), state(memory=mem))) == {"A", "B"}
    held = state(holdings={"A": 1.0, "B": 1.0}, weights={"A": 0.5, "B": 0.5}, memory=mem)
    assert set(strat.targets(ts(4), sig_row({"A": 0.1, "B": 0.2, "C": 9.0}), held)) == {"A", "B"}      # not 15:00 yet
    assert set(strat.targets(ts(15), sig_row({"A": 0.1, "B": 0.2, "C": 9.0}), held)) == {"B", "C"}     # B rank 2 kept
    held2 = state(holdings={"B": 1.0, "C": 1.0}, weights={"B": 0.5, "C": 0.5}, memory=mem)
    assert set(strat.targets(ts(16), sig_row({"A": 9.0, "B": 0.2, "C": 0.1}), held2)) == {"B", "C"}    # held to next 15:00


def test_residual_momentum_removes_the_market_component_and_keeps_idiosyncratic_trend():
    rng = np.random.default_rng(1)
    n = 800
    r_btc, r_idio = rng.normal(0.001, 0.01, n), rng.normal(0.001, 0.01, n)
    prices = panel2({"BTC/USD": 100 * np.exp(np.cumsum(r_btc)),
                     "TWIN/USD": 100 * np.exp(np.cumsum(2 * r_btc)),      # a pure beta-2 clone of BTC
                     "IDIO/USD": 100 * np.exp(np.cumsum(r_idio))})        # its own trend, unrelated to BTC
    raw = Momentum(MomentumParams(**LONG)).signals(prices)
    res = Momentum(MomentumParams(residual_weight=1.0, beta_window_h=336, **LONG)).signals(prices)
    twin_raw, twin_res = raw[("score", "TWIN/USD")].iloc[-1], res[("score", "TWIN/USD")].iloc[-1]
    assert abs(twin_raw) > 0.5                                             # the clone trends (with BTC)
    assert abs(twin_res) < 0.2 * abs(twin_raw)                             # ...but has no trend of its own
    idio_raw, idio_res = raw[("score", "IDIO/USD")].iloc[-1], res[("score", "IDIO/USD")].iloc[-1]
    assert idio_res == pytest.approx(idio_raw, rel=0.5)                    # idiosyncratic trend survives
    assert res[("score", "BTC/USD")].iloc[-1] == pytest.approx(raw[("score", "BTC/USD")].iloc[-1])   # market: raw


def test_volume_confirmation_favours_rising_volume_on_identical_price_paths():
    rng = np.random.default_rng(2)
    n = 800
    px = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.005, n)))           # a clear uptrend
    prices = panel2({"A/USD": px, "B/USD": px},
                    volume={"A/USD": np.linspace(1, 3, n), "B/USD": np.linspace(3, 1, n)})
    off = Momentum(MomentumParams(**LONG)).signals(prices)
    on = Momentum(MomentumParams(volume_confirm=True, volume_short_h=168, volume_long_h=720, **LONG)).signals(prices)
    assert off[("score", "A/USD")].iloc[-1] == off[("score", "B/USD")].iloc[-1]
    assert on[("score", "A/USD")].iloc[-1] > on[("score", "B/USD")].iloc[-1] > 0


def test_funding_filter_drops_crowded_assets_from_the_score():
    n = 400
    idx = pd.DatetimeIndex([ts(h) for h in range(n)], name="time")
    funding = pd.DataFrame({"A/USD": 0.001, "B/USD": 0.0001}, index=idx)   # A: 0.1% per 8h — crowded longs
    prices = panel2({"A/USD": [100 + i for i in range(n)], "B/USD": [100 + i for i in range(n)]},
                    extra={"funding": funding})
    sig = Momentum(MomentumParams(funding_max=0.0005, funding_window_h=72, **LONG)).signals(prices)
    assert math.isnan(sig[("score", "A/USD")].iloc[-1])
    assert sig[("score", "B/USD")].iloc[-1] > 0


def test_selection_at_several_utc_hours_per_day():
    strat = Momentum(MomentumParams(k=2, buffer_rank=2, select_hours_utc=(0, 12)))
    mem = {}
    assert set(strat.targets(ts(0), sig_row({"A": 3.0, "B": 2.0, "C": 1.0}), state(memory=mem))) == {"A", "B"}
    held = state(holdings={"A": 1.0, "B": 1.0}, weights={"A": 0.5, "B": 0.5}, memory=mem)
    new_ranks = sig_row({"A": 0.1, "B": 0.2, "C": 9.0})
    assert set(strat.targets(ts(6), new_ranks, held)) == {"A", "B"}          # 06:00 is not a selection hour
    assert set(strat.targets(ts(12), new_ranks, held)) == {"B", "C"}         # 12:00 is
