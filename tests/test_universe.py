"""Universe: Roostoo exchangeInfo snapshot -> tradeable assets, each mapped to a data source and symbol."""
from qtrading.data.universe import Asset, build_universe


def pair(coin, asset_type, can_trade=True):
    return {"Coin": coin, "CoinFullName": coin, "Unit": "USD", "UnitFullName": "US Dollar", "CanTrade": can_trade,
            "PricePrecision": 2, "AmountPrecision": 5, "MiniOrder": 1, "AssetType": asset_type}


SNAPSHOT = {
    "IsRunning": True,
    "InitialWallet": {"USD": 50000},
    "TradePairs": {
        "BTC/USD": pair("BTC", "crypto"),
        "NVDAB/USD": pair("NVDAB", "stock"),
        "ZZZB/USD": pair("ZZZB", "stock"),                 # no known underlying
        "OLD/USD": pair("OLD", "crypto", can_trade=False),
    },
}


def by_pair(universe):
    return {a.pair: a for a in universe}


def test_crypto_pairs_map_to_binance_usdt_symbols():
    u = by_pair(build_universe(SNAPSHOT))
    assert u["BTC/USD"] == Asset(pair="BTC/USD", coin="BTC", asset_type="crypto", source="binance", symbol="BTCUSDT")


def test_stock_pairs_map_to_yahoo_tickers_of_the_underlying():
    u = by_pair(build_universe(SNAPSHOT))
    assert u["NVDAB/USD"] == Asset(pair="NVDAB/USD", coin="NVDAB", asset_type="stock", source="yahoo", symbol="NVDA")


def test_untradeable_and_unmapped_pairs_are_excluded():
    pairs = set(by_pair(build_universe(SNAPSHOT)))
    assert "OLD/USD" not in pairs
    assert "ZZZB/USD" not in pairs
