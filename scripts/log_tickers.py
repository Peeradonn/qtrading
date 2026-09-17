"""Record every Roostoo ticker at a fixed interval, so questions the API docs do not answer can be answered from
data: do tokenised stocks price outside US hours and over the weekend, how far do they sit from the underlying, how
stale is the crypto feed against Binance, what do bid/ask spreads look like.

Appends one row per pair per poll to a CSV (git-ignored). Public endpoint only, no keys. Polite: one request per poll.

  .venv\\Scripts\\python.exe scripts\\log_tickers.py [--every 300] [--out data/ticks/roostoo_ticker.csv]
"""
import argparse
import csv
import datetime as dt
import logging
import sys
import time
from pathlib import Path

from qtrading.roostoo.client import RoostooClient

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["polled_at", "pair", "last", "bid", "ask", "change_24h", "coin_volume_24h", "unit_volume_24h"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=300, help="seconds between polls")
    ap.add_argument("--out", default="data/ticks/roostoo_ticker.csv")
    args = ap.parse_args()
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = RoostooClient(api_key="", secret_key="")
    new = not out.exists()
    while True:
        polled_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        try:
            quotes = client.ticker()
            with out.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                if new:
                    w.writeheader()
                    new = False
                for pair, t in sorted(quotes.items()):
                    w.writerow({"polled_at": polled_at, "pair": pair, "last": t.last, "bid": t.bid, "ask": t.ask,
                                "change_24h": t.change_24h, "coin_volume_24h": t.coin_volume_24h,
                                "unit_volume_24h": t.unit_volume_24h})
            logging.info("logged %d pairs", len(quotes))
        except Exception as exc:                      # a failed poll must not end a multi-day watch
            logging.warning("poll failed: %s", exc)
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
