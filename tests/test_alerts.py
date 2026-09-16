"""Alerts: Discord webhook first, Telegram as fallback, silent when unconfigured; heartbeat pings for a dead-man's
switch. Nothing here may ever raise into the trading loop."""
from qtrading.engine.alerts import make_alerter, make_heartbeat


def clear_env(monkeypatch):
    for k in ("ALERT_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "HEARTBEAT_URL"):
        monkeypatch.delenv(k, raising=False)


def explode(*a, **kw):
    raise AssertionError("must not be called")


# --- webhook (Discord) ---------------------------------------------------------

def test_discord_webhook_posts_json_content(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    sent = []
    alert = make_alerter(enabled=True, post_json=lambda url, payload: sent.append((url, payload)), post_form=explode)
    alert("bot started")
    assert sent == [("https://discord.com/api/webhooks/1/abc", {"content": "bot started"})]


def test_webhook_wins_over_telegram_when_both_are_configured(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent = []
    make_alerter(enabled=True, post_json=lambda url, payload: sent.append(url), post_form=explode)("x")
    assert sent == ["https://discord.com/api/webhooks/1/abc"]


def test_long_messages_are_truncated_under_the_discord_limit(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    sent = []
    make_alerter(enabled=True, post_json=lambda url, payload: sent.append(payload["content"]), post_form=explode)("x" * 5000)
    assert len(sent[0]) <= 2000


# --- telegram fallback ----------------------------------------------------------

def test_telegram_posts_a_form_to_the_bot_api(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent = []
    make_alerter(enabled=True, post_json=explode, post_form=lambda url, data: sent.append((url, data)))("equity moved")
    assert sent == [("https://api.telegram.org/bot123:abc/sendMessage", {"chat_id": "42", "text": "equity moved"})]


# --- off switches ---------------------------------------------------------------

def test_without_any_credentials_the_alerter_is_a_silent_noop(monkeypatch):
    clear_env(monkeypatch)
    make_alerter(enabled=True, post_json=explode, post_form=explode)("hello")


def test_disabled_never_posts_even_with_credentials(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    make_alerter(enabled=False, post_json=explode, post_form=explode)("x")


def test_a_failing_post_never_raises_into_the_trading_loop(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")

    def boom(url, payload):
        raise ConnectionError("discord down")
    make_alerter(enabled=True, post_json=boom, post_form=explode)("x")


# --- heartbeat (dead-man's switch) ----------------------------------------------

def test_heartbeat_pings_the_url_on_success_and_the_fail_endpoint_on_failure(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("HEARTBEAT_URL", "https://hc-ping.com/uuid")
    pings = []
    beat = make_heartbeat(get=lambda url: pings.append(url))
    beat(True)
    beat(False)
    assert pings == ["https://hc-ping.com/uuid", "https://hc-ping.com/uuid/fail"]


def test_heartbeat_without_a_url_is_a_noop_and_failures_are_swallowed(monkeypatch):
    clear_env(monkeypatch)
    make_heartbeat(get=explode)(True)
    monkeypatch.setenv("HEARTBEAT_URL", "https://hc-ping.com/uuid")

    def boom(url):
        raise ConnectionError("down")
    make_heartbeat(get=boom)(True)
