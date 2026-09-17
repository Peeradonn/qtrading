"""PRE-REGISTERED STUDY (2026-09-17): can the core keep its tails and still take part in big rallies?

The problem, measured. Screen 2 is a top-20-by-return gate, and against 34 hold-one-coin books the core is a
selloff specialist: in fortnights where BTC gains more than 10% it captures a median 60% of BTC's move, beats
under 40% of the field and reaches the top 40% of the field 24% of the time (0% when BTC gains over 20%); the
full-exposure twin captures 112% and reaches the top 40% in 80% of those fortnights, at the price of a −33% worst
fortnight. The cause is sizing, not signal: crypto rallies come with rising volatility, and a total-volatility
target cuts exposure into exactly the move the gate rewards.

Candidates, one parameter each, both aimed at the sizing rule and not at the signal:
  * downside targeting: size the book on downside deviation (EWMA of negative returns only, scaled by sqrt 2 so
    symmetric returns give the same number), so upside volatility no longer cuts exposure. This is also the
    natural rule when the score weights Sortino, which penalises downside deviation only. Plateau: 1.5 / 2 / 2.5%.
  * an exposure floor under the total-volatility target: never below 50% or 70% invested once anything is selected.

Pass rule versus the core, in-sample, fixed before running:
  1. top-40%-of-field rate in BTC-up fortnights at least 10 points above the core's (40%), and median capture
     of BTC's move in fortnights where BTC gains over 10% materially above the core's 60%;
  2. top-40% rate in BTC-down fortnights within 5 points of the core's (88%);
  3. p10 and worst fortnight no worse than the core's by more than 2 points; median Sharpe and Sortino no lower
     by more than 0.05;
  4. total return not below the core's;
  5. plateau across the parameter; direction holds on windows after 2026-05-15 (unsealed; consistency only).
Among passing configurations, prefer the highest overall top-40% rate (the gate is the objective here), then the
ratios. If nothing passes, the core stays and the rally exposure question is answered by the risk-on twin.

RESULT OF RUN 1 (2026-09-17): nothing passed rule 1. Downside targeting at 2% is a wash with the core on every
column (downside deviation rises in a crypto rally too); at 2.5% and with a 70% floor the book is 77-80% invested
yet reaches the top 40% of the field in only 22-30% of BTC>10% fortnights, while the tails give up 3-4 points.
What the table exposed: the core's inverse-vol WEIGHTING is a second brake -- at full exposure inverse-vol makes
+90% over the sample and equal weight +263%, because inverse-vol tilts to BTC and gold, which lag an alt rally.
Added after run 1, labelled post-hoc: equal weight with a volatility target ("eqvt"), the bridge between the core
and the twin that nobody had tested. Same pass rule.

  .venv\\Scripts\\python.exe scripts\\exposure_study.py
"""
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
    for vt in (0.015, 0.02, 0.025):
        yield f"down{vt * 100:g}", Momentum(MomentumParams(**{**CORE, "vol_target_daily": vt}, vol_target_on="downside"),
                                            name=f"down{vt * 100:g}")
    for floor in (0.5, 0.7):
        yield f"floor{floor:g}", Momentum(MomentumParams(**CORE, min_exposure=floor), name=f"floor{floor:g}")
    for vt in (0.02, 0.03, 0.04):                       # post-hoc: equal weight (the twin's tilt) with a vol target
        yield f"eqvt{vt * 100:g}", Momentum(MomentumParams(**RISKON, vol_target_daily=vt), name=f"eqvt{vt * 100:g}")
    # robustness around eqvt3 (post-hoc): neighbouring targets, K, and the selection hour -- the battery the core had
    yield "eqvt2.5", Momentum(MomentumParams(**RISKON, vol_target_daily=0.025), name="eqvt2.5")
    yield "eqvt3.5", Momentum(MomentumParams(**RISKON, vol_target_daily=0.035), name="eqvt3.5")
    yield "eqvt3k8", Momentum(MomentumParams(**{**RISKON, "k": 8, "buffer_rank": 16}, vol_target_daily=0.03), name="eqvt3k8")
    yield "eqvt3h12", Momentum(MomentumParams(**RISKON, vol_target_daily=0.03, select_hour_utc=12), name="eqvt3h12")


def run(prices, rules, strat, every=1):
    assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
    return simulate(prices, strat, rules, SimConfig(decision_every_h=every))


def pct(x, q):
    return float(np.nanpercentile(x, q))


def report(title, rows, sample, btc_ret):
    print(f"\n=== {title}: {len(sample)} windows ===")
    head = ("strategy", "medR", "p10R", "worst", "p90R", "%>BTC", "top40", "up", "dn", "|", "BTC>10%: n", "medR",
            "capture", "top40", "|", "Sharpe", "Sortno", "Calmar", "|", "total", "maxDD", "fees", "expo%", "act")
    print("{:10} {:>7} {:>7} {:>7} {:>7} {:>5} {:>5} {:>4} {:>4} {} {:>10} {:>7} {:>7} {:>5} {} {:>6} {:>6} {:>6} {} "
          "{:>7} {:>6} {:>5} {:>5} {:>5}".format(*head))
    b = btc_ret.reindex(sample)
    up, big = b > 0, b > 0.10
    for name, (w, res, fb, ad) in rows.items():
        w, fb, ad = w.reindex(sample), fb.reindex(sample), ad.reindex(sample)
        span = (res.equity.index >= sample[0]) & (res.equity.index <= sample[-1] + pd.Timedelta(days=14))
        eq = res.equity[span]
        total = eq.iloc[-1] / eq.iloc[0] - 1
        maxdd = ((eq / eq.cummax()) - 1).min()
        fees = sum(t.fee for t in res.trades if eq.index[0] <= t.time <= eq.index[-1]) / eq.mean()
        expo = res.weights.loc[eq.index].sum(axis=1).mean() * 100
        capture = (w.ret[big] / b[big]).median() * 100 if big.any() else np.nan
        print(f"{name:10} {pct(w.ret, 50) * 100:6.2f}% {pct(w.ret, 10) * 100:6.2f}% {w.ret.min() * 100:6.2f}% "
              f"{pct(w.ret, 90) * 100:6.2f}% {(w.ret > b).mean() * 100:4.0f}% {(fb >= .6).mean() * 100:4.0f}% "
              f"{(fb[up] >= .6).mean() * 100:3.0f}% {(fb[~up] >= .6).mean() * 100:3.0f}% | "
              f"{int(big.sum()):10d} {w.ret[big].median() * 100:6.1f}% {capture:6.0f}% {(fb[big] >= .6).mean() * 100:4.0f}% | "
              f"{pct(w.sharpe, 50):6.2f} {pct(w.sortino, 50):6.2f} {pct(w.calmar, 50):6.2f} | "
              f"{total * 100:+6.1f}% {maxdd * 100:5.1f}% {fees * 100:4.2f}% {expo:4.0f}% {int(pct(ad, 10)):2d}/{int(ad.median()):2d}")


def biggest_rallies(rows, sample, btc_ret, names, n=8):
    b = btc_ret.reindex(sample)
    print(f"\n=== the {n} biggest BTC fortnights in this sample: each book's return and share of the field beaten ===")
    print(f"{'start':10} {'BTC':>7} | " + " | ".join(f"{k:>16}" for k in names))
    for t in b.nlargest(n).index:
        cells = " | ".join(f"{rows[k][0]['ret'].get(t, np.nan) * 100:6.1f}% ({rows[k][2].get(t, np.nan) * 100:3.0f}%)" for k in names)
        print(f"{t:%Y-%m-%d} {b[t] * 100:6.1f}% | {cells}")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="comma-separated substrings; run only matching strategies")
    args = ap.parse_args()
    wanted = args.only.split(",") if args.only else None
    snapshot = load_snapshot(SNAPSHOT)
    universe = [a for a in build_universe(snapshot) if a.pair in LIQUID]
    rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
    store = PriceStore(cache_dir=ROOT / "data" / "cache",
                       sources={"binance": BinanceSource(), "yahoo": YahooSource()})
    prices = store.closes(universe, pd.Timestamp(START, tz="UTC"), pd.Timestamp(CACHE_END, tz="UTC"),
                          deadline=lambda: True)
    print(f"{len(universe)} assets, {prices.close.index[0]:%Y-%m-%d} -> {prices.close.index[-1]:%Y-%m-%d %H:%M} UTC\n")
    RESULTS.mkdir(parents=True, exist_ok=True)

    rows = {}
    btc = run(prices, rules, BuyAndHold(BTC), every=24)
    btc_w = window_metrics(btc.equity)
    rows["hold:BTC"] = (btc_w, btc, field_beaten(btc_w["ret"], prices.close, LIQUID),
                        active_days_per_window(btc.trades, btc_w.index))
    for name, strat in strategies():
        if wanted and not any(w in name for w in wanted):
            continue
        t0 = time.time()
        res = run(prices, rules, strat)
        w = window_metrics(res.equity)
        rows[name] = (w, res, field_beaten(w["ret"], prices.close, LIQUID), active_days_per_window(res.trades, w.index))
        w.to_csv(RESULTS / f"exposure_{name}_windows.csv")
        print(f"  {name:10} {len(res.trades):5d} trades  total {res.equity.iloc[-1] / res.equity.iloc[0] - 1:+7.1%}  "
              f"({time.time() - t0:.0f}s)")
        sys.stdout.flush()

    all_w = rows["core"][0].index
    in_sample = all_w[all_w <= pd.Timestamp(IN_SAMPLE_END, tz="UTC") - pd.Timedelta(days=14)]
    later = all_w[all_w >= pd.Timestamp("2026-05-15", tz="UTC")]
    btc_ret = rows["hold:BTC"][0]["ret"]
    names = [n for n in ("core", "riskon", "down2", "floor0.7", "eqvt2", "eqvt3", "eqvt4", "eqvt3k8", "eqvt3h12") if n in rows]
    report("IN-SAMPLE", rows, in_sample, btc_ret)
    biggest_rallies(rows, in_sample, btc_ret, names)
    report("POST 2026-05-15 (unsealed; consistency only)", rows, later, btc_ret)
    biggest_rallies(rows, later, btc_ret, names, n=4)
    print("\ncolumns: top40 = share of windows beating >= 60% of the 35 hold-one-coin competitors (up/dn = BTC-up / "
          "BTC-down); 'BTC>10%' block = fortnights where BTC gained over 10%: count, the book's median return, median "
          "share of BTC's move captured, top-40% rate; expo% = mean invested weight; act = active days p10/median")
    return 0


if __name__ == "__main__":
    sys.exit(main())
