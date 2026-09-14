"""Pull ~2 years of hourly history for the whole Roostoo universe into the local cache.

Run:  .venv\\Scripts\\python.exe scripts\\fetch_history.py [--days 725]
Re-running only fetches the missing tail. Prints coverage per asset and flags tickers that returned nothing
(the unverified stock mappings in universe.STOCK_UNDERLYING).
"""
import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

from qtrading.data.binance import BinanceSource
from qtrading.data.store import PriceStore
from qtrading.data.universe import build_universe, load_snapshot
from qtrading.data.yahoo import YahooSource

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"
CACHE = ROOT / "data" / "cache"

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=725, help="lookback in days (Yahoo caps hourly data at 730)")
    args = ap.parse_args()

    end = pd.Timestamp.now(tz="UTC").floor("h")
    start = end - pd.Timedelta(days=args.days)
    universe = build_universe(load_snapshot(SNAPSHOT))
    store = PriceStore(cache_dir=CACHE, sources={"binance": BinanceSource(), "yahoo": YahooSource()})
    print(f"{len(universe)} assets, {start:%Y-%m-%d} -> {end:%Y-%m-%d %H:%M} UTC, cache {CACHE}\n")

    rows, empty = [], []
    t0 = time.time()
    for a in sorted(universe, key=lambda x: (x.asset_type, x.pair)):
        try:
            p = store.closes([a], start, end)
        except Exception as e:                       # one bad ticker must not kill the run
            print(f"  {a.pair:14} {a.source:8} {a.symbol:12} FAILED: {type(e).__name__}: {e}")
            empty.append(a)
            continue
        s = p.close[a.pair].dropna()
        if s.empty:
            print(f"  {a.pair:14} {a.source:8} {a.symbol:12} NO DATA")
            empty.append(a)
            continue
        real = (~p.stale[a.pair]).sum()
        rows.append((a.asset_type, a.pair, a.source, a.symbol, s.index[0], s.index[-1], real))
        print(f"  {a.pair:14} {a.source:8} {a.symbol:12} {real:6d} real bars  {s.index[0]:%Y-%m-%d} -> {s.index[-1]:%Y-%m-%d %H:%M}")
        sys.stdout.flush()

    print(f"\n{len(rows)} assets with data, {len(empty)} without, {time.time()-t0:.0f}s")
    if empty:
        print("no data:", ", ".join(f"{a.pair}->{a.symbol}" for a in empty))
    return 0


if __name__ == "__main__":
    sys.exit(main())
