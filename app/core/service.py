"""
Бизнес-логика приёма заявок.

LeadService — единая точка, через которую проходят все заявки
независимо от того, из какого мессенджера они пришли.
Сервис не знает ничего о Telegram, Google Sheets или SQLite —
только об интерфейсах Storage и Notifier.
"""
from __future__ import annotations

import logging

from app.core.models import Lead
from app.notify.base import Notifier
from app.storage.base import Storage

log = logging.getLogger(__name__)


class LeadService:
    """Оркестратор: сохранить заявку и уведомить менеджера."""

    def __init__(self, storage: Storage, notifier: Notifier) -> None:
        self._storage = storage
        self._notifier = notifier

    async def register_lead(self, lead: Lead) -> int:
        """Главный сценарий: сохраняем заявку, потом шлём уведомление.

        Порядок важен: сначала надёжно сохраняем (это главная ценность)
        и получаем номер заявки, затем уведомляем.
        Ошибка уведомления не теряет заявку.

        Возвращает номер заявки (#1, #2, …), чтобы адаптер мог показать
        его клиенту.
        """
        number = await self._storage.save(lead)
        lead.lead_number = number
        await self._notifier.notify_new_lead(lead)
        log.info("Заявка #%s полностью обработана: %s", number, lead.name)
        return number
