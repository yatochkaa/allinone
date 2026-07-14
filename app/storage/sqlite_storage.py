"""
Бонус: хранилище на SQLite (файловая БД, нулевая настройка).

Данный класс НИЧЕГО не требует кроме стандартной библиотеки Python.
Чтобы переключиться на него — поставьте STORAGE_BACKEND=sqlite в .env.
Это наглядно показывает, что благодаря интерфейсу Storage базу данных
можно менять без правок в core/ и адаптерах.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3

from app.core.models import Lead

log = logging.getLogger(__name__)


class SqliteStorage:
    """Сохраняет заявки в локальный файл SQLite."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _init_sync(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at   TEXT NOT NULL,
                    chat_id      TEXT,
                    source       TEXT NOT NULL,
                    request_type TEXT NOT NULL,
                    name         TEXT NOT NULL,
                    phone        TEXT NOT NULL,
                    brand        TEXT,
                    model        TEXT,
                    year         TEXT,
                    vin          TEXT,
                    request_text TEXT NOT NULL,
                    marketing_consent TEXT,
                    status       TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _save_sync(self, lead: Lead) -> int:
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "INSERT INTO leads "
                "(created_at, chat_id, source, request_type, name, phone, "
                "brand, model, year, vin, request_text, marketing_consent, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lead.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    lead.external_user_id,
                    lead.source,
                    lead.request_type_label,
                    lead.name,
                    lead.phone,
                    lead.brand,
                    lead.model,
                    lead.year,
                    lead.vin,
                    lead.request_text,
                    lead.consent_label,
                    lead.status,
                ),
            )
            conn.commit()
            # lastrowid = автоинкрементный id = номер заявки.
            return int(cur.lastrowid)

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)
        log.info("SQLite готов: %s", self._db_path)

    async def save(self, lead: Lead) -> int:
        number = await asyncio.to_thread(self._save_sync, lead)
        log.info("Заявка #%s сохранена в SQLite: %s / %s", number, lead.name, lead.phone)
        return number
