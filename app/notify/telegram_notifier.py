"""Реализация уведомлений через Telegram."""
from __future__ import annotations

import logging

from aiogram import Bot

from app.core.models import Lead

log = logging.getLogger(__name__)


class TelegramNotifier:
    """Отправляет уведомление о новой заявке менеджеру в Telegram.

    Переиспользуем тот же экземпляр Bot, что и адаптер, —
    это экономит ресурсы и избавляет от второго подключения.
    """

    def __init__(self, bot: Bot, manager_chat_id: int) -> None:
        self._bot = bot
        self._manager_chat_id = manager_chat_id

    async def notify_new_lead(self, lead: Lead) -> None:
        try:
            await self._bot.send_message(
                chat_id=self._manager_chat_id,
                text=lead.as_message(),
            )
            log.info("Уведомление менеджеру отправлено (chat_id=%s)", self._manager_chat_id)
        except Exception:
            # Уведомление — вторичное действие. Если оно упало — логируем,
            # но НЕ роняем обработку заявки (заявка уже сохранена).
            log.exception("Не удалось отправить уведомление менеджеру")
