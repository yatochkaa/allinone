"""
Конфигурация приложения.

Все секреты и настройки читаются из переменных окружения (.env).
Никакого хардкода токенов в коде — это и безопаснее, и удобнее при деплое.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Загружаем .env в переменные окружения один раз при импорте модуля.
load_dotenv()


def _require(name: str) -> str:
    """Вернуть обязательную переменную окружения или упасть с понятной ошибкой."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Не задана обязательная переменная окружения {name}. "
            f"Проверь свой .env файл (см. .env.example)."
        )
    return value


@dataclass(frozen=True)
class Config:
    """Неизменяемый объект конфигурации, собранный из окружения."""

    # Telegram
    bot_token: str
    manager_chat_id: int
    
    # Канал уведомления менеджера: "telegram" | "max" | "vk"
    manager_channel: str

    # MAX
    max_bot_token: str
    max_manager_user_id: int
    
    # VK
    vk_bot_token: str
    vk_manager_peer_id: int

    # Хранилище
    storage_backend: str  # "google_sheets" | "sqlite"

    # Google Sheets
    google_sheet_id: str
    google_worksheet_name: str
    google_credentials_file: str

    # SQLite
    sqlite_path: str

    # Логи
    log_level: str

    @staticmethod
    def load() -> "Config":
        """Собрать конфиг из переменных окружения."""
        backend = os.getenv("STORAGE_BACKEND", "google_sheets").strip().lower()

        # Google-настройки обязательны только если реально используем Sheets.
        google_sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
        google_credentials_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "service_account.json")
        if backend == "google_sheets":
            google_sheet_id = _require("GOOGLE_SHEET_ID")

        manager_channel = os.getenv("MANAGER_CHANNEL", "telegram").strip().lower()

        # MAX-настройки обязательны только если менеджер сидит в MAX.
        max_bot_token = os.getenv("MAX_BOT_TOKEN", "")
        max_manager_user_id = int(os.getenv("MAX_MANAGER_USER_ID") or 0)
        if manager_channel == "max":
            max_bot_token = _require("MAX_BOT_TOKEN")
            max_manager_user_id = int(_require("MAX_MANAGER_USER_ID"))
            
        # VK-настройки обязательны только если менеджер сидит в VK.
        vk_bot_token = os.getenv("VK_BOT_TOKEN", "")
        vk_manager_peer_id = int(os.getenv("VK_MANAGER_PEER_ID") or 0)
        if manager_channel == "vk":
            vk_bot_token = _require("VK_BOT_TOKEN")
            vk_manager_peer_id = int(_require("VK_MANAGER_PEER_ID"))

        # MANAGER_CHAT_ID нужен только когда менеджер получает уведомления в Telegram.
        # Для каналов max/vk требовать его не нужно — иначе бот падал бы на старте.
        if manager_channel == "telegram":
            manager_chat_id = int(_require("MANAGER_CHAT_ID"))
        else:
            manager_chat_id = int(os.getenv("MANAGER_CHAT_ID") or 0)

        return Config(
            bot_token=_require("BOT_TOKEN"),
            manager_chat_id=manager_chat_id,
            manager_channel=manager_channel,
            max_bot_token=max_bot_token,
            max_manager_user_id=max_manager_user_id,
            vk_bot_token=vk_bot_token,
            vk_manager_peer_id=vk_manager_peer_id,
            storage_backend=backend,
            google_sheet_id=google_sheet_id,
            google_worksheet_name=os.getenv("GOOGLE_WORKSHEET_NAME", "Заявки"),
            google_credentials_file=google_credentials_file,
            sqlite_path=os.getenv("SQLITE_PATH", "leads.db"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
