"""PriceStore: per-symbol parquet cache with incremental updates, assembled into hourly UTC panels.

Grid rule: grid time T holds the last bar whose close time falls in (T - 1h, T]. A bar closing at 01:30 is
therefore first visible at 02:00 — never at 01:00 — so consumers cannot see the future by construction.
Hours with no closing bar carry the previous close forward and are flagged in `stale`.
"""
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .universe import Asset


@dataclass
class Prices:
    close: pd.DataFrame                    # hourly UTC index × Roostoo pair; NaN before an asset's first bar
    stale: pd.DataFrame                    # True where no bar closed within the hour (value carried forward, or NaN)
    volume: pd.DataFrame | None = None     # dollar volume traded in bars closing within the hour; 0 where none
    extra: dict = field(default_factory=dict)   # other aligned panels by name, e.g. "funding"


class PriceStore:
    def __init__(self, cache_dir, sources: dict, interval: str = "1h"):
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._sources = sources
        self._interval = interval
        self._step = pd.Timedelta(interval)

    # ---- panels -----------------------------------------------------------

    def closes(self, assets: list[Asset], start: pd.Timestamp, end: pd.Timestamp) -> Prices:
        grid = self._grid(start, end)
        close, stale, volume = {}, {}, {}
        for a in assets:
            bars = self._bars(a, start, end)
            on_grid = bars["close"].resample(self._step, label="right", closed="right").last().reindex(grid)
            stale[a.pair] = on_grid.isna()
            close[a.pair] = on_grid.ffill()
            dollars = bars["quote_volume"] if "quote_volume" in bars.columns else bars["volume"] * bars["close"]
            volume[a.pair] = dollars.resample(self._step, label="right", closed="right").sum().reindex(grid).fillna(0.0)
        return Prices(close=pd.DataFrame(close, index=grid), stale=pd.DataFrame(stale, index=grid),
                      volume=pd.DataFrame(volume, index=grid))

    def funding(self, assets: list[Asset], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """Perpetual funding rate per pair, carried forward from each settlement until the next.
        Pairs whose source has no funding data get a NaN column."""
        grid = self._grid(start, end)
        out = {}
        for a in assets:
            source = self._sources.get(a.source)
            if source is None or not hasattr(source, "funding_rates"):
                out[a.pair] = pd.Series(float("nan"), index=grid)
                continue
            path = self._dir / f"{a.source}_funding_{a.symbol.replace('.', '_')}.parquet"
            frame = self._cached(path, lambda s, e: source.funding_rates(a.symbol, s, e).to_frame("funding_rate"),
                                 start, end, step=pd.Timedelta(hours=8))
            series = frame["funding_rate"] if not frame.empty else pd.Series(dtype=float)
            out[a.pair] = series.reindex(grid, method="ffill") if not series.empty else pd.Series(float("nan"), index=grid)
        return pd.DataFrame(out, index=grid)

    def _grid(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
        """Whole-hour grid inside [start, end]: bars close on the hour, so an off-hour request must snap."""
        return pd.date_range(start.ceil(self._step), end.floor(self._step), freq=self._step, name="time")

    # ---- cache ------------------------------------------------------------

    def _path(self, a: Asset) -> Path:
        return self._dir / f"{a.source}_{a.symbol.replace('.', '_')}_{self._interval}.parquet"

    def _bars(self, a: Asset, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        source = self._sources[a.source]
        return self._cached(self._path(a), lambda s, e: source.bars(a.symbol, s, e), start, end, step=self._step)

    @staticmethod
    def _cached(path: Path, fetch, start: pd.Timestamp, end: pd.Timestamp, step: pd.Timedelta) -> pd.DataFrame:
        """Serve [start, end] from the parquet at ``path``, fetching only the missing head and/or tail."""
        cached = pd.read_parquet(path) if path.exists() else None
        if cached is not None and cached.empty:
            cached = None

        if cached is None:
            merged = fetch(start, end)
        else:
            parts = [cached]
            if start < cached.index[0]:
                parts.append(fetch(start, cached.index[0] - step))
            if end > cached.index[-1]:
                parts.append(fetch(cached.index[-1] + step, end))
            merged = pd.concat([p for p in parts if not p.empty]).sort_index()
            merged = merged[~merged.index.duplicated(keep="last")]

        if not merged.empty:
            merged.to_parquet(path)
        return merged[(merged.index >= start) & (merged.index <= end)]
