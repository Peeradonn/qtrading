"""PRE-REGISTERED STUDY (2026-09-17): tokenised stocks in the ranking pool.

Why now. Roostoo's stock pairs price around the clock (verified 2026-09-17: live spreads and moving prints seven
hours after the US close, within ~0.2% of Bybit's xStocks). The repo's earlier stock tests assumed the tokens were
stale outside US hours -- an artefact of using the underlying share's history -- and selecting during US hours
degraded the crypto book. With the tokens live at 00:00 UTC, stocks can simply join the ranking at the entry's
own settings.

Data. Two histories. (a) The underlying share from Yahoo (US hours only; 20 of 21 names, SKHYB excluded as
mis-mapped), carried forward and treated as TRADABLE outside US hours ("assumed live"), with volatility still
measured on live bars only through extra["live_bars"]. (b) The tokens themselves from Bybit, 24/7 hourly since
mid-2025, for the 7 names Bybit lists. (b) validates (a) on their overlap: if the approximation is sound, "7 stocks
via Yahoo, assumed live" and "7 tokens via Bybit" must agree in direction against the crypto-only entry.

Configs, all at the entry's settings (equal weight, 3%/day target, K=6, hysteresis 12, EWMA volatility):
  entry             35 crypto pairs                                    (reference)
  entry+stocks      35 crypto + 20 stocks, Yahoo, assumed live          (the candidate)
  entry+stocks:raw  35 crypto + 20 stocks, Yahoo, stale as recorded     (the old, confounded treatment, for the record)
  core+stocks       the fallback core with the same 20 stocks           (for the record)
Validation on the overlap 2025-06-30 -> 2026-09-14 (first month is warm-up): entry; entry+7 via Yahoo, assumed
live; entry+7 via Bybit.

Pass rule versus the entry, in-sample windows (start <= 2026-04-30), fixed before running:
  1. top-40%-of-field rate in BTC-up fortnights and in BTC-down fortnights each not lower by more than 3 points;
  2. p10 and worst fortnight not worse by more than 2 points;
  3. median Sharpe and Sortino not lower by more than 0.05;
  4. total return not lower;
  5. validation: the Yahoo-assumed-live and Bybit panels agree in direction against the entry on 1-4 over the overlap;
  6. direction holds on windows starting after 2026-05-15 (unsealed; consistency only).
If it passes, the 20 stocks join the entry's universe. Caveats stated up front: Roostoo's stock list is hand-picked
AI and crypto-adjacent names, so the in-sample drift is flattered by hindsight; fills outside US hours are modelled
at the carried-forward close, so a real fill differs by the overnight move (both directions); weekend pricing is
being observed by scripts/log_tickers.py and is an operational check before go-live, not part of this test.

  .venv\\Scripts\\python.exe scripts\\stocks_study.py
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
from qtrading.data.bybit import BybitSource
from qtrading.data.store import PriceStore, Prices
from qtrading.data.universe import build_universe, load_snapshot, token_assets
from qtrading.data.yahoo import YahooSource
from qtrading.roostoo.models import PairInfo
from qtrading.strategy.baselines import BuyAndHold
from qtrading.strategy.momentum import Momentum, MomentumParams

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"
RESULTS = ROOT / "data" / "results"
START, IN_SAMPLE_END, CACHE_END = "2024-09-19", "2026-05-14 23:00", "2026-09-14 13:00"
OVERLAP_START = "2025-06-30"
BTC = "BTC/USD"

LIQUID = tuple(f"{c}/USD" for c in (
    "BTC ETH ZEC SOL XRP BNB FIL SUI NEAR DOGE UNI TRX TAO ADA PEPE LINK PUMP LTC ARB ENA WLD TRUMP AVAX AAVE "
    "FET XLM ICP PAXG ONDO WLFI CAKE DOT APT XPL PENGU").split())
EWMA = dict(vol_model="ewma", ewma_lambda=0.99)
ENTRY = dict(select_every_h=24, lookbacks_h=(72, 168, 336), weighting="equal", vol_target_daily=0.03, **EWMA)
CORE = dict(select_every_h=24, lookbacks_h=(72, 168, 336), weighting="inverse_vol", vol_target_daily=0.02, **EWMA)


def assume_live(prices: Prices, pairs) -> Prices:
    """Treat ``pairs`` as tradable whenever they have any price (Roostoo's tokens do), while the true live-bar mask
    still drives the volatility estimate."""
    stale = prices.stale.copy()
    for p in pairs:
        stale[p] = prices.close[p].isna()
    return Prices(close=prices.close, stale=stale, volume=prices.volume,
                  extra={**prices.extra, "live_bars": ~prices.stale})


def restrict(prices: Prices, pairs, start=None) -> Prices:
    cols = list(pairs)
    sl = slice(pd.Timestamp(start, tz="UTC") if start else None, None)
    extra = {k: (v.loc[sl, cols] if hasattr(v, "loc") else v) for k, v in prices.extra.items()}
    return Prices(close=prices.close.loc[sl, cols], stale=prices.stale.loc[sl, cols],
                  volume=None if prices.volume is None else prices.volume.loc[sl, cols], extra=extra)


def run(prices, rules, strat, every=1):
    assert_no_lookahead(strat, prices, at=len(prices.close) // 2)
    return simulate(prices, strat, rules, SimConfig(decision_every_h=every))


def pct(x, q):
    return float(np.nanpercentile(x, q))


def report(title, rows, sample, btc_ret, stock_pairs):
    print(f"\n=== {title}: {len(sample)} windows ===")
    head = ("strategy", "medR", "p10R", "worst", "p90R", "%>BTC", "top40", "up", "dn", "|", "BTC>10%:medR", "top40",
            "|", "Sharpe", "Sortno", "Calmar", "|", "total", "maxDD", "fees", "expo%", "stock%", "act")
    print("{:17} {:>7} {:>7} {:>7} {:>7} {:>5} {:>5} {:>4} {:>4} {} {:>12} {:>5} {} {:>6} {:>6} {:>6} {} {:>7} {:>6} "
          "{:>5} {:>5} {:>6} {:>5}".format(*head))
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
        expo = wts.sum(axis=1).mean() * 100
        stock = wts[[p for p in stock_pairs if p in wts.columns]].sum(axis=1).mean() * 100 if stock_pairs else 0.0
        print(f"{name:17} {pct(w.ret, 50) * 100:6.2f}% {pct(w.ret, 10) * 100:6.2f}% {w.ret.min() * 100:6.2f}% "
              f"{pct(w.ret, 90) * 100:6.2f}% {(w.ret > b).mean() * 100:4.0f}% {(fb >= .6).mean() * 100:4.0f}% "
              f"{(fb[up] >= .6).mean() * 100:3.0f}% {(fb[~up] >= .6).mean() * 100:3.0f}% | "
              f"{w.ret[big].median() * 100:11.1f}% {(fb[big] >= .6).mean() * 100:4.0f}% | "
              f"{pct(w.sharpe, 50):6.2f} {pct(w.sortino, 50):6.2f} {pct(w.calmar, 50):6.2f} | "
              f"{total * 100:+6.1f}% {maxdd * 100:5.1f}% {fees * 100:4.2f}% {expo:4.0f}% {stock:5.0f}% "
              f"{int(pct(ad, 10)):2d}/{int(ad.median()):2d}")


def main() -> int:
    snapshot = load_snapshot(SNAPSHOT)
    rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
    every = build_universe(snapshot)
    crypto = [a for a in every if a.pair in LIQUID]
    stocks = [a for a in every if a.asset_type == "stock" and a.coin != "SKHYB"]
    tokens = token_assets(snapshot)
    store = PriceStore(cache_dir=ROOT / "data" / "cache",
                       sources={"binance": BinanceSource(), "yahoo": YahooSource(), "bybit": BybitSource()})
    t0, t1 = pd.Timestamp(START, tz="UTC"), pd.Timestamp(CACHE_END, tz="UTC")
    full = store.closes(crypto + stocks, t0, t1, deadline=lambda: True)               # cache only
    toks = store.closes(crypto + tokens, pd.Timestamp(OVERLAP_START, tz="UTC"), t1, deadline=lambda: True)
    stock_pairs = [a.pair for a in stocks]
    token_pairs = [a.pair for a in tokens]
    print(f"{len(crypto)} crypto + {len(stocks)} stocks (Yahoo), {full.close.index[0]:%Y-%m-%d} -> "
          f"{full.close.index[-1]:%Y-%m-%d %H:%M}; {len(tokens)} tokens (Bybit) from {toks.close.index[0]:%Y-%m-%d}")
    live_h = (~full.stale[stock_pairs]).mean().mean() * 100
    print(f"stocks have a live bar in {live_h:.0f}% of hours in the Yahoo panel; the tokens in "
          f"{(~toks.stale[token_pairs]).mean().mean() * 100:.0f}% of hours in the Bybit panel\n")
    RESULTS.mkdir(parents=True, exist_ok=True)

    def sim(name, prices, params, pairs):
        t = time.time()
        strat = Momentum(MomentumParams(pairs=tuple(pairs), **params), name=name)
        res = run(prices, rules, strat)
        w = window_metrics(res.equity)
        fb = field_beaten(w["ret"], prices.close, [p for p in LIQUID if p in prices.close.columns])
        safe = "".join(c if c.isalnum() else "_" for c in name)
        w.to_csv(RESULTS / f"stocks_{safe}_windows.csv")
        n_stock = sum(1 for tr in res.trades if tr.pair in stock_pairs + token_pairs)
        print(f"  {name:17} {len(res.trades):5d} trades ({n_stock} in stocks)  total "
              f"{res.equity.iloc[-1] / res.equity.iloc[0] - 1:+7.1%}  ({time.time() - t:.0f}s)")
        sys.stdout.flush()
        return w, res, fb, active_days_per_window(res.trades, w.index)

    # --- main panel -------------------------------------------------------------------------------------------
    btc = run(full, rules, BuyAndHold(BTC), every=24)
    btc_w = window_metrics(btc.equity)
    live_panel = assume_live(full, stock_pairs)
    rows = {"hold:BTC": (btc_w, btc, field_beaten(btc_w["ret"], full.close, LIQUID),
                         active_days_per_window(btc.trades, btc_w.index))}
    rows["entry"] = sim("entry", full, ENTRY, LIQUID)
    rows["entry+stocks"] = sim("entry+stocks", live_panel, ENTRY, list(LIQUID) + stock_pairs)
    rows["entry+stocks:raw"] = sim("entry+stocks:raw", full, ENTRY, list(LIQUID) + stock_pairs)
    rows["core+stocks"] = sim("core+stocks", live_panel, CORE, list(LIQUID) + stock_pairs)

    all_w = rows["entry"][0].index
    in_sample = all_w[all_w <= pd.Timestamp(IN_SAMPLE_END, tz="UTC") - pd.Timedelta(days=14)]
    later = all_w[all_w >= pd.Timestamp("2026-05-15", tz="UTC")]
    report("IN-SAMPLE", rows, in_sample, btc_w["ret"], stock_pairs)
    report("POST 2026-05-15 (unsealed; consistency only)", rows, later, btc_w["ret"], stock_pairs)

    # --- validation of the assumed-live approximation on the token overlap -----------------------------------
    print("\n--- validation: the same 7 names via Yahoo (assumed live) and via Bybit tokens (24/7) ---")
    y7 = assume_live(restrict(full, list(LIQUID) + token_pairs, OVERLAP_START), token_pairs)
    v = {}
    btc2 = run(toks, rules, BuyAndHold(BTC), every=24)
    btc2_w = window_metrics(btc2.equity)
    v["hold:BTC"] = (btc2_w, btc2, field_beaten(btc2_w["ret"], toks.close, LIQUID),
                     active_days_per_window(btc2.trades, btc2_w.index))
    v["entry"] = sim("entry (overlap)", restrict(full, LIQUID, OVERLAP_START), ENTRY, LIQUID)
    v["entry+7 yahoo"] = sim("entry+7 yahoo", y7, ENTRY, list(LIQUID) + token_pairs)
    v["entry+7 bybit"] = sim("entry+7 bybit", toks, ENTRY, list(LIQUID) + token_pairs)
    ov = v["entry"][0].index
    ov = ov[ov >= pd.Timestamp(OVERLAP_START, tz="UTC") + pd.Timedelta(days=35)]      # after warm-up
    report(f"OVERLAP {OVERLAP_START} -> {CACHE_END[:10]} (both panels, after warm-up)", v, ov, btc2_w["ret"], token_pairs)
    print("\ncolumns: top40 = share of windows beating >= 60% of the 35 hold-one-coin crypto competitors (up/dn = BTC-up / "
          "BTC-down); 'BTC>10%' = fortnights where BTC gained over 10%; expo% = mean invested weight; stock% = mean "
          "weight in stock pairs; act = active days p10/median")
    return 0


if __name__ == "__main__":
    sys.exit(main())
