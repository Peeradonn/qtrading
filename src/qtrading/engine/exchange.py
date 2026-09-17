"""One Exchange interface, two implementations the engine cannot tell apart.

PaperExchange fills market orders at the live price feed, charges the real fee, and keeps its wallet in a JSON
file — a keyless dry run on real prices. RoostooExchange adapts the API client.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..execution import floor_to
from ..roostoo.models import PairInfo


class InsufficientFunds(Exception):
    """The paper wallet cannot cover the order."""


@dataclass(frozen=True)
class Fill:
    pair: str
    side: str
    quantity: float
    price: float
    notional: float
    fee: float
    order_id: int
    status: str


class Exchange(Protocol):
    def balances(self) -> dict[str, float]: ...          # asset -> free quantity (USD included)
    def prices(self) -> dict[str, float]: ...            # pair -> last price
    def rules(self) -> dict[str, PairInfo]: ...
    def place_market(self, pair: str, side: str, quantity: float) -> Fill: ...
    def pending_orders(self) -> list: ...
    def cancel_all(self) -> list[int]: ...


class PaperExchange:
    def __init__(self, price_feed, rules: dict[str, PairInfo], wallet_path, fee_rate: float = 0.001,
                 initial_usd: float = 1_000_000.0, allow_short: bool = False):
        self._feed = price_feed
        self._allow_short = allow_short          # a sell beyond the holding leaves a negative balance: a short
        self._rules = rules
        self._path = Path(wallet_path)
        self._fee = fee_rate
        if self._path.exists():
            self._wallet = json.loads(self._path.read_text(encoding="utf-8"))
        else:
            self._wallet = {"USD": float(initial_usd), "_next_order_id": 1}
            self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._wallet, indent=1), encoding="utf-8")

    def balances(self) -> dict[str, float]:
        return {k: float(v) for k, v in self._wallet.items() if not k.startswith("_")}

    def prices(self) -> dict[str, float]:
        return dict(self._feed())

    def rules(self) -> dict[str, PairInfo]:
        return dict(self._rules)

    def place_market(self, pair: str, side: str, quantity: float) -> Fill:
        price = self.prices()[pair]
        coin = pair.split("/")[0]
        notional = quantity * price
        fee = notional * self._fee
        if side == "BUY":
            if self._wallet.get("USD", 0.0) < notional + fee:
                raise InsufficientFunds(f"need {notional + fee:.2f} USD, have {self._wallet.get('USD', 0.0):.2f}")
            self._wallet["USD"] -= notional + fee
            self._wallet[coin] = self._wallet.get(coin, 0.0) + quantity
        elif side == "SELL":
            if not self._allow_short and self._wallet.get(coin, 0.0) + 1e-12 < quantity:
                raise InsufficientFunds(f"need {quantity} {coin}, have {self._wallet.get(coin, 0.0)}")
            self._wallet[coin] = self._wallet.get(coin, 0.0) - quantity
            if abs(self._wallet[coin]) < 1e-12:
                self._wallet[coin] = 0.0
            self._wallet["USD"] += notional - fee
        else:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        order_id = int(self._wallet["_next_order_id"])
        self._wallet["_next_order_id"] = order_id + 1
        self._save()
        return Fill(pair, side, quantity, price, notional, fee, order_id, "FILLED")

    def pending_orders(self) -> list:
        return []

    def cancel_all(self) -> list[int]:
        return []


class RoostooExchange:
    def __init__(self, client):
        self._client = client
        self._rules: dict[str, PairInfo] | None = None

    def rules(self) -> dict[str, PairInfo]:
        if self._rules is None:
            self._rules = self._client.exchange_info()
        return self._rules

    def balances(self) -> dict[str, float]:
        return {asset: float(b.free) for asset, b in self._client.balance().items()}

    def prices(self) -> dict[str, float]:
        return {pair: float(t.last) for pair, t in self._client.ticker().items()}

    def place_market(self, pair: str, side: str, quantity: float) -> Fill:
        precision = self.rules()[pair].amount_precision
        qty_str = f"{floor_to(quantity, precision):.{precision}f}"          # never scientific notation on the wire
        order = self._client.place_order(pair, side, "MARKET", qty_str)
        return Fill(pair, side, order.filled_quantity, order.filled_avg_price,
                    order.filled_quantity * order.filled_avg_price, order.commission, order.order_id, order.status)

    def pending_orders(self) -> list:
        return self._client.query_order(pending_only=True)

    def cancel_all(self) -> list[int]:
        return self._client.cancel_order()
