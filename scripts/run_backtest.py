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
from qtrading.strategy.momentum import Momentum, MomentumParams

ROOT = Path(__file__).resolve().parents[1]

# Crypto pairs with > $5M 24h volume on Roostoo at the 2026-09-14 snapshot (the spike's universe) + PAXG.
LIQUID = tuple(f"{c}/USD" for c in (
    "BTC ETH ZEC SOL XRP BNB FIL SUI NEAR DOGE UNI TRX TAO ADA PEPE LINK PUMP LTC ARB ENA WLD TRUMP AVAX AAVE "
    "FET XLM ICP PAXG ONDO WLFI CAKE DOT APT XPL PENGU").split())
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
    """(strategy, decision cadence in hours). Baselines rebalance daily; momentum decides hourly like the live bot."""
    crypto = [a.pair for a in universe if a.asset_type == "crypto"]
    mom = lambda name, **kw: (Momentum(MomentumParams(pairs=LIQUID, **kw), name=name), 1)
    # Run 2 (2026-09-15) established: daily selection (s24) and dropping the 24h horizon (L3) cut fees ~60% and
    # doubled net return; binary regime gates cost far more return than tail they saved; vol targeting did the
    # Screen 3 work. Run 3 explores around that: ungated inverse-vol + vol target, and the K / cadence / own-gate dials.
    L3 = (72, 168, 336)
    base = dict(select_every_h=24, lookbacks_h=L3)
    iv = dict(weighting="inverse_vol", **base)
    return [
        (BuyAndHold("BTC/USD"), 24),
        mom("mom:eq:s24:L3", **base),                                             # run-2 reference
        mom("mom:iv:s24:L3", **iv),
        mom("mom:iv:vt2:s24:L3", vol_target_daily=0.02, **iv),
        mom("mom:iv:vt3:s24:L3", vol_target_daily=0.03, **iv),
        mom("mom:iv:vt4:s24:L3", vol_target_daily=0.04, **iv),
        mom("mom:iv:own:vt3:s24:L3", vol_target_daily=0.03, gate="own", **iv),
        mom("mom:iv:vt3:s48:L3", vol_target_daily=0.03, weighting="inverse_vol", select_every_h=48, lookbacks_h=L3),
        mom("mom:iv:vt3:s24:L3:k4", vol_target_daily=0.03, k=4, buffer_rank=8, **iv),
        mom("mom:iv:vt3:s24:L3:k8", vol_target_daily=0.03, k=8, buffer_rank=16, **iv),
    ]


def pct(x, q):
    return float(np.nanpercentile(x, q))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-09-19")
    ap.add_argument("--oos", action="store_true", help="include the out-of-sample holdout")
    ap.add_argument("--every", type=int, default=None, help="override every strategy's decision cadence (hours)")
    ap.add_argument("--only", default=None, help="run only strategies whose name contains this substring")
    args = ap.parse_args()
    end = CACHE_END if args.oos else IN_SAMPLE_END

    universe, rules, prices = load(args.start, end)
    print(f"{len(universe)} assets, {prices.close.index[0]:%Y-%m-%d} -> {prices.close.index[-1]:%Y-%m-%d %H:%M} UTC"
          f"{'  [INCLUDES OOS HOLDOUT]' if args.oos else '  (in-sample; holdout hidden)'}\n")
    RESULTS.mkdir(parents=True, exist_ok=True)

    windows, results = {}, {}
    for strat, every in strategies(universe):
        if args.only and args.only not in strat.name and strat.name != "hold:BTC/USD":
            continue
        t0 = time.time()
        assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
        res = simulate(prices, strat, rules, SimConfig(decision_every_h=args.every or every))
        w = window_metrics(res.equity)
        windows[strat.name], results[strat.name] = w, res
        safe = "".join(c if c.isalnum() else "_" for c in strat.name)
        w.to_csv(RESULTS / f"{safe}_windows.csv")
        print(f"  {strat.name:14} simulated in {time.time()-t0:4.1f}s, {len(res.trades)} trades")

    bench = windows["hold:BTC/USD"]["ret"]
    beats = {}
    print(f"\n{'strategy':24} {'medR':>7} {'p10R':>7} {'p90R':>7} {'worstR':>7} {'%R>0':>5} {'%>BTC':>5} | "
          f"{'medMDD':>7} {'p90MDD':>7} | {'Sharpe':>7} {'Sortino':>8} {'Calmar':>7} | {'total':>8} {'maxDD':>7} {'fees':>6}")
    print(f"{'':24} (fees = total commissions / average equity over the sample)")
    for name, w in windows.items():
        res = results[name]
        eq = res.equity
        total = eq.iloc[-1] / eq.iloc[0] - 1
        maxdd = ((eq / eq.cummax()) - 1).min()
        fees = sum(t.fee for t in res.trades) / eq.mean()          # relative to average equity, not initial
        beats[name] = (w["ret"] > bench.reindex(w.index)).mean() * 100
        print(f"{name:24} {pct(w.ret,50)*100:6.2f}% {pct(w.ret,10)*100:6.2f}% {pct(w.ret,90)*100:6.2f}% "
              f"{w.ret.min()*100:6.2f}% {(w.ret>0).mean()*100:4.0f}% {beats[name]:4.0f}% | "
              f"{pct(w.mdd,50)*100:6.2f}% {pct(w.mdd,90)*100:6.2f}% | "
              f"{pct(w.sharpe,50):7.2f} {pct(w.sortino,50):8.2f} {pct(w.calmar,50):7.2f} | "
              f"{total*100:+7.1f}% {maxdd*100:6.1f}% {fees*100:5.2f}%")

    comp = rank_composite(windows)
    print("\nScreen 3 proxy: rank-normalised composite (0.4 Sortino + 0.3 Sharpe + 0.3 Calmar), median over windows;"
          "\nScreen 2 proxy: share of windows beating BTC hold.")
    for name, score in comp.sort_values(ascending=False).items():
        print(f"  {name:24} composite {score:.3f}   beats BTC {beats[name]:3.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
