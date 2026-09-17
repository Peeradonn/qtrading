"""Does market sentiment carry information our price signal does not? (2026-09-17)

The only sentiment series with a free, daily, multi-year history is alternative.me's Crypto Fear & Greed index
(volatility, momentum/volume, social media, surveys, BTC dominance, Google Trends). Headline-level news scored by an
LLM cannot be backtested honestly -- the model has read the history it would be scored on -- so this is the
sentiment test that *can* be run. Descriptive: rank correlations and bucket tables, no strategy, no fees.

  .venv\\Scripts\\python.exe scripts\\sentiment_check.py

Result on 2024-09-19 -> 2026-09-16 (728 days): rank correlation between the index and BTC's forward return is
+0.02 (1d), +0.00 (3d), +0.03 (7d), +0.07 (14d) -- indistinguishable from zero and the same sign and size as the
trailing 14-day return, with which the index is 0.56 rank-correlated. It is price momentum with a survey attached.
The core's fortnight return is likewise uncorrelated with the index at the window start (+0.06). Rejected as a
signal; see the whitepaper, section 7.
"""
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
FNG_URL = "https://api.alternative.me/fng/?limit=0&format=json"
LABELS = ["extreme fear <=25", "fear 26-45", "neutral 46-55", "greed 56-75", "extreme greed >75"]


def rank_corr(a: pd.Series, b: pd.Series) -> float:
    ok = a.notna() & b.notna()
    return float(a[ok].rank().corr(b[ok].rank()))


def fear_and_greed() -> pd.Series:
    path = CACHE / "fear_greed.csv"
    if path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)["fng"]
    req = urllib.request.Request(FNG_URL, headers={"User-Agent": "qtrading-research"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)["data"]
    s = pd.Series({pd.Timestamp(int(d["timestamp"]), unit="s", tz="UTC"): int(d["value"]) for d in rows}, name="fng")
    s = s.sort_index()
    s.to_frame().to_csv(path)
    return s


def main() -> int:
    btc = pd.read_parquet(CACHE / "binance_BTCUSDT_1h.parquet")["close"].sort_index()
    daily = btc[btc.index.hour == 0]
    fng = fear_and_greed().reindex(daily.index, method="ffill")
    past14 = daily / daily.shift(14) - 1
    print(f"{len(daily)} days, {daily.index[0]:%Y-%m-%d} -> {daily.index[-1]:%Y-%m-%d}; "
          f"index mean {fng.mean():.0f}, range {fng.min():.0f}-{fng.max():.0f}")

    print("\n=== rank correlation with BTC's forward return ===")
    for h in (1, 3, 7, 14):
        fwd = daily.shift(-h) / daily - 1
        print(f"  {h:2d}d: Fear&Greed {rank_corr(fng, fwd):+.3f}   trailing 14d return {rank_corr(past14, fwd):+.3f}")
    print(f"  Fear&Greed vs trailing 14d return: {rank_corr(fng, past14):+.2f}   (day-to-day autocorrelation "
          f"{fng.autocorr(1):.2f})")

    fwd14 = daily.shift(-14) / daily - 1
    bucket = pd.cut(fng, [0, 25, 45, 55, 75, 100], labels=LABELS)
    g = fwd14.groupby(bucket, observed=False)
    print("\n=== BTC forward 14-day return by bucket ===")
    print(pd.DataFrame({"n": g.count(), "median %": g.median() * 100, "p10 %": g.quantile(.1) * 100,
                        "P(>0) %": g.apply(lambda s: (s > 0).mean()) * 100}).round(2).to_string())

    core_path = ROOT / "data" / "results" / "gold_core_windows.csv"
    if core_path.exists():
        core = pd.read_csv(core_path, index_col=0, parse_dates=True)["ret"]
        common = core.index.intersection(fng.dropna().index)
        c, f = core.reindex(common), fng.reindex(common)
        gc = c.groupby(pd.cut(f, [0, 25, 45, 55, 75, 100], labels=LABELS), observed=False)
        print("\n=== the core's fortnight return by the index level at the window start ===")
        print(pd.DataFrame({"n": gc.count(), "median %": gc.median() * 100, "p10 %": gc.quantile(.1) * 100,
                            "P(>0) %": gc.apply(lambda s: (s > 0).mean()) * 100}).round(2).to_string())
        print(f"  rank correlation with the core's fortnight return: {rank_corr(f, c):+.3f}")
    else:
        print("\n(run scripts/gold_sleeve_study.py first to compare against the core's fortnights)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
