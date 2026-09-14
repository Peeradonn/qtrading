"""RoostooClient against a fake transport. Fixtures mirror the API docs' responses completely."""
import hashlib
import hmac
from types import SimpleNamespace

import pytest

from qtrading.roostoo.client import RoostooClient
from qtrading.roostoo.errors import OrderUncertain, RoostooAPIError, RoostooNetworkError

API_KEY = "USEAPIKEYASMYID"
SECRET = "S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep"
NOW_MS = 1580774512000

# --- response fixtures, verbatim from roostoo/Roostoo-API-Documents (exchangeInfo from the live endpoint) ---

SERVER_TIME = {"ServerTime": 1570083944052}

EXCHANGE_INFO = {
    "IsRunning": True,
    "InitialWallet": {"USD": 50000},
    "TradePairs": {
        "BTC/USD": {"Coin": "BTC", "CoinFullName": "Bitcoin", "Unit": "USD", "UnitFullName": "US Dollar",
                    "CanTrade": True, "PricePrecision": 2, "AmountPrecision": 5, "MiniOrder": 1, "AssetType": "crypto"},
    },
}

TICKER_EOS = {
    "Success": True, "ErrMsg": "", "ServerTime": 1580762734517,
    "Data": {"EOS/USD": {"MaxBid": 4.2139, "MinAsk": 4.2149, "LastPrice": 4.2137, "Change": -0.0112,
                         "CoinTradeValue": 8493899.21, "UnitTradeValue": 36057856.188109}},
}

BALANCE = {
    "Success": True, "ErrMsg": "",
    "Wallet": {"BTC": {"Free": 0.454878, "Lock": 0.555}, "ETH": {"Free": 0, "Lock": 0},
               "USD": {"Free": 98389854.152001, "Lock": 1601798.197999}},
}

NO_PENDING = {"Success": False, "ErrMsg": "no pending order under this account", "TotalPending": 0, "OrderPairs": {}}
NO_ORDER_MATCHED = {"Success": False, "ErrMsg": "no order matched"}

ORDER_FILLED = {
    "Success": True, "ErrMsg": "",
    "OrderDetail": {"Pair": "BTC/USD", "OrderID": 81, "Status": "FILLED", "Role": "TAKER", "ServerTimeUsage": 0.039723,
                    "CreateTimestamp": 1570224271550, "FinishTimestamp": 1570224271590, "Side": "SELL", "Type": "MARKET",
                    "StopType": "GTC", "Price": 8149.07, "Quantity": 11.112, "FilledQuantity": 11.112,
                    "FilledAverPrice": 8149.07, "CoinChange": 11.112, "UnitChange": 90552.46584, "CommissionCoin": "USD",
                    "CommissionChargeValue": 10.8662959008, "CommissionPercent": 0.00012},
}

CANCELED = {"Success": True, "ErrMsg": "", "CanceledList": [20, 35]}


# --- test doubles ---

class FakeEnv:
    """Fake monotonic clock; sleeping advances it."""
    def __init__(self):
        self.mono_s = 0.0

    def mono(self):
        return self.mono_s

    def sleep(self, s):
        self.mono_s += s


class FixedClock:
    def now_ms(self):
        return NOW_MS

    def invalidate(self):
        pass


class FakeTransport:
    """Replays scripted responses (dicts) or raises scripted exceptions; records every request."""
    def __init__(self, responses, env):
        self.responses = list(responses)
        self.env = env
        self.calls = []

    def send(self, method, url, headers, query, body):
        self.calls.append(SimpleNamespace(method=method, url=url, headers=headers, query=query, body=body, at=self.env.mono()))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make(responses, env=None, **kw):
    env = env or FakeEnv()
    transport = FakeTransport(responses, env)
    client = RoostooClient(API_KEY, SECRET, transport=transport, clock=FixedClock(),
                           sleep=env.sleep, monotonic=env.mono, **kw)
    return client, transport


# --- signing & wire format ---

def test_signed_get_signs_exactly_the_query_string_it_sends():
    client, t = make([BALANCE])
    client.balance()
    req = t.calls[0]
    assert req.method == "GET"
    assert req.url.endswith("/v3/balance")
    assert req.query == f"timestamp={NOW_MS}"
    assert req.headers["RST-API-KEY"] == API_KEY
    expected_sig = hmac.new(SECRET.encode(), req.query.encode(), hashlib.sha256).hexdigest()
    assert req.headers["MSG-SIGNATURE"] == expected_sig


@pytest.mark.parametrize("kwargs, body", [
    (dict(pair="BTC/USD", side="BUY", order_type="MARKET", quantity="0.1"),
     f"pair=BTC/USD&quantity=0.1&side=BUY&timestamp={NOW_MS}&type=MARKET"),
    (dict(pair="BTC/USD", side="BUY", order_type="LIMIT", quantity="0.1", price="50000"),
     f"pair=BTC/USD&price=50000&quantity=0.1&side=BUY&timestamp={NOW_MS}&type=LIMIT"),
])
def test_post_body_is_the_canonical_string_verbatim(kwargs, body):
    client, t = make([ORDER_FILLED])
    client.place_order(**kwargs)
    req = t.calls[0]
    assert req.method == "POST"
    assert req.body == body
    assert req.query is None
    assert req.headers["Content-Type"] == "application/x-www-form-urlencoded"
    expected_sig = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    assert req.headers["MSG-SIGNATURE"] == expected_sig


def test_ticker_sends_timestamp_only_and_no_signature():
    client, t = make([TICKER_EOS])
    client.ticker("EOS/USD")
    req = t.calls[0]
    assert req.query == f"pair=EOS/USD&timestamp={NOW_MS}"
    assert "MSG-SIGNATURE" not in req.headers


# --- response parsing ---

def test_server_time_returns_int_ms():
    client, _ = make([SERVER_TIME])
    assert client.server_time() == 1570083944052


def test_exchange_info_parses_pair_rules():
    client, _ = make([EXCHANGE_INFO])
    info = client.exchange_info()
    btc = info["BTC/USD"]
    assert (btc.coin, btc.unit, btc.can_trade) == ("BTC", "USD", True)
    assert (btc.price_precision, btc.amount_precision, btc.min_order) == (2, 5, 1)
    assert btc.asset_type == "crypto"


def test_ticker_parses_quotes():
    client, _ = make([TICKER_EOS])
    q = client.ticker("EOS/USD")["EOS/USD"]
    assert (q.bid, q.ask, q.last) == (4.2139, 4.2149, 4.2137)
    assert q.change_24h == -0.0112
    assert q.unit_volume_24h == 36057856.188109


def test_balance_parses_wallet():
    client, _ = make([BALANCE])
    wallet = client.balance()
    assert wallet["USD"].free == 98389854.152001
    assert wallet["USD"].lock == 1601798.197999
    assert wallet["ETH"].free == 0


def test_place_order_parses_order_detail():
    client, _ = make([ORDER_FILLED])
    o = client.place_order(pair="BTC/USD", side="SELL", order_type="MARKET", quantity="11.112")
    assert (o.order_id, o.status, o.role) == (81, "FILLED", "TAKER")
    assert (o.filled_quantity, o.filled_avg_price) == (11.112, 8149.07)
    assert (o.commission_coin, o.commission) == ("USD", 10.8662959008)


def test_cancel_order_returns_canceled_ids():
    client, _ = make([CANCELED])
    assert client.cancel_order(pair="BTC/USD") == [20, 35]


# --- envelope handling ---

def test_api_failure_raises_with_server_message():
    client, _ = make([{"Success": False, "ErrMsg": "insufficient balance"}])
    with pytest.raises(RoostooAPIError, match="insufficient balance"):
        client.place_order(pair="BTC/USD", side="BUY", order_type="MARKET", quantity="1")


def test_no_pending_orders_is_an_empty_result_not_an_error():
    client, _ = make([NO_PENDING])
    assert client.pending_count() == (0, {})


def test_no_order_matched_is_an_empty_list_not_an_error():
    client, _ = make([NO_ORDER_MATCHED])
    assert client.query_order(pair="BTC/USD") == []


# --- retry policy ---

def test_read_call_retries_network_errors_then_succeeds():
    client, t = make([RoostooNetworkError("boom"), RoostooNetworkError("boom"), TICKER_EOS], max_retries=3)
    assert "EOS/USD" in client.ticker()
    assert len(t.calls) == 3


def test_read_call_gives_up_after_max_retries():
    client, t = make([RoostooNetworkError("boom")] * 3, max_retries=3)
    with pytest.raises(RoostooNetworkError):
        client.ticker()
    assert len(t.calls) == 3


def test_place_order_never_retries_and_reports_uncertainty():
    client, t = make([RoostooNetworkError("timeout"), ORDER_FILLED], max_retries=3)
    with pytest.raises(OrderUncertain):
        client.place_order(pair="BTC/USD", side="BUY", order_type="MARKET", quantity="1")
    assert len(t.calls) == 1


# --- throttle ---

def test_consecutive_requests_are_spaced_by_min_interval():
    env = FakeEnv()
    client, t = make([TICKER_EOS, TICKER_EOS], env=env, min_interval_s=0.25)
    client.ticker()
    client.ticker()
    assert t.calls[1].at - t.calls[0].at >= 0.25


# --- audit log ---

def test_every_request_and_response_is_logged(caplog):
    client, _ = make([ORDER_FILLED])
    with caplog.at_level("INFO", logger="qtrading.roostoo"):
        client.place_order(pair="BTC/USD", side="SELL", order_type="MARKET", quantity="11.112")
    assert "/v3/place_order" in caplog.text
    assert "FILLED" in caplog.text
    assert SECRET not in caplog.text
