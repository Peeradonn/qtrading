"""The hourly cycle.

run_once(now): reload mode -> refresh market data -> check freshness -> reconcile from the exchange ->
sanity-check equity -> strategy targets (with the activity floor) -> plan_orders -> execute (sells first,
stop on any uncertainty) -> persist memory and state -> journal. Any exception anywhere means no orders.
Every cycle ends with a heartbeat ping (success or fail) and, on cadence, a digest to the operator.
"""
import copy
import datetime as dt
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..execution import PlannedOrder, plan_orders
from ..roostoo.errors import OrderUncertain
from ..strategy import State
from .activity import ActivityTracker
from .config import BotConfig
from .exchange import Exchange, Fill, InsufficientFunds
from .journal import Journal
from .report import cycle_digest
from .state import load_memory, reconcile, save_memory

FAR_FUTURE = dt.date(2099, 1, 1)


class StaleData(Exception):
    """Market data is too old to decide on."""


@dataclass
class CycleResult:
    mode: str
    reason: str                                  # ok | hold | error | equity_jump
    targets: dict = field(default_factory=dict)
    orders: list[PlannedOrder] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    behind_pace: bool = False
    equity: float = 0.0


class Bot:
    def __init__(self, config: BotConfig, strategy, exchange: Exchange, store, universe, journal: Journal,
                 alerter=None, mode_reader=None, heartbeat=None):
        self.config = config
        self.strategy = strategy
        self.exchange = exchange
        self.store = store
        pairs = config.strategy.pairs
        self.universe = [a for a in universe if pairs is None or a.pair in pairs]
        self._pairs = [a.pair for a in self.universe]
        self.journal = journal
        self.alert = alerter or (lambda message: None)
        self.heartbeat = heartbeat or (lambda ok=True: None)
        self._mode_reader = mode_reader
        self.mode_override: str | None = None
        self._state = self._load_state()
        self._last_state: State | None = None
        self._up_since = pd.Timestamp.now(tz="UTC")
        if "activity" in self._state:
            self._tracker = ActivityTracker.from_json(self._state["activity"])
        else:
            self._tracker = ActivityTracker(config.competition_start or FAR_FUTURE, config.competition_days,
                                            config.required_active_days)

    # ---- one cycle ----------------------------------------------------------

    def run_once(self, now: pd.Timestamp) -> CycleResult:
        cfg = self.config
        mode = self.mode_override or (self._mode_reader() if self._mode_reader else cfg.mode)
        self.journal.record("cycle_start", at=now, mode=mode)
        self._last_state = None
        self._started = time.monotonic()

        if mode == "hold":
            self.journal.record("cycle_end", at=now, reason="hold", fills=0, duration_s=self._elapsed())
            result = CycleResult(mode, "hold")
        else:
            try:
                result = self._cycle(now, mode)
            except Exception as e:                                   # never trade blind
                self.journal.record("error", at=now, error=f"{type(e).__name__}: {e}", duration_s=self._elapsed())
                self.alert(f"[{cfg.name}] cycle error, no orders: {type(e).__name__}: {e}")
                result = CycleResult(mode, "error")

        self.heartbeat(result.reason != "error")
        if mode != "hold" and cfg.digest_every_h and now.hour % cfg.digest_every_h == 0:
            state = self._last_state or State(holdings={}, weights={}, cash=0.0, equity=0.0, peak_equity=0.0)
            first_order_at = self._state.get("first_order_at")
            self.alert(cycle_digest(cfg.name, now, result, state, self._tracker, self._state.get("initial_equity"),
                                    first_order_at=pd.Timestamp(first_order_at) if first_order_at else None,
                                    up_since=self._up_since))
        return result

    def _cycle(self, now: pd.Timestamp, mode: str) -> CycleResult:
        cfg, limits = self.config, self.config.limits
        end = now.floor("h")
        # a slow network must not stretch a cycle: once the budget is spent the store serves cache, those assets
        # look stale for the newest hour, and nothing downstream trades them
        budget_over = self._budget(limits.data_deadline_s)
        prices = self.store.closes(self.universe, end - pd.Timedelta(days=cfg.lookback_days), end,
                                   deadline=budget_over)
        if budget_over():
            self.journal.record("data_budget_spent", at=now, budget_s=limits.data_deadline_s)
        self._check_freshness(prices, now)
        tickers = self.exchange.prices()
        balances = self.exchange.balances()
        rules = self.exchange.rules()
        memory = load_memory(cfg.paths.memory)
        state = reconcile(balances, tickers, self._pairs, memory, float(self._state.get("peak_equity", 0.0)),
                          allow_short=cfg.allow_short)
        self._last_state = state
        self._state.setdefault("initial_equity", state.equity)

        last_equity = self._state.get("last_equity")
        self._state["last_equity"] = state.equity
        if last_equity and abs(state.equity - last_equity) / last_equity > limits.equity_jump_alert:
            self._save_state()
            self.journal.record("equity_jump", at=now, equity=state.equity, last_equity=last_equity)
            self.alert(f"[{cfg.name}] equity moved {state.equity / last_equity - 1:+.1%} since last cycle "
                       f"without trades — holding this cycle")
            return CycleResult(mode, "equity_jump", equity=state.equity)

        behind = self._tracker.behind_pace(now.date())
        memory_in = copy.deepcopy(memory)                      # the inputs replay needs, before targets() mutates them
        if mode == "liquidate":
            targets = {}
        else:
            if behind:
                memory["force_rebalance"] = True
            signals = self.strategy.signals(prices)
            targets = self.strategy.targets(now, signals.iloc[-1], state) or {}
            memory.pop("force_rebalance", None)

        stale_now = {p for p in self._pairs if bool(prices.stale[p].iloc[-1])}
        orders = plan_orders(targets, state.holdings, tickers, stale_now, state.cash, state.equity, rules,
                             cfg.fee_rate, cfg.min_trade_notional, allow_short=cfg.allow_short)
        fills = self._execute(orders, state.equity, now)

        save_memory(cfg.paths.memory, memory)
        self._state.update(peak_equity=state.peak_equity,
                           last_equity=state.equity - sum(f.fee for f in fills),
                           activity=self._tracker.to_json())
        self._save_state()
        self.journal.record("cycle_end", at=now, equity=state.equity, cash=state.cash, targets=targets,
                            orders=len(orders), fills=len(fills), behind_pace=behind,
                            active_days=len(self._tracker.active_days()), duration_s=self._elapsed(),
                            state={"holdings": state.holdings, "weights": state.weights, "cash": state.cash,
                                   "equity": state.equity, "peak_equity": state.peak_equity},
                            memory_in=memory_in)
        return CycleResult(mode, "ok", targets, orders, fills, behind, state.equity)

    # ---- pieces -------------------------------------------------------------

    def _elapsed(self) -> float:
        return round(time.monotonic() - self._started, 1)

    def _budget(self, seconds: float):
        """A callable that becomes True once this cycle has spent ``seconds`` on refreshing data."""
        until = time.monotonic() + seconds
        return lambda: time.monotonic() >= until

    def _check_freshness(self, prices, now: pd.Timestamp) -> None:
        pair = self.config.strategy.gate_pair if self.config.strategy.gate_pair in self._pairs else self._pairs[0]
        live = prices.close.index[~prices.stale[pair].to_numpy()]
        if len(live) == 0:
            raise StaleData(f"no live bars for {pair}")
        lag = now - live.max()
        if lag > pd.Timedelta(hours=self.config.limits.data_max_lag_h):
            raise StaleData(f"newest {pair} bar is {lag} old")

    def _execute(self, orders: list[PlannedOrder], equity: float, now: pd.Timestamp) -> list[Fill]:
        limits = self.config.limits
        fills: list[Fill] = []
        for o in orders[:limits.max_orders_per_cycle]:
            if o.notional > limits.max_order_fraction * equity:
                self.journal.record("order_skipped", at=now, pair=o.pair, side=o.side, notional=o.notional,
                                    reason="above per-order cap")
                continue
            try:
                fill = self.exchange.place_market(o.pair, o.side, o.quantity)
            except OrderUncertain as e:
                self.journal.record("order_uncertain", at=now, pair=o.pair, side=o.side, quantity=o.quantity,
                                    error=str(e))
                self.alert(f"[{self.config.name}] order uncertain on {o.pair} {o.side}: {e} — stopping this cycle")
                break
            except InsufficientFunds as e:
                self.journal.record("order_skipped", at=now, pair=o.pair, side=o.side, reason=str(e))
                continue
            self.journal.record("fill", at=now, pair=fill.pair, side=fill.side, quantity=fill.quantity,
                                price=fill.price, notional=fill.notional, fee=fill.fee, order_id=fill.order_id,
                                status=fill.status)
            fills.append(fill)
            self._tracker.record(now.date())
            self._state.setdefault("first_order_at", now.isoformat())
        return fills

    def _load_state(self) -> dict:
        p = Path(self.config.paths.state)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def _save_state(self) -> None:
        p = Path(self.config.paths.state)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._state, indent=1), encoding="utf-8")
