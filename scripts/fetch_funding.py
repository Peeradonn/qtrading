"""Pull perpetual funding-rate history from Binance futures for the liquid crypto universe into the cache.

Run:  .venv\\Scripts\\python.exe scripts\\fetch_funding.py
Symbols without a perpetual (e.g. PAXG) simply return nothing and are reported.
"""
import sys
import time
from pathlib import Path

import pandas as pd

from qtrading.data.binance import BinanceSource
from qtrading.data.store import PriceStore
from qtrading.data.universe import build_universe, load_snapshot

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"
CACHE = ROOT / "data" / "cache"

# Same list as scripts/run_backtest.py — kept in sync by hand until a shared research config exists.
LIQUID = tuple(f"{c}/USD" for c in (
    "BTC ETH ZEC SOL XRP BNB FIL SUI NEAR DOGE UNI TRX TAO ADA PEPE LINK PUMP LTC ARB ENA WLD TRUMP AVAX AAVE "
    "FET XLM ICP PAXG ONDO WLFI CAKE DOT APT XPL PENGU").split())


def main() -> int:
    end = pd.Timestamp("2026-09-14 13:00", tz="UTC")
    start = end - pd.Timedelta(days=725)
    universe = [a for a in build_universe(load_snapshot(SNAPSHOT)) if a.pair in LIQUID and a.source == "binance"]
    store = PriceStore(cache_dir=CACHE, sources={"binance": BinanceSource(), "yahoo": None})
    t0 = time.time()
    ok, empty = [], []
    for a in universe:
        try:
            f = store.funding([a], start, end)[a.pair].dropna()
        except Exception as e:
            print(f"  {a.pair:12} FAILED: {type(e).__name__}: {e}")
            empty.append(a.pair)
            continue
        if f.empty:
            print(f"  {a.pair:12} no perpetual / no data")
            empty.append(a.pair)
        else:
            ok.append(a.pair)
            print(f"  {a.pair:12} {len(f):6d} hourly points  {f.index[0]:%Y-%m-%d} -> {f.index[-1]:%Y-%m-%d}  "
                  f"mean {f.mean()*100:+.4f}%/8h  max {f.max()*100:+.3f}%")
        sys.stdout.flush()
    print(f"\n{len(ok)} with funding, {len(empty)} without ({', '.join(empty)}), {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
