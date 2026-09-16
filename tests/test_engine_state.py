"""Reconciliation from exchange balances, and strategy-memory persistence across restarts."""
import pandas as pd

from qtrading.engine.state import load_memory, reconcile, save_memory


def test_reconcile_builds_state_from_balances_and_prices():
    st = reconcile(balances={"USD": 500.0, "BTC": 0.01, "DUST": 0.0, "XYZ": 3.0},
                   prices={"BTC/USD": 50_000.0, "ETH/USD": 3_000.0},
                   pairs=["BTC/USD", "ETH/USD"], memory={"k": 1}, peak_equity=900.0)
    assert st.holdings == {"BTC/USD": 0.01}
    assert st.cash == 500.0
    assert st.equity == 1_000.0
    assert st.weights == {"BTC/USD": 0.5}
    assert st.peak_equity == 1_000.0                       # peak moves up with equity
    assert st.memory == {"k": 1}


def test_memory_round_trips_through_json_with_timestamps_restored(tmp_path):
    mem = {"selected": ["A/USD", "B/USD"], "last_select": pd.Timestamp("2026-09-30 00:00", tz="UTC"),
           "peak": 1_000_000.0, "flat_since": None}
    save_memory(tmp_path / "m.json", mem)
    back = load_memory(tmp_path / "m.json")
    assert back["selected"] == ["A/USD", "B/USD"]
    assert back["last_select"] == pd.Timestamp("2026-09-30 00:00", tz="UTC")
    assert back["peak"] == 1_000_000.0
    assert back["flat_since"] is None


def test_missing_memory_file_loads_as_empty(tmp_path):
    assert load_memory(tmp_path / "nope.json") == {}
