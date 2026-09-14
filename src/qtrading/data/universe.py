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
    "SKHYB": "000660.KS",   # SK Hynix on KRX; KRW-denominated, so returns differ from the USD token by USDKRW moves
}


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
