"""Roostoo REST client.

Design rules:
- What is signed is what is sent: the canonical param string goes on the wire verbatim
  (GET query / POST body), never re-encoded.
- Timestamps come from a server-synchronised Clock, never the bare local clock.
- Reads retry transient failures; place_order never does — a lost response raises
  OrderUncertain so the caller reconciles instead of double-ordering.
- Every signed request/response is logged at INFO (trade-log evidence); public ones at DEBUG.
"""
import logging
import time
from typing import Protocol

import requests

from .clock import Clock
from .errors import OrderUncertain, RoostooAPIError, RoostooNetworkError
from .models import Balance, Order, PairInfo, Ticker
from .signing import canonical_query, sign

log = logging.getLogger("qtrading.roostoo")

DEFAULT_BASE_URL = "https://mock-api.roostoo.com"
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"


class Transport(Protocol):
    def send(self, method: str, url: str, headers: dict, query: str | None, body: str | None) -> dict: ...


class RequestsTransport:
    """HTTP via requests. Raises RoostooNetworkError for anything where no JSON answer was obtained."""

    def __init__(self, timeout_s: float = 10.0, session: requests.Session | None = None):
        self._timeout = timeout_s
        self._session = session or requests.Session()

    def send(self, method, url, headers, query, body):
        full_url = f"{url}?{query}" if query else url
        try:
            resp = self._session.request(method, full_url, headers=headers, data=body, timeout=self._timeout)
        except requests.RequestException as e:
            raise RoostooNetworkError(str(e)) from e
        if resp.status_code >= 500:
            raise RoostooNetworkError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as e:
            raise RoostooAPIError(f"non-JSON response (HTTP {resp.status_code}): {resp.text[:200]}") from e


class RoostooClient:
    def __init__(self, api_key: str, secret_key: str, base_url: str = DEFAULT_BASE_URL, transport: Transport | None = None,
                 clock: Clock | None = None, min_interval_s: float = 2.0, max_retries: int = 3,
                 backoff_s: float = 0.5, sleep=time.sleep, monotonic=time.monotonic):
        self._key = api_key
        self._secret = secret_key
        self._base = base_url.rstrip("/")
        self._transport = transport or RequestsTransport()
        self._clock = clock or Clock(fetch_server_ms=self.server_time)
        self._min_interval = min_interval_s
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._sleep = sleep
        self._mono = monotonic
        self._last_sent: float | None = None

    # ---- public endpoints -------------------------------------------------

    def server_time(self) -> int:
        return int(self._request("GET", "/v3/serverTime", {}, auth="none", retry=True)["ServerTime"])

    def exchange_info(self) -> dict[str, PairInfo]:
        payload = self._request("GET", "/v3/exchangeInfo", {}, auth="none", retry=True)
        return {p: PairInfo.from_payload(p, d) for p, d in payload["TradePairs"].items()}

    def ticker(self, pair: str | None = None) -> dict[str, Ticker]:
        payload = self._request("GET", "/v3/ticker", {"pair": pair}, auth="timestamp", retry=True)
        return {p: Ticker.from_payload(p, d) for p, d in payload["Data"].items()}

    # ---- signed endpoints -------------------------------------------------

    def balance(self) -> dict[str, Balance]:
        payload = self._request("GET", "/v3/balance", {}, auth="signed", retry=True)
        return {asset: Balance(float(b["Free"]), float(b["Lock"])) for asset, b in payload["Wallet"].items()}

    def pending_count(self) -> tuple[int, dict[str, int]]:
        payload = self._request("GET", "/v3/pending_count", {}, auth="signed", retry=True,
                                empty_ok={"no pending order under this account"})
        return int(payload.get("TotalPending", 0)), dict(payload.get("OrderPairs") or {})

    def place_order(self, pair: str, side: str, order_type: str, quantity, price=None) -> Order:
        params = {"pair": pair, "side": side, "type": order_type, "quantity": str(quantity),
                  "price": None if price is None else str(price)}
        payload = self._request("POST", "/v3/place_order", params, auth="signed", retry=False)
        return Order.from_payload(payload["OrderDetail"])

    def query_order(self, order_id=None, pair: str | None = None, pending_only: bool | None = None,
                    offset: int | None = None, limit: int | None = None) -> list[Order]:
        if order_id is not None and any(v is not None for v in (pair, pending_only, offset, limit)):
            raise ValueError("order_id cannot be combined with other filters")
        params = {"order_id": order_id, "pair": pair, "offset": offset, "limit": limit,
                  "pending_only": None if pending_only is None else ("TRUE" if pending_only else "FALSE")}
        payload = self._request("POST", "/v3/query_order", params, auth="signed", retry=True,
                                empty_ok={"no order matched"})
        return [Order.from_payload(o) for o in payload.get("OrderMatched", [])]

    def cancel_order(self, order_id=None, pair: str | None = None) -> list[int]:
        """Cancel one order, all pending orders on a pair, or (no args) every pending order."""
        if order_id is not None and pair is not None:
            raise ValueError("specify at most one of order_id, pair")
        payload = self._request("POST", "/v3/cancel_order", {"order_id": order_id, "pair": pair},
                                auth="signed", retry=True)
        return [int(x) for x in payload.get("CanceledList", [])]

    # ---- core -------------------------------------------------------------

    def _request(self, method: str, path: str, params: dict, auth: str, retry: bool, empty_ok=frozenset()) -> dict:
        params = dict(params)
        if auth != "none":
            params["timestamp"] = self._clock.now_ms()
        total = canonical_query(params)

        headers = {}
        if auth == "signed":
            headers["RST-API-KEY"] = self._key
            headers["MSG-SIGNATURE"] = sign(self._secret, total)
        if method == "POST":
            headers["Content-Type"] = FORM_CONTENT_TYPE
            query, body = None, total
        else:
            query, body = (total or None), None

        url = self._base + path
        level = logging.INFO if auth == "signed" else logging.DEBUG
        attempts = self._max_retries if retry else 1
        for attempt in range(1, attempts + 1):
            self._throttle()
            log.log(level, "-> %s %s %s", method, path, total)
            try:
                payload = self._transport.send(method, url, headers, query, body)
            except RoostooNetworkError as e:
                log.warning("!! %s %s attempt %d/%d failed: %s", method, path, attempt, attempts, e)
                if not retry:
                    raise OrderUncertain(f"{method} {path} sent but no response: {e}") from e
                if attempt == attempts:
                    raise
                self._sleep(self._backoff_s * 2 ** (attempt - 1))
                continue
            log.log(level, "<- %s %s %s", method, path, payload)
            return self._check(payload, empty_ok)
        raise AssertionError("unreachable")

    @staticmethod
    def _check(payload: dict, empty_ok) -> dict:
        if payload.get("Success", True) is False:
            msg = payload.get("ErrMsg", "")
            if msg in empty_ok:
                return payload
            raise RoostooAPIError(msg or "request failed", payload)
        return payload

    def _throttle(self) -> None:
        if self._last_sent is not None:
            wait = self._min_interval - (self._mono() - self._last_sent)
            if wait > 0:
                self._sleep(wait)
        self._last_sent = self._mono()
