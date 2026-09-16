"""Hourly portfolio simulator mirroring Roostoo's spot rules.

Fills at the decision hour's close (Roostoo's mock book shows bid == ask, so no spread by default; slippage is a
parameter). Fee on notional. Quantities floored to the pair's AmountPrecision; orders under MiniOrder or under a
minimum trade notional are skipped; no trades on stale bars. Sells execute before buys so rotations fit in cash.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..data.store import Prices
from ..execution import plan_orders
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


def simulate(prices: Prices, strategy: Strategy, rules: dict[str, PairInfo], config: SimConfig = SimConfig()) -> Result:
    close = prices.close
    pairs = list(close.columns)
    col = {p: j for j, p in enumerate(pairs)}
    C = close.to_numpy(dtype=float)
    S = prices.stale.to_numpy(dtype=bool)
    SIG = strategy.signals(prices).reindex(index=close.index)     # keep any extra columns (gates, vols) for targets()
    n = len(close)

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

            prices_now = {p: px[j] for p, j in col.items()}
            stale_now = {p for p, j in col.items() if S[i, j]}
            holdings_now = {p: qty[j] for p, j in col.items() if qty[j] > 0}
            orders = plan_orders(targets, holdings_now, prices_now, stale_now, cash, equity, rules,
                                 config.fee_rate, config.min_trade_notional, config.slippage_bps)
            traded = 0.0
            for o in orders:
                j = col[o.pair]
                if o.side == "SELL":
                    cash += o.notional - o.fee
                    qty[j] -= o.quantity
                    if qty[j] < 10 ** -rules[o.pair].amount_precision:          # dust after flooring
                        qty[j] = 0.0
                else:
                    cash -= o.notional + o.fee
                    qty[j] += o.quantity
                trades.append(Trade(t, o.pair, o.side, o.quantity, o.price, o.notional, o.fee))
                traded += o.notional

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
