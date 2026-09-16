"""Run strategies through the competition-faithful harness and print the comparison table.

Run:  .venv\\Scripts\\python.exe scripts\\run_backtest.py [--oos] [--every N] [--only substr] [--funding]
Uses only the local cache (fixed --start/--end so no network is touched). The last months are held out as
out-of-sample and hidden unless --oos is passed. --funding loads the cached perpetual funding panel.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from qtrading.backtest.checks import assert_no_lookahead
from qtrading.backtest.metrics import active_days_per_window, rank_composite, window_metrics
from qtrading.backtest.simulator import SimConfig, simulate
from qtrading.data.binance import BinanceSource
from qtrading.data.store import PriceStore
from qtrading.data.universe import build_universe, load_snapshot
from qtrading.data.yahoo import YahooSource
from qtrading.roostoo.models import PairInfo
from qtrading.strategy.baselines import BuyAndHold
from qtrading.strategy.momentum import Momentum, MomentumParams

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"
CACHE = ROOT / "data" / "cache"
RESULTS = ROOT / "data" / "results"

IN_SAMPLE_END = "2026-05-14 23:00"     # holdout starts 2026-05-15
CACHE_END = "2026-09-14 13:00"         # last bar in the cache; keeps runs offline and reproducible

# Crypto pairs with > $5M 24h volume on Roostoo at the 2026-09-14 snapshot (the spike's universe) + PAXG.
LIQUID = tuple(f"{c}/USD" for c in (
    "BTC ETH ZEC SOL XRP BNB FIL SUI NEAR DOGE UNI TRX TAO ADA PEPE LINK PUMP LTC ARB ENA WLD TRUMP AVAX AAVE "
    "FET XLM ICP PAXG ONDO WLFI CAKE DOT APT XPL PENGU").split())
# Tokenized stocks with > $1M 24h volume on Roostoo at the snapshot.
STOCKS = tuple(f"{c}/USD" for c in "SNDKB CRCLB SPCXB NVDAB MSTRB MUB SKHYB TSLAB LITEB GOOGLB INTCB".split())


def load(start, end, with_funding: bool):
    snapshot = load_snapshot(SNAPSHOT)
    universe = build_universe(snapshot)
    rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
    store = PriceStore(cache_dir=CACHE, sources={"binance": BinanceSource(), "yahoo": YahooSource()})
    t0, t1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    prices = store.closes(universe, t0, t1)
    if with_funding:
        perps = [a for a in universe if a.source == "binance" and a.pair in LIQUID]
        prices.extra["funding"] = store.funding(perps, t0, t1)
    return universe, rules, prices


def strategies():
    """(strategy, decision cadence in hours). Momentum decides hourly like the live bot."""
    def mom(name, pairs=LIQUID, **kw):
        return Momentum(MomentumParams(pairs=pairs, **kw), name=name), 1

    # Run 4 (2026-09-15): vol target plateau is 1.5-2.0 (2.5 falls off); K=6 > K=8; residual momentum at 0.5 and
    # volume confirmation each lift Sharpe/Sortino with return and tails unchanged; the funding filter at 0.05%/8h
    # never triggered; stocks add diversification but selecting at 15:00 UTC hurt the crypto book too.
    # Run 5: do the two positives stack; does the funding filter bind at a realistic threshold; how sensitive is the
    # core to its selection hour (an overfitting check on the 00:00 UTC choice).
    L3 = (72, 168, 336)
    core = dict(select_every_h=24, lookbacks_h=L3, weighting="inverse_vol", vol_target_daily=0.02)
    both = dict(residual_weight=0.5, volume_confirm=True)
    riskon = dict(select_every_h=24, lookbacks_h=L3)                     # same signal, equal weight, no vol target
    # 2026-09-16: the EWMA volatility model won the pre-registered forecast-error experiment (see the design doc).
    # The accept rule's second half is this: adopting it must not degrade the backtest.
    # Plateau check on the risk-on twin, where the EWMA volatility model produced a large in-sample jump.
    # The shipped configuration, after the volatility-forecast experiment of 2026-09-16.
    ewma = dict(vol_model="ewma", ewma_lambda=0.99)
    return [
        (BuyAndHold("BTC/USD"), 24),
        mom("core", **core, **ewma),
        mom("core:trailing (old)", **core),
        mom("riskon", **riskon, **ewma),
    ]


def pct(x, q):
    return float(np.nanpercentile(x, q))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-09-19")
    ap.add_argument("--oos", action="store_true", help="include the out-of-sample holdout")
    ap.add_argument("--every", type=int, default=None, help="override every strategy's decision cadence (hours)")
    ap.add_argument("--only", default=None, help="run only strategies whose name contains this substring")
    ap.add_argument("--funding", action="store_true", help="load the cached funding panel into prices.extra")
    ap.add_argument("--report-from", default=None, help="score only windows starting on/after this date (UTC)")
    args = ap.parse_args()
    end = CACHE_END if args.oos else IN_SAMPLE_END

    universe, rules, prices = load(args.start, end, args.funding)
    print(f"{len(universe)} assets, {prices.close.index[0]:%Y-%m-%d} -> {prices.close.index[-1]:%Y-%m-%d %H:%M} UTC"
          f"{'  [INCLUDES OOS HOLDOUT]' if args.oos else '  (in-sample; holdout hidden)'}"
          f"{'  +funding' if args.funding else ''}\n")
    RESULTS.mkdir(parents=True, exist_ok=True)

    windows, results, active = {}, {}, {}
    for strat, every in strategies():
        if args.only and args.only not in strat.name and strat.name != "hold:BTC/USD":
            continue
        t0 = time.time()
        assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
        res = simulate(prices, strat, rules, SimConfig(decision_every_h=args.every or every))
        w = window_metrics(res.equity)
        windows[strat.name], results[strat.name] = w, res
        active[strat.name] = active_days_per_window(res.trades, w.index)
        safe = "".join(c if c.isalnum() else "_" for c in strat.name)
        w.to_csv(RESULTS / f"{safe}_windows.csv")
        print(f"  {strat.name:20} simulated in {time.time()-t0:5.1f}s, {len(res.trades)} trades")
        sys.stdout.flush()

    if args.report_from:
        cutoff = pd.Timestamp(args.report_from, tz="UTC")
        windows = {n: w[w.index >= cutoff] for n, w in windows.items()}
        active = {n: a[a.index >= cutoff] for n, a in active.items()}
        print(f"\nscoring {len(next(iter(windows.values())))} windows starting on/after {cutoff:%Y-%m-%d}")
    bench = windows["hold:BTC/USD"]["ret"]
    beats = {}
    print(f"\n{'strategy':20} {'medR':>7} {'p10R':>7} {'p90R':>7} {'worstR':>7} {'%R>0':>5} {'%>BTC':>5} | "
          f"{'medMDD':>7} {'p90MDD':>7} | {'Sharpe':>7} {'Sortino':>8} {'Calmar':>7} | {'total':>8} {'maxDD':>7} {'fees':>6} | "
          f"{'actDays':>8}")
    print(f"{'':20} (fees = commissions / average equity; actDays = p10/median trading days per 14-day window)")
    for name, w in windows.items():
        res = results[name]
        eq = res.equity
        total = eq.iloc[-1] / eq.iloc[0] - 1
        maxdd = ((eq / eq.cummax()) - 1).min()
        fees = sum(t.fee for t in res.trades) / eq.mean()
        beats[name] = (w["ret"] > bench.reindex(w.index)).mean() * 100
        ad = active[name]
        print(f"{name:20} {pct(w.ret,50)*100:6.2f}% {pct(w.ret,10)*100:6.2f}% {pct(w.ret,90)*100:6.2f}% "
              f"{w.ret.min()*100:6.2f}% {(w.ret>0).mean()*100:4.0f}% {beats[name]:4.0f}% | "
              f"{pct(w.mdd,50)*100:6.2f}% {pct(w.mdd,90)*100:6.2f}% | "
              f"{pct(w.sharpe,50):7.2f} {pct(w.sortino,50):8.2f} {pct(w.calmar,50):7.2f} | "
              f"{total*100:+7.1f}% {maxdd*100:6.1f}% {fees*100:5.2f}% | {int(pct(ad, 10)):3d}/{int(ad.median()):3d}")

    comp = rank_composite(windows)
    print("\nScreen 3 proxy: rank-normalised composite (0.4 Sortino + 0.3 Sharpe + 0.3 Calmar), median over windows;"
          "\nScreen 2 proxy: share of windows beating BTC hold.")
    for name, score in comp.sort_values(ascending=False).items():
        print(f"  {name:20} composite {score:.3f}   beats BTC {beats[name]:3.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
