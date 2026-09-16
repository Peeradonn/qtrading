"""Check that the live bot decided what the strategy says it should have.

  .venv\\Scripts\\python.exe scripts\\replay.py --config configs\\paper-core.toml

For every journalled cycle, this rebuilds the price panel for that hour, rebuilds the reconciled book and the
strategy memory the bot decided from, recomputes the targets, and compares. Cycles journalled before the inputs
were recorded are skipped. A mismatch means the data moved, the code changed, or there is a bug.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from qtrading.backtest.replay import replay_cycle
from qtrading.data.binance import BinanceSource
from qtrading.data.store import PriceStore
from qtrading.data.universe import build_universe, load_snapshot
from qtrading.data.yahoo import YahooSource
from qtrading.engine.config import load_config
from qtrading.strategy.momentum import Momentum

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"


def cycles(journal_path: Path) -> list[dict]:
    if not journal_path.exists():
        return []
    out = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("kind") == "cycle_end" and "state" in rec:
            out.append(rec)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--limit", type=int, default=0, help="check only the most recent N cycles")
    args = ap.parse_args()

    cfg = load_config(Path(args.config).resolve())
    journal_path = ROOT / cfg.paths.journal
    records = cycles(journal_path)
    if args.limit:
        records = records[-args.limit:]
    if not records:
        print(f"no replayable cycles in {journal_path} (older cycles did not record their inputs)")
        return 0

    universe = [a for a in build_universe(load_snapshot(SNAPSHOT)) if a.pair in cfg.strategy.pairs]
    store = PriceStore(cache_dir=ROOT / "data" / "cache", sources={"binance": BinanceSource(), "yahoo": YahooSource()})
    strategy = Momentum(cfg.strategy, name=cfg.name)

    print(f"replaying {len(records)} cycle(s) of {cfg.name} from {journal_path.name}\n")
    checks = []
    for rec in records:
        at = pd.Timestamp(rec["at"]).floor("h")
        prices = store.closes(universe, at - pd.Timedelta(days=cfg.lookback_days), at)
        check = replay_cycle(strategy, prices, rec)
        checks.append(check)
        mark = "ok  " if check.matches else "DIFF"
        detail = check.error or ("" if check.matches else
                                 "  " + ", ".join(f"{p}: live {a} vs replay {b}" for p, (a, b) in check.differences.items()))
        print(f"  {mark} {check.at:%Y-%m-%d %H:%M} UTC  {len(rec['targets'])} targets{detail}")

    agreed = sum(c.matches for c in checks)
    print(f"\n{agreed}/{len(checks)} cycles reproduced exactly")
    return 0 if agreed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
