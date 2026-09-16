"""Why does the bot hold what it holds? Prints the live ranking with every input to the decision.

  .venv\\Scripts\\python.exe scripts\\explain_selection.py --config configs\\paper-core.toml

For each asset: the return over each lookback (skipping the most recent hours, as the strategy does), the
volatility estimate, each horizon's risk-adjusted score, the composite, and its rank. Then the current book and
the strategy memory (when it last selected, and what). Uses cached prices only, so it never touches the network.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from qtrading.data.binance import BinanceSource
from qtrading.data.store import PriceStore
from qtrading.data.universe import build_universe, load_snapshot
from qtrading.engine.config import load_config
from qtrading.engine.state import load_memory
from qtrading.strategy.momentum import Momentum

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--top", type=int, default=35)
    args = ap.parse_args()

    cfg = load_config(Path(args.config).resolve())
    p = cfg.strategy
    universe = [a for a in build_universe(load_snapshot(SNAPSHOT)) if a.pair in p.pairs]
    store = PriceStore(cache_dir=ROOT / "data" / "cache", sources={"binance": BinanceSource(), "yahoo": None})
    end = pd.Timestamp.now(tz="UTC").floor("h")
    prices = store.closes(universe, end - pd.Timedelta(days=cfg.lookback_days), end, deadline=lambda: True)

    # the panel may end before `end` if the cache has not been refreshed this hour; use its newest complete row
    live = ~prices.stale.all(axis=1)
    at = prices.close.index[live][-1]
    strat = Momentum(p, name=cfg.name)
    sig = strat.signals(prices).loc[:at].iloc[-1]
    close = prices.close.loc[:at]

    rows = []
    for pair in p.pairs:
        if pair not in close.columns:
            continue
        c = close[pair]
        vol = sig[("vol", pair)]
        row = {"pair": pair, "score": sig[("score", pair)], "vol_daily": vol * np.sqrt(24)}
        for L in p.lookbacks_h:
            r = c.iloc[-1 - p.skip_h] / c.iloc[-1 - p.skip_h - L] - 1 if len(c) > p.skip_h + L else np.nan
            row[f"r{L // 24}d"] = r
            row[f"s{L // 24}d"] = r / (vol * np.sqrt(L)) if vol and np.isfinite(vol) else np.nan
        rows.append(row)
    table = pd.DataFrame(rows).set_index("pair").sort_values("score", ascending=False)
    table["rank"] = range(1, len(table) + 1)

    memory = load_memory(ROOT / cfg.paths.memory)
    selected = set(memory.get("selected", []))
    wallet = json.loads((ROOT / cfg.paths.wallet).read_text(encoding="utf-8")) if cfg.exchange == "paper" else {}
    held = {f"{k}/USD" for k, v in wallet.items() if not k.startswith("_") and k != "USD" and v > 0}

    horizons = [f"{L // 24}d" for L in p.lookbacks_h]
    print(f"{cfg.name}: signals as of {at:%Y-%m-%d %H:%M} UTC  "
          f"(vol model {p.vol_model}{'' if p.vol_model == 'trailing' else f' lambda {p.ewma_lambda}'}, "
          f"skip last {p.skip_h}h, hold top {p.k}, keep while rank <= {p.buffer_rank})\n")
    head = f"{'rank':>4} {'pair':11}" + "".join(f"{'ret ' + h:>9}" for h in horizons) + \
           f"{'vol/day':>9}" + "".join(f"{'score ' + h:>10}" for h in horizons) + f"{'SCORE':>8}  status"
    print(head)
    for pair, r in table.head(args.top).iterrows():
        status = ("HELD" if pair in held else "") + (" selected" if pair in selected else "")
        if not status and r["rank"] <= p.k:
            status = "top-k, not selected"
        if np.isnan(r["score"]):
            status = "ineligible (too new or stale)"
        rets = "".join(f"{r['r' + h] * 100:8.1f}%" for h in horizons)
        scores = "".join(f"{r['s' + h]:10.2f}" for h in horizons)
        score = "     n/a" if np.isnan(r["score"]) else f"{r['score']:8.2f}"
        print(f"{int(r['rank']):4d} {pair:11}{rets}{r['vol_daily'] * 100:8.1f}%{scores}{score}  {status.strip()}")

    positive = int((table["score"] > 0).sum())
    print(f"\n{positive} of {int(table['score'].notna().sum())} eligible assets have a positive composite score.")
    last = memory.get("last_select")
    print(f"last selection: {last}  ->  {sorted(selected)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
