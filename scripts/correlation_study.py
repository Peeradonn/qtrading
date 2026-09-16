"""PRE-REGISTERED STUDY (2026-09-16): is there a family uncorrelated with the core, fit to be a second bot?

Two bots improve the odds only if they win in different fortnights. The primary measure is therefore the
correlation of 14-day window returns with the core -- mechanical, and much harder to fool yourself about than
PnL. Returns are reported for context and are NOT the selection criterion.

Decision rule, fixed before running:
  * a candidate is interesting only if its window-return correlation with the core is below 0.7;
  * of those, prefer the one whose worst fortnight is least correlated with the core's worst fortnights;
  * a candidate that cannot plausibly clear a return threshold is a Screen-3 specialist, not a Screen-2 entry,
    and must be judged as such.
Nothing here overrides the core, which has already passed an out-of-sample test.

  .venv\\Scripts\\python.exe scripts\\correlation_study.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from qtrading.backtest.metrics import window_metrics
from qtrading.backtest.simulator import SimConfig, simulate
from qtrading.data.binance import BinanceSource
from qtrading.data.store import PriceStore
from qtrading.data.universe import build_universe, load_snapshot
from qtrading.data.yahoo import YahooSource
from qtrading.roostoo.models import PairInfo
from qtrading.strategy.candidates import LowVolatility
from qtrading.strategy.momentum import Momentum, MomentumParams

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"
IN_SAMPLE_END = "2026-05-14 23:00"

LIQUID = tuple(f"{c}/USD" for c in (
    "BTC ETH ZEC SOL XRP BNB FIL SUI NEAR DOGE UNI TRX TAO ADA PEPE LINK PUMP LTC ARB ENA WLD TRUMP AVAX AAVE "
    "FET XLM ICP PAXG ONDO WLFI CAKE DOT APT XPL PENGU").split())

CORE = dict(pairs=LIQUID, select_every_h=24, lookbacks_h=(72, 168, 336), weighting="inverse_vol",
            vol_target_daily=0.02, vol_model="ewma", ewma_lambda=0.99)


def candidates():
    """Each reuses the core's portfolio machinery; only the ranking differs."""
    return [
        Momentum(MomentumParams(**CORE), name="core"),
        Momentum(MomentumParams(**{**CORE, "weighting": "equal", "vol_target_daily": None}), name="riskon"),
        LowVolatility(MomentumParams(**CORE), name="lowvol"),
        # risk parity: hold everything eligible, weighted by inverse volatility -- no selection at all
        Momentum(MomentumParams(**{**CORE, "k": 40, "buffer_rank": 80}), name="riskparity"),
    ]


def main() -> int:
    snapshot = load_snapshot(SNAPSHOT)
    universe = [a for a in build_universe(snapshot) if a.pair in LIQUID]
    rules = {p: PairInfo.from_payload(p, d) for p, d in snapshot["TradePairs"].items()}
    store = PriceStore(cache_dir=ROOT / "data" / "cache", sources={"binance": BinanceSource(), "yahoo": YahooSource()})
    prices = store.closes(universe, pd.Timestamp("2024-09-19", tz="UTC"),
                          pd.Timestamp(IN_SAMPLE_END, tz="UTC"), deadline=lambda: True)
    print(f"{len(universe)} assets, {prices.close.index[0]:%Y-%m-%d} -> {prices.close.index[-1]:%Y-%m-%d} "
          f"(in sample)\n")

    windows, equity = {}, {}
    for strat in candidates():
        t0 = time.time()
        res = simulate(prices, strat, rules, SimConfig(decision_every_h=1))
        windows[strat.name] = window_metrics(res.equity)
        equity[strat.name] = res.equity
        w = windows[strat.name]
        print(f"  {strat.name:12} {len(res.trades):5d} trades  medR {np.nanpercentile(w.ret, 50) * 100:6.2f}%  "
              f"worst {w.ret.min() * 100:7.2f}%  Sharpe {np.nanpercentile(w.sharpe, 50):5.2f}  "
              f"Sortino {np.nanpercentile(w.sortino, 50):5.2f}  "
              f"total {res.equity.iloc[-1] / res.equity.iloc[0] - 1:+7.1%}  ({time.time() - t0:.0f}s)")
        sys.stdout.flush()

    names = list(windows)
    ret = pd.DataFrame({n: windows[n]["ret"] for n in names}).dropna()
    daily = pd.DataFrame({n: equity[n][equity[n].index.hour == 0].pct_change() for n in names}).dropna()

    print("\n=== PRIMARY: correlation of 14-day window returns ===")
    print(f"{'':12}" + "".join(f"{n:>12}" for n in names))
    corr = ret.corr()
    for a in names:
        print(f"{a:12}" + "".join(f"{corr.loc[a, b]:12.2f}" for b in names))

    print("\n=== daily-return correlation (context) ===")
    dcorr = daily.corr()
    for a in names:
        print(f"{a:12}" + "".join(f"{dcorr.loc[a, b]:12.2f}" for b in names))

    print("\n=== do they lose in the same fortnights? ===")
    core_bad = ret["core"] < ret["core"].quantile(0.25)
    print(f"{'candidate':12} {'corr w/ core':>13} {'mean when core in worst quartile':>34}")
    print(f"{'core':12} {1.00:13.2f} {ret['core'][core_bad].mean() * 100:33.2f}%")
    for n in names[1:]:
        print(f"{n:12} {corr.loc['core', n]:13.2f} {ret[n][core_bad].mean() * 100:33.2f}%")

    print("\n=== a 50/50 split of capital between the core and each candidate ===")
    print(f"{'pairing':22} {'medR':>8} {'p10':>8} {'worst':>8} {'Sharpe':>8} {'Sortino':>8}")
    for n in names:
        blend = (ret["core"] + ret[n]) / 2 if n != "core" else ret["core"]
        sharpe = blend.mean() / blend.std() * np.sqrt(365 / 14) if blend.std() else np.nan
        down = np.sqrt(np.mean(np.minimum(blend, 0) ** 2))
        sortino = blend.mean() / down * np.sqrt(365 / 14) if down else np.nan
        label = "core alone" if n == "core" else f"core + {n}"
        print(f"{label:22} {blend.median() * 100:7.2f}% {blend.quantile(0.1) * 100:7.2f}% "
              f"{blend.min() * 100:7.2f}% {sharpe:8.2f} {sortino:8.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
