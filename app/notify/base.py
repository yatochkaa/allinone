"""
Интерфейс уведомлений.

Любой канал уведомлений (Telegram, email, SMS) реализует этот протокол.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.models import Lead


@runtime_checkable
class Notifier(Protocol):
    """Контракт уведомлятеля о новых заявках."""

    async def notify_new_lead(self, lead: Lead) -> None:
        """Отправить менеджеру уведомление о новой заявке."""
        ...
