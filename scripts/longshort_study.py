"""PRE-REGISTERED STUDY (2026-09-17): a short leg on the bottom of the ranking.

Why. The rules allow a 1x short, and the book is long-only. A BTC hedge went through the harness (hedge_study.py) and
was rejected; shorting the ranking's losers was only ever tried in a daily throwaway spike (short leg -27% in-sample,
-30% post-May; a long/short book Sharpe 2.5 in-sample and 0.4 after). That spike overstated the hedge's benefit,
so its verdict on the short leg is a hint, not a result. This is the harness test, so that "long-only by evidence"
is true of both short families.

Assumptions, as in the hedge study and unverified on the exchange: a short is a SELL beyond the holding, valued as a
negative quantity at price; 0.1% commission both ways; no borrow cost; gross exposure capped at 1x; every liquid
pair can be shorted.

Family, on the entry's settings (equal weight, 3%/day target on the signed book, K=6 longs, daily selection):
  ls25 / ls50     short the bottom 6 of the ranking with 25% / 50% of gross (50% = dollar-neutral), hysteresis 12
  ls25n / ls50n   the same, shorting only names whose momentum score is negative
  short_only      100% of gross in the short leg: the leg on its own, for the record
  core:ls50       the fallback core's settings (inverse-vol, 2%) with a 50% short leg, for the record

Pass rule versus the entry, in-sample windows, fixed before running:
  1. total return not lower;
  2. p10 and worst fortnight not worse by more than 2 points;
  3. median Sharpe and Sortino not lower by more than 0.05;
  4. top-40%-of-field rate in BTC-up and in BTC-down fortnights each not lower by more than 3 points;
  5. plateau: 25% and 50% agree in direction;
  6. direction holds on windows starting after 2026-05-15 (unsealed; consistency only).
If nothing passes, the book stays long-only and the README's claim is backed by the harness for both families.

RESULT OF RUN 1 (2026-09-17): every configuration fails rule 4 and passes the rest. The short leg alone loses (-24%
in-sample, -19% post-May, worst fortnight -35%), as the spike said. As 25% of gross it is a different thing: median
+1.38 -> +2.17%, p10 -10.3 -> -7.0%, worst -23.3 -> -18.3%, median 14-day drawdown 6.8 -> 4.6% (the core's), Sharpe
1.04 -> 2.08, Sortino 1.68 -> 3.85, Calmar 0.20 -> 0.50, total +176 -> +222%, and the same direction post-May (Sharpe
1.59 -> 2.16). The price is rally rank: top-40% of the field in BTC-up fortnights 52 -> 44% (post-May 45 -> 33%). The
50% share is not robust post-May (Sharpe 0.81), which is what the spike had seen. `--battery` (added after run 1,
labelled post-hoc) is the robustness pass the entry had: neighbouring shares, short count, K, selection hour, the
core's settings, and whether the short leg lets a higher volatility target win the rally rank back.

RESULT OF THE BATTERY: the short share is a smooth dial (15/25/35%: Sharpe 1.38/2.08/2.43, p10 -8.6/-7.0/-5.1%, top-40%
in BTC-up 47/44/39%); 4, 6 or 8 shorts all work; at K=8 longs Sharpe is 1.28 against the entry's 0.80 at K=8. At the
12:00 selection hour the tails are still much better (p10 -9.4 -> -6.5%, worst -22.2 -> -15.8%) but Sharpe moves only
1.30 -> 1.39: the tail gain is robust, the ratio doubling is partly hour luck. A higher target (4%, 5%) does not buy
the rally rank back (45%, 46%) because the 1x cap on gross binds. Not adopted: every number rests on exchange mechanics
the API documents do not describe. Path: build engine support behind a flag, paper-trade it, test one real short on
the test account, adopt only if the mechanics match the assumptions at the top of this file.

  .venv\\Scripts\\python.exe scripts\\longshort_study.py
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
ENTRY = dict(pairs=LIQUID, select_every_h=24, lookbacks_h=(72, 168, 336), weighting="equal", vol_target_daily=0.03, **EWMA)
CORE = dict(pairs=LIQUID, select_every_h=24, lookbacks_h=(72, 168, 336), weighting="inverse_vol",
            vol_target_daily=0.02, **EWMA)
SHORT = dict(short_k=6, short_buffer_rank=12)


def strategies():
    yield "entry", Momentum(MomentumParams(**ENTRY), name="entry")
    yield "ls25", Momentum(MomentumParams(**ENTRY, **SHORT, short_share=0.25), name="ls25")
    yield "ls50", Momentum(MomentumParams(**ENTRY, **SHORT, short_share=0.5), name="ls50")
    yield "ls25n", Momentum(MomentumParams(**ENTRY, **SHORT, short_share=0.25, short_negative_only=True), name="ls25n")
    yield "ls50n", Momentum(MomentumParams(**ENTRY, **SHORT, short_share=0.5, short_negative_only=True), name="ls50n")
    yield "short_only", Momentum(MomentumParams(**ENTRY, **SHORT, short_share=1.0), name="short_only")
    yield "core:ls50", Momentum(MomentumParams(**CORE, **SHORT, short_share=0.5), name="core:ls50")


def battery():
    e = ENTRY
    yield "entry", Momentum(MomentumParams(**e), name="entry")
    yield "ls25", Momentum(MomentumParams(**e, **SHORT, short_share=0.25), name="ls25")
    yield "ls15", Momentum(MomentumParams(**e, **SHORT, short_share=0.15), name="ls15")
    yield "ls35", Momentum(MomentumParams(**e, **SHORT, short_share=0.35), name="ls35")
    yield "ls25:s4", Momentum(MomentumParams(**e, short_k=4, short_buffer_rank=8, short_share=0.25), name="ls25:s4")
    yield "ls25:s8", Momentum(MomentumParams(**e, short_k=8, short_buffer_rank=16, short_share=0.25), name="ls25:s8")
    yield "ls25:k8", Momentum(MomentumParams(**{**e, "k": 8, "buffer_rank": 16}, **SHORT, short_share=0.25), name="ls25:k8")
    yield "ls25:h12", Momentum(MomentumParams(**e, **SHORT, short_share=0.25, select_hour_utc=12), name="ls25:h12")
    yield "ls25:vt4", Momentum(MomentumParams(**{**e, "vol_target_daily": 0.04}, **SHORT, short_share=0.25), name="ls25:vt4")
    yield "ls25:vt5", Momentum(MomentumParams(**{**e, "vol_target_daily": 0.05}, **SHORT, short_share=0.25), name="ls25:vt5")
    yield "core:ls25", Momentum(MomentumParams(**CORE, **SHORT, short_share=0.25), name="core:ls25")


def run(prices, rules, strat, every=1):
    assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
    return simulate(prices, strat, rules, SimConfig(decision_every_h=every, allow_short=True))


def pct(x, q):
    return float(np.nanpercentile(x, q))


def report(title, rows, sample, btc_ret):
    print(f"\n=== {title}: {len(sample)} windows ===")
    head = ("strategy", "medR", "p10R", "worst", "p90R", "%>BTC", "top40", "up", "dn", "|", "BTC>10%:medR", "top40",
            "|", "Sharpe", "Sortno", "Calmar", "|", "total", "maxDD", "fees", "long%", "short%", "gross", "act")
    print("{:11} {:>7} {:>7} {:>7} {:>7} {:>5} {:>5} {:>4} {:>4} {} {:>12} {:>5} {} {:>6} {:>6} {:>6} {} {:>7} {:>6} "
          "{:>5} {:>5} {:>6} {:>5} {:>5}".format(*head))
    b = btc_ret.reindex(sample)
    up, big = b > 0, b > 0.10
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
        print(f"{name:11} {pct(w.ret, 50) * 100:6.2f}% {pct(w.ret, 10) * 100:6.2f}% {w.ret.min() * 100:6.2f}% "
              f"{pct(w.ret, 90) * 100:6.2f}% {(w.ret > b).mean() * 100:4.0f}% {(fb >= .6).mean() * 100:4.0f}% "
              f"{(fb[up] >= .6).mean() * 100:3.0f}% {(fb[~up] >= .6).mean() * 100:3.0f}% | "
              f"{w.ret[big].median() * 100:11.1f}% {(fb[big] >= .6).mean() * 100:4.0f}% | "
              f"{pct(w.sharpe, 50):6.2f} {pct(w.sortino, 50):6.2f} {pct(w.calmar, 50):6.2f} | "
              f"{total * 100:+6.1f}% {maxdd * 100:5.1f}% {fees * 100:4.2f}% {long:4.0f}% {short:5.0f}% {gross:5.2f} "
              f"{int(pct(ad, 10)):2d}/{int(ad.median()):2d}")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--battery", action="store_true", help="the post-hoc robustness pass around ls25")
    args = ap.parse_args()
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
    for name, strat in (battery() if args.battery else strategies()):
        t0 = time.time()
        res = run(prices, rules, strat)
        w = window_metrics(res.equity)
        rows[name] = (w, res, field_beaten(w["ret"], prices.close, LIQUID), active_days_per_window(res.trades, w.index))
        safe = "".join(c if c.isalnum() else "_" for c in name)
        w.to_csv(RESULTS / f"longshort_{safe}_windows.csv")
        n_short = sum(1 for tr in res.trades if tr.side == "SELL")
        print(f"  {name:11} {len(res.trades):5d} trades  total {res.equity.iloc[-1] / res.equity.iloc[0] - 1:+7.1%}  "
              f"max gross {res.weights.abs().sum(axis=1).max():.2f}  min weight {res.weights.min().min():+.2f}  "
              f"({time.time() - t0:.0f}s)")
        sys.stdout.flush()

    all_w = rows["entry"][0].index
    in_sample = all_w[all_w <= pd.Timestamp(IN_SAMPLE_END, tz="UTC") - pd.Timedelta(days=14)]
    later = all_w[all_w >= pd.Timestamp("2026-05-15", tz="UTC")]
    report("IN-SAMPLE", rows, in_sample, btc_w["ret"])
    report("POST 2026-05-15 (unsealed; consistency only)", rows, later, btc_w["ret"])
    print("\ncolumns: top40 = share of windows beating >= 60% of the 35 hold-one-coin competitors (up/dn = BTC-up / "
          "BTC-down); long%/short% = mean long and short weight; gross = max longs+|shorts|; act = active days p10/median")
    return 0


if __name__ == "__main__":
    sys.exit(main())
