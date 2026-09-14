"""Typed views over Roostoo API payloads. Field names follow the docs' casing on the wire."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PairInfo:
    pair: str
    coin: str
    unit: str
    can_trade: bool
    price_precision: int
    amount_precision: int
    min_order: float
    asset_type: str          # "crypto" observed; used to separate coins / tokenized stocks / gold

    @classmethod
    def from_payload(cls, pair: str, d: dict) -> "PairInfo":
        return cls(pair, d["Coin"], d["Unit"], bool(d["CanTrade"]), int(d["PricePrecision"]),
                   int(d["AmountPrecision"]), float(d["MiniOrder"]), d.get("AssetType", ""))


@dataclass(frozen=True)
class Ticker:
    pair: str
    bid: float
    ask: float
    last: float
    change_24h: float        # fraction, e.g. -0.0112 == -1.12%
    coin_volume_24h: float
    unit_volume_24h: float   # 24h traded value in USD

    @classmethod
    def from_payload(cls, pair: str, d: dict) -> "Ticker":
        return cls(pair, float(d["MaxBid"]), float(d["MinAsk"]), float(d["LastPrice"]), float(d["Change"]),
                   float(d["CoinTradeValue"]), float(d["UnitTradeValue"]))


@dataclass(frozen=True)
class Balance:
    free: float
    lock: float


@dataclass(frozen=True)
class Order:
    pair: str
    order_id: int
    status: str              # FILLED | PENDING | CANCELED
    role: str                # TAKER | MAKER
    side: str                # BUY | SELL
    order_type: str          # MARKET | LIMIT
    price: float
    quantity: float
    filled_quantity: float
    filled_avg_price: float
    commission_coin: str
    commission: float
    create_ts: int
    finish_ts: int

    @classmethod
    def from_payload(cls, d: dict) -> "Order":
        return cls(d["Pair"], int(d["OrderID"]), d["Status"], d["Role"], d["Side"], d["Type"], float(d["Price"]),
                   float(d["Quantity"]), float(d["FilledQuantity"]), float(d["FilledAverPrice"]),
                   d["CommissionCoin"], float(d["CommissionChargeValue"]), int(d["CreateTimestamp"]),
                   int(d["FinishTimestamp"]))
