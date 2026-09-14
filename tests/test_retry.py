"""HTTP retry policy for market-data fetches: transient failures retry with backoff; permanent ones don't."""
from types import SimpleNamespace

import pytest
import requests

from qtrading.data.binance import with_retries


class FakeGet:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, url, params):
        self.calls += 1
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


def http_error(status):
    return requests.HTTPError(response=SimpleNamespace(status_code=status))


def test_connection_errors_are_retried_until_success():
    get = FakeGet([requests.ConnectionError("down"), requests.Timeout("slow"), [["ok"]]])
    rows = with_retries(get, attempts=5, backoff_s=0.5, sleep=lambda s: None)("u", {})
    assert rows == [["ok"]]
    assert get.calls == 3


def test_server_errors_and_rate_limits_are_retried():
    get = FakeGet([http_error(503), http_error(429), [["ok"]]])
    assert with_retries(get, attempts=5, backoff_s=0.5, sleep=lambda s: None)("u", {}) == [["ok"]]
    assert get.calls == 3


def test_gives_up_after_max_attempts():
    get = FakeGet([requests.ConnectionError("down")] * 3)
    with pytest.raises(requests.ConnectionError):
        with_retries(get, attempts=3, backoff_s=0.5, sleep=lambda s: None)("u", {})
    assert get.calls == 3


def test_client_errors_are_not_retried():
    get = FakeGet([http_error(400), [["never"]]])
    with pytest.raises(requests.HTTPError):
        with_retries(get, attempts=5, backoff_s=0.5, sleep=lambda s: None)("u", {})
    assert get.calls == 1


def test_backoff_doubles_between_attempts():
    waits = []
    get = FakeGet([requests.ConnectionError("a"), requests.ConnectionError("b"), requests.ConnectionError("c"), [["ok"]]])
    with_retries(get, attempts=5, backoff_s=0.5, sleep=waits.append)("u", {})
    assert waits == [0.5, 1.0, 2.0]
