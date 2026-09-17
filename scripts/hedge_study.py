"""PRE-REGISTERED STUDY (2026-09-17): a BTC short against the long book -- the first use of the rules' "1x short".

Assumptions, to be verified on the competition account before anything goes live: a short is a SELL beyond the
holding and is valued as a negative quantity at price; commission 0.1% both ways; no borrow cost; gross exposure
(longs + |shorts|) capped at 1x equity; BTC/USD can be shorted; shorts fill at the same price as longs.

Hypothesis. The long book's excess return over BTC (it beats BTC in ~56% of fortnights) is selection alpha; a BTC
short removes market beta and keeps the alpha. A throwaway spike (daily decisions, equal-weight legs, no vol
target) put the hedged book ahead of the core on total return and every ratio with similar tails. This is the
harness test: hourly decisions, real fees, precision and minimum-order rules.

Family. hedge_ratio h in {0.25, 0.5, 0.75, 1.0} on two long legs: the core (inverse-vol, 2%/day vol target) and
the risk-on twin (equal weight, full exposure). Gross is capped at 1.0 by scaling the whole book, so on the
risk-on leg h=0.5 means long 2/3, short 1/3.

Pass rule versus the core, in-sample, fixed before running:
  1. total return not lower than the core's (the stated Screen 2 objective: keep return high);
  2. p10 and worst fortnight not worse than the core's;
  3. median Sharpe and Sortino higher than the core's;
  4. top-40%-of-field rate not lower (Screen 2 proxy);
  5. plateau in h: neighbouring ratios agree; choose the middle of a plateau, never the peak;
  6. consistency: the direction of 1-3 holds on windows starting after 2026-05-15 (unsealed; consistency only).
Among passing configurations, prefer the higher total return on the plateau, because the two legs trade return
for tails and the user has said which side to favour. If nothing passes, the core stays.

  .venv\\Scripts\\python.exe scripts\\hedge_study.py [--check-equity path/to/equity.csv]
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from qtrading.backtest.checks import assert_no_lookahead
from qtrading.backtest.metrics import active_days_per_window, field_beaten, window_metrics
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
RESULTS = ROOT / "data" / "results"
START, IN_SAMPLE_END, CACHE_END = "2024-09-19", "2026-05-14 23:00", "2026-09-14 13:00"
BTC = "BTC/USD"
RATIOS = (0.25, 0.5, 0.75, 1.0)

LIQUID = tuple(f"{c}/USD" for c in (
    "BTC ETH ZEC SOL XRP BNB FIL SUI NEAR DOGE UNI TRX TAO ADA PEPE LINK PUMP LTC ARB ENA WLD TRUMP AVAX AAVE "
    "FET XLM ICP PAXG ONDO WLFI CAKE DOT APT XPL PENGU").split())
EWMA = dict(vol_model="ewma", ewma_lambda=0.99)
CORE = dict(pairs=LIQUID, select_every_h=24, lookbacks_h=(72, 168, 336), weighting="inverse_vol",
            vol_target_daily=0.02, **EWMA)
RISKON = dict(pairs=LIQUID, select_every_h=24, lookbacks_h=(72, 168, 336), **EWMA)


def strategies():
    yield "core", Momentum(MomentumParams(**CORE), name="core")
    yield "riskon", Momentum(MomentumParams(**RISKON), name="riskon")
    for h in RATIOS:
        yield f"core:hg{h:g}", Momentum(MomentumParams(**CORE, hedge_pair=BTC, hedge_ratio=h), name=f"core:hg{h:g}")
    for h in RATIOS:
        yield f"riskon:hg{h:g}", Momentum(MomentumParams(**RISKON, hedge_pair=BTC, hedge_ratio=h),
                                          name=f"riskon:hg{h:g}")


def run(prices, rules, strat, every=1):
    assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
    return simulate(prices, strat, rules, SimConfig(decision_every_h=every, allow_short=True))


def pct(x, q):
    return float(np.nanpercentile(x, q))


def report(title, rows, sample, btc_ret, core_ret):
    print(f"\n=== {title}: {len(sample)} windows ===")
    head = ("strategy", "medR", "p10R", "p5R", "worst", "p90R", "%>BTC", "top40", "up", "dn", "|", "medMDD",
            "Sharpe", "Sortno", "Calmar", "|", "total", "maxDD", "fees", "|", "long%", "short%", "gross", "act")
    print("{:14} {:>7} {:>7} {:>7} {:>7} {:>7} {:>5} {:>5} {:>4} {:>4} {} {:>6} {:>6} {:>6} {:>6} {} {:>7} {:>6} "
          "{:>5} {} {:>5} {:>6} {:>5} {:>5}".format(*head))
    up = btc_ret.reindex(sample) > 0
    for name, (w, res, fb, ad) in rows.items():
        w, fb, ad = w.reindex(sample), fb.reindex(sample), ad.reindex(sample)
        span = (res.equity.index >= sample[0]) & (res.equity.index <= sample[-1] + pd.Timedelta(days=14))
        eq = res.equity[span]
        total = eq.iloc[-1] / eq.iloc[0] - 1
        maxdd = ((eq / eq.cummax()) - 1).min()
        fees = sum(t.fee for t in res.trades if eq.index[0] <= t.time <= eq.index[-1]) / eq.mean()
        wts = res.weights.loc[eq.index]
        long = wts.clip(lower=0).sum(axis=1).mean() * 100
        short = -wts.clip(upper=0).sum(axis=1).mean() * 100
        gross = wts.abs().sum(axis=1).max()
        beats = (w.ret > btc_ret.reindex(sample)).mean() * 100
        print(f"{name:14} {pct(w.ret, 50) * 100:6.2f}% {pct(w.ret, 10) * 100:6.2f}% {pct(w.ret, 5) * 100:6.2f}% "
              f"{w.ret.min() * 100:6.2f}% {pct(w.ret, 90) * 100:6.2f}% {beats:4.0f}% {(fb >= .6).mean() * 100:4.0f}% "
              f"{(fb[up] >= .6).mean() * 100:3.0f}% {(fb[~up] >= .6).mean() * 100:3.0f}% | "
              f"{pct(w.mdd, 50) * 100:5.2f}% {pct(w.sharpe, 50):6.2f} {pct(w.sortino, 50):6.2f} {pct(w.calmar, 50):6.2f} | "
              f"{total * 100:+6.1f}% {maxdd * 100:5.1f}% {fees * 100:4.2f}% | {long:4.0f}% {short:5.0f}% {gross:5.2f} "
              f"{int(pct(ad, 10)):2d}/{int(ad.median()):2d}")


def explain_worst(rows, sample, prices, names, n=8):
    """The n worst core fortnights: each strategy's return, BTC over the window, and each book's short weight at
    the window start."""
    daily = prices.close[prices.close.index.hour == 0]
    fwd = daily.shift(-14) / daily - 1
    core_ret = rows["core"][0]["ret"].reindex(sample)
    print(f"\n=== the {n} worst core fortnights in this sample ===")
    print(f"{'start':10} " + " ".join(f"{k:>13}" for k in names) + f" {'| BTC':>9} |"
          + " ".join(f"{k + ' short%':>18}" for k in names))
    for t in core_ret.nsmallest(n).index:
        rets = " ".join(f"{rows[k][0]['ret'].get(t, np.nan) * 100:12.2f}%" for k in names)
        shorts = " ".join(f"{-rows[k][1].weights.loc[t].clip(upper=0).sum() * 100:17.0f}%" for k in names)
        print(f"{t:%Y-%m-%d} {rets} {fwd[BTC].get(t, np.nan) * 100:8.2f}% | {shorts}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-equity", default=None, help="equity.csv from before the change; core must match")
    args = ap.parse_args()

    snapshot = load_snapshot(SNAPSHOT)
    universe = [a for a in build_universe(snapshot) if a.pair in LIQUID]
    rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
    store = PriceStore(cache_dir=ROOT / "data" / "cache",
                       sources={"binance": BinanceSource(), "yahoo": YahooSource()})
    prices = store.closes(universe, pd.Timestamp(START, tz="UTC"), pd.Timestamp(CACHE_END, tz="UTC"),
                          deadline=lambda: True)
    print(f"{len(universe)} assets, {prices.close.index[0]:%Y-%m-%d} -> {prices.close.index[-1]:%Y-%m-%d %H:%M} UTC; "
          f"in-sample windows end by {IN_SAMPLE_END}, later windows are the unsealed post-May-15 period\n")
    RESULTS.mkdir(parents=True, exist_ok=True)

    rows = {}
    btc = run(prices, rules, BuyAndHold(BTC), every=24)
    btc_w = window_metrics(btc.equity)
    rows["hold:BTC"] = (btc_w, btc, field_beaten(btc_w["ret"], prices.close, LIQUID),
                        active_days_per_window(btc.trades, btc_w.index))
    for name, strat in strategies():
        t0 = time.time()
        res = run(prices, rules, strat)
        w = window_metrics(res.equity)
        rows[name] = (w, res, field_beaten(w["ret"], prices.close, LIQUID), active_days_per_window(res.trades, w.index))
        safe = "".join(c if c.isalnum() else "_" for c in name)
        w.to_csv(RESULTS / f"hedge_{safe}_windows.csv")
        total = res.equity.iloc[-1] / res.equity.iloc[0] - 1
        print(f"  {name:14} {len(res.trades):5d} trades  total {total:+7.1%}  max gross "
              f"{res.weights.abs().sum(axis=1).max():.2f}  ({time.time() - t0:.0f}s)")
        sys.stdout.flush()

    if args.check_equity:
        old = pd.read_csv(args.check_equity, index_col=0, parse_dates=True)
        for name in ("core", "riskon"):
            if name not in old:
                continue
            new = rows[name][1].equity
            common = old.index.intersection(new.index)
            gap = (new.reindex(common) / old[name].reindex(common) - 1).abs().max()
            print(f"regression check: {name} equity vs the pre-change run, max |rel diff| = {gap:.2e} "
                  f"{'OK' if gap < 1e-9 else 'MISMATCH'}")

    all_w = rows["core"][0].index
    in_sample = all_w[all_w <= pd.Timestamp(IN_SAMPLE_END, tz="UTC") - pd.Timedelta(days=14)]
    later = all_w[all_w >= pd.Timestamp("2026-05-15", tz="UTC")]
    btc_ret, core_ret = rows["hold:BTC"][0]["ret"], rows["core"][0]["ret"]
    names = ["core", "riskon", "core:hg0.5", "riskon:hg0.5", "riskon:hg0.75"]
    report("IN-SAMPLE", rows, in_sample, btc_ret, core_ret)
    explain_worst(rows, in_sample, prices, names)
    report("POST 2026-05-15 (unsealed; consistency only)", rows, later, btc_ret, core_ret)
    explain_worst(rows, later, prices, names, n=5)
    print("\ncolumns: top40 = share of windows beating >= 60% of the 35 hold-one-coin competitors (up/dn = BTC-up / "
          "BTC-down windows); long%/short% = mean long and short weight; gross = max longs+|shorts|; "
          "act = active days p10/median")
    return 0


if __name__ == "__main__":
    sys.exit(main())
