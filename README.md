# Lead Bot — приём заявок из мессенджеров (MVP, Этап 1: Telegram)

Telegram-бот ведёт короткий диалог (имя → телефон → запрос), сохраняет заявку
в Google Sheets и уведомляет менеджера в Telegram.

Архитектура разделена на слои, чтобы потом добавить VK/MAX/WhatsApp и сменить БД
без переписывания бизнес-логики.

## Структура

```
lead-bot/
├── run.py                      # точка входа (composition root)
├── requirements.txt
├── .env.example
├── .gitignore
└── app/
    ├── config.py               # загрузка .env
    ├── logging_config.py
    ├── core/
    │   ├── models.py           # модель Lead (ядро, без мессенджеров)
    │   └── service.py          # LeadService: сохранить + уведомить
    ├── adapters/
    │   ├── base.py             # MessengerAdapter (Protocol)
    │   └── telegram_adapter.py # TelegramAdapter (aiogram 3.x, FSM-диалог)
    ├── storage/
    │   ├── base.py             # Storage (Protocol)
    │   ├── google_sheets.py    # GoogleSheetsStorage
    │   └── sqlite_storage.py   # SqliteStorage (бонус, замена в 1 строку)
    └── notify/
        ├── base.py             # Notifier (Protocol)
        └── telegram_notifier.py
```

## Быстрый старт

```bash
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # заполнить значения
python run.py
```

Подробная инструкция (BotFather, Google сервисный аккаунт, деплой) — в Notion.
