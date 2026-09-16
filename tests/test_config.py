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
    assert cfg.telegram is False
