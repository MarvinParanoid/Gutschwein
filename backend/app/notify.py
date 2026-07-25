"""Fire-and-forget notifications into the family chat.

The bot instance is injected at startup so routers stay independent of aiogram;
when no bot or no chat id is configured, notifications are silently dropped.
"""

import logging
from typing import Protocol

from app.config import settings

log = logging.getLogger(__name__)


class Notifier(Protocol):
    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> object: ...


_notifier: Notifier | None = None


def set_notifier(notifier: Notifier | None) -> None:
    global _notifier
    _notifier = notifier


async def notify(text: str) -> None:
    if _notifier is None or settings.family_chat_id is None:
        return
    try:
        await _notifier.send_message(
            settings.family_chat_id, text, parse_mode="HTML", disable_notification=True
        )
    except Exception:  # noqa: BLE001 - notifications must never break a request
        log.warning("failed to send family notification", exc_info=True)
