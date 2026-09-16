"""Reconcile the strategy State from the exchange, and persist the strategy's memory across restarts."""
import json
from pathlib import Path

import pandas as pd

from ..strategy import State


def reconcile(balances: dict[str, float], prices: dict[str, float], pairs: list[str], memory: dict,
              peak_equity: float) -> State:
    """Holdings are whatever the exchange says we own of each tradeable pair's coin, valued at the last price.
    The peak only ever moves up."""
    holdings, values = {}, {}
    for pair in pairs:
        coin = pair.split("/")[0]
        qty = float(balances.get(coin, 0.0))
        price = prices.get(pair)
        if qty > 0 and price is not None and price > 0:
            holdings[pair] = qty
            values[pair] = qty * price
    cash = float(balances.get("USD", 0.0))
    equity = cash + sum(values.values())
    weights = {p: v / equity for p, v in values.items()} if equity > 0 else {}
    return State(holdings=holdings, weights=weights, cash=cash, equity=equity,
                 peak_equity=max(peak_equity, equity), memory=memory)


def save_memory(path, memory: dict) -> None:
    def encode(v):
        return {"__ts__": v.isoformat()} if isinstance(v, pd.Timestamp) else v
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({k: encode(v) for k, v in memory.items()}, default=str), encoding="utf-8")


def load_memory(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {k: pd.Timestamp(v["__ts__"]) if isinstance(v, dict) and "__ts__" in v else v for k, v in data.items()}
