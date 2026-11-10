"""Telegram notifications (optional)."""

from __future__ import annotations

import requests

from studio import config
from studio.logs import get_logger

log = get_logger(__name__)


def send(msg: str) -> None:
    """Log the message and, when configured, push it to Telegram."""
    log.info(msg.replace("\n", " | ")[:300])
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg[:3500]},
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram error: %s", exc)


__all__ = ["send"]
