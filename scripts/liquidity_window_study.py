"""PRE-REGISTERED STUDY (2026-09-18): is seven days the right window for the liquidity rule?

The question, asked by the operator. A pair is admitted while its dollar volume, averaged over the trailing
`liquidity_window_h = 168` hours, is at least $5M a day. The seven was never derived: it is PIT_DAYS from the bias
study. And the window does more than smooth. A small coin's volume surges when its price does, so a short window
admits it during the very move that makes it rank well (HEMI, August 2026: $1M to $16M a day while gaining 71%),
and a long window admits it late or not at all. The window therefore sets how much of the book can sit in names
that are liquid only because they are pumping. Is 7 days a good place for that dial?

What this study can and cannot do, said before the run. The floor study (cf55b45) showed that variants of the
universe rule whose fortnight returns are 0.97 correlated differ by 0.2 of composite, and that the months after
May are decided by one fortnight. We therefore EXPECT this study to read SENSITIVE with no TREND, in which case the
honest answer to "is 7 the right number" is that this data cannot say and no other number is better supported.
It is run anyway because that answer should be measured, not assumed, and because one thing here CAN be measured
well: the mechanism. `surge%` is the book's mean weight in names whose trailing THIRTY-day volume is below the
floor at that hour, that is, names a slow window would not yet have admitted. It is a record of holdings, not a
noisy ratio, and this time daily holdings are saved for every arm.

Expected direction, written down so it can be wrong: surge% falls as the window lengthens, and so do trades and
the share of BTC-up fortnights in the top 40% of the field. For tails we have no expectation.

This is a robustness check and NOT a search. No window is adopted because it scored best.

Design. Five windows: 1, 3, 7, 14 and 30 days. Both books, over the pool of 65, floor fixed at $5M, on the panel,
windows and 35-book competitor field of the floor study, nothing else changed. One confound is removed by design:
the gate is off while its window warms up, so a 30-day arm sits in cash for a month at the start of the panel
while a 1-day arm does not. Every arm is therefore scored only on fortnights starting on or after 2024-10-19,
thirty days in, when all five gates are warm. The 7-day arm is ALSO printed on the full in-sample windows, where
it must match the floor study's $5M row to the digit (0.94, -17.34%, -38.2%).

The reading, fixed before the run, with the floor study's bands. Per book, in-sample, a neighbour of 7 days
(3 or 14) is APART if the Screen 3 composite differs by more than 0.15, or the worst fortnight or the max
drawdown by more than 2 points.

  PLATEAU     neither neighbour apart. Keep 7 days; section 8 says the window was tested and matters little.
  SENSITIVE   a neighbour apart, either way. Keep 7 days all the same; section 8 states the spread.
  TREND       composite strictly monotone across all five windows, the same direction in-sample AND after May, in
              BOTH books, with worst fortnight and max drawdown at the better end not more than 2 points worse
              than at 7 days. The only reading under which another window is defensible, because it is a shape
              and not a cell. Even then nothing is adopted here: the strategy is locked, so it is reported as a
              recommendation to move ONE step, and the decision is the operator's.

The entry's reading is the one that counts. The months after May are shown and used only for the TREND test.

  .venv\\Scripts\\python.exe scripts\\liquidity_window_study.py
"""
import sys
import time

import numpy as np
import pandas as pd

from liquidity_floor_study import (BAND_COMPOSITE, BAND_TAIL, BOOKS, BTC, CACHE_END, FIELD, IN_SAMPLE_END, POOL,
                                   RESULTS, ROOT, SNAPSHOT, START, measure, monotone)
from qtrading.backtest.checks import assert_no_lookahead
from qtrading.backtest.metrics import field_beaten, window_metrics
from qtrading.backtest.simulator import SimConfig, simulate
from qtrading.data.binance import BinanceSource
from qtrading.data.store import PriceStore
from qtrading.data.universe import build_universe, load_snapshot
from qtrading.roostoo.models import PairInfo
from qtrading.strategy.baselines import BuyAndHold
from qtrading.strategy.momentum import HOURS_PER_DAY, Momentum, MomentumParams, liquidity_gate

WINDOWS_D = (1, 3, 7, 14, 30)                   # days; fixed before the run
REFERENCE_D, NEIGHBOURS_D = 7, (3, 14)
FLOOR = 5_000_000.0
SLOW_D = 30                                     # surge% is measured against this window's gate, in every arm
WARM_FROM = pd.Timestamp(START, tz="UTC") + pd.Timedelta(days=max(WINDOWS_D))


def gate_for(prices, days: int) -> pd.DataFrame:
    w = days * HOURS_PER_DAY
    daily = prices.volume[list(POOL)].rolling(w, min_periods=w).sum() / days
    return liquidity_gate(daily, FLOOR, FLOOR)


def reading(ins: dict[int, dict]) -> tuple[str, list[str]]:
    ref, notes = ins[REFERENCE_D], []
    for n in NEIGHBOURS_D:
        d = {k: ins[n][k] - ref[k] for k in ("composite", "worst", "maxdd")}
        apart = abs(d["composite"]) > BAND_COMPOSITE or abs(d["worst"]) > BAND_TAIL or abs(d["maxdd"]) > BAND_TAIL
        notes.append(f"{n}d vs {REFERENCE_D}d: composite {d['composite']:+.2f}, worst {d['worst'] * 100:+.1f} pts, "
                     f"max drawdown {d['maxdd'] * 100:+.1f} pts -> {'APART' if apart else 'within the band'}")
    return ("SENSITIVE" if any("APART" in n for n in notes) else "PLATEAU"), notes


def trend(results) -> tuple[bool, str]:
    dirs = {(b, p): monotone([results[b][p][d]["composite"] for d in WINDOWS_D]) for b in BOOKS for p in ("in", "post")}
    shape = ", ".join(f"{b}/{p} {'rising' if v > 0 else 'falling' if v < 0 else 'not monotone'}" for (b, p), v in dirs.items())
    if len(set(dirs.values())) != 1 or 0 in dirs.values():
        return False, f"no TREND ({shape})"
    better = WINDOWS_D[-1] if next(iter(dirs.values())) > 0 else WINDOWS_D[0]
    for b in BOOKS:
        ref, end = results[b]["in"][REFERENCE_D], results[b]["in"][better]
        if end["worst"] < ref["worst"] - BAND_TAIL or end["maxdd"] < ref["maxdd"] - BAND_TAIL:
            return False, f"monotone toward {better}d ({shape}) but the {b}'s tails there are materially worse: no TREND"
    return True, f"TREND toward {better}d ({shape}), tails not materially worse"


def table(title: str, rows: dict[str, dict]) -> None:
    print(f"\n=== {title} ===")
    print(f"{'arm':10} {'comp':>5} {'medR':>7} {'p10R':>7} {'worst':>7} {'maxDD':>7} {'total':>8} {'Sharpe':>6} "
          f"{'up':>4} {'dn':>4} {'expo%':>5} {'fees':>6} {'trades':>6} {'surge%':>6} {'n_adm':>5}")
    for name, m in rows.items():
        print(f"{name:10} {m['composite']:5.2f} {m['median'] * 100:6.2f}% {m['p10'] * 100:6.2f}% {m['worst'] * 100:6.2f}% "
              f"{m['maxdd'] * 100:6.1f}% {m['total'] * 100:+7.1f}% {m['sharpe']:6.2f} {m['top40_up'] * 100:3.0f}% "
              f"{m['top40_dn'] * 100:3.0f}% {m['expo'] * 100:4.0f}% {m['fees'] * 100:5.2f}% {m['trades']:6d} "
              f"{m['surge'] * 100:5.1f}% {m['n_adm']:5.1f}")


def main() -> int:
    snapshot = load_snapshot(SNAPSHOT)
    rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
    crypto = [a for a in build_universe(snapshot) if a.pair in POOL]
    store = PriceStore(cache_dir=ROOT / "data" / "cache", sources={"binance": BinanceSource(), "yahoo": None})
    prices = store.closes(crypto, pd.Timestamp(START, tz="UTC"), pd.Timestamp(CACHE_END, tz="UTC"),
                          deadline=lambda: True)                               # cache only, no network
    print(f"panel {len(POOL)} pairs, {prices.close.index[0]:%Y-%m-%d} -> {prices.close.index[-1]:%Y-%m-%d %H:%M}; "
          f"windows {', '.join(f'{d}d' for d in WINDOWS_D)}; floor ${FLOOR / 1e6:g}M; scored from {WARM_FROM:%Y-%m-%d}")
    RESULTS.mkdir(parents=True, exist_ok=True)
    slow_off = gate_for(prices, SLOW_D) == 0                                   # names a 30-day window has not admitted
    n_adm = {d: float(gate_for(prices, d).loc[WARM_FROM:].sum(axis=1).mean()) for d in WINDOWS_D}

    btc = simulate(prices, BuyAndHold(BTC), rules, SimConfig(decision_every_h=24))
    btc_w = window_metrics(btc.equity)
    all_w = btc_w.index
    in_end = pd.Timestamp(IN_SAMPLE_END, tz="UTC") - pd.Timedelta(days=14)
    samples = {"in": all_w[(all_w >= WARM_FROM) & (all_w <= in_end)], "post": all_w[all_w >= pd.Timestamp("2026-05-15", tz="UTC")]}
    full_in = all_w[all_w <= in_end]

    results = {b: {"in": {}, "post": {}} for b in BOOKS}
    check = {}
    for book, params in BOOKS.items():
        for d in WINDOWS_D:
            t = time.time()
            name = f"{book}:{d}d"
            strat = Momentum(MomentumParams(pairs=POOL, liquidity_min_daily=FLOOR,
                                            liquidity_window_h=d * HOURS_PER_DAY, **params), name=name)
            assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
            res = simulate(prices, strat, rules, SimConfig(decision_every_h=1))
            w = window_metrics(res.equity)
            w.to_csv(RESULTS / f"window_{book}_{d}d_windows.csv")
            res.weights[res.weights.index.hour == 0].round(4).to_csv(RESULTS / f"window_{book}_{d}d_weights.csv")
            fb = field_beaten(w["ret"], prices.close, FIELD)
            surge_w = (res.weights.reindex(columns=list(POOL)).fillna(0.0) * slow_off.reindex(res.weights.index)).sum(axis=1)
            for period, sample in samples.items():
                m = measure(res, w, fb, btc_w["ret"], sample)
                lo, hi = sample[0], sample[-1] + pd.Timedelta(days=14)
                m["surge"] = float(surge_w.loc[lo:hi].mean())
                m["trades"] = sum(1 for tr in res.trades if lo <= tr.time <= hi)
                m["n_adm"] = n_adm[d]
                results[book][period][d] = m
            if d == REFERENCE_D:
                check[book] = measure(res, w, fb, btc_w["ret"], full_in)
            print(f"  {name:10} {len(res.trades):5d} trades  in-sample composite "
                  f"{results[book]['in'][d]['composite']:.2f}  ({time.time() - t:.0f}s)")
            sys.stdout.flush()

    print("\nreproduction check, the 7-day arms on the FULL in-sample windows (floor study: entry 0.94 / -17.34% / "
          "-38.2%, core 0.81 / -13.02% / -28.5%):")
    for book, m in check.items():
        print(f"  {book:6} composite {m['composite']:.2f}  worst {m['worst'] * 100:.2f}%  max drawdown {m['maxdd'] * 100:.1f}%")

    for period, title in (("in", f"IN-SAMPLE from {WARM_FROM:%Y-%m-%d}"), ("post", "POST 2026-05-15 (shown; used only for the TREND test)")):
        table(f"{title}: {len(samples[period])} windows",
              {f"{b}:{d}d": results[b][period][d] for b in BOOKS for d in WINDOWS_D})

    print("\n=== THE READING, by the rule fixed before the run ===")
    for book in BOOKS:
        label, notes = reading(results[book]["in"])
        print(f"{book.upper()}: {label}" + ("   <- the reading that counts" if book == "entry" else ""))
        for n in notes:
            print(f"    {n}")
    is_trend, why = trend(results)
    print(f"TREND test: {why}")
    print("\nthe mechanism, in-sample, against the direction expected beforehand (falling as the window lengthens):")
    for book in BOOKS:
        for key, label in (("surge", "surge%"), ("trades", "trades"), ("top40_up", "top-40% in BTC-up fortnights")):
            vals = [results[book]["in"][d][key] for d in WINDOWS_D]
            shown = ", ".join(f"{v * 100:.1f}%" if key != "trades" else f"{v}" for v in vals)
            print(f"    {book:6} {label:30} {shown}   -> {'falls as expected' if monotone(vals) < 0 else 'rises: expectation wrong' if monotone(vals) > 0 else 'not monotone'}")
    print(f"\n7 days is kept in every reading. {'A one-step move is RECOMMENDED to the operator, not adopted.' if is_trend else 'No other window is defensible from this run.'}")
    print("columns: comp = Screen 3 composite on median window ratios; up/dn = share of BTC-up / BTC-down windows "
          "beating >= 60% of the 35 hold-one-coin books; surge% = mean weight in names whose trailing 30-day volume "
          "is below the floor at that hour; n_adm = mean pairs the gate admits (before the minimum-age rule)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
