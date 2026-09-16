"""Re-derive each journalled live decision from the inputs it was made from.

"Backtest equals live" is a design claim until something checks it. The engine journals the reconciled book and
the strategy memory it decided from, so every cycle can be recomputed here and compared with what the bot
actually targeted. A mismatch means the data changed under us, the code changed, or there is a bug — all three
are things to find before the competition rather than during it.
"""
import re
from dataclasses import dataclass, field

import pandas as pd

from ..strategy import State

TOLERANCE = 1e-9
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


@dataclass
class CycleCheck:
    at: pd.Timestamp
    matches: bool
    differences: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    error: str | None = None


def _revive(value):
    """The journal writes timestamps as ISO strings; the strategy does date arithmetic on them."""
    if isinstance(value, str) and ISO_DATETIME.match(value):
        try:
            return pd.Timestamp(value)
        except ValueError:
            return value
    return value


def state_from_record(record: dict) -> State:
    s = record["state"]
    memory = {k: _revive(v) for k, v in (record.get("memory_in") or {}).items()}
    return State(holdings=dict(s.get("holdings") or {}), weights=dict(s.get("weights") or {}),
                 cash=float(s.get("cash", 0.0)), equity=float(s.get("equity", 0.0)),
                 peak_equity=float(s.get("peak_equity", 0.0)), memory=memory)


def compare_targets(record: dict, recomputed: dict, tolerance: float = TOLERANCE) -> CycleCheck:
    journalled = record.get("targets") or {}
    differences = {}
    for pair in sorted(set(journalled) | set(recomputed)):
        a, b = journalled.get(pair), recomputed.get(pair)
        if a is None or b is None or abs(a - b) > tolerance:
            differences[pair] = (a, b)
    return CycleCheck(at=pd.Timestamp(record["at"]), matches=not differences, differences=differences)


def replay_cycle(strategy, prices, record: dict) -> CycleCheck:
    """Recompute one cycle's targets from a price panel ending at that cycle's hour."""
    at = pd.Timestamp(record["at"])
    try:
        signals = strategy.signals(prices)
        recomputed = strategy.targets(at, signals.iloc[-1], state_from_record(record)) or {}
    except Exception as e:
        return CycleCheck(at=at, matches=False, error=f"{type(e).__name__}: {e}")
    return compare_targets(record, recomputed)
