"""Replay: re-derive each journalled decision from the same inputs and prove live matched the strategy."""
import pandas as pd
import pytest

from qtrading.backtest.replay import CycleCheck, compare_targets, state_from_record


def record(targets, holdings=None, memory=None, equity=1_000_000.0):
    return {"kind": "cycle_end", "at": "2026-10-03T14:00:00+00:00", "targets": targets,
            "memory_in": memory or {},
            "state": {"holdings": holdings or {}, "weights": {}, "cash": equity, "equity": equity,
                      "peak_equity": equity}}


def test_state_is_rebuilt_from_the_record():
    st = state_from_record(record({}, holdings={"BTC/USD": 2.0}, memory={"peak": 5.0}))
    assert st.holdings == {"BTC/USD": 2.0}
    assert st.equity == 1_000_000.0
    assert st.memory == {"peak": 5.0}


def test_identical_targets_match():
    check = compare_targets(record({"BTC/USD": 0.5}), {"BTC/USD": 0.5})
    assert check.matches is True
    assert check.differences == {}


def test_a_weight_that_moved_is_reported_with_both_values():
    check = compare_targets(record({"BTC/USD": 0.5}), {"BTC/USD": 0.4})
    assert check.matches is False
    assert check.differences == {"BTC/USD": (0.5, 0.4)}


def test_a_position_only_one_side_holds_is_reported():
    check = compare_targets(record({"BTC/USD": 0.5}), {"BTC/USD": 0.5, "ETH/USD": 0.2})
    assert check.matches is False
    assert check.differences == {"ETH/USD": (None, 0.2)}


def test_tiny_floating_point_differences_are_tolerated():
    assert compare_targets(record({"BTC/USD": 0.5}), {"BTC/USD": 0.5 + 1e-12}).matches is True


def test_the_check_carries_the_cycle_time():
    check = compare_targets(record({}), {})
    assert check.at == pd.Timestamp("2026-10-03 14:00", tz="UTC")
    assert isinstance(check, CycleCheck)
