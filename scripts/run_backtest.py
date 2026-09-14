"""Run strategies through the competition-faithful harness and print the comparison table.

Run:  .venv\\Scripts\\python.exe scripts\\run_backtest.py [--oos] [--every 24]
Uses only the local cache (fixed --start/--end so no network is touched). The last months are held out as
out-of-sample and hidden unless --oos is passed.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from qtrading.backtest.checks import assert_no_lookahead
from qtrading.backtest.metrics import rank_composite, window_metrics
from qtrading.backtest.simulator import SimConfig, simulate
from qtrading.data.binance import BinanceSource
from qtrading.data.store import PriceStore
from qtrading.data.universe import build_universe, load_snapshot
from qtrading.data.yahoo import YahooSource
from qtrading.roostoo.models import PairInfo
from qtrading.strategy.baselines import BuyAndHold, EqualWeight

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"
CACHE = ROOT / "data" / "cache"
RESULTS = ROOT / "data" / "results"

IN_SAMPLE_END = "2026-05-14 23:00"     # holdout starts 2026-05-15
CACHE_END = "2026-09-14 13:00"         # last bar in the cache; keeps runs offline and reproducible


def load(start, end):
    snapshot = load_snapshot(SNAPSHOT)
    universe = build_universe(snapshot)
    rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
    store = PriceStore(cache_dir=CACHE, sources={"binance": BinanceSource(), "yahoo": YahooSource()})
    prices = store.closes(universe, pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"))
    return universe, rules, prices


def strategies(universe):
    crypto = [a.pair for a in universe if a.asset_type == "crypto"]
    return [
        BuyAndHold("BTC/USD"),
        EqualWeight(min_age_h=720, pairs=crypto, name="eqw:crypto"),
        EqualWeight(min_age_h=720, name="eqw:all"),
    ]


def pct(x, q):
    return float(np.nanpercentile(x, q))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-09-19")
    ap.add_argument("--oos", action="store_true", help="include the out-of-sample holdout")
    ap.add_argument("--every", type=int, default=24, help="decision cadence in hours")
    args = ap.parse_args()
    end = CACHE_END if args.oos else IN_SAMPLE_END

    universe, rules, prices = load(args.start, end)
    print(f"{len(universe)} assets, {prices.close.index[0]:%Y-%m-%d} -> {prices.close.index[-1]:%Y-%m-%d %H:%M} UTC"
          f"{'  [INCLUDES OOS HOLDOUT]' if args.oos else '  (in-sample; holdout hidden)'}\n")
    RESULTS.mkdir(parents=True, exist_ok=True)

    config = SimConfig(decision_every_h=args.every)
    windows, results = {}, {}
    for strat in strategies(universe):
        t0 = time.time()
        assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
        res = simulate(prices, strat, rules, config)
        w = window_metrics(res.equity)
        windows[strat.name], results[strat.name] = w, res
        safe = "".join(c if c.isalnum() else "_" for c in strat.name)
        w.to_csv(RESULTS / f"{safe}_windows.csv")
        print(f"  {strat.name:14} simulated in {time.time()-t0:4.1f}s, {len(res.trades)} trades")

    bench = windows["hold:BTC/USD"]["ret"]
    print(f"\n{'strategy':14} {'medR':>7} {'p10R':>7} {'p90R':>7} {'worstR':>7} {'%R>0':>5} {'%>BTC':>5} | "
          f"{'medMDD':>7} {'p90MDD':>7} | {'Sharpe':>7} {'Sortino':>8} {'Calmar':>7} | {'total':>8} {'maxDD':>7} {'fees':>6}")
    for name, w in windows.items():
        res = results[name]
        eq = res.equity
        total = eq.iloc[-1] / eq.iloc[0] - 1
        maxdd = ((eq / eq.cummax()) - 1).min()
        fees = sum(t.fee for t in res.trades) / eq.iloc[0]
        beat = (w["ret"] > bench.reindex(w.index)).mean() * 100
        print(f"{name:14} {pct(w.ret,50)*100:6.2f}% {pct(w.ret,10)*100:6.2f}% {pct(w.ret,90)*100:6.2f}% "
              f"{w.ret.min()*100:6.2f}% {(w.ret>0).mean()*100:4.0f}% {beat:4.0f}% | "
              f"{pct(w.mdd,50)*100:6.2f}% {pct(w.mdd,90)*100:6.2f}% | "
              f"{pct(w.sharpe,50):7.2f} {pct(w.sortino,50):8.2f} {pct(w.calmar,50):7.2f} | "
              f"{total*100:+7.1f}% {maxdd*100:6.1f}% {fees*100:5.2f}%")

    comp = rank_composite(windows)
    print("\nrank-normalised composite (0.4 Sortino + 0.3 Sharpe + 0.3 Calmar), median over windows:")
    for name, score in comp.sort_values(ascending=False).items():
        print(f"  {name:14} {score:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
