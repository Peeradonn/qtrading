"""Alerts: a no-op when Telegram is not configured; a correctly shaped Bot API call when it is."""
from qtrading.engine.alerts import make_alerter


def test_without_credentials_the_alerter_is_a_silent_noop(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    alert = make_alerter(enabled=True, post=lambda url, data: (_ for _ in ()).throw(AssertionError("must not post")))
    alert("hello")                                    # no exception, nothing posted


def test_with_credentials_it_posts_to_the_bot_api(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent = []
    alert = make_alerter(enabled=True, post=lambda url, data: sent.append((url, data)))
    alert("equity moved")
    assert sent == [("https://api.telegram.org/bot123:abc/sendMessage", {"chat_id": "42", "text": "equity moved"})]


def test_disabled_never_posts_even_with_credentials(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent = []
    make_alerter(enabled=False, post=lambda url, data: sent.append(1))("x")
    assert sent == []


def test_a_failing_post_never_raises_into_the_trading_loop(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    def boom(url, data):
        raise ConnectionError("telegram down")
    make_alerter(enabled=True, post=boom)("x")        # swallowed
