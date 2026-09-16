"""The cycle digest: what an operator needs to know, in one message that fits a phone screen."""
import pandas as pd

from ..strategy import State
from .activity import ActivityTracker


def cycle_digest(name: str, now: pd.Timestamp, result, state: State, tracker: ActivityTracker,
                 initial_equity: float | None) -> str:
    status = "ERROR" if result.reason == "error" else result.reason.upper()
    lines = [f"[{name}] {now:%Y-%m-%d %H:%M} UTC — {status}"]

    since_start = f"{state.equity / initial_equity - 1:+.1%} since start" if initial_equity else "start"
    from_peak = f"{state.equity / state.peak_equity - 1:+.1%} from peak" if state.peak_equity else ""
    exposure = sum(state.weights.values())
    cash = state.cash / state.equity if state.equity else 0.0
    lines.append(f"equity {state.equity:,.0f} ({since_start}, {from_peak}) | exposure {exposure:.0%} | cash {cash:.0%}")

    holdings = ", ".join(f"{p} {w:.0%}" for p, w in sorted(state.weights.items(), key=lambda kv: -kv[1])) or "none"
    lines.append(f"holdings: {holdings}")

    if tracker.in_window(now.date()):
        active = len({d for d in tracker.active_days() if tracker.in_window(d)})
        pace = "BEHIND PACE — forcing rebalances" if result.behind_pace else "pace OK"
        lines.append(f"active days {active}/{tracker.required} ({pace})")
    else:
        lines.append("active days: outside competition window")

    fills = "; ".join(f"{f.side} {f.quantity:g} {f.pair} @ {f.price:g}" for f in result.fills) or "none"
    lines.append(f"fills: {fills}")
    return "\n".join(lines)
