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

Design. Two corrections, because the obvious one is not enough.

  established (29)  drops the six pairs with NO price at the in-sample start: PENGU, TRUMP, ONDO, WLFI, PUMP,
                    XPL. This is the partial correction -- it catches names that did not exist, but waves through
                    names that existed and were far too illiquid to have been picked.
  pit (26)          the universe a $5M/day floor would have chosen AT THE START of the sample rather than at its
                    end, computed from the panel's own dollar volume over its first 7 days. It drops the six, and
                    also XLM, PAXG and ZEC, which existed in 2024 on $4.1M, $2.4M and $1.9M a day. ZEC is the
                    best performer in the whole holdout and PAXG is the gold sleeve section 3 credits with a
                    third of total return, so this is where the correction bites.

All books run on the SAME price panel with only the selectable universe changed, so the naive hold-one-coin
competitor field is identical everywhere and the comparison is like for like.

  roll (rule)       the floor as a ROLLING rule (`liquidity_min_daily`): at every hour, an asset is in the pool
                    if its trailing 7-day dollar volume is at least $5M/day. Point-in-time by construction, and
                    the same code runs live. ZEC crosses on 2024-10-11 at $35.54 and is legitimately in the book
                    for the +4,055% that followed; pit throws it out for the whole sample over one thin week.
  roll:band         the same with hysteresis: admitted at $5M/day, kept until $2.5M/day. ZEC sat above $5M in
                    only 65% of hours after crossing, so the unbanded rule may churn it.

  roll:all          the rolling rule over the POOL: every crypto pair Roostoo will trade that Binance carries
                    (65 at the snapshot), instead of the 35-pair list. The list was the last hindsight-selected
                    input; with the rule doing the selecting, the pool is the principled universe.

  entry / entry:pit / entry:roll / entry:roll:band / entry:roll:all    equal weight, 3%/day target   (the entry)
  core  / core:pit  / core:roll  / core:roll:band  / core:roll:all     inverse vol, 2%/day target    (the fallback)
  (established, the partial correction, is dropped from this run; its numbers are in commit c1349a1)

Reading roll:all against roll, pre-registered: the honesty argument carries adoption on its own, so the bar is
only that tails and holdout ratios are not MATERIALLY worse -- outside 2 points on worst fortnight or max
drawdown, or 0.2 of holdout Sharpe. Result (2026-09-18): worst fortnight -23.3% -> -17.3%, max drawdown -46.5% ->
-38.2%, in-sample composite 0.75 -> 0.94 against BTC's 0.73; holdout entry Sharpe 2.16 -> 1.92 (past the band,
with Sortino flat and the core moving +0.60 the other way on the same windows), and top-40%-of-field in rising
fortnights 73% -> 45%, because the top six of 65 holds more volatile names and the vol model sizes them smaller
(62% invested against 72%). Adopted: the tails gain is on the metric section 2 calls most valuable, and the
rally cost is the exposure-for-tails dial of section 5.2, stated rather than hidden. The competitor field for
top40 stays the 35 hold-one-coin books in every arm, so the columns are comparable.

Reading the result. Fixed-list arms are biased in opposite directions: `entry` upward (hindsight), `pit`
downward (one thin week bans a name for two years). The roll arms are the honest number. Between the two roll
arms, pre-registered: adopt the band if it cuts trades by at least 10% with total return not lower; otherwise
the unbanded rule. That is one binary choice on one criterion, stated before the run.

Two things the roll arms decide. Whether the strategy's edge survives an honest universe at all, in-sample and
in the holdout. And whether a rolling rule is fit to run LIVE: it would replace the hardcoded pair list with a
threshold in the config, so its churn, fees and tails are part of the reading, not just its return.

Two caveats on the pit arm. Binance quote volume is a proxy for Roostoo's -- the scales are comparable (BTC
$1,346M/day against Roostoo's $963M/24h today) but PAXG trades thin on Binance relative to gold overall, so its
exclusion may be an artefact where ZEC's, at $1.9M against a $5M floor, is not. And measuring volume over the
sample's first 7 days peeks 7 days into the sample; for a liquidity screen, rather than a return forecast, that
is immaterial.

What this CANNOT measure: coins that never entered the universe at all -- delisted, or never listed by Roostoo.
They are absent from the 2026 snapshot and were never fetched, so even the pit arm is a lower bound on the true
survivorship effect.

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
# every tradeable crypto pair with Binance history: the pool the configs carry since 2026-09-18
POOL = tuple(sorted(a.pair for a in build_universe(load_snapshot(SNAPSHOT)) if a.asset_type == "crypto"))
# no price at START: listed mid-sample, so their presence in the pool is a decision made with hindsight
LATE = ("PENGU/USD", "TRUMP/USD", "ONDO/USD", "WLFI/USD", "PUMP/USD", "XPL/USD")
ESTABLISHED = tuple(p for p in LIQUID if p not in LATE)

PIT_DAYS, PIT_MIN_DAILY = 7, 5_000_000.0        # the same floor the 2026 universe used, applied at the start

ROLL = dict(liquidity_min_daily=PIT_MIN_DAILY, liquidity_window_h=24 * PIT_DAYS)
BAND = dict(**ROLL, liquidity_exit_daily=PIT_MIN_DAILY / 2)

EWMA = dict(vol_model="ewma", ewma_lambda=0.99)
ENTRY = dict(select_every_h=24, lookbacks_h=(72, 168, 336), weighting="equal", vol_target_daily=0.03, **EWMA)
CORE = dict(select_every_h=24, lookbacks_h=(72, 168, 336), weighting="inverse_vol", vol_target_daily=0.02, **EWMA)


def point_in_time_universe(prices, pairs, days=PIT_DAYS, min_daily=PIT_MIN_DAILY):
    """The pairs a liquidity floor would have admitted at the START of the sample.

    Uses the panel's own dollar volume over its first `days`, so the rule is reproducible from the same data the
    backtest runs on. A pair that had not listed yet has zero volume there and drops out on the same test, which
    is why this universe is a subset of `established` rather than a different cut of it.
    """
    window = prices.volume.loc[:prices.volume.index[0] + pd.Timedelta(days=days), list(pairs)]
    daily = window.sum() / days
    return tuple(p for p in pairs if daily[p] >= min_daily), daily


def run(prices, rules, strat, every=1):
    assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
    return simulate(prices, strat, rules, SimConfig(decision_every_h=every))


def pct(x, q):
    return float(np.nanpercentile(x, q))


def report(title, rows, sample, btc_ret, HINDSIGHT=()):
    print(f"\n=== {title}: {len(sample)} windows ===")
    head = ("strategy", "medR", "p10R", "worst", "p90R", "%>BTC", "top40", "up", "dn", "|", "Sharpe", "Sortno",
            "Calmar", "|", "total", "maxDD", "fees", "expo%", "hind%", "act")
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
        hind = wts[[p for p in HINDSIGHT if p in wts.columns]].sum(axis=1).mean() * 100
        print(f"{name:20} {pct(w.ret, 50) * 100:6.2f}% {pct(w.ret, 10) * 100:6.2f}% {w.ret.min() * 100:6.2f}% "
              f"{pct(w.ret, 90) * 100:6.2f}% {(w.ret > b).mean() * 100:4.0f}% {(fb >= .6).mean() * 100:4.0f}% "
              f"{(fb[up] >= .6).mean() * 100:3.0f}% {(fb[~up] >= .6).mean() * 100:3.0f}% | "
              f"{pct(w.sharpe, 50):6.2f} {pct(w.sortino, 50):6.2f} {pct(w.calmar, 50):6.2f} | "
              f"{total * 100:+6.1f}% {maxdd * 100:5.1f}% {fees * 100:4.2f}% {expo:4.0f}% {hind:4.0f}% "
              f"{int(pct(ad, 10)):2d}/{int(ad.median()):2d}")


def main() -> int:
    snapshot = load_snapshot(SNAPSHOT)
    rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
    crypto = [a for a in build_universe(snapshot) if a.pair in POOL]          # superset: the 35 are a subset
    store = PriceStore(cache_dir=ROOT / "data" / "cache", sources={"binance": BinanceSource(), "yahoo": None})
    t0, t1 = pd.Timestamp(START, tz="UTC"), pd.Timestamp(CACHE_END, tz="UTC")
    prices = store.closes(crypto, t0, t1, deadline=lambda: True)               # cache only, no network
    pit, daily = point_in_time_universe(prices, LIQUID)
    hindsight = tuple(p for p in LIQUID if p not in pit)
    print(f"panel {len(POOL)} pairs ({len(LIQUID)} in the list), {prices.close.index[0]:%Y-%m-%d} -> "
          f"{prices.close.index[-1]:%Y-%m-%d %H:%M}")
    print(f"excluded as listed mid-sample ({len(LATE)}): {', '.join(p.split('/')[0] for p in LATE)}")
    print(f"established universe: {len(ESTABLISHED)} pairs")
    print(f"point-in-time universe at a ${PIT_MIN_DAILY:,.0f}/day floor over the first {PIT_DAYS} days: "
          f"{len(pit)} pairs")
    extra = [p for p in hindsight if p not in LATE]
    print("  existed at the start but below the floor: "
          + ", ".join(f"{p.split('/')[0]} ${daily[p] / 1e6:.1f}M/day" for p in sorted(extra, key=lambda q: -daily[q])))
    print()
    RESULTS.mkdir(parents=True, exist_ok=True)

    def sim(name, params, pairs):
        t = time.time()
        res = run(prices, rules, Momentum(MomentumParams(pairs=tuple(pairs), **params), name=name))
        w = window_metrics(res.equity)
        safe = "".join(c if c.isalnum() else "_" for c in name)
        w.to_csv(RESULTS / f"universe_{safe}_windows.csv")
        n_late = sum(1 for tr in res.trades if tr.pair in LATE)
        print(f"  {name:20} {len(res.trades):5d} trades ({n_late} in the six)   total "
              f"{res.equity.iloc[-1] / res.equity.iloc[0] - 1:+7.1%}  ({time.time() - t:.0f}s)")
        sys.stdout.flush()
        return w, res, field_beaten(w["ret"], prices.close, LIQUID), active_days_per_window(res.trades, w.index)

    btc = run(prices, rules, BuyAndHold(BTC), every=24)
    btc_w = window_metrics(btc.equity)
    rows = {"hold:BTC": (btc_w, btc, field_beaten(btc_w["ret"], prices.close, LIQUID),
                         active_days_per_window(btc.trades, btc_w.index))}
    rows["entry"] = sim("entry", ENTRY, LIQUID)
    rows["entry:pit"] = sim("entry:pit", ENTRY, pit)
    rows["entry:roll"] = sim("entry:roll", {**ENTRY, **ROLL}, LIQUID)
    rows["entry:roll:band"] = sim("entry:roll:band", {**ENTRY, **BAND}, LIQUID)
    rows["entry:roll:all"] = sim("entry:roll:all", {**ENTRY, **ROLL}, POOL)
    rows["core"] = sim("core", CORE, LIQUID)
    rows["core:pit"] = sim("core:pit", CORE, pit)
    rows["core:roll"] = sim("core:roll", {**CORE, **ROLL}, LIQUID)
    rows["core:roll:band"] = sim("core:roll:band", {**CORE, **BAND}, LIQUID)
    rows["core:roll:all"] = sim("core:roll:all", {**CORE, **ROLL}, POOL)

    all_w = rows["entry"][0].index
    in_sample = all_w[all_w <= pd.Timestamp(IN_SAMPLE_END, tz="UTC") - pd.Timedelta(days=14)]
    later = all_w[all_w >= pd.Timestamp("2026-05-15", tz="UTC")]
    report("IN-SAMPLE", rows, in_sample, btc_w["ret"], hindsight)
    report("POST 2026-05-15 (the unsealed holdout)", rows, later, btc_w["ret"], hindsight)
    report("FULL SAMPLE", rows, all_w, btc_w["ret"], hindsight)
    print("\ncolumns: top40 = share of windows beating >= 60% of the 35 hold-one-coin competitors (up/dn = BTC-up / "
          "BTC-down); expo% = mean invested weight; hind% = mean weight in names the point-in-time floor "
          "would not have admitted; "
          "act = active days p10/median")
    return 0


if __name__ == "__main__":
    sys.exit(main())
