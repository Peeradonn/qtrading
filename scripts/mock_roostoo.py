"""Run the local Roostoo stand-in, so the signed order path can be rehearsed without a competition key.

  .venv\\Scripts\\python.exe scripts\\mock_roostoo.py                 # static prices from the last snapshot
  .venv\\Scripts\\python.exe scripts\\mock_roostoo.py --live-prices   # mirror the real public ticker each minute

Then point a bot at it:  .venv\\Scripts\\python.exe scripts\\run_bot.py --config configs\\mock-core.toml --once
The credentials below are fixed test values; configs/mock-core.toml carries the matching pair.
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qtrading.roostoo.client import RoostooClient  # noqa: E402
from qtrading.roostoo.mock_server import MockRoostoo, serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "snapshots" / "exchange_info_2026-09-14.json"
API_KEY = "MOCKKEY"
SECRET_KEY = "MOCKSECRET"  # pragma: allowlist secret


def public_prices() -> dict:
    client = RoostooClient(api_key="", secret_key="")
    return {pair: t.last for pair, t in client.ticker().items()}


def refresh_forever(exchange: MockRoostoo, every_s: int = 60) -> None:
    while True:
        time.sleep(every_s)
        try:
            exchange.prices.update(public_prices())
        except Exception as e:
            print(f"price refresh failed: {type(e).__name__}: {e}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--wallet", type=float, default=1_000_000.0)
    ap.add_argument("--live-prices", action="store_true", help="mirror the real public ticker")
    args = ap.parse_args()

    pairs = json.loads(SNAPSHOT.read_text(encoding="utf-8-sig"))["TradePairs"]
    if args.live_prices:
        prices = public_prices()
        print(f"seeded {len(prices)} live prices from the public ticker")
    else:
        prices = {pair: 100.0 for pair in pairs}
        print(f"using flat placeholder prices for {len(prices)} pairs (pass --live-prices for real ones)")

    exchange = MockRoostoo(API_KEY, SECRET_KEY, pairs, prices, wallet={"USD": args.wallet})
    if args.live_prices:
        threading.Thread(target=refresh_forever, args=(exchange,), daemon=True).start()

    server = serve(exchange, port=args.port)
    print(f"mock Roostoo on http://127.0.0.1:{args.port}  key={API_KEY}  wallet=${args.wallet:,.0f}")
    print("point a bot at it with configs/mock-core.toml; Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        filled = [o for o in exchange.orders if o["Status"] == "FILLED"]
        print(f"\n{len(exchange.requests)} requests, {len(exchange.orders)} orders ({len(filled)} filled)")
        print("wallet:", {a: round(q, 6) for a, q in exchange.wallet.items() if q})
    return 0


if __name__ == "__main__":
    sys.exit(main())
