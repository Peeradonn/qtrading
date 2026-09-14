"""Hourly portfolio simulator mirroring Roostoo's spot rules.

Fills at the decision hour's close (Roostoo's mock book shows bid == ask, so no spread by default; slippage is a
parameter). Fee on notional. Quantities floored to the pair's AmountPrecision; orders under MiniOrder or under a
minimum trade notional are skipped; no trades on stale bars. Sells execute before buys so rotations fit in cash.
"""
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..data.store import Prices
from ..roostoo.models import PairInfo
from ..strategy import State, Strategy


@dataclass
class SimConfig:
    initial_cash: float = 1_000_000.0
    fee_rate: float = 0.001             # taker; 0.0005 for maker/limit
    slippage_bps: float = 0.0
    decision_every_h: int = 1
    min_trade_notional: float = 50.0    # don't model dust trades we would never place


@dataclass(frozen=True)
class Trade:
    time: pd.Timestamp
    pair: str
    side: str
    quantity: float
    price: float
    notional: float
    fee: float


@dataclass
class Result:
    equity: pd.Series
    cash: pd.Series
    holdings: pd.DataFrame
    weights: pd.DataFrame
    turnover: pd.Series                 # notional traded / equity, per hour
    trades: list[Trade] = field(default_factory=list)


def _floor(x: float, precision: int) -> float:
    f = 10 ** precision
    return math.floor(x * f + 1e-9) / f


def simulate(prices: Prices, strategy: Strategy, rules: dict[str, PairInfo], config: SimConfig = SimConfig()) -> Result:
    close = prices.close
    pairs = list(close.columns)
    col = {p: j for j, p in enumerate(pairs)}
    C = close.to_numpy(dtype=float)
    S = prices.stale.to_numpy(dtype=bool)
    SIG = strategy.signals(prices).reindex(index=close.index)     # keep any extra columns (gates, vols) for targets()
    n = len(close)
    slip = config.slippage_bps / 10_000

    cash = float(config.initial_cash)
    qty = np.zeros(len(pairs))
    peak = cash
    equity_out = np.empty(n)
    cash_out = np.empty(n)
    turnover_out = np.zeros(n)
    holdings_out = np.empty((n, len(pairs)))
    weights_out = np.empty((n, len(pairs)))
    trades: list[Trade] = []
    memory: dict = {}                                   # the strategy's scratch, carried between decisions

    for i in range(n):
        t = close.index[i]
        px = C[i]
        value = np.where(np.isnan(px), 0.0, qty * px)
        equity = cash + value.sum()

        if i % config.decision_every_h == 0:
            peak = max(peak, equity)
            state = State(holdings={p: qty[j] for p, j in col.items() if qty[j] > 0},
                          weights={p: value[j] / equity for p, j in col.items() if qty[j] > 0},
                          cash=cash, equity=equity, peak_equity=peak, memory=memory)
            targets = strategy.targets(t, SIG.iloc[i], state) or {}

            orders = []
            for p in set(targets) | {p for p, j in col.items() if qty[j] > 0}:
                j = col.get(p)
                if j is None or np.isnan(px[j]) or S[i, j]:
                    continue
                delta = targets.get(p, 0.0) * equity - qty[j] * px[j]
                if abs(delta) < config.min_trade_notional:
                    continue
                orders.append((p, j, delta))

            traded = 0.0
            for p, j, delta in sorted(orders, key=lambda o: o[2]):          # sells (negative) first
                prec, min_order = rules[p].amount_precision, rules[p].min_order
                if delta < 0:
                    fill = px[j] * (1 - slip)
                    q = _floor(min(-delta / fill, qty[j]), prec)
                    notional = q * fill
                    if q <= 0 or notional < min_order:
                        continue
                    fee = notional * config.fee_rate
                    cash += notional - fee
                    qty[j] -= q
                    if qty[j] < 10 ** -prec:                              # dust after flooring
                        qty[j] = 0.0
                    trades.append(Trade(t, p, "SELL", q, fill, notional, fee))
                else:
                    fill = px[j] * (1 + slip)
                    affordable = cash / (fill * (1 + config.fee_rate))
                    q = _floor(min(delta / fill, affordable), prec)
                    notional = q * fill
                    if q <= 0 or notional < min_order:
                        continue
                    fee = notional * config.fee_rate
                    cash -= notional + fee
                    qty[j] += q
                    trades.append(Trade(t, p, "BUY", q, fill, notional, fee))
                traded += notional

            turnover_out[i] = traded / equity if equity > 0 else 0.0
            value = np.where(np.isnan(px), 0.0, qty * px)
            equity = cash + value.sum()

        equity_out[i] = equity
        cash_out[i] = cash
        holdings_out[i] = qty
        weights_out[i] = value / equity if equity > 0 else 0.0

    idx = close.index
    return Result(equity=pd.Series(equity_out, index=idx, name="equity"),
                  cash=pd.Series(cash_out, index=idx, name="cash"),
                  holdings=pd.DataFrame(holdings_out, index=idx, columns=pairs),
                  weights=pd.DataFrame(weights_out, index=idx, columns=pairs),
                  turnover=pd.Series(turnover_out, index=idx, name="turnover"),
                  trades=trades)
