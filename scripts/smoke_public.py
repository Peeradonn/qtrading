"""Live smoke test against Roostoo's public endpoints (no API keys needed).

Run:  .venv\\Scripts\\python.exe scripts\\smoke_public.py
Checks transport, clock sync, and response parsing end-to-end.
"""
import logging
import sys
import time

from qtrading.roostoo.client import RoostooClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main() -> int:
    client = RoostooClient(api_key="", secret_key="")

    local_ms = int(time.time() * 1000)
    server_ms = client.server_time()
    print(f"serverTime      {server_ms}  (local clock is {local_ms - server_ms:+d} ms vs server)")

    info = client.exchange_info()
    by_type = {}
    for p in info.values():
        by_type.setdefault(p.asset_type or "?", []).append(p.pair)
    print(f"exchangeInfo    {len(info)} pairs: " + ", ".join(f"{k}={len(v)}" for k, v in sorted(by_type.items())))
    btc = info["BTC/USD"]
    print(f"  BTC/USD rules: pricePrec={btc.price_precision} amtPrec={btc.amount_precision} minOrder={btc.min_order}")

    quotes = client.ticker()
    top = sorted(quotes.values(), key=lambda q: -q.unit_volume_24h)[:5]
    print(f"ticker          {len(quotes)} quotes; top by 24h USD volume:")
    for q in top:
        print(f"  {q.pair:10} last={q.last:<12g} bid={q.bid:<12g} ask={q.ask:<12g} 24h={q.change_24h:+.2%}")

    one = client.ticker("ETH/USD")
    assert set(one) == {"ETH/USD"}, one.keys()
    print(f"ticker(pair)    ETH/USD last={one['ETH/USD'].last}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
