"""The cycle digest: the five things an operator wants to know, in one message."""
from datetime import date

import pandas as pd

from qtrading.engine.activity import ActivityTracker
from qtrading.engine.exchange import Fill
from qtrading.engine.loop import CycleResult
from qtrading.engine.report import cycle_digest
from qtrading.strategy import State


def test_digest_reports_equity_drawdown_exposure_holdings_pace_and_fills():
    state = State(holdings={"BTC/USD": 2.0, "ETH/USD": 50.0}, weights={"BTC/USD": 0.10, "ETH/USD": 0.15},
                  cash=750_000.0, equity=1_000_000.0, peak_equity=1_050_000.0, memory={})
    fills = [Fill("BTC/USD", "BUY", 0.5, 50_000.0, 25_000.0, 25.0, 7, "FILLED")]
    result = CycleResult("trade", "ok", targets={"BTC/USD": 0.1, "ETH/USD": 0.15}, orders=[], fills=fills,
                         behind_pace=False, equity=1_000_000.0)
    tracker = ActivityTracker(date(2026, 9, 30), active=[date(2026, 9, 30), date(2026, 10, 1)])
    text = cycle_digest("core", pd.Timestamp("2026-10-02 00:00", tz="UTC"), result, state, tracker,
                        initial_equity=950_000.0)
    assert "core" in text
    assert "1,000,000" in text
    assert "+5.3%" in text                     # since start
    assert "-4.8%" in text                     # drawdown from peak
    assert "25%" in text                       # exposure
    assert "BTC/USD 10%" in text and "ETH/USD 15%" in text
    assert "2/8" in text                       # active days vs required
    assert "BUY 0.5 BTC/USD @ 50000" in text


def test_digest_flags_errors_and_pace_problems():
    state = State(holdings={}, weights={}, cash=1_000_000.0, equity=1_000_000.0, peak_equity=1_000_000.0, memory={})
    result = CycleResult("trade", "error", behind_pace=True, equity=1_000_000.0)
    tracker = ActivityTracker(date(2026, 9, 30))
    text = cycle_digest("core", pd.Timestamp("2026-10-09 00:00", tz="UTC"), result, state, tracker,
                        initial_equity=1_000_000.0)
    assert "ERROR" in text
    assert "BEHIND PACE" in text


def _paper_digest(tracker, **kwargs):
    state = State(holdings={}, weights={}, cash=1_000_000.0, equity=1_000_000.0, peak_equity=1_000_000.0, memory={})
    result = CycleResult("trade", "ok", equity=1_000_000.0)
    return cycle_digest("paper", pd.Timestamp("2026-09-18 14:00", tz="UTC"), result, state, tracker,
                        initial_equity=1_000_000.0, **kwargs)


def test_digest_outside_window_counts_active_days_from_the_first_order():
    tracker = ActivityTracker(date(2099, 1, 1), active=[date(2026, 9, 16), date(2026, 9, 18)])
    text = _paper_digest(tracker, first_order_at=pd.Timestamp("2026-09-16 09:00", tz="UTC"),
                         up_since=pd.Timestamp("2026-09-17 12:30", tz="UTC"))
    assert "active days 2/3 since first order 2026-09-16 09:00 UTC | up 1d 1h" in text
    assert "outside competition window" not in text


def test_digest_outside_window_falls_back_to_the_first_active_day_and_handles_no_orders():
    tracker = ActivityTracker(date(2099, 1, 1), active=[date(2026, 9, 16)])
    assert "active days 1/3 since first order 2026-09-16\n" in _paper_digest(tracker)
    text = _paper_digest(ActivityTracker(date(2099, 1, 1)), up_since=pd.Timestamp("2026-09-18 13:15", tz="UTC"))
    assert "active days: no orders yet | up 0h 45m" in text
