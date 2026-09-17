"""Bot configuration from a committed TOML file."""
from qtrading.engine.config import load_config

SAMPLE = """
name = "core"
mode = "trade"
exchange = "paper"
pairs = ["BTC/USD", "ETH/USD"]
fee_rate = 0.001
min_trade_notional = 50.0
lookback_days = 60
competition_start = 2026-09-30
competition_days = 14
required_active_days = 8

[strategy]
select_every_h = 24
lookbacks_h = [72, 168, 336]
weighting = "inverse_vol"
vol_target_daily = 0.02

[paths]
wallet = "data/paper/core_wallet.json"
journal = "logs/core.jsonl"
memory = "data/paper/core_memory.json"
state = "data/paper/core_state.json"

[limits]
max_orders_per_cycle = 12
max_order_fraction = 0.4
data_max_lag_h = 2
equity_jump_alert = 0.05
"""


def test_config_loads_strategy_params_and_paths(tmp_path):
    p = tmp_path / "core.toml"
    p.write_text(SAMPLE)
    cfg = load_config(p)
    assert cfg.name == "core"
    assert cfg.mode == "trade"
    assert cfg.strategy.pairs == ("BTC/USD", "ETH/USD")
    assert cfg.strategy.lookbacks_h == (72, 168, 336)
    assert cfg.strategy.vol_target_daily == 0.02
    assert cfg.strategy.weighting == "inverse_vol"
    assert cfg.competition_start.isoformat() == "2026-09-30"
    assert cfg.paths.journal == "logs/core.jsonl"
    assert cfg.limits.max_orders_per_cycle == 12
    assert cfg.key_suffix == ""
    assert cfg.alerts is False
    assert cfg.digest_every_h == 24


def test_base_url_defaults_to_none_and_can_be_overridden(tmp_path):
    p = tmp_path / "a.toml"
    p.write_text(SAMPLE)
    assert load_config(p).base_url is None
    p2 = tmp_path / "b.toml"
    p2.write_text(SAMPLE.replace('exchange = "paper"', 'exchange = "roostoo"\nbase_url = "http://127.0.0.1:8787"'))
    assert load_config(p2).base_url == "http://127.0.0.1:8787"


def test_shipped_configs_select_at_midnight_utc_whenever_the_bot_starts():
    """The backtest and the out-of-sample test select at 00:00 UTC. A bot first started at 05:31 must still select
    at 00:00 thereafter -- counting 24 hours from start-up would silently move the live schedule to 05:31."""
    import pandas as pd
    from pathlib import Path

    from qtrading.strategy import State
    from qtrading.strategy.momentum import Momentum

    root = Path(__file__).resolve().parents[1]
    for name in ("core", "riskon", "paper-core", "mock-core"):
        strat = Momentum(load_config(root / "configs" / f"{name}.toml").strategy)
        row = pd.Series({("score", "A"): 2.0, ("score", "B"): 1.0, ("vol", "A"): 0.01, ("vol", "B"): 0.01,
                         ("gate", "MARKET"): 1.0})
        mem = {}
        state = State(holdings={}, weights={}, cash=1.0, equity=1.0, peak_equity=1.0, memory=mem)
        start = pd.Timestamp("2026-09-16 05:31", tz="UTC")
        strat.targets(start, row, state)                                   # first call always selects
        selections = []
        for hour in range(1, 48):
            t = start.floor("h") + pd.Timedelta(hours=hour)
            before = mem["last_select"]
            strat.targets(t, row, state)
            if mem["last_select"] != before:
                selections.append(t.hour)
        assert selections == [0, 0], f"{name} re-selected at hours {selections}"


def test_each_bot_can_have_its_own_price_cache(tmp_path):
    base = tmp_path / 'base.toml'
    base.write_text(SAMPLE, encoding='utf-8')
    assert load_config(base).paths.cache == 'data/cache'                          # the default
    own = tmp_path / 'own.toml'
    own.write_text(SAMPLE.replace('[limits]', 'cache = "data/cache-own"' + chr(10) + '[limits]'), encoding='utf-8')
    assert load_config(own).paths.cache == 'data/cache-own'
