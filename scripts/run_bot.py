"""Run one bot from a committed config.

  .venv\\Scripts\\python.exe scripts\\run_bot.py --config configs\\paper-core.toml          # loop: every hour at :00:30
  .venv\\Scripts\\python.exe scripts\\run_bot.py --config configs\\paper-core.toml --once   # one cycle now, then exit

Keys come from .env (ROOSTOO_API_KEY / ROOSTOO_SECRET_KEY, optionally suffixed per config.key_suffix). The paper
exchange needs no keys: it fills at Roostoo's public ticker. The config's `mode` is re-read every cycle, so the
emergency stop is a committed config change, never a manual API call.
"""
import argparse
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pandas as pd

from qtrading.data.binance import BinanceSource
from qtrading.data.store import PriceStore
from qtrading.data.universe import build_universe, load_snapshot
from qtrading.data.yahoo import YahooSource
from qtrading.engine.alerts import make_alerter, make_heartbeat
from qtrading.engine.config import load_config
from qtrading.engine.exchange import PaperExchange, RoostooExchange
from qtrading.engine.journal import Journal, current_commit
from qtrading.engine.loop import Bot
from qtrading.roostoo.client import DEFAULT_BASE_URL, RoostooClient
from qtrading.roostoo.models import PairInfo
from qtrading.strategy.momentum import Momentum

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"
log = logging.getLogger("qtrading.bot")


def load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, never overriding variables already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def setup_logging(name: str) -> None:
    (ROOT / "logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handlers = [RotatingFileHandler(ROOT / "logs" / f"{name}.log", maxBytes=20_000_000, backupCount=5, encoding="utf-8"),
                logging.StreamHandler(sys.stdout)]
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def build(config_path: Path):
    cfg = load_config(config_path)
    for field in ("wallet", "journal", "memory", "state"):                # config paths are repo-relative
        setattr(cfg.paths, field, str(ROOT / getattr(cfg.paths, field)))
    snapshot = load_snapshot(SNAPSHOT)
    universe = [a for a in build_universe(snapshot) if a.pair in cfg.strategy.pairs]
    store = PriceStore(cache_dir=ROOT / "data" / "cache", sources={"binance": BinanceSource(), "yahoo": YahooSource()})
    base_url = os.environ.get("ROOSTOO_BASE_URL", DEFAULT_BASE_URL)

    if cfg.exchange == "paper":
        public = RoostooClient(api_key="", secret_key="", base_url=base_url)
        rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
        exchange = PaperExchange(lambda: {p: t.last for p, t in public.ticker().items()}, rules, cfg.paths.wallet,
                                 fee_rate=cfg.fee_rate)
    elif cfg.exchange == "roostoo":
        key = os.environ[f"ROOSTOO_API_KEY{cfg.key_suffix}"]
        secret = os.environ[f"ROOSTOO_SECRET_KEY{cfg.key_suffix}"]
        exchange = RoostooExchange(RoostooClient(key, secret, base_url=base_url))
    else:
        raise ValueError(f"unknown exchange {cfg.exchange!r}")

    journal = Journal(cfg.paths.journal, current_commit(ROOT))
    alerter = make_alerter(cfg.alerts)
    bot = Bot(cfg, Momentum(cfg.strategy, name=cfg.name), exchange, store, universe, journal, alerter,
              mode_reader=lambda: load_config(config_path).mode, heartbeat=make_heartbeat())
    return cfg, bot


def next_cycle(now: pd.Timestamp) -> pd.Timestamp:
    """Top of the next hour plus 30 s, so Binance's hourly candle has closed and is fetchable."""
    return now.floor("h") + pd.Timedelta(hours=1, seconds=30)


def summarize(res) -> str:
    fills = ", ".join(f"{f.side} {f.quantity:g} {f.pair} @ {f.price:g}" for f in res.fills) or "no fills"
    return (f"mode={res.mode} reason={res.reason} equity={res.equity:,.0f} targets={len(res.targets)} "
            f"orders={len(res.orders)} behind_pace={res.behind_pace} | {fills}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--once", action="store_true", help="run a single cycle now and exit")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    config_path = Path(args.config).resolve()
    cfg, bot = build(config_path)
    setup_logging(cfg.name)
    log.info("starting %s (%s exchange, %d pairs, commit %s)", cfg.name, cfg.exchange, len(bot.universe), current_commit(ROOT))
    bot.alert(f"[{cfg.name}] started on {cfg.exchange} at commit {current_commit(ROOT)}")

    if args.once:
        res = bot.run_once(pd.Timestamp.now(tz="UTC"))
        log.info(summarize(res))
        return 0 if res.reason in ("ok", "hold") else 1

    while True:
        now = pd.Timestamp.now(tz="UTC")
        wake = next_cycle(now)
        log.info("next cycle at %s (in %.0f s)", wake, (wake - now).total_seconds())
        time.sleep(max(0.0, (wake - now).total_seconds()))
        try:
            res = bot.run_once(pd.Timestamp.now(tz="UTC"))
            log.info(summarize(res))
        except Exception as e:                                             # run_once should never raise; belt and braces
            log.exception("cycle crashed: %s", e)
            bot.alert(f"[{cfg.name}] cycle crashed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main())
