"""
Единая модель заявки (Lead).

Это "ядро" системы: модель НЕ зависит ни от Telegram, ни от Google Sheets.
Любой адаптер мессенджера приводит входящее сообщение к этому виду,
а любое хранилище умеет его сохранять. Так мы сможем добавлять VK / MAX /
WhatsApp и менять БД, не трогая бизнес-логику.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from html import escape


# Статусы заявки. На MVP используется только NEW, но фиксируем перечень,
# чтобы потом не плодить "магические строки".
STATUS_NEW = "новая"

# Человекочитаемые названия типов запроса.
# Ключи (parts/repair/question) хранятся в callback-кнопках и не зависят от языка.
REQUEST_TYPE_LABELS = {
    "parts": "Запчасти",
    "repair": "Ремонт",
    "question": "Другое",
}


@dataclass
class Lead:
    """Одна заявка от клиента.

    Поля специально простые (строки/даты), чтобы их легко было сложить
    в строку Google Sheets или в любую БД.
    """

    name: str                       # Имя клиента
    phone: str                      # Телефон клиента (уже нормализованный)
    request_text: str               # Суть запроса
    request_type: str = "question"  # Тип запроса: parts | repair | question

    # Авто. Для ремонта заполняем марку/модель/год отдельными вопросами,
    # для запчастей — либо VIN, либо марку+год (что клиент укажет).
    brand: str = ""                 # Марка (Lada, Toyota, …)
    model: str = ""                 # Модель (Priora, Camry, …)
    year: str = ""                  # Год выпуска
    vin: str = ""                   # VIN (17 символов)

    source: str = "telegram"        # Источник заявки
    status: str = STATUS_NEW        # Статус (на MVP всегда "новая")
    created_at: datetime = field(default_factory=datetime.now)

    # Номер заявки (#1, #2, …). Присваивается хранилищем при сохранении.
    lead_number: int | None = None

    # Согласие на рассылку акций/бонусов (Этап 2а).
    marketing_consent: bool = False

    # Технические поля — пригодятся позже (дедупликация, ответы клиенту).
    external_user_id: str | None = None   # ID пользователя в мессенджере (chat_id)
    external_username: str | None = None  # @username, если есть

    @property
    def request_type_label(self) -> str:
        """Человекочитаемое название типа запроса."""
        return REQUEST_TYPE_LABELS.get(self.request_type, self.request_type)

    @property
    def consent_label(self) -> str:
        """«да»/«нет» для колонки согласия (строчными — под формулы FILTER в таблице)."""
        return "да" if self.marketing_consent else "нет"

    @property
    def vehicle_display(self) -> str:
        """Авто одной строкой — для превью клиенту и уведомления менеджеру."""
        parts = [p for p in (self.brand, self.model, self.year) if p]
        label = " ".join(parts)
        if self.vin:
            label = (label + " · " if label else "") + f"VIN {self.vin}"
        return label

    def as_row(self) -> list[str]:
        """Строка для листа «Заявки» (порядок строго совпадает с row_header()).

        client_id и Телефон пишем с ведущим апострофом, чтобы Google Sheets
        не превращал их в число и не съедал «+» у телефона.
        """
        chat_id = str(self.external_user_id or "")
        return [
            self.created_at.strftime("%Y-%m-%d %H:%M:%S"),  # Дата/время
            f"'{chat_id}" if chat_id else "",               # client_id (chat_id)
            self.source,                                     # Источник
            self.request_type_label,                         # Тип обращения
            self.name,                                       # Имя
            f"'{self.phone}" if self.phone else "",          # Телефон (как текст)
            self.brand,                                      # Марка
            self.model,                                      # Модель
            self.year,                                       # Год
            self.vin,                                        # VIN
            "",                                              # Категория детали (менеджер)
            self.request_text,                               # Текст запроса
            self.status,                                     # Статус
            "",                                              # Сумма сделки (менеджер)
            "",                                              # Дата закрытия (менеджер)
        ]

    @staticmethod
    def row_header() -> list[str]:
        """Заголовок листа «Заявки» — должен совпадать по порядку с as_row()."""
        return [
            "Дата/время",
            "chat_id",
            "Источник",
            "Тип обращения",
            "Имя",
            "Телефон",
            "Марка",
            "Модель",
            "Год",
            "VIN",
            "Категория детали",
            "Текст запроса",
            "Статус",
            "Сумма сделки",
            "Дата закрытия",
        ]

    @staticmethod
    def clients_header() -> list[str]:
        """Заголовок листа «Клиенты» (бот ведёт его сам).

        Порядок 1-в-1 с вашим листом (18 колонок A…R). Колонки D, L, M, N, R —
        формульные, бот их НЕ пишет, они считаются в самой таблице.
        """
        return [
            "chat_id",                    # A
            "Имя",                        # B
            "Телефон (как ввёл клиент)",  # C — бот пишет сюда
            "Телефон ✓ (единый)",         # D — ФОРМУЛА (бот не трогает)
            "Источник",                   # E
            "Марка",                      # F
            "Модель",                     # G
            "Год",                        # H
            "VIN",                        # I
            "Дата 1-го контакта",         # J
            "Дата посл. контакта",        # K
            "Кол-во заявок",              # L — ФОРМУЛА
            "Сумма покупок",              # M — ФОРМУЛА
            "Дней без контакта",          # N — ФОРМУЛА
            "Согласие на рассылку",       # O — бот пишет сюда
            "Теги",                       # P
            "Заметки",                    # Q
            "цифры (служебная)",          # R — ФОРМУЛА
        ]

    def as_message(self) -> str:
        """Человекочитаемый текст уведомления менеджеру."""
        number = f"#{self.lead_number}" if self.lead_number else ""
        # Экранируем ТОЛЬКО значения (свои теги <b> не трогаем): при глобальном
        # parse_mode=HTML символы <, >, & в пользовательском вводе ломают парсер.
        name = escape(self.name)
        phone = escape(self.phone)
        vehicle = escape(self.vehicle_display)
        request_text = escape(self.request_text)
        source = escape(self.source)
        lines = [
            f"🔔 <b>Новая заявка {number}</b>".strip(),
            "",
            f"👤 <b>Имя:</b> {name}",
            f"📞 <b>Телефон:</b> {phone}",
            f"🏷 <b>Тип:</b> {self.request_type_label}",
        ]
        if self.vehicle_display:
            lines.append(f"🚗 <b>Авто:</b> {vehicle}")
        lines.append(f"📝 <b>Запрос:</b> {request_text}")
        lines.append(f"🌐 <b>Источник:</b> {source}")
        lines.append(f"🕒 <b>Время:</b> {self.created_at.strftime('%d.%m.%Y %H:%M')}")
        return "\n".join(lines)

    def as_confirmation(self) -> str:
        # Экранируем значения: экран подтверждения тоже уходит при parse_mode=HTML,
        # и символ < или & в имени/тексте иначе уронит отправку (клиент застрянет).
        name = escape(self.name)
        phone = escape(self.phone)
        vehicle = escape(self.vehicle_display)
        request_text = escape(self.request_text)
        lines = [
            "Проверьте, всё ли верно 👇",
            "",
            f"👤 Имя: {name}",
            f"📞 Телефон: {phone}",
            f"📁 Тип: {self.request_type_label}",
        ]
        if self.vehicle_display:
            lines.append(f"🚗 Авто: {vehicle}")
        lines.append(f"📝 Запрос: {request_text}")
        lines += [
            "",
            "Нажимая «✅ Согласен, отправить заявку», вы даёте согласие на "
            "обработку персональных данных: имени, телефона, данных авто и "
            "текста заявки.",
            "",
            "Данные используются только для обработки обращения и связи с вами "
            "по заявке.",
        ]
        return "\n".join(lines)
