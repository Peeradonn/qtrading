"""The hourly cycle: reconcile -> decide -> plan -> execute -> journal, and every way it must refuse to trade."""
import datetime as dt
import json

import pandas as pd
import pytest

from qtrading.data.store import Prices
from qtrading.data.universe import Asset
from qtrading.engine.config import BotConfig, Limits, Paths
from qtrading.engine.exchange import PaperExchange
from qtrading.engine.journal import Journal
from qtrading.engine.loop import Bot
from qtrading.roostoo.errors import OrderUncertain
from qtrading.roostoo.models import PairInfo
from qtrading.strategy.momentum import MomentumParams

NOW = pd.Timestamp("2026-10-03 14:00", tz="UTC")
PAIRS = ("BTC/USD", "ETH/USD")
UNIVERSE = [Asset("BTC/USD", "BTC", "crypto", "binance", "BTCUSDT"), Asset("ETH/USD", "ETH", "crypto", "binance", "ETHUSDT")]
RULES = {"BTC/USD": PairInfo("BTC/USD", "BTC", "USD", True, 2, 5, 1.0, "crypto"),
         "ETH/USD": PairInfo("ETH/USD", "ETH", "USD", True, 2, 4, 1.0, "crypto")}
TICKER = {"BTC/USD": 50_000.0, "ETH/USD": 3_000.0}


def panel(stale_btc_last_hours: int = 0, end: pd.Timestamp = NOW) -> Prices:
    idx = pd.date_range(end=end, periods=24 * 60, freq="1h", name="time")
    close = pd.DataFrame({p: 100.0 for p in PAIRS}, index=idx)
    stale = pd.DataFrame(False, index=idx, columns=list(PAIRS))
    if stale_btc_last_hours:
        stale.iloc[-stale_btc_last_hours:, stale.columns.get_loc("BTC/USD")] = True
    return Prices(close=close, stale=stale)


class FakeStore:
    def __init__(self, prices: Prices):
        self.prices = prices

    def closes(self, assets, start, end):
        return self.prices


class ConstantTargets:
    """Test double. Honours the drift band the way Momentum does, and the engine's force_rebalance flag."""
    name = "const"

    def __init__(self, targets, band=0.05, raise_on_targets=False):
        self._targets = targets
        self._band = band
        self._raise = raise_on_targets

    def signals(self, prices):
        return pd.DataFrame(0.0, index=prices.close.index, columns=prices.close.columns)

    def targets(self, t, s, state):
        if self._raise:
            raise RuntimeError("strategy blew up")
        forced = state.memory.pop("force_rebalance", False)
        out = {}
        for pair, w in self._targets.items():
            current = state.weights.get(pair, 0.0)
            out[pair] = current if (current > 0 and abs(w - current) < self._band and not forced) else w
        return out


def config(tmp_path, mode="trade", competition_start=dt.date(2026, 9, 30), **limits):
    return BotConfig(name="t", mode=mode, exchange="paper", strategy=MomentumParams(pairs=PAIRS), fee_rate=0.001,
                     min_trade_notional=50.0, lookback_days=60, competition_start=competition_start,
                     competition_days=14, required_active_days=8,
                     paths=Paths(wallet=str(tmp_path / "w.json"), journal=str(tmp_path / "j.jsonl"),
                                 memory=str(tmp_path / "m.json"), state=str(tmp_path / "s.json")),
                     limits=Limits(**limits))


def make_bot(tmp_path, strategy, prices=None, mode="trade", exchange=None, ticker=None, **limits):
    cfg = config(tmp_path, mode=mode, **limits)
    ex = exchange or PaperExchange(lambda: dict(ticker or TICKER), RULES, cfg.paths.wallet, fee_rate=0.001,
                                   initial_usd=1_000_000.0)
    bot = Bot(cfg, strategy, ex, FakeStore(prices or panel()), UNIVERSE, Journal(cfg.paths.journal, commit="test"))
    return bot, ex


def journal_kinds(tmp_path):
    return [json.loads(line)["kind"] for line in (tmp_path / "j.jsonl").read_text().splitlines()]


# --- happy path ---------------------------------------------------------------

def test_cycle_places_orders_journals_fills_and_persists_memory(tmp_path):
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5, "ETH/USD": 0.3}))
    result = bot.run_once(NOW)
    assert [f.side for f in result.fills] == ["BUY", "BUY"]
    assert ex.balances()["BTC"] == pytest.approx(500_000 / 50_000 / 1.0, rel=1e-3)   # ~10 BTC (fee-capped floor)
    kinds = journal_kinds(tmp_path)
    assert kinds.count("fill") == 2 and kinds[-1] == "cycle_end"
    assert (tmp_path / "m.json").exists() and (tmp_path / "s.json").exists()


def test_second_cycle_within_band_places_nothing(tmp_path):
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5}))
    bot.run_once(NOW)
    result = bot.run_once(NOW + pd.Timedelta(hours=1))
    assert result.fills == []


# --- modes --------------------------------------------------------------------

def test_hold_mode_trades_nothing(tmp_path):
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5}), mode="hold")
    result = bot.run_once(NOW)
    assert result.fills == [] and result.reason == "hold"


def test_liquidate_mode_sells_everything(tmp_path):
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5}))
    bot.run_once(NOW)
    bot.mode_override = "liquidate"
    result = bot.run_once(NOW + pd.Timedelta(hours=1))
    assert [f.side for f in result.fills] == ["SELL"]
    assert ex.balances()["BTC"] == 0.0


# --- refusing to trade --------------------------------------------------------

def test_stale_market_data_means_no_orders(tmp_path):
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5}), prices=panel(stale_btc_last_hours=3), data_max_lag_h=2)
    result = bot.run_once(NOW)
    assert result.fills == [] and result.reason == "error"
    assert "error" in journal_kinds(tmp_path)


def test_strategy_exception_means_no_orders_and_is_journaled(tmp_path):
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5}, raise_on_targets=True))
    result = bot.run_once(NOW)
    assert result.fills == [] and result.reason == "error"
    assert ex.balances() == {"USD": 1_000_000.0}


class UncertainOnce(PaperExchange):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls = 0

    def place_market(self, pair, side, quantity):
        self.calls += 1
        if self.calls == 1:
            raise OrderUncertain("timeout")
        return super().place_market(pair, side, quantity)


def test_uncertain_order_stops_the_cycle_before_any_further_order(tmp_path):
    cfg = config(tmp_path)
    ex = UncertainOnce(lambda: dict(TICKER), RULES, cfg.paths.wallet, fee_rate=0.001, initial_usd=1_000_000.0)
    bot, _ = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.4, "ETH/USD": 0.4}), exchange=ex)
    result = bot.run_once(NOW)
    assert ex.calls == 1 and result.fills == []
    assert "order_uncertain" in journal_kinds(tmp_path)


def test_unexplained_equity_jump_puts_the_bot_on_hold_for_a_cycle(tmp_path):
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5}), equity_jump_alert=0.05)
    bot.run_once(NOW)
    ex._wallet["USD"] += 200_000.0                          # money appears from nowhere
    ex._save()
    result = bot.run_once(NOW + pd.Timedelta(hours=1))
    assert result.fills == [] and result.reason == "equity_jump"


def test_orders_above_the_per_order_cap_are_skipped(tmp_path):
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5, "ETH/USD": 0.1}), max_order_fraction=0.2)
    result = bot.run_once(NOW)
    assert [f.pair for f in result.fills] == ["ETH/USD"]


# --- activity floor -----------------------------------------------------------

def test_activity_floor_forces_a_rebalance_when_behind_pace(tmp_path):
    later = pd.Timestamp("2026-10-10 14:00", tz="UTC")
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5}), prices=panel(end=later))
    bot.run_once(NOW)                                                # 1 active day (Oct 3)
    # jump to Oct 10 with no other trading days: 1 active, need 7 more, 4 days left -> behind pace
    ex._wallet["BTC"] *= 1.02                                       # 1 pt drift: inside the 5-pt band
    ex._save()
    result = bot.run_once(later)
    assert result.behind_pace is True
    assert len(result.fills) == 1


# --- heartbeat and digest -------------------------------------------------------

def test_heartbeat_reports_success_and_failure(tmp_path):
    beats = []
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5}))
    bot.heartbeat = beats.append
    bot.run_once(NOW)
    bot.strategy = ConstantTargets({"BTC/USD": 0.5}, raise_on_targets=True)
    bot.run_once(NOW + pd.Timedelta(hours=1))
    assert beats == [True, False]


def test_digest_is_sent_on_the_configured_cadence(tmp_path):
    messages = []
    midnight = pd.Timestamp("2026-10-04 00:00", tz="UTC")
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5}), prices=panel(end=midnight))
    bot.alert = messages.append
    bot.config.digest_every_h = 24
    bot.run_once(NOW)                                            # 14:00 -> no digest
    assert messages == []
    bot.run_once(midnight)                                       # 00:00 -> digest
    assert len(messages) == 1 and "equity" in messages[0].lower()


def test_cycle_end_records_how_long_the_cycle_took(tmp_path):
    bot, ex = make_bot(tmp_path, ConstantTargets({"BTC/USD": 0.5}))
    bot.run_once(NOW)
    last = bot.journal.last("cycle_end")
    assert last["duration_s"] >= 0.0
