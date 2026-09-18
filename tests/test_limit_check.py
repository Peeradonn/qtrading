"""The pre-registered limit-order check: one order, one rule written before the run.

The end-to-end test runs the real client against the mock exchange, which rests every limit order, so it covers
the path where the check has to clean up after itself. The rule's other branches are tested on observations built
by hand, since no exchange we can reach today produces them.
"""
import threading
from dataclasses import replace

import pytest

from qtrading.roostoo.client import RoostooClient
from qtrading.roostoo.limit_check import Observation, observe, touch_price, verdict
from qtrading.roostoo.mock_server import MockRoostoo, serve
from qtrading.roostoo.models import Order

API_KEY = "TESTKEY"
SECRET = "TESTSECRET"  # pragma: allowlist secret
RULES = {"BTC/USD": {"Coin": "BTC", "CoinFullName": "Bitcoin", "Unit": "USD", "UnitFullName": "US Dollar",
                     "CanTrade": True, "PricePrecision": 2, "AmountPrecision": 5, "MiniOrder": 1,
                     "AssetType": "crypto"}}


@pytest.fixture
def exchange():
    return MockRoostoo(api_key=API_KEY, secret_key=SECRET, pairs=RULES, prices={"BTC/USD": 50_000.0},
                       wallet={"USD": 50_000.0}, fee_rate=0.001)


@pytest.fixture
def client(exchange):
    server = serve(exchange, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield RoostooClient(API_KEY, SECRET, base_url=f"http://127.0.0.1:{port}", min_interval_s=0.0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_limit_order_that_rests_is_cancelled_and_the_verdict_is_to_keep_market_orders(client, exchange):
    obs = observe(client, "BTC/USD", notional=100.0)
    assert len(exchange.orders) == 1                                  # ONE order: that is the whole check
    sent = exchange.orders[0]
    assert (sent["Type"], sent["Side"]) == ("LIMIT", "BUY")
    assert sent["Price"] == obs.limit_price and obs.ask <= obs.limit_price < obs.ask + 0.01    # at the touch
    assert 99.0 < sent["Quantity"] * sent["Price"] <= 100.0
    assert obs.placed.status == "PENDING" and obs.cancelled
    assert sent["Status"] == "CANCELED" and obs.pending_after == 0    # the account is left as it was found
    assert exchange.wallet == {"USD": 50_000.0}

    adopt, lines = verdict(obs)
    assert not adopt
    assert lines[0].startswith("FAIL") and "PENDING" in lines[0]
    assert "cancelled" in lines[-1]


def test_the_limit_is_the_ask_rounded_up_to_the_price_step_so_it_is_always_marketable():
    assert touch_price(100.001, 2) == 100.01            # nearest would give 100.00, below the ask: it would rest
    assert touch_price(50_000.50, 2) == 50_000.50       # an ask already on the step is used as it is
    assert touch_price(0.00001234, 8) == 0.00001234


# --- the rule's other branches, on observations no reachable exchange produces yet ---------------------------------

def filled(price=50_000.5, commission=0.05, coin="USD", quantity=0.00199, filled_quantity=None, role="TAKER") -> Order:
    fq = quantity if filled_quantity is None else filled_quantity
    return Order("BTC/USD", 7, "FILLED", role, "BUY", "LIMIT", 50_000.5, quantity, fq, price, coin, commission, 1, 2)


def observation(order: Order, **overrides) -> Observation:
    base = Observation("BTC/USD", bid=49_999.5, ask=50_000.5, limit_price=50_000.5, quantity=0.00199, placed=order,
                       queried=order, cancelled=False, pending_after=0, locked_after={})
    return replace(base, **overrides)


def test_filled_at_once_at_the_limit_rate_with_nothing_left_behind_is_the_only_adopt():
    adopt, lines = verdict(observation(filled()))                     # 0.05 on 99.50 is 5.0bp
    assert adopt and all(line.startswith("PASS") for line in lines)


def test_the_role_label_does_not_decide_it_the_commission_charged_does():
    assert verdict(observation(filled(role="MAKER", commission=0.10)))[0] is False
    assert verdict(observation(filled(role="TAKER", commission=0.05)))[0] is True


def test_a_fill_at_the_market_rate_keeps_market_orders():
    adopt, lines = verdict(observation(filled(commission=0.10)))      # 10bp: the discount needs a resting order
    assert not adopt and lines[2].startswith("FAIL") and "0.1005%" in lines[2]


def test_a_commission_charged_in_the_coin_is_measured_against_the_coin_bought():
    assert verdict(observation(filled(commission=0.00199 * 0.0005, coin="BTC")))[0] is True
    assert verdict(observation(filled(commission=0.00199 * 0.0010, coin="BTC")))[0] is False


def test_a_fill_above_the_limit_price_a_partial_fill_or_a_locked_balance_each_fail_the_rule():
    assert verdict(observation(filled(price=50_010.0)))[0] is False
    assert verdict(observation(filled(filled_quantity=0.001)))[0] is False
    assert verdict(observation(filled(), locked_after={"USD": 99.5}))[0] is False
    assert verdict(observation(filled(), pending_after=1))[0] is False
