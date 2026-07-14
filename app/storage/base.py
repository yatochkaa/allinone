"""
Интерфейс хранилища.

Любое место, куда мы кладём заявки (Google Sheets, SQLite, Notion, Postgres),
реализует этот протокол. core работает только с этим интерфейсом
и не знает, куда конкретно сохраняются данные.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.models import Lead


@runtime_checkable
class Storage(Protocol):
    """Контракт хранилища заявок."""

    async def init(self) -> None:
        """Подготовить хранилище (создать таблицу/заголовок, если нужно)."""
        ...

    async def save(self, lead: Lead) -> int:
        """Сохранить одну заявку и вернуть её порядковый номер (#1, #2, …)."""
        ...
