"""PRE-REGISTERED STUDY (2026-09-18): how much of the backtest is universe-selection bias?

The question. The 35-pair universe was chosen from Roostoo's 24h traded volume on 2026-09-14 -- the END of the
backtest sample -- and then run over the two years before it. Coins that launched during the sample and grew
liquid enough to clear a $5M floor by September 2026 are in the pool; coins that launched and died, or that were
liquid in 2024 and faded, are not. A momentum strategy buys recent winners, so a universe pre-filtered toward
survivors may hand it a better menu than it would have had in real time. Whitepaper section 8 does not list this,
and the look-ahead checker cannot catch it: the universe is a constant input to a run, not a signal within it.

Not blind, and said so up front. A per-pair cohort check was run first (2026-09-18) and pointed the other way:
all six mid-sample listings UNDERPERFORMED the median established pair over the windows the strategy could
actually trade them, by 2.5 to 32 points, because min_age_h = 720 bars a new listing for its first 30 days and so
excludes the launch spike. This study is the portfolio-level version of that check, and its expected direction is
therefore known in advance. It is evidence, not a sealed test.

Design. Six of the 35 pairs had no price at the in-sample start (2024-09-19): PENGU, TRUMP, ONDO, WLFI, PUMP and
XPL. "established" is the other 29. Both books are run on the SAME price panel, with only the selectable universe
changed, so the naive hold-one-coin competitor field is identical in both and the comparison is like for like.

  entry / entry:established    equal weight, 3%/day target   (the competition entry)
  core  / core:established     inverse vol, 2%/day target    (the fallback)

Reading the result. The 29-pair book is the strategy's return without the six names selection bias could have
favoured. If the 35-pair book is much higher, the headline numbers are inflated and section 8 needs the number.
If they are close, or the 29-pair book is higher, the bias is not what is driving the result and section 8 can
say so with evidence. Either way the outcome is recorded; nothing in the strategy changes on it, because the
universe is fixed before Oct 1 and the competition is out-of-sample by construction.

What this CANNOT measure: coins that never entered the universe at all -- delisted, or never listed by Roostoo.
They are absent from the snapshot and were never fetched, so the true survivorship set stays unmeasured.

  .venv\\Scripts\\python.exe scripts\\universe_bias_study.py
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
# no price at START: listed mid-sample, so their presence in the pool is a decision made with hindsight
LATE = ("PENGU/USD", "TRUMP/USD", "ONDO/USD", "WLFI/USD", "PUMP/USD", "XPL/USD")
ESTABLISHED = tuple(p for p in LIQUID if p not in LATE)

EWMA = dict(vol_model="ewma", ewma_lambda=0.99)
ENTRY = dict(select_every_h=24, lookbacks_h=(72, 168, 336), weighting="equal", vol_target_daily=0.03, **EWMA)
CORE = dict(select_every_h=24, lookbacks_h=(72, 168, 336), weighting="inverse_vol", vol_target_daily=0.02, **EWMA)


def run(prices, rules, strat, every=1):
    assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
    return simulate(prices, strat, rules, SimConfig(decision_every_h=every))


def pct(x, q):
    return float(np.nanpercentile(x, q))


def report(title, rows, sample, btc_ret):
    print(f"\n=== {title}: {len(sample)} windows ===")
    head = ("strategy", "medR", "p10R", "worst", "p90R", "%>BTC", "top40", "up", "dn", "|", "Sharpe", "Sortno",
            "Calmar", "|", "total", "maxDD", "fees", "expo%", "late%", "act")
    print("{:20} {:>7} {:>7} {:>7} {:>7} {:>5} {:>5} {:>4} {:>4} {} {:>6} {:>6} {:>6} {} {:>7} {:>6} {:>5} {:>5} "
          "{:>5} {:>5}".format(*head))
    b = btc_ret.reindex(sample)
    up = b > 0
    for name, (w, res, fb, ad) in rows.items():
        w, fb, ad = w.reindex(sample), fb.reindex(sample), ad.reindex(sample)
        span = (res.equity.index >= sample[0]) & (res.equity.index <= sample[-1] + pd.Timedelta(days=14))
        eq = res.equity[span]
        total = eq.iloc[-1] / eq.iloc[0] - 1
        maxdd = ((eq / eq.cummax()) - 1).min()
        fees = sum(t.fee for t in res.trades if eq.index[0] <= t.time <= eq.index[-1]) / eq.mean()
        wts = res.weights.loc[eq.index]
        expo = wts.sum(axis=1).mean() * 100
        late = wts[[p for p in LATE if p in wts.columns]].sum(axis=1).mean() * 100
        print(f"{name:20} {pct(w.ret, 50) * 100:6.2f}% {pct(w.ret, 10) * 100:6.2f}% {w.ret.min() * 100:6.2f}% "
              f"{pct(w.ret, 90) * 100:6.2f}% {(w.ret > b).mean() * 100:4.0f}% {(fb >= .6).mean() * 100:4.0f}% "
              f"{(fb[up] >= .6).mean() * 100:3.0f}% {(fb[~up] >= .6).mean() * 100:3.0f}% | "
              f"{pct(w.sharpe, 50):6.2f} {pct(w.sortino, 50):6.2f} {pct(w.calmar, 50):6.2f} | "
              f"{total * 100:+6.1f}% {maxdd * 100:5.1f}% {fees * 100:4.2f}% {expo:4.0f}% {late:4.0f}% "
              f"{int(pct(ad, 10)):2d}/{int(ad.median()):2d}")


def main() -> int:
    snapshot = load_snapshot(SNAPSHOT)
    rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
    crypto = [a for a in build_universe(snapshot) if a.pair in LIQUID]
    store = PriceStore(cache_dir=ROOT / "data" / "cache", sources={"binance": BinanceSource(), "yahoo": None})
    t0, t1 = pd.Timestamp(START, tz="UTC"), pd.Timestamp(CACHE_END, tz="UTC")
    prices = store.closes(crypto, t0, t1, deadline=lambda: True)               # cache only, no network
    print(f"{len(LIQUID)} pairs, {prices.close.index[0]:%Y-%m-%d} -> {prices.close.index[-1]:%Y-%m-%d %H:%M}")
    print(f"excluded as listed mid-sample ({len(LATE)}): {', '.join(p.split('/')[0] for p in LATE)}")
    print(f"established universe: {len(ESTABLISHED)} pairs\n")
    RESULTS.mkdir(parents=True, exist_ok=True)

    def sim(name, params, pairs):
        t = time.time()
        res = run(prices, rules, Momentum(MomentumParams(pairs=tuple(pairs), **params), name=name))
        w = window_metrics(res.equity)
        safe = "".join(c if c.isalnum() else "_" for c in name)
        w.to_csv(RESULTS / f"universe_{safe}_windows.csv")
        n_late = sum(1 for tr in res.trades if tr.pair in LATE)
        print(f"  {name:20} {len(res.trades):5d} trades ({n_late} in the six)  total "
              f"{res.equity.iloc[-1] / res.equity.iloc[0] - 1:+7.1%}  ({time.time() - t:.0f}s)")
        sys.stdout.flush()
        return w, res, field_beaten(w["ret"], prices.close, LIQUID), active_days_per_window(res.trades, w.index)

    btc = run(prices, rules, BuyAndHold(BTC), every=24)
    btc_w = window_metrics(btc.equity)
    rows = {"hold:BTC": (btc_w, btc, field_beaten(btc_w["ret"], prices.close, LIQUID),
                         active_days_per_window(btc.trades, btc_w.index))}
    rows["entry"] = sim("entry", ENTRY, LIQUID)
    rows["entry:established"] = sim("entry:established", ENTRY, ESTABLISHED)
    rows["core"] = sim("core", CORE, LIQUID)
    rows["core:established"] = sim("core:established", CORE, ESTABLISHED)

    all_w = rows["entry"][0].index
    in_sample = all_w[all_w <= pd.Timestamp(IN_SAMPLE_END, tz="UTC") - pd.Timedelta(days=14)]
    later = all_w[all_w >= pd.Timestamp("2026-05-15", tz="UTC")]
    report("IN-SAMPLE", rows, in_sample, btc_w["ret"])
    report("POST 2026-05-15 (the unsealed holdout)", rows, later, btc_w["ret"])
    report("FULL SAMPLE", rows, all_w, btc_w["ret"])
    print("\ncolumns: top40 = share of windows beating >= 60% of the 35 hold-one-coin competitors (up/dn = BTC-up / "
          "BTC-down); expo% = mean invested weight; late% = mean weight in the six mid-sample listings; "
          "act = active days p10/median")
    return 0


if __name__ == "__main__":
    sys.exit(main())
