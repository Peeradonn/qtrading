"""Telegram alerts, optional. Configured from TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID; silent when absent.
An alert must never raise into the trading loop."""
import logging
import os

import requests

log = logging.getLogger(__name__)


def _post(url: str, data: dict) -> None:
    requests.post(url, data=data, timeout=10)


def make_alerter(enabled: bool, post=_post):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not enabled or not token or not chat:
        return lambda message: None
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    def alert(message: str) -> None:
        try:
            post(url, {"chat_id": chat, "text": message[:4000]})
        except Exception as e:                       # alerting is best-effort
            log.warning("alert failed: %s", e)

    return alert
