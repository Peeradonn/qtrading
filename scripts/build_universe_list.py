"""Derive the tradeable universe from committed snapshots, by rule rather than by hand.

The pair list in the configs is a strategy parameter: it decides what the ranking is allowed to choose from, and
every backtest in the whitepaper depends on it. It was originally applied by hand from a live ticker reading, so
the repo could state the rule ("crypto pairs above $5M of 24h volume, plus gold") without being able to reproduce
it. This script makes the rule executable: exchangeInfo says what can be traded, a ticker snapshot says how much
of it trades, and the floor does the rest.

  python scripts/build_universe_list.py                                  # derive from the committed snapshots
  python scripts/build_universe_list.py --config configs/eqvt3.toml      # ...and diff against that config
  python scripts/build_universe_list.py --capture                        # take a fresh ticker snapshot first

Deriving needs no network and no keys: it reads the newest snapshot of each kind under data/snapshots. Capturing
calls the public ticker endpoint once and writes a dated snapshot beside them, so the reading that produced a
universe is committed with it.

Tokenised equities are excluded by rule, not by volume: whitepaper section 7 rejected them for the entry. PAXG is
not special-cased — gold clears the floor on its own.
"""
import argparse
import datetime as dt
import json
import sys
import tomllib
from pathlib import Path

from qtrading.data.universe import liquid_pairs

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "snapshots"
DEFAULT_MIN_VOLUME = 5_000_000.0


def newest(pattern: str) -> Path:
    found = sorted(SNAPSHOTS.glob(pattern))
    if not found:
        raise SystemExit(f"no snapshot matching {pattern} in {SNAPSHOTS}; run with --capture first")
    return found[-1]


def capture_ticker() -> Path:
    """One public ticker call, written as a dated snapshot. No keys, no auth."""
    from qtrading.roostoo.client import RoostooClient

    tickers = RoostooClient(api_key="", secret_key="").ticker()
    polled_at = dt.datetime.now(dt.timezone.utc)
    snapshot = {
        "polled_at": polled_at.isoformat(),
        "source": "Roostoo GET /v3/ticker",
        "note": "24h traded value in USD (UnitTradeValue), the input to the universe's liquidity floor",
        "pairs": {pair: {"last": t.last, "unit_volume_24h": t.unit_volume_24h} for pair, t in sorted(tickers.items())},
    }
    out = SNAPSHOTS / f"ticker_{polled_at:%Y-%m-%d}.json"
    out.write_text(json.dumps(snapshot, indent=1) + "\n", encoding="utf-8")
    print(f"captured {len(snapshot['pairs'])} pairs at {polled_at:%Y-%m-%d %H:%M} UTC -> {out.relative_to(ROOT)}")
    return out


def as_toml(pairs: list[str], per_line: int = 3) -> str:
    """The list as a configs/*.toml `pairs` array, ready to paste."""
    quoted = [f'"{p}"' for p in pairs]
    lines = [", ".join(quoted[i:i + per_line]) for i in range(0, len(quoted), per_line)]
    body = ",\n         ".join(lines)
    return f"pairs = [{body}]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", action="store_true", help="take a fresh public ticker snapshot first")
    ap.add_argument("--min-volume", type=float, default=DEFAULT_MIN_VOLUME, help="24h USD traded value floor")
    ap.add_argument("--config", help="diff the derived list against this config's pairs")
    args = ap.parse_args()

    if args.capture:
        capture_ticker()
    info_path, ticker_path = newest("exchange_info_*.json"), newest("ticker_*.json")
    exchange_info = json.loads(info_path.read_text(encoding="utf-8-sig"))
    ticker = json.loads(ticker_path.read_text(encoding="utf-8-sig"))
    volumes = {pair: float(d["unit_volume_24h"]) for pair, d in ticker["pairs"].items()}
    pairs = liquid_pairs(exchange_info, volumes, args.min_volume)

    print(f"exchangeInfo : {info_path.name}")
    print(f"ticker       : {ticker_path.name}  (polled {ticker['polled_at']})")
    print(f"rule         : AssetType crypto, CanTrade, 24h traded value >= ${args.min_volume:,.0f}")
    print(f"result       : {len(pairs)} pairs\n")
    for pair in pairs:
        print(f"  {pair:14s} ${volumes[pair] / 1e6:9.2f}M")

    if args.config:
        current = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))["pairs"]
        added, dropped = sorted(set(pairs) - set(current)), sorted(set(current) - set(pairs))
        print(f"\nagainst {args.config}: {len(current)} pairs, +{len(added)} / -{len(dropped)}")
        for pair in added:
            print(f"  +  {pair:14s} ${volumes.get(pair, 0.0) / 1e6:9.2f}M   above the floor, not in the config")
        for pair in dropped:
            print(f"  -  {pair:14s} ${volumes.get(pair, 0.0) / 1e6:9.2f}M   in the config, below the floor now")
        if not added and not dropped:
            print("  (identical)")

    print(f"\n{as_toml(pairs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
