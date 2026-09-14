"""Signing must reproduce the vector published in the Roostoo API docs byte-for-byte."""
from qtrading.roostoo.signing import canonical_query, sign

# Test credentials and expected output published in roostoo/Roostoo-API-Documents.
DOCS_SECRET = "S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep"
DOCS_QUERY = "pair=BNB/USD&quantity=2000&side=BUY&timestamp=1580774512000&type=MARKET"
DOCS_SIGNATURE = "20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff"


def test_canonical_query_sorts_keys_and_leaves_values_unencoded():
    params = {"type": "MARKET", "pair": "BNB/USD", "quantity": 2000, "side": "BUY", "timestamp": 1580774512000}
    assert canonical_query(params) == DOCS_QUERY


def test_canonical_query_omits_none_values():
    # MARKET orders carry price=None; it must not appear as "price=None".
    assert canonical_query({"pair": "BTC/USD", "price": None, "timestamp": 1}) == "pair=BTC/USD&timestamp=1"


def test_sign_reproduces_the_published_docs_vector():
    assert sign(DOCS_SECRET, DOCS_QUERY) == DOCS_SIGNATURE
