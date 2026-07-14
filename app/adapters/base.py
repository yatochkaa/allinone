"""
Общий интерфейс транспортного адаптера мессенджера.

Сейчас реализован только TelegramAdapter, но любой будущий адаптер
(VkAdapter, MaxAdapter, WhatsappGreenAdapter) должен реализовать этот протокол.
Так core/ никогда не придётся переписывать ради нового канала.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.core.models import Lead


@runtime_checkable
class MessengerAdapter(Protocol):
    """Контракт транспортного адаптера."""

    async def listen(self) -> None:
        """Запустить прослушивание входящих сообщений (блокирующий цикл)."""
        ...

    async def send(self, chat_id: Any, text: str) -> None:
        """Отправить текстовое сообщение пользователю."""
        ...

    def normalize(self, raw: Any) -> Lead:
        """Преобразовать сыроё сообщение мессенджера в единую модель Lead."""
        ...
