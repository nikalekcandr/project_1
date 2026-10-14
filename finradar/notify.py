"""Delivery channels for digests (Telegram bot)."""

from __future__ import annotations

import os

import requests


class NotifyError(Exception):
    pass


def send_telegram(messages: list[str], token: str | None = None, chat_id: str | None = None) -> int:
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        raise NotifyError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not configured")
    sent = 0
    for text in messages:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=20,
        )
        if resp.status_code != 200 or not resp.json().get("ok"):
            raise NotifyError(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
        sent += 1
    return sent
