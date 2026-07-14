"""
Валидаторы и нормализаторы пользовательского ввода.

Живут в core/, потому что это бизнес-правила (что считаем валидным телефоном),
а не транспортная логика. Адаптер любого мессенджера может их переиспользовать.
"""
from __future__ import annotations

import re

# VIN: ровно 17 символов, латиница без I, O, Q + цифры.
_VIN_RE = re.compile(r"^[A-HJ-NPR-Za-hj-npr-z0-9]{17}$")
# Год выпуска: 19xx или 20xx.
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def normalize_phone(raw: str) -> str | None:
    """Привести телефон к виду +7XXXXXXXXXX или вернуть None, если это не номер.

    Принимаем то, как реально пишут люди: с +7, 8, пробелами, скобками, дефисами.
    Возвращаем единый формат, чтобы в таблице не было каши.
    """
    if not raw:
        return None

    # Оставляем только цифры (плюс обработаем отдельно).
    digits = re.sub(r"\D", "", raw)

    # 8XXXXXXXXXX или 7XXXXXXXXXX (11 цифр) -> +7XXXXXXXXXX
    if len(digits) == 11 and digits[0] in ("7", "8"):
        return "+7" + digits[1:]

    # XXXXXXXXXX (10 цифр, без кода страны) -> +7XXXXXXXXXX
    if len(digits) == 10:
        return "+7" + digits

    # Всё остальное (в т.ч. иностранные номера) НЕ принимаем —
    # сервис работает по РФ, нужен +7 / 8 и 11 цифр (или 10 без кода).
    return None


def parse_vehicle_freeform(text: str) -> dict[str, str]:
    """Разобрать свободный ввод авто для ЗАПЧАСТЕЙ.

    Логика «как попадёт»: клиент пишет либо VIN, либо марку и год.
    - Если ввод — это 17-значный VIN, заполняем только vin.
    - Иначе вытаскиваем год (если есть), а остаток считаем маркой/моделью.

    Возвращаем словарь с ключами brand / model / year / vin (пустые строки, если нет).
    """
    result = {"brand": "", "model": "", "year": "", "vin": ""}
    text = (text or "").strip()
    if not text:
        return result

    # Срезаем ведущее слово "VIN"/"ВИН", если оно есть.
    cleaned = re.sub(r"^(?:vin|вин)[:\s]*", "", text, flags=re.IGNORECASE).strip()
    compact = re.sub(r"[\s\-]", "", cleaned)

    # Похоже на VIN — берём его и больше ничего не парсим.
    if _VIN_RE.match(compact):
        result["vin"] = compact.upper()
        return result

    # Иначе пытаемся вытащить год.
    work = text
    ym = _YEAR_RE.search(work)
    if ym:
        result["year"] = ym.group(0)
        work = (work[: ym.start()] + work[ym.end():]).strip()

    # Остаток: первое слово — марка, остальное — модель.
    tokens = work.split()
    if tokens:
        result["brand"] = tokens[0]
        if len(tokens) > 1:
            result["model"] = " ".join(tokens[1:])
    return result
