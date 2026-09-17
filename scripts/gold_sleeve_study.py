"""PRE-REGISTERED STUDY (2026-09-17): does holding idle cash in gold improve the core's tails without costing
its Screen-2 standing?

Background. Under a long-only spot mandate the core's only defensive asset is cash. PAXG is the one asset on
Roostoo whose fortnight returns are uncorrelated with the core (0.03 over 2024-09 -> 2026-09; the tokenised
stocks are ~0.5 and every crypto is above 0.7). A sleeve that holds the cash the vol target leaves idle in gold
changes nothing about the crypto book: same signal, same selection, same weights, same exposure.

Hypothesis. Core + gold sleeve (cash mode, fraction 1.0) improves the p10 and worst fortnight over the core.

Pass rule, fixed before running (in-sample windows, 2024-09-19 -> 2026-05-14):
  1. p10 and worst fortnight both improve on the core;
  2. none of %>BTC, top-40%-of-field, median Sharpe, median Sortino falls by more than noise (3 pts / 0.05);
  3. plateau: fractions 0.25 / 0.5 / 0.75 / 1.0 move the tails monotonically -- no spike at one value;
  4. robustness: with gold's in-sample drift removed (a counterfactual PAXG that ends the period flat), p10 and
     worst are still no worse than the core's on the same counterfactual panel. The benefit must come from the
     correlation, not from gold's 2025 rally;
  5. consistency: the direction of the tail change holds on windows starting after 2026-05-15 (already unsealed
     by the OOS check of 2026-09-16, so this is a consistency check, not a holdout).
Book mode (gold inside the inverse-vol book, with the vol target treating it as uncorrelated) is reported for
comparison and is not pre-registered. If the primary fails any of 1, 2 or 4, the core stays as it is.

RESULT OF RUN 1 (2026-09-17): the primary FAILED rules 1, 4 and 5. p10 improved by 0.4 pts but the worst fortnight
went from -15.8% to -19.3% (flat gold: -15.9% -> -20.3%), and in the post-May-15 period both tails were worse.
Two things the design missed, both visible in the worst windows (late January 2026, BTC -20..-30% in a fortnight):
  * PAXG was already a *candidate* in the core, and gold's 2025 trend put it at the top of the ranking often
    enough to average 18% of the book in-sample. The sleeve removed it from the ranking pool, so the "unchanged
    crypto book" was in fact more crypto than the core's. `core:xg` (gold never held) was added after run 1 as the
    baseline with an identical crypto book -- a post-hoc addition, labelled as such.
  * A cash sleeve is pro-cyclical in the wrong direction: before a crash crypto is calm and trending, the vol
    target leaves little idle cash, so there is little gold exactly when it is needed. Gold held by rank is there
    because gold is trending, whatever crypto is doing. The weights dump and the worst-window table below exist
    to show this rather than assert it.

  .venv\\Scripts\\python.exe scripts\\gold_sleeve_study.py [--check-equity path/to/equity.csv]
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
from qtrading.data.store import PriceStore, Prices
from qtrading.data.universe import build_universe, load_snapshot
from qtrading.data.yahoo import YahooSource
from qtrading.roostoo.models import PairInfo
from qtrading.strategy.baselines import BuyAndHold
from qtrading.strategy.momentum import Momentum, MomentumParams

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"
RESULTS = ROOT / "data" / "results"
START, IN_SAMPLE_END, CACHE_END = "2024-09-19", "2026-05-14 23:00", "2026-09-14 13:00"
GOLD = "PAXG/USD"

LIQUID = tuple(f"{c}/USD" for c in (
    "BTC ETH ZEC SOL XRP BNB FIL SUI NEAR DOGE UNI TRX TAO ADA PEPE LINK PUMP LTC ARB ENA WLD TRUMP AVAX AAVE "
    "FET XLM ICP PAXG ONDO WLFI CAKE DOT APT XPL PENGU").split())
CORE = dict(pairs=LIQUID, select_every_h=24, lookbacks_h=(72, 168, 336), weighting="inverse_vol",
            vol_target_daily=0.02, vol_model="ewma", ewma_lambda=0.99)


def strategies():
    yield "core", Momentum(MomentumParams(**CORE), name="core")
    # post-hoc baseline (see docstring): the core with gold removed from the ranking pool, i.e. exactly the crypto
    # book every sleeved variant runs, with nothing held in the idle cash
    yield "core:xg", Momentum(MomentumParams(**{**CORE, "pairs": tuple(p for p in LIQUID if p != GOLD)}), name="core:xg")
    for f in (1.0, 0.75, 0.5, 0.25):
        yield f"gold:cash{f:g}", Momentum(MomentumParams(**CORE, sleeve=(GOLD,), sleeve_fraction=f),
                                          name=f"gold:cash{f:g}")
    yield "gold:book", Momentum(MomentumParams(**CORE, sleeve=(GOLD,), sleeve_mode="book"), name="gold:book")


def flat_gold(prices: Prices, through: str) -> Prices:
    """Counterfactual panel: PAXG with its mean live-hour log return over the in-sample period removed."""
    g = prices.close[GOLD]
    live = ~prices.stale[GOLD]
    lr = np.log(g).diff().where(live)
    mu = lr.loc[:pd.Timestamp(through, tz="UTC")].mean()
    adjust = np.exp(-mu * live.cumsum())
    close = prices.close.copy()
    close[GOLD] = g * adjust
    return Prices(close=close, stale=prices.stale, volume=prices.volume, extra=prices.extra)


def run(prices, rules, strat, every=1):
    assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
    return simulate(prices, strat, rules, SimConfig(decision_every_h=every))


def pct(x, q):
    return float(np.nanpercentile(x, q))


def report(title, rows, sample, btc_ret, core_ret):
    print(f"\n=== {title}: {len(sample)} windows ===")
    head = ("strategy", "medR", "p10R", "p5R", "worst", "p90R", "%>BTC", "top40", "up", "dn", "|", "medMDD",
            "Sharpe", "Sortno", "Calmar", "|", "total", "maxDD", "fees", "|", "gold%", "cryp%", "corr", "act")
    print("{:16} {:>7} {:>7} {:>7} {:>7} {:>7} {:>5} {:>5} {:>4} {:>4} {} {:>6} {:>6} {:>6} {:>6} {} {:>7} {:>6} "
          "{:>5} {} {:>5} {:>5} {:>5} {:>5}".format(*head))
    up = btc_ret.reindex(sample) > 0
    for name, (w, res, fb, ad) in rows.items():
        w, fb, ad = w.reindex(sample), fb.reindex(sample), ad.reindex(sample)
        span = (res.equity.index >= sample[0]) & (res.equity.index <= sample[-1] + pd.Timedelta(days=14))
        eq = res.equity[span]
        total = eq.iloc[-1] / eq.iloc[0] - 1
        maxdd = ((eq / eq.cummax()) - 1).min()
        fees = sum(t.fee for t in res.trades if eq.index[0] <= t.time <= eq.index[-1]) / eq.mean()
        wts = res.weights.loc[eq.index]
        gold = wts[GOLD].mean() * 100 if GOLD in wts else 0.0
        crypto = wts.drop(columns=[GOLD], errors="ignore").sum(axis=1).mean() * 100
        corr = w["ret"].corr(core_ret.reindex(sample))
        beats = (w.ret > btc_ret.reindex(sample)).mean() * 100
        print(f"{name:16} {pct(w.ret, 50) * 100:6.2f}% {pct(w.ret, 10) * 100:6.2f}% {pct(w.ret, 5) * 100:6.2f}% "
              f"{w.ret.min() * 100:6.2f}% {pct(w.ret, 90) * 100:6.2f}% {beats:4.0f}% {(fb >= .6).mean() * 100:4.0f}% "
              f"{(fb[up] >= .6).mean() * 100:3.0f}% {(fb[~up] >= .6).mean() * 100:3.0f}% | "
              f"{pct(w.mdd, 50) * 100:5.2f}% {pct(w.sharpe, 50):6.2f} {pct(w.sortino, 50):6.2f} {pct(w.calmar, 50):6.2f} | "
              f"{total * 100:+6.1f}% {maxdd * 100:5.1f}% {fees * 100:4.2f}% | {gold:4.0f}% {crypto:4.0f}% {corr:5.2f} "
              f"{int(pct(ad, 10)):2d}/{int(ad.median()):2d}")


def explain_worst(rows, sample, prices, names, n=8):
    """The n worst core fortnights: each strategy's return, what BTC and gold did over the window, and -- the
    mechanism -- how much gold and how much crypto each book held when the window began."""
    daily = prices.close[prices.close.index.hour == 0]
    fwd = daily.shift(-14) / daily - 1
    core_ret = rows["core"][0]["ret"].reindex(sample)
    print(f"\n=== the {n} worst core fortnights in this sample ===")
    print(f"{'start':10} " + " ".join(f"{k:>10}" for k in names) + f" {'| BTC':>9} {'gold':>7} |"
          + " ".join(f"{k + ' g%/c%':>15}" for k in names))
    for t in core_ret.nsmallest(n).index:
        rets = " ".join(f"{rows[k][0]['ret'].get(t, np.nan) * 100:9.2f}%" for k in names)
        held = []
        for k in names:
            w = rows[k][1].weights.loc[t]
            gold = w.get(GOLD, 0.0) * 100
            held.append(f"{gold:6.0f}%/{(w.sum() - w.get(GOLD, 0.0)) * 100:3.0f}%   ")
        print(f"{t:%Y-%m-%d} {rets} {fwd['BTC/USD'].get(t, np.nan) * 100:8.2f}% {fwd[GOLD].get(t, np.nan) * 100:6.2f}% |"
              + " ".join(held))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-equity", default=None, help="equity.csv from before the refactor; core must match")
    args = ap.parse_args()

    snapshot = load_snapshot(SNAPSHOT)
    universe = [a for a in build_universe(snapshot) if a.pair in LIQUID]
    rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
    store = PriceStore(cache_dir=ROOT / "data" / "cache",
                       sources={"binance": BinanceSource(), "yahoo": YahooSource()})
    prices = store.closes(universe, pd.Timestamp(START, tz="UTC"), pd.Timestamp(CACHE_END, tz="UTC"),
                          deadline=lambda: True)
    print(f"{len(universe)} assets, {prices.close.index[0]:%Y-%m-%d} -> {prices.close.index[-1]:%Y-%m-%d %H:%M} UTC; "
          f"in-sample windows end by {IN_SAMPLE_END}, later windows are the unsealed post-May-15 period")
    RESULTS.mkdir(parents=True, exist_ok=True)

    panels = {"": prices, " [flat gold]": flat_gold(prices, IN_SAMPLE_END)}
    g0, g1 = panels[" [flat gold]"].close[GOLD].dropna().iloc[[0, -1]]
    r0, r1 = prices.close[GOLD].dropna().iloc[[0, -1]]
    print(f"counterfactual gold: {g0:.0f} -> {g1:.0f} over the whole panel (real: {r0:.0f} -> {r1:.0f})\n")

    rows = {}
    btc = run(prices, rules, BuyAndHold("BTC/USD"), every=24)
    btc_w = window_metrics(btc.equity)
    rows["hold:BTC"] = (btc_w, btc, field_beaten(btc_w["ret"], prices.close, LIQUID),
                        active_days_per_window(btc.trades, btc_w.index))
    for suffix, panel in panels.items():
        for name, strat in strategies():
            if suffix and name not in ("core", "gold:cash1"):
                continue
            t0 = time.time()
            res = run(panel, rules, strat)
            w = window_metrics(res.equity)
            label = name + suffix
            rows[label] = (w, res, field_beaten(w["ret"], panel.close, LIQUID),
                           active_days_per_window(res.trades, w.index))
            safe = "".join(c if c.isalnum() else "_" for c in label)
            w.to_csv(RESULTS / f"gold_{safe}_windows.csv")
            total = res.equity.iloc[-1] / res.equity.iloc[0] - 1
            print(f"  {label:22} {len(res.trades):5d} trades  total {total:+7.1%}  ({time.time() - t0:.0f}s)")
            sys.stdout.flush()

    if args.check_equity:
        old = pd.read_csv(args.check_equity, index_col=0, parse_dates=True)["core"]
        new = rows["core"][1].equity
        common = old.index.intersection(new.index)
        gap = (new.reindex(common) / old.reindex(common) - 1).abs().max()
        verdict = "OK" if gap < 1e-9 else "MISMATCH"
        print(f"\nregression check: core equity vs pre-refactor run, max |rel diff| over {len(common)} hours = "
              f"{gap:.2e} {verdict}")

    all_w = rows["core"][0].index
    in_sample = all_w[all_w <= pd.Timestamp(IN_SAMPLE_END, tz="UTC") - pd.Timedelta(days=14)]
    later = all_w[all_w >= pd.Timestamp("2026-05-15", tz="UTC")]
    btc_ret, core_ret = rows["hold:BTC"][0]["ret"], rows["core"][0]["ret"]
    real = {k: v for k, v in rows.items() if "flat" not in k}
    flat = {k: v for k, v in rows.items() if "flat" in k or k == "hold:BTC"}
    report("IN-SAMPLE", real, in_sample, btc_ret, core_ret)
    explain_worst(rows, in_sample, prices, ["core", "core:xg", "gold:cash1", "gold:book"])
    report("IN-SAMPLE, counterfactual flat gold", flat, in_sample, btc_ret, core_ret)
    report("POST 2026-05-15 (unsealed; consistency only)", real, later, btc_ret, core_ret)
    explain_worst(rows, later, prices, ["core", "core:xg", "gold:cash1", "gold:book"], n=5)
    pd.DataFrame({k: v[1].weights.get(GOLD, pd.Series(0.0, index=v[1].weights.index)) for k, v in real.items()}
                 ).to_csv(RESULTS / "gold_weight_by_strategy.csv")
    print("\ncolumns: top40 = share of windows beating >= 60% of the 35 hold-one-coin competitors (up/dn = BTC-up / "
          "BTC-down windows); gold%/cryp% = mean weight; corr = fortnight-return correlation with the core; "
          "act = active days p10/median")
    return 0


if __name__ == "__main__":
    sys.exit(main())
