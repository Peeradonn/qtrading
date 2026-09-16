"""A local stand-in for the Roostoo exchange, faithful to the published API documents.

Why it exists: no test API key is available before the competition, so without this the signed order path would
first run against the real exchange on the day it matters. This server enforces the documented contract —
`RST-API-KEY` and `MSG-SIGNATURE` headers, HMAC-SHA256 over the exact bytes the client sent, the +/-60s
timestamp window, the response shapes and the `Success: false` envelopes — so pointing ROOSTOO_BASE_URL at it
exercises the real client, the real exchange adapter and the real engine.

It is a test double, not a simulator of market microstructure: market orders fill at the current price and
limit orders simply rest. Faults can be injected (`fail_next`, `drop_next`, `clock_skew_ms`) to rehearse the
failures the engine must survive.
"""
import hashlib
import hmac
import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl

TIMESTAMP_WINDOW_MS = 60_000
PUBLIC = {"/v3/serverTime", "/v3/exchangeInfo"}
TIMESTAMP_ONLY = {"/v3/ticker"}


class DropConnection(Exception):
    """Injected fault: answer nothing at all, as a lost response would."""


class MockRoostoo:
    def __init__(self, api_key: str, secret_key: str, pairs: dict, prices: dict, wallet: dict | None = None,
                 fee_rate: float = 0.001):
        self.api_key = api_key
        self.secret_key = secret_key
        self.pairs = pairs
        self.prices = prices
        self.wallet = dict(wallet or {"USD": 1_000_000.0})
        self.fee_rate = fee_rate
        self.orders: list[dict] = []
        self.requests: list[tuple[str, str]] = []          # (path, raw params) — what the client actually sent
        self._next_id = 1
        # injectable faults; set fault_path to restrict them to one endpoint
        self.fail_next = 0                                 # answer this many requests with HTTP 500
        self.drop_next = 0                                 # drop this many responses entirely
        self.fault_path: str | None = None
        self.clock_skew_ms = 0                             # pretend the server clock is this far ahead

    # ---- helpers ------------------------------------------------------------

    def now_ms(self) -> int:
        return int(time.time() * 1000) + self.clock_skew_ms

    def _sign(self, total_params: str) -> str:
        return hmac.new(self.secret_key.encode(), total_params.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _floor(x: float, precision: int) -> float:
        f = 10 ** precision
        return math.floor(x * f + 1e-9) / f

    def _ok(self, **fields) -> dict:
        return {"Success": True, "ErrMsg": "", **fields}

    def _fail(self, message: str, **fields) -> dict:
        return {"Success": False, "ErrMsg": message, **fields}

    # ---- request handling ---------------------------------------------------

    def handle(self, path: str, raw_params: str, headers: dict) -> dict:
        """Returns the JSON body to send. Raises DropConnection or RuntimeError for injected faults."""
        self.requests.append((path, raw_params))
        faulty = self.fault_path is None or self.fault_path == path
        if faulty and self.drop_next > 0:
            self.drop_next -= 1
            self._dispatch(path, dict(parse_qsl(raw_params)))     # the work still happens; the answer is lost
            raise DropConnection(path)
        if faulty and self.fail_next > 0:
            self.fail_next -= 1
            raise RuntimeError("injected server error")

        params = dict(parse_qsl(raw_params))
        if path not in PUBLIC:
            error = self._check_auth(path, raw_params, params, headers)
            if error:
                return error
        return self._dispatch(path, params)

    def _check_auth(self, path: str, raw_params: str, params: dict, headers: dict) -> dict | None:
        timestamp = params.get("timestamp")
        if timestamp is None:
            return self._fail("timestamp is mandatory")
        try:
            skew = abs(self.now_ms() - int(timestamp))
        except ValueError:
            return self._fail("timestamp must be a 13-digit millisecond value")
        if skew > TIMESTAMP_WINDOW_MS:
            return self._fail(f"timestamp outside the {TIMESTAMP_WINDOW_MS} ms window")
        if path in TIMESTAMP_ONLY:
            return None
        if headers.get("RST-API-KEY") != self.api_key:
            return self._fail("invalid api key")
        if not hmac.compare_digest(headers.get("MSG-SIGNATURE", ""), self._sign(raw_params)):
            return self._fail("invalid signature")
        return None

    def _dispatch(self, path: str, params: dict) -> dict:
        if path == "/v3/serverTime":
            return {"ServerTime": self.now_ms()}
        if path == "/v3/exchangeInfo":
            return {"IsRunning": True, "InitialWallet": {"USD": 1_000_000}, "TradePairs": self.pairs}
        if path == "/v3/ticker":
            return self._ok(ServerTime=self.now_ms(), Data=self._ticker(params.get("pair")))
        if path == "/v3/balance":
            return self._ok(Wallet={a: {"Free": q, "Lock": 0} for a, q in self.wallet.items()})
        if path == "/v3/pending_count":
            return self._pending_count()
        if path == "/v3/place_order":
            return self._place_order(params)
        if path == "/v3/query_order":
            return self._query_order(params)
        if path == "/v3/cancel_order":
            return self._cancel_order(params)
        return self._fail(f"unknown endpoint {path}")

    # ---- endpoints ----------------------------------------------------------

    def _ticker(self, pair: str | None) -> dict:
        wanted = [pair] if pair else list(self.prices)
        data = {}
        for p in wanted:
            price = self.prices.get(p)
            if price is None:
                continue
            data[p] = {"MaxBid": round(price * 0.99999, 8), "MinAsk": round(price * 1.00001, 8), "LastPrice": price,
                       "Change": 0.0, "CoinTradeValue": 1000.0, "UnitTradeValue": 1000.0 * price}
        return data

    def _pending_count(self) -> dict:
        pending = [o for o in self.orders if o["Status"] == "PENDING"]
        if not pending:
            return self._fail("no pending order under this account", TotalPending=0, OrderPairs={})
        pairs: dict[str, int] = {}
        for o in pending:
            pairs[o["Pair"]] = pairs.get(o["Pair"], 0) + 1
        return self._ok(TotalPending=len(pending), OrderPairs=pairs)

    def _place_order(self, params: dict) -> dict:
        pair, side, order_type = params.get("pair"), params.get("side"), params.get("type")
        if pair not in self.pairs:
            return self._fail(f"pair {pair} is not listed")
        if side not in ("BUY", "SELL"):
            return self._fail("side must be BUY or SELL")
        if order_type not in ("MARKET", "LIMIT"):
            return self._fail("type must be MARKET or LIMIT")
        try:
            quantity = float(params["quantity"])
        except (KeyError, ValueError):
            return self._fail("quantity is mandatory and must be numeric")

        rules = self.pairs[pair]
        coin = rules["Coin"]
        if quantity != self._floor(quantity, rules["AmountPrecision"]):
            return self._fail(f"quantity exceeds AmountPrecision {rules['AmountPrecision']}")

        price = float(params["price"]) if order_type == "LIMIT" else self.prices[pair]
        if order_type == "LIMIT" and price != round(price, rules["PricePrecision"]):
            return self._fail(f"price exceeds PricePrecision {rules['PricePrecision']}")
        notional = quantity * price
        if notional < rules["MiniOrder"]:
            return self._fail(f"order value {notional} is below MiniOrder {rules['MiniOrder']}")

        order_id, self._next_id = self._next_id, self._next_id + 1
        now = self.now_ms()
        order = {"Pair": pair, "OrderID": order_id, "Status": "PENDING", "Role": "MAKER", "ServerTimeUsage": 0.04,
                 "CreateTimestamp": now, "FinishTimestamp": 0, "Side": side, "Type": order_type, "StopType": "GTC",
                 "Price": price, "Quantity": quantity, "FilledQuantity": 0, "FilledAverPrice": 0, "CoinChange": 0,
                 "UnitChange": 0, "CommissionCoin": "USD", "CommissionChargeValue": 0, "CommissionPercent": self.fee_rate}

        if order_type == "MARKET":
            fee = notional * self.fee_rate
            if side == "BUY":
                if self.wallet.get("USD", 0.0) < notional + fee:
                    return self._fail("insufficient balance")
                self.wallet["USD"] = self.wallet.get("USD", 0.0) - notional - fee
                self.wallet[coin] = self.wallet.get(coin, 0.0) + quantity
            else:
                if self.wallet.get(coin, 0.0) + 1e-12 < quantity:
                    return self._fail(f"insufficient {coin} balance")
                self.wallet[coin] = self.wallet.get(coin, 0.0) - quantity
                self.wallet["USD"] = self.wallet.get("USD", 0.0) + notional - fee
            order.update(Status="FILLED", Role="TAKER", FinishTimestamp=now, FilledQuantity=quantity,
                         FilledAverPrice=price, CoinChange=quantity, UnitChange=notional,
                         CommissionChargeValue=fee)

        self.orders.append(order)
        return self._ok(OrderDetail=order)

    def _query_order(self, params: dict) -> dict:
        if "order_id" in params:
            matched = [o for o in self.orders if str(o["OrderID"]) == str(params["order_id"])]
        else:
            matched = list(self.orders)
            if "pair" in params:
                matched = [o for o in matched if o["Pair"] == params["pair"]]
            if params.get("pending_only", "FALSE").upper() == "TRUE":
                matched = [o for o in matched if o["Status"] == "PENDING"]
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", 100))
            matched = matched[offset:offset + limit]
        if not matched:
            return self._fail("no order matched")
        return self._ok(OrderMatched=matched)

    def _cancel_order(self, params: dict) -> dict:
        pending = [o for o in self.orders if o["Status"] == "PENDING"]
        if "order_id" in params:
            targets = [o for o in pending if str(o["OrderID"]) == str(params["order_id"])]
        elif "pair" in params:
            targets = [o for o in pending if o["Pair"] == params["pair"]]
        else:
            targets = pending
        for o in targets:
            o["Status"] = "CANCELED"
            o["FinishTimestamp"] = self.now_ms()
        return self._ok(CanceledList=[o["OrderID"] for o in targets])


def serve(exchange: MockRoostoo, port: int = 8787, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Return an unstarted server; call serve_forever() on it (usually in a thread)."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, fmt, *args):                 # quiet by default; the exchange records requests
            pass

        def _respond(self, path: str, raw_params: str) -> None:
            headers = {k: v for k, v in self.headers.items()}
            try:
                body = exchange.handle(path, raw_params, headers)
            except DropConnection:
                self.close_connection = True               # answer nothing, as a lost response would
                return
            except Exception as e:
                self.send_error(500, str(e))
                return
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path, _, query = self.path.partition("?")
            self._respond(path, query)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode()
            self._respond(self.path.partition("?")[0], raw)

    return ThreadingHTTPServer((host, port), Handler)
