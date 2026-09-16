"""The pre-commit secret scanner: catch credentials before they reach a public repo."""
from qtrading.secrets import scan_text


def findings(text, path="x.py"):
    return [f.reason for f in scan_text(path, text)]


def test_flags_a_discord_webhook_url():
    assert findings("ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/1234567890123456789/aB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dExyz") \  # pragma: allowlist secret (fixtures for this scanner)
        == ["Discord webhook URL"]


def test_flags_a_telegram_bot_token():
    assert findings("token = '8123456789:AAH1bC2dE3fG4hI5jK6lM7nO8pQ9rS0tU1v'") == ["Telegram bot token"]  # pragma: allowlist secret (fixtures for this scanner)


def test_flags_a_healthchecks_ping_url():
    assert findings("HEARTBEAT_URL=https://hc-ping.com/8f1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9") \  # pragma: allowlist secret (fixtures for this scanner)
        == ["healthchecks.io ping URL"]


def test_flags_a_long_value_assigned_to_a_key_or_secret_name():
    assert findings("ROOSTOO_SECRET_KEY=S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep") \  # pragma: allowlist secret (fixtures for this scanner)
        == ["assignment to a secret-looking name"]
    assert findings("api_key = 'aZ9xQ2wE8rT4yU6iO0pA1sD3fG5hJ7kL'") == ["assignment to a secret-looking name"]  # pragma: allowlist secret (fixtures for this scanner)


def test_allows_placeholders_and_empty_values():
    assert findings("ROOSTOO_API_KEY=your-api-key") == []
    assert findings("ALERT_WEBHOOK_URL=") == []
    assert findings("TELEGRAM_BOT_TOKEN=") == []
    assert findings("api_key = os.environ['ROOSTOO_API_KEY']") == []


def test_allows_a_line_marked_with_the_allowlist_pragma():
    assert findings("SECRET = 'S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep'  "  # pragma: allowlist secret (fixtures for this scanner)
                    "# pragma: allowlist secret") == []


def test_allows_obvious_test_fixtures():
    assert findings("url = 'https://discord.com/api/webhooks/1/abc'") == []


def test_reports_the_file_and_line_of_each_finding():
    text = "safe = 1\nALERT_WEBHOOK_URL=https://discord.com/api/webhooks/1234567890123456789/aB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dEaB3dExyz\n"  # pragma: allowlist secret (fixtures for this scanner)
    (finding,) = scan_text("configs/x.env", text)
    assert (finding.path, finding.line) == ("configs/x.env", 2)
