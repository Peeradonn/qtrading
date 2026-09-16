"""A local stand-in for the Roostoo API, and the end-to-end check of our client against it.

No test key is available for the real exchange, so the signed order path would otherwise never touch an HTTP
server before the competition. These tests run the real RoostooClient over a real socket against a server that
enforces the documented contract: header names, HMAC over the exact bytes sent, the timestamp window, and the
documented response and error envelopes.
"""
import threading

import pytest

from qtrading.roostoo.client import RoostooClient
from qtrading.roostoo.errors import OrderUncertain, RoostooAPIError
from qtrading.roostoo.mock_server import MockRoostoo, serve

API_KEY = "TESTKEY"
SECRET = "TESTSECRET"  # pragma: allowlist secret
RULES = {
    "BTC/USD": {"Coin": "BTC", "CoinFullName": "Bitcoin", "Unit": "USD", "UnitFullName": "US Dollar",
                "CanTrade": True, "PricePrecision": 2, "AmountPrecision": 5, "MiniOrder": 1, "AssetType": "crypto"},
    "ETH/USD": {"Coin": "ETH", "CoinFullName": "Ethereum", "Unit": "USD", "UnitFullName": "US Dollar",
                "CanTrade": True, "PricePrecision": 2, "AmountPrecision": 4, "MiniOrder": 1, "AssetType": "crypto"},
}
PRICES = {"BTC/USD": 50_000.0, "ETH/USD": 3_000.0}


@pytest.fixture
def exchange():
    return MockRoostoo(api_key=API_KEY, secret_key=SECRET, pairs=RULES, prices=dict(PRICES),
                       wallet={"USD": 1_000_000.0}, fee_rate=0.001)


@pytest.fixture
def client(exchange):
    """A real RoostooClient talking to the mock over a real socket."""
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


# --- the contract our client must satisfy on the wire ---------------------------

def test_public_endpoints_need_no_signature(client):
    assert client.server_time() > 1_700_000_000_000
    assert client.exchange_info()["BTC/USD"].amount_precision == 5
    assert client.ticker()["BTC/USD"].last == 50_000.0


def test_signed_read_round_trips(client):
    assert client.balance()["USD"].free == 1_000_000.0


def test_market_buy_fills_and_moves_the_wallet(client, exchange):
    order = client.place_order(pair="BTC/USD", side="BUY", order_type="MARKET", quantity="0.5")
    assert (order.status, order.role, order.filled_quantity, order.filled_avg_price) == ("FILLED", "TAKER", 0.5, 50_000.0)
    assert order.commission == pytest.approx(25.0)
    assert exchange.wallet["USD"] == pytest.approx(1_000_000 - 25_000 - 25)
    assert exchange.wallet["BTC"] == pytest.approx(0.5)


def test_market_sell_returns_proceeds_net_of_fee(client, exchange):
    client.place_order(pair="BTC/USD", side="BUY", order_type="MARKET", quantity="0.5")
    client.place_order(pair="BTC/USD", side="SELL", order_type="MARKET", quantity="0.5")
    assert exchange.wallet["BTC"] == pytest.approx(0.0)
    assert exchange.wallet["USD"] == pytest.approx(1_000_000 - 25 - 25)


def test_a_limit_order_rests_and_can_be_queried_and_cancelled(client):
    order = client.place_order(pair="BTC/USD", side="BUY", order_type="LIMIT", quantity="0.1", price="40000")
    assert (order.status, order.role) == ("PENDING", "MAKER")
    assert client.pending_count() == (1, {"BTC/USD": 1})
    assert [o.order_id for o in client.query_order(pending_only=True)] == [order.order_id]
    assert client.cancel_order(order_id=order.order_id) == [order.order_id]
    assert client.pending_count() == (0, {})


def test_documented_empty_envelopes_are_not_errors(client):
    assert client.pending_count() == (0, {})
    assert client.query_order(pair="BTC/USD") == []


def test_insufficient_balance_is_reported_as_a_failure(client):
    with pytest.raises(RoostooAPIError, match="insufficient"):
        client.place_order(pair="BTC/USD", side="BUY", order_type="MARKET", quantity="100")


def test_an_order_below_the_pair_minimum_is_rejected(client):
    with pytest.raises(RoostooAPIError, match="MiniOrder|minimum"):
        client.place_order(pair="BTC/USD", side="BUY", order_type="MARKET", quantity="0.0000100")


def test_an_unknown_pair_is_rejected(client):
    with pytest.raises(RoostooAPIError, match="pair"):
        client.place_order(pair="NOPE/USD", side="BUY", order_type="MARKET", quantity="1")


# --- the failures the engine must survive ---------------------------------------

def test_a_wrong_signature_is_rejected(exchange):
    server = serve(exchange, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        wrong = RoostooClient(API_KEY, "WRONGSECRET", base_url=f"http://127.0.0.1:{port}", min_interval_s=0.0)
        with pytest.raises(RoostooAPIError, match="signature"):
            wrong.balance()
    finally:
        server.shutdown()
        server.server_close()


class DriftedClock:
    """A client clock that has drifted two minutes from the server's."""

    def now_ms(self):
        import time
        return int(time.time() * 1000) + 120_000

    def invalidate(self):
        pass


def test_a_client_whose_clock_has_drifted_is_rejected(client):
    client._clock = DriftedClock()
    with pytest.raises(RoostooAPIError, match="timestamp"):
        client.balance()


def test_a_dropped_response_to_place_order_raises_order_uncertain(client, exchange):
    client.server_time()                                  # let the clock sync before faults are armed
    exchange.fault_path, exchange.drop_next = "/v3/place_order", 1
    with pytest.raises(OrderUncertain):
        client.place_order(pair="BTC/USD", side="BUY", order_type="MARKET", quantity="0.1")


def test_a_dropped_order_may_still_have_executed_and_is_visible_to_reconciliation(client, exchange):
    """The reason place_order never retries: the order can exist even though the client saw no response."""
    client.server_time()
    exchange.fault_path, exchange.drop_next = "/v3/place_order", 1
    with pytest.raises(OrderUncertain):
        client.place_order(pair="BTC/USD", side="BUY", order_type="MARKET", quantity="0.1")
    assert [o.filled_quantity for o in client.query_order(pair="BTC/USD")] == [0.1]


def test_transient_server_errors_are_retried_on_reads(client, exchange):
    client.server_time()
    exchange.fault_path, exchange.fail_next = "/v3/balance", 2
    assert client.balance()["USD"].free == 1_000_000.0    # two 500s, then success
    assert exchange.fail_next == 0
