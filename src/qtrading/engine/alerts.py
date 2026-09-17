"""Operator notifications. Two channels, both optional, both best-effort — nothing here may raise into the loop.

Alerts:    ALERT_WEBHOOK_URL (Discord-style webhook: POST {"content": text}) wins; otherwise Telegram via
           TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID; otherwise silent.
Heartbeat: HEARTBEAT_URL (healthchecks.io-style): GET it after every cycle, GET <url>/fail after a failed one.
           The service alerts you when pings stop — the one failure a dead bot cannot report itself.
           Give each bot its own check in HEARTBEAT_URL_<NAME> (paper-core -> HEARTBEAT_URL_PAPER_CORE): with one
           check shared by several bots, the live ones keep pinging it and a dead one goes unnoticed.
"""
import logging
import os
import re

import requests

log = logging.getLogger(__name__)
DISCORD_LIMIT = 2000


def _post_json(url: str, payload: dict) -> None:
    requests.post(url, json=payload, timeout=10)


def _post_form(url: str, data: dict) -> None:
    requests.post(url, data=data, timeout=10)


def _get(url: str) -> None:
    requests.get(url, timeout=10)


def make_alerter(enabled: bool, post_json=_post_json, post_form=_post_form):
    def silent(message: str) -> None:
        return None

    if not enabled:
        return silent
    webhook = os.environ.get("ALERT_WEBHOOK_URL")
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")

    if webhook:
        def alert(message: str) -> None:
            try:
                post_json(webhook, {"content": message[:DISCORD_LIMIT - 100]})
            except Exception as e:
                log.warning("alert failed: %s", e)
        return alert

    if token and chat:
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        def alert(message: str) -> None:
            try:
                post_form(url, {"chat_id": chat, "text": message[:4000]})
            except Exception as e:
                log.warning("alert failed: %s", e)
        return alert

    return silent


def heartbeat_env_name(bot_name: str) -> str:
    return "HEARTBEAT_URL_" + re.sub(r"[^A-Z0-9]+", "_", bot_name.upper()).strip("_")


def make_heartbeat(get=_get, bot_name: str | None = None):
    url = (os.environ.get(heartbeat_env_name(bot_name)) if bot_name else None) or os.environ.get("HEARTBEAT_URL")
    if not url:
        return lambda ok=True: None

    def beat(ok: bool = True) -> None:
        try:
            get(url if ok else url.rstrip("/") + "/fail")
        except Exception as e:
            log.warning("heartbeat failed: %s", e)
    return beat
