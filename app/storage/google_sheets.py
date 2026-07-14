"""
Реализация хранилища на Google Sheets.

gspread — синхронная библиотека, поэтому все блокирующие вызовы
оборачиваем в asyncio.to_thread, чтобы не блокировать event loop бота.

Два листа:
  • «Заявки» — каждая заявка отдельной строкой (журнал).
  • «Клиенты» — одна строка на клиента (CRM-профиль), бот ведёт её сам
    по chat_id (upsert: нашёл — обновил, нет — добавил).

ВАЖНО про лист «Клиенты»: столбцы K/L/M (Кол-во заявок, Сумма покупок,
Дней без контакта) должны быть ARRAYFORMULA в строке 2 — бот их НЕ трогает,
они сами распространяются на новые строки.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from app.core.models import Lead

log = logging.getLogger(__name__)

# Минимально необходимые права: таблицы + файлы Drive.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Имя листа с CRM-профилями клиентов.
CLIENTS_WORKSHEET = "Клиенты"


class GoogleSheetsStorage:
    """Сохраняет заявки в лист «Заявки» и ведёт CRM-лист «Клиенты»."""

    def __init__(
        self,
        credentials_file: str,
        sheet_id: str,
        worksheet_name: str,
        clients_worksheet_name: str = CLIENTS_WORKSHEET,
    ) -> None:
        self._credentials_file = credentials_file
        self._sheet_id = sheet_id
        self._worksheet_name = worksheet_name
        self._clients_name = clients_worksheet_name
        self._worksheet: gspread.Worksheet | None = None
        self._clients_ws: gspread.Worksheet | None = None
        # Сериализация записи: Telegram и VK сохраняют заявки параллельно,
        # а нумерация и upsert клиента не атомарны (возможны дубли номеров
        # и затирание строк на листе «Клиенты»).
        self._lock = asyncio.Lock()

    def _connect_sync(self) -> tuple[gspread.Worksheet, gspread.Worksheet]:
        """Синхронно подключиться и вернуть листы (Заявки, Клиенты)."""
        creds = Credentials.from_service_account_file(
            self._credentials_file, scopes=SCOPES
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(self._sheet_id)

        # Лист «Заявки».
        try:
            worksheet = spreadsheet.worksheet(self._worksheet_name)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=self._worksheet_name, rows=1000, cols=15
            )
        if not worksheet.get_all_values():
            worksheet.append_row(Lead.row_header(), value_input_option="USER_ENTERED")

        # Лист «Клиенты».
        try:
            clients = spreadsheet.worksheet(self._clients_name)
        except gspread.WorksheetNotFound:
            clients = spreadsheet.add_worksheet(
                title=self._clients_name, rows=1000, cols=18
            )
        if not clients.get_all_values():
            clients.append_row(Lead.clients_header(), value_input_option="USER_ENTERED")

        return worksheet, clients

    def _save_sync(self, lead: Lead) -> int:
        """Посчитать номер заявки, проставить его и добавить строку в «Заявки»."""
        assert self._worksheet is not None
        # Номер заявки = число уже заполненных строк данных (без заголовка) + 1.
        existing = self._worksheet.get_all_values()
        number = max(len(existing) - 1, 0) + 1
        lead.lead_number = number
        self._worksheet.append_row(
            lead.as_row(),
            value_input_option="USER_ENTERED",
        )
        return number

    def _upsert_client_sync(self, lead: Lead) -> None:
        """Добавить или обновить клиента на листе «Клиенты» по chat_id.

        Макет листа (18 колонок):
          A chat_id | B Имя | C Телефон (raw) | D Телефон ✓ (формула) |
          E Источник | F Марка | G Модель | H Год | I VIN |
          J Дата 1-го контакта | K Дата посл. контакта |
          L Кол-во (ф) | M Сумма (ф) | N Дней без контакта (ф) |
          O Согласие | P Теги | Q Заметки | R цифры (ф)

        Бот пишет ТОЛЬКО статичные колонки: A–C и E–K.
        Колонку O (Согласие) бот БОЛЬШЕ НЕ трогает — её заполнит будущий опрос/менеджер.
        Формульные D, L, M, N, R и ручные O, P, Q не трогаем.
        Диапазон A:C и E:K пишем отдельно, чтобы перепрыгнуть формулу в D.
        """
        assert self._clients_ws is not None
        chat_id = str(lead.external_user_id or "").strip()
        if not chat_id:
            # Без chat_id клиента в CRM не ведём (не по чему связывать).
            return

        ws = self._clients_ws
        values = ws.get_all_values()  # включая строку заголовка
        today = datetime.now().strftime("%Y-%m-%d")

        # Ищем клиента по колонке A (chat_id). Сравниваем как текст.
        target_row: int | None = None
        existing_row: list[str] = []
        for i, row in enumerate(values[1:], start=2):
            if row and row[0].strip() == chat_id:
                target_row = i
                existing_row = row
                break

        def _cell(idx: int) -> str:
            # idx — 0-базовый номер колонки (A=0, C=2, E=4, …)
            return existing_row[idx] if len(existing_row) > idx else ""

        if target_row is not None:
            # Обновляем: дату 1-го контакта (J=9) сохраняем,
            # авто (F–I = 5..8) не затираем пустым.
            first_contact = _cell(9) or today
            brand = lead.brand or _cell(5)
            model = lead.model or _cell(6)
            year = lead.year or _cell(7)
            vin = lead.vin or _cell(8)
            ws.update(
                range_name=f"A{target_row}:C{target_row}",
                values=[[f"'{chat_id}", lead.name, f"'{lead.phone}"]],
                value_input_option="USER_ENTERED",
            )
            ws.update(
                range_name=f"E{target_row}:K{target_row}",
                values=[[lead.source, brand, model, year, vin, first_contact, today]],
                value_input_option="USER_ENTERED",
            )
        else:
            # Новый клиент: пишем в следующую строку напрямую
            # (не append_row, чтобы не конфликтовать с формулами).
            new_row = len(values) + 1
            ws.update(
                range_name=f"A{new_row}:C{new_row}",
                values=[[f"'{chat_id}", lead.name, f"'{lead.phone}"]],
                value_input_option="USER_ENTERED",
            )
            ws.update(
                range_name=f"E{new_row}:K{new_row}",
                values=[[lead.source, lead.brand, lead.model, lead.year, lead.vin, today, today]],
                value_input_option="USER_ENTERED",
            )

    async def init(self) -> None:
        """Подключиться один раз при старте и закэшировать листы."""
        self._worksheet, self._clients_ws = await asyncio.to_thread(self._connect_sync)
        log.info(
            "Google Sheets подключён: листы '%s' и '%s'",
            self._worksheet_name, self._clients_name,
        )

    async def save(self, lead: Lead) -> int:
        """Добавить заявку в «Заявки» и обновить профиль в «Клиенты»."""
        if self._worksheet is None:
            await self.init()
        # Под блокировкой: чтение номера + append и upsert клиента должны идти
        # последовательно, иначе параллельные заявки (Telegram/VK) дадут
        # одинаковый номер или затрут строку клиента.
        async with self._lock:
            number = await asyncio.to_thread(self._save_sync, lead)
            log.info(
                "Заявка #%s сохранена в Google Sheets: %s / %s",
                number, lead.name, lead.phone,
            )
            # Обновление CRM-листа — вторичное: если упало, заявка уже сохранена.
            try:
                await asyncio.to_thread(self._upsert_client_sync, lead)
            except Exception:
                log.exception("Не удалось обновить лист '%s'", self._clients_name)
        return number
