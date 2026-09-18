"""PRE-REGISTERED CHECK (2026-09-18): is a limit order at the touch a market order at half the fee?

The question. The rules charge 0.05% on a limit order and 0.1% on a market order, and the bot sends market orders
only. The entry pays about 0.25% of equity a fortnight in fees, so the most limit orders can be worth is 0.12%;
run through the harness at the halved fee, the in-sample total rises 13 points and the holdout total FALLS 4,
which is path noise and means the saving is smaller than the noise.

What they would COST depends on one fact the API documents do not state: what Roostoo does with a limit order
that is already marketable. If it fills at once and is charged the limit rate, a limit order at the touch is a
market order at half price and adopting it changes two arguments of one call. If it rests, or fills at the market
rate, the discount exists only for an order that waits between cycles, and the engine has no such state:
reconcile reads free balances, so funds locked in an open order look like a loss and can trip the equity hold; an
unfilled order on a selection day threatens the eight-active-day floor; polling and cancelling spend the
thirty-calls-a-minute budget; and the simulator cannot model a fill rule we cannot see, which would end
backtest-equals-live. None of that is worth twelve basis points a fortnight, so nothing is built until this
check has run.

The check. ONE order on the TEST account: read the ticker, place a LIMIT BUY of about $100 priced at the ask
(marketable at the touch, not through it), then read the order back, the pending count and the balance. If it
rests it is cancelled, so the account is left as it was found.

The rule, fixed before the run. Adopt only if ALL of these hold:
  1. the place_order response itself says FILLED, for the whole quantity;
  2. the fill price is no worse than the limit price;
  3. the commission charged is the limit rate, 0.05% of the notional (whatever `Role` says -- it is recorded);
  4. nothing is left behind: no pending order and no locked balance.
Any other outcome -- it rests, it is rejected, it fills at 0.1% -- and the entry keeps market orders. One binary
decision on one order; there is no second look with a different price.
"""
import math
from dataclasses import asdict, dataclass

from ..execution import floor_to
from .client import RoostooClient
from .models import Order

LIMIT_RATE = 0.0005
RATE_TOLERANCE = 0.10          # commission is rounded to the cent on a ~$100 order; 10% of 5 cents is half a cent


@dataclass(frozen=True)
class Observation:
    pair: str
    bid: float
    ask: float
    limit_price: float
    quantity: float
    placed: Order              # the place_order response: what the engine would have to act on
    queried: Order | None      # the same order read back a moment later
    cancelled: bool            # it rested and the check cancelled it
    pending_after: int
    locked_after: dict[str, float]

    def to_record(self) -> dict:
        return asdict(self)


def touch_price(ask: float, precision: int) -> float:
    """The ask rounded UP to the pair's price step. Rounding to nearest can land below the ask, and a limit below
    the ask is not marketable: it would rest on any exchange and the check would blame the exchange for it."""
    scale = 10 ** precision
    return math.ceil(ask * scale - 1e-9) / scale


def observe(client: RoostooClient, pair: str = "BTC/USD", notional: float = 100.0) -> Observation:
    """Place the one order and record what the exchange did with it. Cancels it if it rests."""
    rules = client.exchange_info()[pair]
    ticker = client.ticker()[pair]
    limit_price = touch_price(ticker.ask, rules.price_precision)
    quantity = floor_to(notional / limit_price, rules.amount_precision)
    placed = client.place_order(pair, "BUY", "LIMIT", f"{quantity:.{rules.amount_precision}f}",
                                f"{limit_price:.{rules.price_precision}f}")
    matched = client.query_order(order_id=placed.order_id)
    queried = matched[0] if matched else None
    cancelled = False
    if (queried or placed).status == "PENDING":
        cancelled = placed.order_id in client.cancel_order(order_id=placed.order_id)
    pending_after, _ = client.pending_count()
    locked_after = {asset: b.lock for asset, b in client.balance().items() if b.lock}
    return Observation(pair, ticker.bid, ticker.ask, limit_price, quantity, placed, queried, cancelled,
                       pending_after, locked_after)


def verdict(obs: Observation) -> tuple[bool, list[str]]:
    """Apply the pre-registered rule. Returns (adopt, one line per condition)."""
    o = obs.placed
    filled = o.status == "FILLED" and abs(o.filled_quantity - obs.quantity) < 1e-12
    lines = [f"{'PASS' if filled else 'FAIL'}  1. filled at once, in full: status {o.status}, "
             f"{o.filled_quantity:g} of {obs.quantity:g}"]
    if not filled:
        lines.append("----  2-3. not evaluated: there is no fill to price")
    else:
        priced = o.filled_avg_price <= obs.limit_price
        lines.append(f"{'PASS' if priced else 'FAIL'}  2. fill price no worse than the limit: "
                     f"{o.filled_avg_price:g} against {obs.limit_price:g} (ask was {obs.ask:g})")
        in_coin = o.commission_coin == obs.pair.split("/")[0]          # a BUY may be charged in the coin it bought
        rate = o.commission / (o.filled_quantity if in_coin else o.filled_quantity * o.filled_avg_price)
        cheap = rate <= LIMIT_RATE * (1 + RATE_TOLERANCE)
        lines.append(f"{'PASS' if cheap else 'FAIL'}  3. charged the limit rate: {rate:.4%} of notional "
                     f"({o.commission:g} {o.commission_coin}), role {o.role}")
        filled = priced and cheap
    clean = obs.pending_after == 0 and not obs.locked_after
    lines.append(f"{'PASS' if clean else 'FAIL'}  4. nothing left behind: {obs.pending_after} pending, "
                 f"locked {obs.locked_after or 'nothing'}" + (" (the resting order was cancelled)" if obs.cancelled else ""))
    return filled and clean, lines
