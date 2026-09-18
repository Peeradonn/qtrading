"""Tradeable universe from a Roostoo exchangeInfo snapshot, each asset mapped to its data source."""
import json
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Roostoo tokenized-stock coin -> Yahoo ticker of the underlying. All 21 verified to return data (2026-09-14).
STOCK_UNDERLYING = {
    "NVDAB": "NVDA", "TSLAB": "TSLA", "GOOGLB": "GOOGL", "MSFTB": "MSFT", "METAB": "META", "AMDB": "AMD",
    "INTCB": "INTC", "QCOMB": "QCOM", "PLTRB": "PLTR", "MSTRB": "MSTR", "COINB": "COIN", "CRCLB": "CRCL",
    "MUB": "MU", "SNDKB": "SNDK", "WDCB": "WDC", "GLWB": "GLW", "LITEB": "LITE", "NBISB": "NBIS",
    "SPCXB": "SPCX",        # SpaceX, listed 2026-06 — short history
    "CBRSB": "CBRS",        # Cerebras, listed 2026-05 — short history
    "SKHYB": "000660.KS",   # SK Hynix on KRX; KRW-denominated -- and the token prints ~178 USD against ~1.7M KRW a share,
                            # so this mapping is suspect; excluded from research until resolved
}

# Roostoo's stock pairs are tokenised equities that price around the clock (verified 2026-09-17). Bybit's spot
# xStocks are the same instrument class with free 24/7 hourly history, for the names it lists.
TOKEN_SYMBOLS = {"COINB": "COINXUSDT", "CRCLB": "CRCLXUSDT", "GOOGLB": "GOOGLXUSDT", "METAB": "METAXUSDT",
                 "NVDAB": "NVDAXUSDT", "TSLAB": "TSLAXUSDT", "SPCXB": "SPCXXUSDT"}


@dataclass(frozen=True)
class Asset:
    pair: str          # Roostoo pair, e.g. "BTC/USD"
    coin: str          # Roostoo coin, e.g. "BTC" or "NVDAB"
    asset_type: str    # "crypto" | "stock"
    source: str        # "binance" | "yahoo"
    symbol: str        # symbol at the data source, e.g. "BTCUSDT" or "NVDA"


def load_snapshot(path) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def build_universe(snapshot: dict) -> list[Asset]:
    assets = []
    for pair, d in snapshot["TradePairs"].items():
        if not d.get("CanTrade"):
            continue
        coin, asset_type = d["Coin"], d.get("AssetType", "")
        if asset_type == "crypto":
            assets.append(Asset(pair, coin, asset_type, "binance", f"{coin}USDT"))
        elif asset_type == "stock":
            ticker = STOCK_UNDERLYING.get(coin)
            if ticker is None:
                log.warning("no known underlying for %s; excluded", pair)
                continue
            assets.append(Asset(pair, coin, asset_type, "yahoo", ticker))
        else:
            log.warning("unknown AssetType %r for %s; excluded", asset_type, pair)
    return assets


def liquid_pairs(snapshot: dict, volumes: dict[str, float], min_volume: float) -> list[str]:
    """The crypto pairs the ranking may choose from: tradeable, and liquid enough to size a position in.

    Ordered by 24h traded value, descending. Tokenised equities are excluded by rule rather than by volume —
    whitepaper section 7 rejected them for the entry — and gold needs no special case, clearing the floor on its
    own. A pair absent from `volumes` is treated as having traded nothing, so a quiet pair is dropped rather than
    silently kept.
    """
    tradeable = {pair: volumes.get(pair, 0.0) for pair, d in snapshot["TradePairs"].items()
                 if d.get("CanTrade") and d.get("AssetType") == "crypto"}
    return sorted((p for p, v in tradeable.items() if v >= min_volume), key=lambda p: (-tradeable[p], p))


def token_assets(snapshot: dict) -> list[Asset]:
    """The stock pairs whose 24/7 token history Bybit publishes, as assets sourced from Bybit."""
    return [Asset(pair, d["Coin"], "stock", "bybit", TOKEN_SYMBOLS[d["Coin"]])
            for pair, d in snapshot["TradePairs"].items()
            if d.get("CanTrade") and d.get("AssetType") == "stock" and d["Coin"] in TOKEN_SYMBOLS]
