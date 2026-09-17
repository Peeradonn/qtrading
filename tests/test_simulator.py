"""Simulator: fills, fees, precision, min-order, stale bars, equity accounting, decision cadence."""
import pandas as pd
import pytest

from qtrading.backtest.simulator import SimConfig, simulate
from qtrading.data.store import Prices
from qtrading.roostoo.models import PairInfo


def ts(h):
    return pd.Timestamp("2026-09-01", tz="UTC") + pd.Timedelta(hours=h)


def panel(closes: dict, stale: dict | None = None) -> Prices:
    """closes: {pair: [price per hour]}; stale: {pair: [bool per hour]} (default all False)."""
    n = len(next(iter(closes.values())))
    idx = pd.DatetimeIndex([ts(h) for h in range(n)], name="time")
    close = pd.DataFrame(closes, index=idx, dtype=float)
    st = pd.DataFrame(stale or {p: [False] * n for p in closes}, index=idx, dtype=bool)
    return Prices(close=close, stale=st)


def rules(pairs, amount_precision=3, min_order=1.0):
    return {p: PairInfo(p, p.split("/")[0], "USD", True, 2, amount_precision, min_order, "crypto") for p in pairs}


class FixedTargets:
    """Test double: a schedule of target weights per hour; hours not listed repeat the previous targets."""
    name = "fixed"

    def __init__(self, schedule: dict[int, dict[str, float]]):
        self.schedule = schedule

    def signals(self, prices):
        return pd.DataFrame(0.0, index=prices.close.index, columns=prices.close.columns)

    def targets(self, t, signals_at_t, state):
        h = int((t - ts(0)) / pd.Timedelta(hours=1))
        last = {}
        for k in sorted(self.schedule):
            if k <= h:
                last = self.schedule[k]
        return last


def run(prices, strategy, r=None, **cfg):
    return simulate(prices, strategy, r or rules(prices.close.columns), SimConfig(**cfg))


def test_buy_debits_cash_by_notional_plus_fee_and_credits_quantity_rounded_down():
    prices = panel({"A/USD": [3.0, 3.0]})
    res = run(prices, FixedTargets({0: {"A/USD": 0.5}}), initial_cash=1000.0, fee_rate=0.001, min_trade_notional=0.0)
    trade = res.trades[0]
    assert trade.quantity == 166.666                       # 500 / 3 = 166.666..., floored to 3 dp
    assert trade.notional == pytest.approx(499.998)
    assert trade.fee == pytest.approx(0.499998)
    assert res.cash.iloc[0] == pytest.approx(1000 - 499.998 - 0.499998)


def test_sell_credits_cash_net_of_fee():
    prices = panel({"A/USD": [3.0, 4.0]})
    res = run(prices, FixedTargets({0: {"A/USD": 0.5}, 1: {}}), initial_cash=1000.0, fee_rate=0.001, min_trade_notional=0.0)
    sell = res.trades[1]
    assert sell.side == "SELL"
    assert sell.quantity == 166.666
    assert sell.fee == pytest.approx(166.666 * 4.0 * 0.001)
    assert res.cash.iloc[1] == pytest.approx(res.cash.iloc[0] + 166.666 * 4.0 - sell.fee)


def test_equity_is_cash_plus_holdings_at_close():
    prices = panel({"A/USD": [3.0, 4.0, 2.0]})
    # min_trade_notional=100 keeps the small drift rebalances at h1/h2 from happening, isolating the accounting
    res = run(prices, FixedTargets({0: {"A/USD": 0.5}}), initial_cash=1000.0, fee_rate=0.001, min_trade_notional=100.0)
    cash0 = res.cash.iloc[0]
    assert res.equity.iloc[1] == pytest.approx(cash0 + 166.666 * 4.0)
    assert res.equity.iloc[2] == pytest.approx(cash0 + 166.666 * 2.0)


def test_trades_below_min_trade_notional_are_skipped():
    prices = panel({"A/USD": [3.0, 3.0]})
    res = run(prices, FixedTargets({0: {"A/USD": 0.02}}), initial_cash=1000.0, min_trade_notional=50.0)
    assert res.trades == []


def test_orders_below_exchange_min_order_are_skipped():
    prices = panel({"A/USD": [3.0, 3.0]})
    r = rules(["A/USD"], min_order=10.0)
    res = run(prices, FixedTargets({0: {"A/USD": 0.005}}), r, initial_cash=1000.0, min_trade_notional=0.0)
    assert res.trades == []


def test_no_trade_on_a_stale_bar():
    prices = panel({"A/USD": [3.0, 3.0]}, stale={"A/USD": [True, False]})
    res = run(prices, FixedTargets({0: {"A/USD": 0.5}}), initial_cash=1000.0, min_trade_notional=0.0)
    assert [t.time for t in res.trades] == [ts(1)]         # deferred to the first live bar


def test_sells_execute_before_buys_so_a_full_rotation_fits_in_cash():
    prices = panel({"A/USD": [10.0, 10.0], "B/USD": [5.0, 5.0]})
    res = run(prices, FixedTargets({0: {"A/USD": 1.0}, 1: {"B/USD": 1.0}}), initial_cash=1000.0, fee_rate=0.001,
              min_trade_notional=0.0)
    assert res.holdings.iloc[1]["A/USD"] == 0
    assert res.holdings.iloc[1]["B/USD"] > 190             # nearly all of ~$998 rotated into B at $5


def test_buy_and_hold_reproduces_price_return_minus_one_fee():
    prices = panel({"A/USD": [100.0, 120.0, 90.0, 150.0]})
    res = run(prices, FixedTargets({0: {"A/USD": 1.0}}), rules(["A/USD"], amount_precision=8), initial_cash=1000.0,
              fee_rate=0.001, min_trade_notional=0.0)
    # all cash goes in at 100 paying 0.1% on notional -> position worth 1000/1.001 at t0; then rides 100 -> 150
    assert res.equity.iloc[-1] == pytest.approx(1000 / 1.001 * 1.5, rel=1e-6)


def test_decisions_happen_only_every_n_hours():
    prices = panel({"A/USD": [3.0] * 5})
    sched = {0: {"A/USD": 0.1}, 1: {"A/USD": 0.2}, 2: {"A/USD": 0.3}, 3: {"A/USD": 0.4}, 4: {"A/USD": 0.5}}
    res = run(prices, FixedTargets(sched), initial_cash=1000.0, decision_every_h=2, min_trade_notional=0.0)
    assert [t.time for t in res.trades] == [ts(0), ts(2), ts(4)]


class GateReader:
    """Test double: buys only if its own extra '_gate' signal column reaches targets()."""
    name = "gate-reader"

    def signals(self, prices):
        sig = pd.DataFrame(0.0, index=prices.close.index, columns=prices.close.columns)
        sig["_gate"] = 1.0
        return sig

    def targets(self, t, s, state):
        return {"A/USD": 0.5} if "_gate" in s.index and s["_gate"] > 0 else {}


def test_extra_signal_columns_are_passed_through_to_targets():
    prices = panel({"A/USD": [3.0, 3.0]})
    res = run(prices, GateReader(), initial_cash=1000.0, min_trade_notional=0.0)
    assert len(res.trades) == 1


class Counter:
    """Test double: counts decisions in state.memory and buys only on the third one."""
    name = "counter"

    def signals(self, prices):
        return pd.DataFrame(0.0, index=prices.close.index, columns=prices.close.columns)

    def targets(self, t, s, state):
        state.memory["n"] = state.memory.get("n", 0) + 1
        return {"A/USD": 0.5} if state.memory["n"] == 3 else {}


def test_state_memory_persists_across_decisions():
    prices = panel({"A/USD": [3.0] * 4})
    res = run(prices, Counter(), initial_cash=1000.0, min_trade_notional=0.0)
    assert [t.time for t in res.trades if t.side == "BUY"] == [ts(2)]   # (the 4th decision then sells it)


def test_equal_sized_orders_are_processed_in_a_deterministic_order():
    # Six equal buys: with a hash-ordered set the fill order (and hence which one is cash-constrained last)
    # would vary between Python processes. Pairs must be processed in sorted order.
    pairs = ["F/USD", "B/USD", "E/USD", "A/USD", "D/USD", "C/USD"]
    prices = panel({p: [3.0, 3.0] for p in pairs})
    res = run(prices, FixedTargets({0: {p: 1 / 6 for p in pairs}}), initial_cash=1000.0, min_trade_notional=0.0)
    assert [t.pair for t in res.trades] == sorted(pairs)


def test_turnover_is_notional_traded_over_equity():
    prices = panel({"A/USD": [3.0, 3.0]})
    res = run(prices, FixedTargets({0: {"A/USD": 0.5}}), initial_cash=1000.0, fee_rate=0.0, min_trade_notional=0.0)
    assert res.turnover.iloc[0] == pytest.approx(499.998 / 1000.0)
    assert res.turnover.iloc[1] == 0.0


# --- shorts: a negative quantity valued at price, opened and covered like any other order ----------------

# hour 0 @10: sell 50 short -> cash 1000 + 500 - 0.5 = 1499.5, equity 1499.5 - 500 = 999.5
# hour 1 @12: cover 50 -> cost 600 + 0.6 -> cash 898.9, equity 898.9 (the short lost 100 plus two fees)
def test_short_position_is_valued_at_price_and_covered_by_a_buy():
    prices = panel({"A/USD": [10.0, 12.0, 12.0]})
    res = run(prices, FixedTargets({0: {"A/USD": -0.5}, 1: {}}), initial_cash=1000.0, allow_short=True,
              min_trade_notional=0.0)
    assert res.holdings["A/USD"].iloc[0] == pytest.approx(-50.0)
    assert list(res.equity.round(6)) == [999.5, 898.9, 898.9]
    assert [(t.side, t.quantity) for t in res.trades] == [("SELL", 50.0), ("BUY", 50.0)]


def test_shorts_are_refused_unless_the_config_allows_them():
    prices = panel({"A/USD": [10.0, 12.0, 12.0]})
    res = run(prices, FixedTargets({0: {"A/USD": -0.5}}), initial_cash=1000.0, min_trade_notional=0.0)
    assert res.trades == [] and list(res.equity) == [1000.0, 1000.0, 1000.0]
