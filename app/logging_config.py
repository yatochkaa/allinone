"""Единая настройка логирования для всего приложения."""
from __future__ import annotations

import logging


def setup_logging(level: str = "INFO") -> None:
    """Настроить корневой логгер с читаемым форматом."""
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # aiogram очень болтлив на DEBUG — приглушим его до WARNING.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
