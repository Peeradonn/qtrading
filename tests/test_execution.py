"""plan_orders: the one order-planning function shared by the simulator and the live engine."""
import math

import pytest

from qtrading.execution import plan_orders
from qtrading.roostoo.models import PairInfo


def rules(pairs, amount_precision=3, min_order=1.0):
    return {p: PairInfo(p, p.split("/")[0], "USD", True, 2, amount_precision, min_order, "crypto") for p in pairs}


def test_sells_come_before_buys_and_fund_them():
    # hold A worth 1000, want 100% B: without the sale first there is no cash for B
    orders = plan_orders(targets={"B/USD": 1.0}, holdings={"A/USD": 100.0}, prices={"A/USD": 10.0, "B/USD": 5.0},
                         stale=set(), cash=0.0, equity=1000.0, rules=rules(["A/USD", "B/USD"]),
                         fee_rate=0.001, min_trade_notional=0.0)
    assert [(o.pair, o.side) for o in orders] == [("A/USD", "SELL"), ("B/USD", "BUY")]
    sell, buy = orders
    assert sell.quantity == 100.0
    # proceeds 1000 - fee 1 = 999 cash; affordable = 999 / (5 * 1.001) = 199.6 -> floored to 199.6
    assert buy.quantity == pytest.approx(199.6)
    assert buy.fee == pytest.approx(199.6 * 5.0 * 0.001)


def test_buy_is_capped_by_cash_after_fees():
    orders = plan_orders(targets={"A/USD": 1.0}, holdings={}, prices={"A/USD": 100.0}, stale=set(), cash=1000.0,
                         equity=1000.0, rules=rules(["A/USD"], amount_precision=8), fee_rate=0.001, min_trade_notional=0.0)
    (buy,) = orders
    assert buy.quantity == pytest.approx(1000 / (100 * 1.001), rel=1e-8)


def test_nan_price_stale_pair_and_unknown_pair_are_skipped():
    orders = plan_orders(targets={"A/USD": 0.3, "B/USD": 0.3, "C/USD": 0.3}, holdings={},
                         prices={"A/USD": math.nan, "B/USD": 10.0, "C/USD": 10.0}, stale={"B/USD"}, cash=1000.0,
                         equity=1000.0, rules=rules(["A/USD", "B/USD"]), fee_rate=0.001, min_trade_notional=0.0)
    assert orders == []


# --- shorts: only when the caller says so; the live engine never does ------------------------------------

def test_a_short_sale_beyond_holdings_needs_allow_short():
    kw = dict(targets={"A/USD": -0.5}, holdings={}, prices={"A/USD": 10.0}, stale=set(), cash=1000.0, equity=1000.0,
              rules=rules(["A/USD"]), fee_rate=0.001, min_trade_notional=0.0)
    assert plan_orders(**kw) == []                                   # default: nothing to sell, nothing planned
    (sell,) = plan_orders(**kw, allow_short=True)
    assert (sell.side, sell.quantity, sell.notional, sell.fee) == ("SELL", 50.0, 500.0, pytest.approx(0.5))


def test_covering_a_short_is_a_buy_funded_from_cash():
    (buy,) = plan_orders(targets={}, holdings={"A/USD": -50.0}, prices={"A/USD": 12.0}, stale=set(), cash=1500.0,
                         equity=900.0, rules=rules(["A/USD"]), fee_rate=0.001, min_trade_notional=0.0, allow_short=True)
    assert (buy.side, buy.quantity, buy.notional) == ("BUY", 50.0, 600.0)
