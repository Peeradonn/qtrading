"""Rolling 14-day scoring, mirroring the competition's Screen 2/3 as far as the rules are known.

Assumptions (to be confirmed at the workshop): portfolio value sampled daily at 00:00 UTC; ratios computed from
daily simple returns with sample standard deviation and annualised by sqrt(365); Calmar = window return / max
drawdown (un-annualised — every team is scored on the same 14 days, so annualisation only rescales).
"""
import numpy as np
import pandas as pd

ANNUALISE = np.sqrt(365)
COMPOSITE_WEIGHTS = {"sortino": 0.4, "sharpe": 0.3, "calmar": 0.3}


def daily_equity(equity: pd.Series, sample_hour: int = 0) -> pd.Series:
    return equity[equity.index.hour == sample_hour]


def window_metrics(equity: pd.Series, window_days: int = 14, sample_hour: int = 0) -> pd.DataFrame:
    """One row per window start (stepping one day): ret, mdd, sharpe, sortino, calmar."""
    daily = daily_equity(equity, sample_hour)
    d = daily.to_numpy(dtype=float)
    rows = []
    for i in range(len(d) - window_days):
        path = d[i:i + window_days + 1]
        r = path[1:] / path[:-1] - 1
        ret = path[-1] / path[0] - 1
        mdd = -((path / np.maximum.accumulate(path)) - 1).min()
        sd = r.std(ddof=1)
        down = np.sqrt(np.mean(np.minimum(r, 0.0) ** 2))
        rows.append((daily.index[i], ret, mdd,
                     r.mean() / sd * ANNUALISE if sd > 0 else np.nan,
                     r.mean() / down * ANNUALISE if down > 0 else np.nan,
                     ret / mdd if mdd > 0 else np.nan))
    return pd.DataFrame(rows, columns=["start", "ret", "mdd", "sharpe", "sortino", "calmar"]).set_index("start")


def rank_composite(windows_by_strategy: dict[str, pd.DataFrame]) -> pd.Series:
    """Judges' composite with each ratio rank-normalised across the compared strategies per window
    (best = 1, worst = 0), then the median over windows. Robust to whatever normalisation the judges use.
    Undefined ratios (a flat window: zero return, zero vol, zero drawdown) count as 0 — between losing and
    winning — so that doing nothing cannot top the table."""
    names = list(windows_by_strategy)
    common = None
    for w in windows_by_strategy.values():
        common = w.index if common is None else common.intersection(w.index)
    scores = pd.Series(0.0, index=names)
    for metric, weight in COMPOSITE_WEIGHTS.items():
        table = pd.DataFrame({n: windows_by_strategy[n].loc[common, metric] for n in names}).fillna(0.0)
        ranks = table.rank(axis=1, method="average")
        norm = (ranks - 1) / max(len(names) - 1, 1)
        scores += weight * norm.median()
    return scores


def active_days_per_window(trades, window_starts: pd.DatetimeIndex, window_days: int = 14) -> pd.Series:
    """Distinct UTC calendar days with at least one trade inside [start, start + window_days), per window.
    The competition requires at least 8 such days per bot over the 14-day contest."""
    days = pd.DatetimeIndex(sorted({t.time.floor("D") for t in trades}))
    counts = []
    for start in window_starts:
        stop = start + pd.Timedelta(days=window_days)
        counts.append(int(((days >= start) & (days < stop)).sum()))
    return pd.Series(counts, index=window_starts, name="active_days")


def field_beaten(window_ret: pd.Series, close: pd.DataFrame, pairs, window_days: int = 14,
                 sample_hour: int = 0) -> pd.Series:
    """Screen 2 is a rank, so: per window start, the share of hold-one-coin competitors (one per pair in ``pairs``)
    whose return over the same window the strategy beat. A pair without a price at both ends of a window is not
    part of that window's field."""
    daily = close[close.index.hour == sample_hour].reindex(columns=list(pairs))
    field = (daily.shift(-window_days) / daily - 1).reindex(window_ret.index)
    beaten = field.lt(window_ret, axis=0) & field.notna()
    return beaten.sum(axis=1) / field.notna().sum(axis=1)
