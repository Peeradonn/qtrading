"""Bot configuration: one committed TOML per bot. Keys never live here — they come from the environment."""
import datetime as dt
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..strategy.momentum import MomentumParams

TUPLE_FIELDS = ("lookbacks_h", "select_hours_utc", "volume_clip")


@dataclass
class Paths:
    wallet: str
    journal: str
    memory: str
    state: str
    cache: str = "data/cache"             # per-bot price cache; two bots on one host must not share one


@dataclass
class Limits:
    max_orders_per_cycle: int = 12
    max_order_fraction: float = 0.6        # of equity, per order: a runaway-sizing guard, above any legitimate weight
    data_max_lag_h: int = 2                # newest BTC bar must be at most this old
    data_deadline_s: float = 300.0         # wall-clock budget for refreshing prices; then serve cache
    equity_jump_alert: float = 0.05        # unexplained equity move since last cycle -> hold + alert
    ticker_max_age_s: int = 120


@dataclass
class BotConfig:
    name: str
    mode: str                              # trade | hold | liquidate — re-read every cycle
    exchange: str                          # paper | roostoo
    strategy: MomentumParams
    fee_rate: float
    min_trade_notional: float
    lookback_days: int
    competition_start: dt.date | None
    competition_days: int
    required_active_days: int
    paths: Paths
    limits: Limits
    alerts: bool = False                   # send operator alerts (Discord webhook or Telegram, from the environment)
    digest_every_h: int = 24               # post a cycle digest at hours divisible by this; 0 = never
    keep_awake: bool = False               # ask the host not to suspend while trading (Windows laptops)
    key_suffix: str = ""                  # ROOSTOO_API_KEY<suffix> — lets two bots use two accounts
    base_url: str | None = None            # override the exchange URL, e.g. the local mock server
    allow_short: bool = False              # plan sells beyond holdings and reconcile negative balances as shorts;
                                           # off unless the exchange's short mechanics have been verified


def load_config(path) -> BotConfig:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    strat = dict(raw.get("strategy", {}))
    for key in TUPLE_FIELDS:
        if key in strat and strat[key] is not None:
            strat[key] = tuple(strat[key])
    strat["pairs"] = tuple(raw["pairs"])
    return BotConfig(
        name=raw["name"],
        mode=raw.get("mode", "trade"),
        exchange=raw.get("exchange", "paper"),
        strategy=MomentumParams(**strat),
        fee_rate=float(raw.get("fee_rate", 0.001)),
        min_trade_notional=float(raw.get("min_trade_notional", 50.0)),
        lookback_days=int(raw.get("lookback_days", 60)),
        competition_start=raw.get("competition_start"),
        competition_days=int(raw.get("competition_days", 14)),
        required_active_days=int(raw.get("required_active_days", 8)),
        paths=Paths(**raw["paths"]),
        limits=Limits(**raw.get("limits", {})),
        alerts=bool(raw.get("alerts", raw.get("telegram", False))),
        digest_every_h=int(raw.get("digest_every_h", 24)),
        keep_awake=bool(raw.get("keep_awake", False)),
        key_suffix=str(raw.get("key_suffix", "")),
        base_url=raw.get("base_url"),
        allow_short=bool(raw.get("allow_short", False)),
    )
