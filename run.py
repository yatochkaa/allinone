"""
Точка входа: собираем все слои вместе (composition root) и запускаем бота.

Именно здесь выбирается конкретная реализация хранилища. Чтобы сменить БД,
достаточно поменять одну ветку здесь — core/ и адаптеры не меняются.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from app.notify.max_notifier import MaxNotifier
from app.notify.vk_notifier import VkNotifier
from app.adapters.telegram_adapter import TelegramAdapter
from app.adapters.vk_adapter import VkAdapter
from app.config import Config
from app.core.service import LeadService
from app.logging_config import setup_logging
from app.notify.telegram_notifier import TelegramNotifier
from app.storage.base import Storage
from app.storage.google_sheets import GoogleSheetsStorage
from app.storage.sqlite_storage import SqliteStorage

log = logging.getLogger(__name__)


def build_storage(config: Config) -> Storage:
    """Выбрать реализацию хранилища по конфигу."""
    if config.storage_backend == "sqlite":
        return SqliteStorage(db_path=config.sqlite_path)
    return GoogleSheetsStorage(
        credentials_file=config.google_credentials_file,
        sheet_id=config.google_sheet_id,
        worksheet_name=config.google_worksheet_name,
    )


async def main() -> None:
    config = Config.load()
    setup_logging(config.log_level)
    log.info("Стартуем. Хранилище: %s", config.storage_backend)

    # Один Bot на весь процесс (и для адаптера, и для уведомлений).
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Собираем зависимости (dependency injection вручную).
    storage = build_storage(config)
    await storage.init()

    if config.manager_channel == "max":
        notifier = MaxNotifier(
            token=config.max_bot_token,
            manager_user_id=config.max_manager_user_id,
        )
    elif config.manager_channel == "vk":
        notifier = VkNotifier(
            token=config.vk_bot_token,
            manager_peer_id=config.vk_manager_peer_id,
        )
    else:
        notifier = TelegramNotifier(bot=bot, manager_chat_id=config.manager_chat_id)

    service = LeadService(storage=storage, notifier=notifier)

    # Источники клиентов (можно несколько одновременно).
    adapters = [TelegramAdapter(bot=bot, service=service)]

    # VK как источник включаем, если задан VK_BOT_TOKEN.
    if config.vk_bot_token:
        adapters.append(
            VkAdapter(
                token=config.vk_bot_token,
                service=service,
                # если менеджер в этом же VK-сообществе — не запускаем для него анкету
                manager_peer_id=(
                    config.vk_manager_peer_id if config.manager_channel == "vk" else None
                ),
            )
        )

    try:
        await asyncio.gather(*(adapter.listen() for adapter in adapters))
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот остановлен вручную.")
