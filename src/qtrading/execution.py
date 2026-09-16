"""Order planning shared by the backtester and the live engine — one function, so backtest == live by construction.

Given target weights and the current book, produce the market orders to place, in execution order:
sells first (largest first) so their proceeds fund the buys; quantities floored to the pair's AmountPrecision;
anything under MiniOrder or under the minimum trade notional is skipped; buys are capped by cash net of fees;
no orders for pairs with a missing/NaN price, a stale bar, or no exchange rules.
"""
import math
from dataclasses import dataclass

from .roostoo.models import PairInfo


@dataclass(frozen=True)
class PlannedOrder:
    pair: str
    side: str            # BUY | SELL
    quantity: float
    price: float         # expected fill price
    notional: float
    fee: float           # expected commission


def floor_to(x: float, precision: int) -> float:
    f = 10 ** precision
    return math.floor(x * f + 1e-9) / f


def plan_orders(targets: dict[str, float], holdings: dict[str, float], prices: dict[str, float], stale,
                cash: float, equity: float, rules: dict[str, PairInfo], fee_rate: float,
                min_trade_notional: float, slippage_bps: float = 0.0) -> list[PlannedOrder]:
    slip = slippage_bps / 10_000
    deltas = []
    for pair in sorted(set(targets) | {p for p, q in holdings.items() if q > 0}):
        px = prices.get(pair)
        if px is None or math.isnan(px) or px <= 0 or pair in stale or pair not in rules:
            continue
        delta = targets.get(pair, 0.0) * equity - holdings.get(pair, 0.0) * px
        if abs(delta) < min_trade_notional:
            continue
        deltas.append((pair, delta))

    orders = []
    for pair, delta in sorted(deltas, key=lambda d: d[1]):          # most negative (sells) first
        r, px = rules[pair], prices[pair]
        if delta < 0:
            fill = px * (1 - slip)
            q = floor_to(min(-delta / fill, holdings.get(pair, 0.0)), r.amount_precision)
            notional = q * fill
            if q <= 0 or notional < r.min_order:
                continue
            fee = notional * fee_rate
            cash += notional - fee
            orders.append(PlannedOrder(pair, "SELL", q, fill, notional, fee))
        else:
            fill = px * (1 + slip)
            affordable = cash / (fill * (1 + fee_rate))
            q = floor_to(min(delta / fill, affordable), r.amount_precision)
            notional = q * fill
            if q <= 0 or notional < r.min_order:
                continue
            fee = notional * fee_rate
            cash -= notional + fee
            orders.append(PlannedOrder(pair, "BUY", q, fill, notional, fee))
    return orders
