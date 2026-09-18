"""Universe: Roostoo exchangeInfo snapshot -> tradeable assets, each mapped to a data source and symbol."""
from qtrading.data.universe import Asset, build_universe, liquid_pairs


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
        "TON/USD": pair("TON", "crypto"),                   # tradeable on Roostoo, no Binance history
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


def test_a_crypto_pair_binance_does_not_carry_is_excluded():
    assert "TON/USD" not in by_pair(build_universe(SNAPSHOT))


# --- the liquidity floor: which pairs the ranking may choose from --------------------------------------------

VOLUMES = {"BTC/USD": 900e6, "ETH/USD": 600e6, "TINY/USD": 4.8e6, "EDGE/USD": 5e6, "NVDAB/USD": 50e6}
LIQUID_SNAPSHOT = {"TradePairs": {
    "BTC/USD": pair("BTC", "crypto"),
    "ETH/USD": pair("ETH", "crypto"),
    "TINY/USD": pair("TINY", "crypto"),                    # trades, but below the floor
    "EDGE/USD": pair("EDGE", "crypto"),                    # exactly at the floor
    "QUIET/USD": pair("QUIET", "crypto"),                  # tradeable, absent from the ticker entirely
    "OLD/USD": pair("OLD", "crypto", can_trade=False),     # delisted, whatever its volume
    "NVDAB/USD": pair("NVDAB", "stock"),                   # liquid, but excluded by rule
}}


def test_liquid_pairs_keeps_tradeable_crypto_above_the_floor_ordered_by_volume():
    assert liquid_pairs(LIQUID_SNAPSHOT, VOLUMES, 5_000_000) == ["BTC/USD", "ETH/USD", "EDGE/USD"]


def test_the_floor_is_inclusive_so_the_rule_does_not_turn_on_a_rounding_error():
    assert "EDGE/USD" in liquid_pairs(LIQUID_SNAPSHOT, VOLUMES, 5_000_000)
    assert "EDGE/USD" not in liquid_pairs(LIQUID_SNAPSHOT, VOLUMES, 5_000_001)


def test_a_pair_missing_from_the_ticker_is_dropped_rather_than_silently_kept():
    assert "QUIET/USD" not in liquid_pairs(LIQUID_SNAPSHOT, VOLUMES, 5_000_000)


def test_tokenised_equities_are_excluded_by_rule_however_liquid():
    assert "NVDAB/USD" not in liquid_pairs(LIQUID_SNAPSHOT, VOLUMES, 1.0)


def test_a_pair_the_exchange_will_not_trade_is_excluded():
    assert "OLD/USD" not in liquid_pairs(LIQUID_SNAPSHOT, {**VOLUMES, "OLD/USD": 900e6}, 5_000_000)
