"""Exchange layer: PaperExchange (fills at the live ticker, wallet on disk) and RoostooExchange (client adapter)."""
import pytest

from qtrading.engine.exchange import InsufficientFunds, PaperExchange, RoostooExchange
from qtrading.roostoo.models import Balance, Order, PairInfo, Ticker


def rules():
    return {"BTC/USD": PairInfo("BTC/USD", "BTC", "USD", True, 2, 5, 1.0, "crypto"),
            "ETH/USD": PairInfo("ETH/USD", "ETH", "USD", True, 2, 4, 1.0, "crypto")}


def feed(prices):
    return lambda: dict(prices)


def test_paper_buy_debits_usd_by_notional_plus_fee_and_credits_the_coin(tmp_path):
    ex = PaperExchange(feed({"BTC/USD": 50_000.0}), rules(), tmp_path / "w.json", fee_rate=0.001, initial_usd=100_000.0)
    fill = ex.place_market("BTC/USD", "BUY", 0.5)
    assert (fill.quantity, fill.price, fill.notional, fill.fee, fill.status) == (0.5, 50_000.0, 25_000.0, 25.0, "FILLED")
    assert ex.balances() == {"USD": pytest.approx(100_000 - 25_000 - 25), "BTC": 0.5}


def test_paper_sell_credits_usd_net_of_fee(tmp_path):
    ex = PaperExchange(feed({"BTC/USD": 50_000.0}), rules(), tmp_path / "w.json", fee_rate=0.001, initial_usd=100_000.0)
    ex.place_market("BTC/USD", "BUY", 0.5)
    ex.place_market("BTC/USD", "SELL", 0.5)
    assert ex.balances()["BTC"] == 0.0
    assert ex.balances()["USD"] == pytest.approx(100_000 - 25 - 25)


def test_paper_wallet_persists_across_instances(tmp_path):
    ex = PaperExchange(feed({"BTC/USD": 50_000.0}), rules(), tmp_path / "w.json", fee_rate=0.001, initial_usd=100_000.0)
    first = ex.place_market("BTC/USD", "BUY", 0.5)
    again = PaperExchange(feed({"BTC/USD": 60_000.0}), rules(), tmp_path / "w.json", fee_rate=0.001, initial_usd=100_000.0)
    assert again.balances()["BTC"] == 0.5
    assert again.place_market("BTC/USD", "SELL", 0.1).order_id > first.order_id


def test_paper_rejects_orders_it_cannot_fund(tmp_path):
    ex = PaperExchange(feed({"BTC/USD": 50_000.0}), rules(), tmp_path / "w.json", fee_rate=0.001, initial_usd=1_000.0)
    with pytest.raises(InsufficientFunds):
        ex.place_market("BTC/USD", "BUY", 0.5)
    with pytest.raises(InsufficientFunds):
        ex.place_market("BTC/USD", "SELL", 0.5)


class FakeClient:
    def __init__(self):
        self.orders = []

    def exchange_info(self):
        return rules()

    def balance(self):
        return {"USD": Balance(free=500.0, lock=0.0), "BTC": Balance(free=0.01, lock=0.0)}

    def ticker(self, pair=None):
        return {"BTC/USD": Ticker("BTC/USD", 49_999.0, 50_001.0, 50_000.0, 0.01, 1.0, 1.0)}

    def place_order(self, pair, side, order_type, quantity, price=None):
        self.orders.append((pair, side, order_type, quantity, price))
        return Order(pair, 81, "FILLED", "TAKER", side, order_type, 50_000.0, float(quantity), float(quantity),
                     50_000.0, "USD", float(quantity) * 50_000.0 * 0.001, 1, 2)


def test_roostoo_formats_quantity_to_the_pair_precision_never_scientific():
    client = FakeClient()
    ex = RoostooExchange(client)
    fill = ex.place_market("BTC/USD", "BUY", 0.00001)
    assert client.orders == [("BTC/USD", "BUY", "MARKET", "0.00001", None)]
    assert (fill.order_id, fill.status, fill.price) == (81, "FILLED", 50_000.0)
    assert fill.fee == pytest.approx(0.0005)


def test_roostoo_balances_and_prices_are_flattened():
    ex = RoostooExchange(FakeClient())
    assert ex.balances() == {"USD": 500.0, "BTC": 0.01}
    assert ex.prices() == {"BTC/USD": 50_000.0}
