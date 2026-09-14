"""Rolling-window scoring the way the competition scores: return, max drawdown, Sharpe, Sortino, Calmar."""
import math

import pandas as pd
import pytest

from qtrading.backtest.metrics import daily_equity, rank_composite, window_metrics


def hourly_equity(daily_values, start="2026-09-01"):
    """Expand daily closes into an hourly series where the value at 00:00 UTC is the day's value."""
    idx = pd.date_range(start, periods=len(daily_values) * 24, freq="1h", tz="UTC")
    vals = []
    for v in daily_values:
        vals.extend([v] * 24)
    return pd.Series(vals, index=idx, dtype=float)


def test_daily_equity_samples_the_midnight_utc_value():
    eq = hourly_equity([100, 110, 99])
    eq.iloc[5] = 999.0                                       # an intraday spike must not leak into daily samples
    d = daily_equity(eq)
    assert list(d) == [100, 110, 99]
    assert d.index[0] == pd.Timestamp("2026-09-01", tz="UTC")


def test_window_metrics_match_hand_computed_values():
    # daily equity 100 -> 110 -> 99 -> 105 ; one 3-day window
    # returns r = [+0.10, -0.10, +0.060606]; mean = 0.020202; sample std = 0.105940
    # downside dev = sqrt(mean(min(r,0)^2)) = sqrt(0.01/3) = 0.057735
    # window return = 0.05 ; max drawdown = (99-110)/110 = 0.10 ; calmar = 0.05/0.10 = 0.5
    w = window_metrics(hourly_equity([100, 110, 99, 105]), window_days=3)
    assert len(w) == 1
    row = w.iloc[0]
    assert row["ret"] == pytest.approx(0.05)
    assert row["mdd"] == pytest.approx(0.10)
    assert row["sharpe"] == pytest.approx(0.020202 / 0.105940 * math.sqrt(365), rel=1e-3)
    assert row["sortino"] == pytest.approx(0.020202 / 0.057735 * math.sqrt(365), rel=1e-3)
    assert row["calmar"] == pytest.approx(0.5)


def test_windows_start_every_day_and_need_window_plus_one_points():
    w = window_metrics(hourly_equity([100 + i for i in range(16)]), window_days=14)
    assert list(w.index) == [pd.Timestamp("2026-09-01", tz="UTC"), pd.Timestamp("2026-09-02", tz="UTC")]


def test_calmar_is_nan_when_there_is_no_drawdown():
    w = window_metrics(hourly_equity([100, 101, 102, 103]), window_days=3)
    assert math.isnan(w.iloc[0]["calmar"])


def test_a_flat_window_ranks_between_a_losing_and_a_winning_one():
    idx = pd.to_datetime(["2026-09-01"], utc=True)
    winner = pd.DataFrame({"sortino": [2.0], "sharpe": [1.5], "calmar": [0.8]}, index=idx)
    flat = pd.DataFrame({"sortino": [math.nan], "sharpe": [math.nan], "calmar": [math.nan]}, index=idx)
    loser = pd.DataFrame({"sortino": [-1.0], "sharpe": [-0.5], "calmar": [-0.4]}, index=idx)
    comp = rank_composite({"win": winner, "flat": flat, "lose": loser})
    assert comp["win"] == pytest.approx(1.0)
    assert comp["flat"] == pytest.approx(0.5)
    assert comp["lose"] == pytest.approx(0.0)


def test_rank_composite_gives_the_dominant_strategy_one_and_the_dominated_zero():
    idx = pd.to_datetime(["2026-09-01", "2026-09-02"], utc=True)
    a = pd.DataFrame({"sortino": [2.0, 3.0], "sharpe": [1.5, 2.5], "calmar": [0.8, 0.9]}, index=idx)
    b = pd.DataFrame({"sortino": [1.0, 1.0], "sharpe": [0.5, 0.5], "calmar": [0.1, 0.2]}, index=idx)
    comp = rank_composite({"A": a, "B": b})
    assert comp["A"] == pytest.approx(1.0)
    assert comp["B"] == pytest.approx(0.0)
