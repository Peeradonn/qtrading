"""PRE-REGISTERED STUDY (2026-09-18): is the $5M liquidity floor on a plateau, or is it a lucky cell?

The question. `liquidity_min_daily = 5_000_000` decides, every hour, which of the 65 pairs the ranking may choose
from. The number was never derived. It was a round figure applied by hand to a live ticker reading on 2026-09-14,
and when the universe became a rolling rule the same figure was carried over on purpose, so that the bias study
changed the timing of the rule and nothing else. It has been tested at one level. A parameter every result rests
on should sit on a plateau, the way the 2% volatility target does (whitepaper section 5): if $3M or $8M gives a
materially different book, then what we report is a cell, not a strategy.

This is a robustness check and NOT a search. No level is adopted because it scored best. Choosing the floor by
score would be a sweep on data already seen, and section 5 says why that is how backtests get overfitted.

Not blind, and said so up front. Two things are known before the run. The $5M arms: entry composite 0.94, worst
fortnight -17.3%, max drawdown -38.2%; core 0.81, -13.0%, -28.5%. And the direction a lower floor is likely to
take: in the bias study a band that kept pairs down to $2.5M lifted the 35-pair entry from 0.75 to 0.91, and the
gain came from holding ZEC through its dips. ZEC crossed $5M on 2024-10-11 and rose about 36-fold, so a lower
floor admits it earlier and a higher one later. Each arm therefore reports ZEC's mean weight and the date the rule
first admits it, so that "a better floor" can be told from "more of one coin". The reading does not depend on
those columns; they are there for whoever interprets it.

Design. Five floors, roughly geometric: $2M, $3M, $5M, $8M, $12M. Both books, over the pool of 65, on the panel,
windows and 35-book competitor field of universe_bias_study.py, with nothing else changed: K, the buffer, the
volatility targets, the selection hour, the 7-day volume window. The $5M arms are re-run here, not reused, so the
study reproduces from one command and its $5M rows can be checked against the bias study's to the digit.

The reading, fixed before the run. Per book, on the in-sample windows, a neighbour ($3M or $8M) is APART from $5M
if any of these hold: Screen 3 composite differs by more than 0.15; worst fortnight by more than 2 points; max
drawdown by more than 2 points. The tail bands are the bias study's "materially worse". The composite band is what
halving the fee moved it by (0.10) plus room for path noise, which alone moved the post-May Sharpe by 0.16.

  PLATEAU     neither neighbour is apart. Keep $5M. Section 8 says the floor is an arbitrary round number that was
              tested and does not matter much.
  SENSITIVE   at least one neighbour is apart, in either direction. Keep $5M all the same. Section 8 states the
              spread from $3M to $8M, and the honest expectation for a headline figure becomes the mean of those
              three levels, not the $5M cell.
  TREND       the composite is strictly monotone across all five floors, in the same direction, in-sample AND in
              the post-May windows, in BOTH books, and at the better end the worst fortnight and max drawdown are
              not more than 2 points worse than at $5M. This is the only reading under which another level is
              defensible, because it is a shape and not a cell. Even then nothing is adopted here: the strategy is
              locked, so it is reported as a recommendation to move ONE step, and the decision is the operator's.

The entry's reading is the one that counts, because the entry is the book that competes; the core's is reported
beside it. The post-May windows hold about eight independent fortnights, so they are shown and used only for the
TREND test, never for a band.

  .venv\\Scripts\\python.exe scripts\\liquidity_floor_study.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from qtrading.backtest.checks import assert_no_lookahead
from qtrading.backtest.metrics import field_beaten, window_metrics
from qtrading.backtest.simulator import SimConfig, simulate
from qtrading.data.binance import BinanceSource
from qtrading.data.store import PriceStore
from qtrading.data.universe import build_universe, load_snapshot
from qtrading.roostoo.models import PairInfo
from qtrading.strategy.baselines import BuyAndHold
from qtrading.strategy.momentum import HOURS_PER_DAY, Momentum, MomentumParams, liquidity_gate

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"
RESULTS = ROOT / "data" / "results"
START, IN_SAMPLE_END, CACHE_END = "2024-09-19", "2026-05-14 23:00", "2026-09-14 13:00"
BTC, ZEC = "BTC/USD", "ZEC/USD"

# the 35 hold-one-coin books every arm is ranked against: the same field as universe_bias_study, so top40 compares
FIELD = tuple(f"{c}/USD" for c in (
    "BTC ETH ZEC SOL XRP BNB FIL SUI NEAR DOGE UNI TRX TAO ADA PEPE LINK PUMP LTC ARB ENA WLD TRUMP AVAX AAVE "
    "FET XLM ICP PAXG ONDO WLFI CAKE DOT APT XPL PENGU").split())
POOL = tuple(sorted(a.pair for a in build_universe(load_snapshot(SNAPSHOT)) if a.asset_type == "crypto"))

FLOORS_M = (2, 3, 5, 8, 12)                     # $M a day; fixed before the run
REFERENCE_M, NEIGHBOURS_M = 5, (3, 8)
WINDOW_H = 24 * 7
BAND_COMPOSITE, BAND_TAIL = 0.15, 0.02          # fixed before the run; see the docstring

EWMA = dict(vol_model="ewma", ewma_lambda=0.99)
BOOKS = {
    "entry": dict(select_every_h=24, lookbacks_h=(72, 168, 336), weighting="equal", vol_target_daily=0.03, **EWMA),
    "core": dict(select_every_h=24, lookbacks_h=(72, 168, 336), weighting="inverse_vol", vol_target_daily=0.02, **EWMA),
}


def composite(w: pd.DataFrame) -> float:
    """Screen 3's formula on the median window's ratios, as the whitepaper and the bias study quote it."""
    med = lambda c: float(np.nanpercentile(w[c], 50))  # noqa: E731
    return 0.4 * med("sortino") + 0.3 * med("sharpe") + 0.3 * med("calmar")


def measure(res, w: pd.DataFrame, fb: pd.Series, btc_ret: pd.Series, sample) -> dict:
    w, fb, b = w.reindex(sample), fb.reindex(sample), btc_ret.reindex(sample)
    eq = res.equity[(res.equity.index >= sample[0]) & (res.equity.index <= sample[-1] + pd.Timedelta(days=14))]
    wts = res.weights.loc[eq.index]
    return dict(composite=composite(w), median=float(np.nanpercentile(w.ret, 50)), p10=float(np.nanpercentile(w.ret, 10)),
                worst=float(w.ret.min()), maxdd=float(((eq / eq.cummax()) - 1).min()),
                total=float(eq.iloc[-1] / eq.iloc[0] - 1), sharpe=float(np.nanpercentile(w.sharpe, 50)),
                top40_up=float((fb[b > 0] >= .6).mean()), top40_dn=float((fb[b <= 0] >= .6).mean()),
                expo=float(wts.sum(axis=1).mean()), zec=float(wts[ZEC].mean()) if ZEC in wts else 0.0,
                fees=float(sum(t.fee for t in res.trades if eq.index[0] <= t.time <= eq.index[-1]) / eq.mean()))


def reading(ins: dict[int, dict]) -> tuple[str, list[str]]:
    """Apply the pre-registered rule to one book. `ins` maps floor ($M) to measure()'s in-sample output."""
    ref, notes = ins[REFERENCE_M], []
    for n in NEIGHBOURS_M:
        d = {k: ins[n][k] - ref[k] for k in ("composite", "worst", "maxdd")}
        apart = abs(d["composite"]) > BAND_COMPOSITE or abs(d["worst"]) > BAND_TAIL or abs(d["maxdd"]) > BAND_TAIL
        notes.append(f"${n}M vs ${REFERENCE_M}M: composite {d['composite']:+.2f}, worst {d['worst'] * 100:+.1f} pts, "
                     f"max drawdown {d['maxdd'] * 100:+.1f} pts -> {'APART' if apart else 'within the band'}")
    label = "SENSITIVE" if any("APART" in n for n in notes) else "PLATEAU"
    return label, notes


def monotone(values: list[float]) -> int:
    """+1 strictly rising with the floor, -1 strictly falling, 0 neither."""
    d = np.diff(values)
    return 1 if (d > 0).all() else -1 if (d < 0).all() else 0


def trend(results: dict[str, dict[str, dict[int, dict]]]) -> tuple[bool, str]:
    """TREND needs one direction in both books and both periods, and tails at the better end not materially worse."""
    dirs = {(book, period): monotone([results[book][period][f]["composite"] for f in FLOORS_M])
            for book in BOOKS for period in ("in", "post")}
    shape = ", ".join(f"{b}/{p} {'rising' if d > 0 else 'falling' if d < 0 else 'not monotone'}" for (b, p), d in dirs.items())
    if len(set(dirs.values())) != 1 or 0 in dirs.values():
        return False, f"no TREND ({shape})"
    better = FLOORS_M[-1] if next(iter(dirs.values())) > 0 else FLOORS_M[0]
    for book in BOOKS:
        ref, end = results[book]["in"][REFERENCE_M], results[book]["in"][better]
        if end["worst"] < ref["worst"] - BAND_TAIL or end["maxdd"] < ref["maxdd"] - BAND_TAIL:
            return False, f"monotone toward ${better}M ({shape}) but the {book}'s tails there are materially worse: no TREND"
    return True, f"TREND toward ${better}M ({shape}), tails not materially worse"


def table(title: str, rows: dict[str, dict], diag: dict[int, dict]) -> None:
    print(f"\n=== {title} ===")
    print(f"{'arm':12} {'comp':>5} {'medR':>7} {'p10R':>7} {'worst':>7} {'maxDD':>7} {'total':>8} {'Sharpe':>6} "
          f"{'up':>4} {'dn':>4} {'expo%':>5} {'fees':>6} {'zec%':>5} {'n_adm':>5}  zec admitted")
    for name, m in rows.items():
        d = diag.get(int(name.split("$")[1].rstrip("M"))) if "$" in name else None
        print(f"{name:12} {m['composite']:5.2f} {m['median'] * 100:6.2f}% {m['p10'] * 100:6.2f}% {m['worst'] * 100:6.2f}% "
              f"{m['maxdd'] * 100:6.1f}% {m['total'] * 100:+7.1f}% {m['sharpe']:6.2f} {m['top40_up'] * 100:3.0f}% "
              f"{m['top40_dn'] * 100:3.0f}% {m['expo'] * 100:4.0f}% {m['fees'] * 100:5.2f}% {m['zec'] * 100:4.1f}% "
              + (f"{d['n_adm']:5.1f}  {d['zec_first']}" if d else ""))


def main() -> int:
    snapshot = load_snapshot(SNAPSHOT)
    rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
    crypto = [a for a in build_universe(snapshot) if a.pair in POOL]
    store = PriceStore(cache_dir=ROOT / "data" / "cache", sources={"binance": BinanceSource(), "yahoo": None})
    t0, t1 = pd.Timestamp(START, tz="UTC"), pd.Timestamp(CACHE_END, tz="UTC")
    prices = store.closes(crypto, t0, t1, deadline=lambda: True)               # cache only, no network
    print(f"panel {len(POOL)} pairs, {prices.close.index[0]:%Y-%m-%d} -> {prices.close.index[-1]:%Y-%m-%d %H:%M}; "
          f"floors {', '.join(f'${f}M' for f in FLOORS_M)}; bands: composite {BAND_COMPOSITE}, tails "
          f"{BAND_TAIL * 100:.0f} pts")
    RESULTS.mkdir(parents=True, exist_ok=True)

    # what each floor admits, from the strategy's own gate (before the minimum-age rule, which is the same in every arm)
    daily = prices.volume[list(POOL)].rolling(WINDOW_H, min_periods=WINDOW_H).sum() / (WINDOW_H / HOURS_PER_DAY)
    diag = {}
    for f in FLOORS_M:
        gate = liquidity_gate(daily, f * 1e6, f * 1e6)
        first = gate.index[gate[ZEC] == 1]
        diag[f] = dict(n_adm=float(gate.iloc[WINDOW_H:].sum(axis=1).mean()),
                       zec_first=f"{first[0]:%Y-%m-%d}" if len(first) else "never")

    btc = simulate(prices, BuyAndHold(BTC), rules, SimConfig(decision_every_h=24))
    btc_w = window_metrics(btc.equity)
    all_w = btc_w.index
    samples = {"in": all_w[all_w <= pd.Timestamp(IN_SAMPLE_END, tz="UTC") - pd.Timedelta(days=14)],
               "post": all_w[all_w >= pd.Timestamp("2026-05-15", tz="UTC")]}

    results = {book: {"in": {}, "post": {}} for book in BOOKS}
    for book, params in BOOKS.items():
        for f in FLOORS_M:
            t = time.time()
            name = f"{book}:${f}M"
            strat = Momentum(MomentumParams(pairs=POOL, liquidity_min_daily=f * 1e6, liquidity_window_h=WINDOW_H,
                                            **params), name=name)
            assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
            res = simulate(prices, strat, rules, SimConfig(decision_every_h=1))
            w = window_metrics(res.equity)
            w.to_csv(RESULTS / f"floor_{book}_{f}M_windows.csv")
            fb = field_beaten(w["ret"], prices.close, FIELD)
            for period, sample in samples.items():
                results[book][period][f] = measure(res, w, fb, btc_w["ret"], sample)
            print(f"  {name:12} {len(res.trades):5d} trades  in-sample composite "
                  f"{results[book]['in'][f]['composite']:.2f}  ({time.time() - t:.0f}s)")
            sys.stdout.flush()

    for period, title in (("in", "IN-SAMPLE"), ("post", "POST 2026-05-15 (shown; used only for the TREND test)")):
        rows = {f"{book}:${f}M": results[book][period][f] for book in BOOKS for f in FLOORS_M}
        table(f"{title}: {len(samples[period])} windows", rows, diag)

    print("\n=== THE READING, by the rule fixed before the run ===")
    for book in BOOKS:
        label, notes = reading(results[book]["in"])
        three = [results[book]["in"][f] for f in (NEIGHBOURS_M[0], REFERENCE_M, NEIGHBOURS_M[1])]
        print(f"{book.upper()}: {label}" + ("   <- the reading that counts" if book == "entry" else ""))
        for n in notes:
            print(f"    {n}")
        print(f"    mean of $3M/$5M/$8M: composite {np.mean([m['composite'] for m in three]):.2f}, worst "
              f"{np.mean([m['worst'] for m in three]) * 100:.1f}%, max drawdown "
              f"{np.mean([m['maxdd'] for m in three]) * 100:.1f}%, total {np.mean([m['total'] for m in three]) * 100:+.0f}%")
    is_trend, why = trend(results)
    print(f"TREND test: {why}")
    print(f"\n$5M is kept in every reading. {'A one-step move is RECOMMENDED to the operator, not adopted.' if is_trend else 'No other level is defensible from this run.'}")
    print("columns: comp = Screen 3 composite on median window ratios; up/dn = share of BTC-up / BTC-down windows "
          "beating >= 60% of the 35 hold-one-coin books; zec% = mean weight in ZEC; n_adm = mean pairs the floor "
          "admits (before the minimum-age rule); zec admitted = first hour the floor admits ZEC")
    return 0


if __name__ == "__main__":
    sys.exit(main())
