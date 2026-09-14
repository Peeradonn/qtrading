"""PriceStore: per-symbol parquet cache with incremental updates, assembled into an hourly UTC panel.

Grid rule: grid time T holds the last bar whose close time falls in (T - 1h, T]. A bar closing at 01:30 is
therefore first visible at 02:00 — never at 01:00 — so consumers cannot see the future by construction.
Hours with no closing bar carry the previous close forward and are flagged in `stale`.
"""
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .universe import Asset


@dataclass
class Prices:
    close: pd.DataFrame   # hourly UTC index × Roostoo pair; NaN before an asset's first bar
    stale: pd.DataFrame   # True where no bar closed within the hour (value carried forward, or NaN)


class PriceStore:
    def __init__(self, cache_dir, sources: dict, interval: str = "1h"):
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._sources = sources
        self._interval = interval
        self._step = pd.Timedelta(interval)

    def closes(self, assets: list[Asset], start: pd.Timestamp, end: pd.Timestamp) -> Prices:
        grid = pd.date_range(start, end, freq=self._step, name="time")
        close, stale = {}, {}
        for a in assets:
            bars = self._bars(a, start, end)
            on_grid = bars["close"].resample(self._step, label="right", closed="right").last().reindex(grid)
            stale[a.pair] = on_grid.isna()
            close[a.pair] = on_grid.ffill()
        return Prices(close=pd.DataFrame(close, index=grid), stale=pd.DataFrame(stale, index=grid))

    # ---- cache ------------------------------------------------------------

    def _path(self, a: Asset) -> Path:
        return self._dir / f"{a.source}_{a.symbol.replace('.', '_')}_{self._interval}.parquet"

    def _bars(self, a: Asset, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        source = self._sources[a.source]
        path = self._path(a)
        cached = pd.read_parquet(path) if path.exists() else None
        if cached is not None and cached.empty:
            cached = None

        if cached is None:
            merged = source.bars(a.symbol, start, end)
        else:
            parts = [cached]
            if start < cached.index[0]:
                parts.append(source.bars(a.symbol, start, cached.index[0] - self._step))
            if end > cached.index[-1]:
                parts.append(source.bars(a.symbol, cached.index[-1] + self._step, end))
            merged = pd.concat([p for p in parts if not p.empty]).sort_index()
            merged = merged[~merged.index.duplicated(keep="last")]

        if not merged.empty:
            merged.to_parquet(path)
        return merged[(merged.index >= start) & (merged.index <= end)]
