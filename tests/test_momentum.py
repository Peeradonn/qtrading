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


def test_force_rebalance_flag_bypasses_the_drift_band_for_one_call():
    strat = Momentum(MomentumParams(k=2, drift_band=0.05))
    row = sig_row({"A": 2.0, "B": 1.0})
    held = dict(holdings={"A": 1.0, "B": 1.0}, weights={"A": 0.48, "B": 0.47})
    assert strat.targets(ts(0), row, state(**held)) == {"A": pytest.approx(0.48), "B": pytest.approx(0.47)}
    forced = strat.targets(ts(1), row, state(**held, memory={"force_rebalance": True}))
    assert forced == {"A": pytest.approx(0.5), "B": pytest.approx(0.5)}
    mem = {"force_rebalance": True}
    strat.targets(ts(2), row, state(**held, memory=mem))
    assert "force_rebalance" not in mem                                    # consumed: one cycle only


# --- volatility model -----------------------------------------------------------

# log returns 0.1, -0.2, 0.3 -> squared 0.01, 0.04, 0.09. Exponentially weighted with lambda 0.5 at the last bar:
# (0.09 + 0.5*0.04 + 0.25*0.01) / (1 + 0.5 + 0.25) = 0.1125 / 1.75 = 0.0642857 -> vol = 0.253546
def test_ewma_volatility_weights_recent_squared_returns_more_heavily():
    prices = panel({"A/USD": [100.0, 100 * math.exp(0.1), 100 * math.exp(-0.1), 100 * math.exp(0.2)]})
    strat = Momentum(MomentumParams(lookbacks_h=(1,), skip_h=0, vol_window_h=3, min_age_h=0,
                                    vol_model="ewma", ewma_lambda=0.5))
    assert strat.signals(prices)[("vol", "A/USD")].iloc[3] == pytest.approx(0.253546, rel=1e-4)


def test_trailing_volatility_remains_the_default():
    prices = panel({"A/USD": [100.0, 100 * math.exp(0.1), 100 * math.exp(-0.1), 100 * math.exp(0.2)]})
    default = Momentum(MomentumParams(lookbacks_h=(1,), skip_h=0, vol_window_h=3, min_age_h=0))
    ewma = Momentum(MomentumParams(lookbacks_h=(1,), skip_h=0, vol_window_h=3, min_age_h=0, vol_model="ewma"))
    a = default.signals(prices)[("vol", "A/USD")].iloc[3]
    b = ewma.signals(prices)[("vol", "A/USD")].iloc[3]
    assert a != pytest.approx(b)


def test_ewma_volatility_reacts_faster_to_a_volatility_spike():
    calm = [100.0 * math.exp(0.001 * (-1) ** i) for i in range(400)]
    spike = [calm[-1] * math.exp(0.05 * (-1) ** i) for i in range(20)]
    prices = panel({"A/USD": calm + spike})
    kw = dict(lookbacks_h=(1,), skip_h=0, vol_window_h=168, min_age_h=0)
    trailing = Momentum(MomentumParams(**kw)).signals(prices)[("vol", "A/USD")].iloc[-1]
    ewma = Momentum(MomentumParams(vol_model="ewma", ewma_lambda=0.99, **kw)).signals(prices)[("vol", "A/USD")].iloc[-1]
    assert ewma > trailing


# --- sleeve: idle cash held in a permanent low-correlation asset (gold) -----------------------------------
# The crypto book is untouched; the sleeve only changes what happens to cash the vol target leaves idle.

def test_sleeve_pair_is_never_ranked_but_keeps_its_vol():
    prices = panel({"BTC/USD": [100, 102, 101, 104, 103], "PAXG/USD": [50, 51, 52, 53, 54]})
    sig = Momentum(MomentumParams(lookbacks_h=(1,), skip_h=0, vol_window_h=3, min_age_h=0, gate_ma_h=2,
                                  sleeve=("PAXG/USD",))).signals(prices)
    assert math.isnan(sig[("score", "PAXG/USD")].iloc[4])
    assert sig[("vol", "PAXG/USD")].iloc[4] > 0
    assert not math.isnan(sig[("score", "BTC/USD")].iloc[4])


def test_sleeve_pair_must_be_in_the_selectable_universe():
    prices = panel({"A/USD": [1, 2, 3], "PAXG/USD": [1, 1, 1]})
    with pytest.raises(ValueError, match="PAXG/USD"):
        Momentum(MomentumParams(pairs=("A/USD",), sleeve=("PAXG/USD",))).signals(prices)


# one of two slots filled -> crypto exposure 0.5; the sleeve takes the idle half
def test_cash_sleeve_takes_the_idle_cash_and_leaves_the_crypto_book_unchanged():
    row = sig_row({"A": 2.0, "PAXG": float("nan")}, vols={"A": 0.01, "PAXG": 0.002})
    plain = Momentum(MomentumParams(k=2, buffer_rank=2)).targets(ts(0), row, state())
    sleeved = Momentum(MomentumParams(k=2, buffer_rank=2, sleeve=("PAXG",))).targets(ts(0), row, state())
    assert plain == {"A": pytest.approx(0.5)}
    assert sleeved == {"A": pytest.approx(0.5), "PAXG": pytest.approx(0.5)}


def test_sleeve_pair_is_excluded_from_selection_even_with_a_high_score():
    row = sig_row({"A": 2.0, "B": 1.0, "PAXG": 9.0}, vols={"A": 0.01, "B": 0.01, "PAXG": 0.002})
    t = Momentum(MomentumParams(k=2, buffer_rank=2, max_exposure=0.6, sleeve=("PAXG",))).targets(ts(0), row, state())
    assert t == {"A": pytest.approx(0.3), "B": pytest.approx(0.3), "PAXG": pytest.approx(0.4)}


def test_cash_sleeve_fraction_scales_how_much_idle_cash_it_takes():
    row = sig_row({"A": 2.0, "B": 1.0, "PAXG": float("nan")}, vols={"A": 0.01, "B": 0.01, "PAXG": 0.002})
    strat = Momentum(MomentumParams(k=2, max_exposure=0.6, sleeve=("PAXG",), sleeve_fraction=0.5))
    assert strat.targets(ts(0), row, state()) == {"A": pytest.approx(0.3), "B": pytest.approx(0.3), "PAXG": pytest.approx(0.2)}


def test_sleeve_holds_when_nothing_is_selected_and_stays_in_cash_without_a_live_vol():
    strat = Momentum(MomentumParams(k=2, sleeve=("PAXG",)))
    nothing = sig_row({"PAXG": float("nan")}, vols={"PAXG": 0.002})                  # no crypto has a score
    assert strat.targets(ts(0), nothing, state()) == {"PAXG": pytest.approx(1.0)}
    no_vol = sig_row({"A": 2.0, "PAXG": float("nan")}, vols={"A": 0.01, "PAXG": float("nan")})
    assert strat.targets(ts(0), no_vol, state()) == {"A": pytest.approx(0.5)}


def test_drift_band_applies_to_the_sleeve_too():
    row = sig_row({"A": 2.0, "PAXG": float("nan")}, vols={"A": 0.01, "PAXG": 0.002})
    strat = Momentum(MomentumParams(k=2, buffer_rank=2, sleeve=("PAXG",), drift_band=0.05))
    t = strat.targets(ts(0), row, state(holdings={"A": 1.0, "PAXG": 1.0}, weights={"A": 0.5, "PAXG": 0.47}))
    assert t == {"A": pytest.approx(0.5), "PAXG": pytest.approx(0.47)}


# book mode: the sleeve is one more inverse-vol position and the vol target treats it as uncorrelated with the book.
# A 4%/day, PAXG 1%/day, k=1 -> inverse-vol weights A 0.2, PAXG 0.8; portfolio vol = sqrt((0.2*0.04)^2 + (0.8*0.01)^2)
# = 0.011314. Target 2% -> exposure capped at 1. Target 0.5% -> exposure 0.44194 -> A 0.088388, PAXG 0.353553.
def test_book_sleeve_is_an_inverse_vol_position_treated_as_uncorrelated_by_the_vol_target():
    hv_a, hv_g = 0.04 / math.sqrt(24), 0.01 / math.sqrt(24)
    row = sig_row({"A": 2.0, "PAXG": float("nan")}, vols={"A": hv_a, "PAXG": hv_g})
    p = dict(k=1, buffer_rank=1, weighting="inverse_vol", sleeve=("PAXG",), sleeve_mode="book", avg_corr=1.0)
    full = Momentum(MomentumParams(vol_target_daily=0.02, **p)).targets(ts(0), row, state())
    assert full == {"A": pytest.approx(0.2), "PAXG": pytest.approx(0.8)}
    scaled = Momentum(MomentumParams(vol_target_daily=0.005, **p)).targets(ts(0), row, state())
    assert scaled == {"A": pytest.approx(0.088388, rel=1e-4), "PAXG": pytest.approx(0.353553, rel=1e-4)}


# --- hedge: a short in one pair sized off the long book, gross exposure capped ------------------------------

# A and B selected at 0.5 each; hedge 0.5 x long notional -> BTC -0.5; gross 1.5 > 1 -> everything x 2/3
def test_hedge_shorts_the_hedge_pair_in_proportion_to_the_long_book_and_caps_gross_exposure():
    row = sig_row({"A": 2.0, "B": 1.0, "BTC": -5.0}, vols={"A": 0.01, "B": 0.01, "BTC": 0.01})
    strat = Momentum(MomentumParams(k=2, buffer_rank=2, hedge_pair="BTC", hedge_ratio=0.5))
    t = strat.targets(ts(0), row, state())
    assert t == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3), "BTC": pytest.approx(-1 / 3)}


def test_hedge_nets_against_a_long_position_in_the_hedge_pair():
    row = sig_row({"BTC": 2.0, "A": 1.0, "B": -1.0}, vols={"A": 0.01, "B": 0.01, "BTC": 0.01})
    strat = Momentum(MomentumParams(k=2, buffer_rank=2, hedge_pair="BTC", hedge_ratio=0.5))
    t = strat.targets(ts(0), row, state())
    assert t == {"BTC": pytest.approx(0.0), "A": pytest.approx(0.5)}       # 0.5 long - 0.5 hedge, gross 0.5


def test_hedge_is_skipped_without_a_live_vol_for_the_hedge_pair():
    row = sig_row({"A": 2.0, "B": 1.0, "BTC": float("nan")}, vols={"A": 0.01, "B": 0.01, "BTC": float("nan")})
    t = Momentum(MomentumParams(k=2, buffer_rank=2, hedge_pair="BTC", hedge_ratio=0.5)).targets(ts(0), row, state())
    assert t == {"A": pytest.approx(0.5), "B": pytest.approx(0.5)}


def test_drift_band_applies_to_a_short_holding():
    row = sig_row({"A": 2.0, "B": 1.0, "BTC": -5.0}, vols={"A": 0.01, "B": 0.01, "BTC": 0.01})
    strat = Momentum(MomentumParams(k=2, buffer_rank=2, hedge_pair="BTC", hedge_ratio=0.5, drift_band=0.05))
    held = state(holdings={"A": 1.0, "B": 1.0, "BTC": -1.0}, weights={"A": 1 / 3, "B": 1 / 3, "BTC": -0.31})
    assert strat.targets(ts(0), row, held) == {"A": pytest.approx(1 / 3), "B": pytest.approx(1 / 3), "BTC": pytest.approx(-0.31)}


# --- exposure policy: downside-only volatility targeting, and a floor on exposure ---------------------------

# an asset that only ever rises has zero downside deviation: downside targeting leaves it fully invested where
# total-vol targeting would cut it
def test_downside_vol_targeting_ignores_upside_volatility():
    up_only = [100.0 * math.exp(sum(0.01 + 0.08 * (j % 2) for j in range(i))) for i in range(40)]   # +1%, +9%, +1%, ...
    prices = panel({"A/USD": up_only})                                    # volatile, but never down
    kw = dict(k=1, buffer_rank=1, lookbacks_h=(1,), skip_h=0, vol_window_h=6, min_age_h=0, vol_target_daily=0.02)
    total = Momentum(MomentumParams(**kw))
    down = Momentum(MomentumParams(**kw, vol_target_on="downside"))
    row_t, row_d = total.signals(prices).iloc[-1], down.signals(prices).iloc[-1]
    assert ("dvol", "A/USD") in down.signals(prices).columns
    assert row_d[("dvol", "A/USD")] == pytest.approx(0.0)
    assert total.targets(ts(39), row_t, state())["A/USD"] < 0.2               # 5%/h vol -> heavily cut
    assert down.targets(ts(39), row_d, state())["A/USD"] == pytest.approx(1.0)


# symmetric moves: downside deviation x sqrt(2) equals total volatility, so the two rules agree
def test_downside_deviation_is_scaled_to_match_total_vol_for_symmetric_returns():
    zigzag = [100.0 * math.exp(0.02 * (-1) ** i) for i in range(400)]
    prices = panel({"A/USD": zigzag})
    kw = dict(lookbacks_h=(1,), skip_h=0, vol_window_h=168, min_age_h=0, vol_model="ewma", ewma_lambda=0.99)
    row = Momentum(MomentumParams(**kw, vol_target_on="downside")).signals(prices).iloc[-1]
    assert row[("dvol", "A/USD")] == pytest.approx(row[("vol", "A/USD")], rel=0.05)


def test_exposure_floor_bounds_the_vol_target_from_below():
    hv = 0.04 / math.sqrt(24)
    row = sig_row({"A": 2.0, "B": 1.0}, vols={"A": hv, "B": hv})
    cut = Momentum(MomentumParams(k=2, vol_target_daily=0.02, avg_corr=1.0)).targets(ts(0), row, state())
    assert cut == {"A": pytest.approx(0.25), "B": pytest.approx(0.25)}
    floored = Momentum(MomentumParams(k=2, vol_target_daily=0.02, avg_corr=1.0, min_exposure=0.8)).targets(ts(0), row, state())
    assert floored == {"A": pytest.approx(0.4), "B": pytest.approx(0.4)}


# the same live-bars-only volatility (0.10690) when the panel marks nothing stale but extra['live_bars'] does
def test_vol_uses_the_live_bars_mask_from_extra_when_present():
    base = panel2({"A/USD": [100, 100, 110, 110, 99, 99, 105]})
    live = pd.DataFrame({"A/USD": [True, False, True, False, True, False, True]}, index=base.close.index)
    prices = Prices(close=base.close, stale=base.stale, volume=None, extra={"live_bars": live})
    strat = Momentum(MomentumParams(lookbacks_h=(1,), skip_h=0, vol_window_h=6, min_age_h=0))
    assert strat.signals(prices)[("vol", "A/USD")].iloc[6] == pytest.approx(0.10690, rel=1e-3)


# --- short leg: the bottom of the same ranking, behind the backtester's allow_short -------------------------

def test_short_leg_takes_the_bottom_of_the_ranking_at_its_share_of_gross():
    row = sig_row({"A": 3.0, "B": 2.0, "C": -1.0, "D": -2.0})
    strat = Momentum(MomentumParams(k=2, buffer_rank=2, short_k=2, short_share=0.5, short_buffer_rank=2))
    t = strat.targets(ts(0), row, state())
    assert t == {"A": pytest.approx(0.25), "B": pytest.approx(0.25), "C": pytest.approx(-0.25), "D": pytest.approx(-0.25)}


def test_a_current_short_is_kept_while_it_stays_inside_the_bottom_buffer():
    row = sig_row({"A": 3.0, "B": 2.0, "C": -1.0, "D": -2.0})
    strat = Momentum(MomentumParams(k=1, buffer_rank=1, short_k=1, short_share=0.5, short_buffer_rank=2))
    held = state(holdings={"C": -1.0}, weights={"C": -0.5})               # D is the worst, but C is held and second worst
    assert strat.targets(ts(0), row, held) == {"A": pytest.approx(0.5), "C": pytest.approx(-0.5)}


def test_long_hysteresis_ignores_names_that_are_held_short():
    row = sig_row({"A": 3.0, "B": 2.0, "C": 1.0})
    strat = Momentum(MomentumParams(k=1, buffer_rank=3))
    assert strat.targets(ts(0), row, state(holdings={"B": -1.0}, weights={"B": -0.3})) == {"A": pytest.approx(1.0)}


# perfectly correlated, equal vol, equal and opposite weights -> estimated portfolio vol is zero, exposure stays full
def test_vol_target_nets_the_short_leg_against_the_longs():
    hv = 0.04 / math.sqrt(24)
    row = sig_row({"A": 2.0, "B": -2.0}, vols={"A": hv, "B": hv})
    strat = Momentum(MomentumParams(k=1, buffer_rank=1, short_k=1, short_share=0.5, short_buffer_rank=1,
                                    vol_target_daily=0.02, avg_corr=1.0))
    assert strat.targets(ts(0), row, state()) == {"A": pytest.approx(0.5), "B": pytest.approx(-0.5)}


def test_negative_only_shorts_leave_the_gross_to_the_longs_when_nothing_is_falling():
    row = sig_row({"A": 3.0, "B": 2.0, "C": 1.0})
    strat = Momentum(MomentumParams(k=2, buffer_rank=2, short_k=2, short_share=0.5, short_negative_only=True))
    assert strat.targets(ts(0), row, state()) == {"A": pytest.approx(0.5), "B": pytest.approx(0.5)}
