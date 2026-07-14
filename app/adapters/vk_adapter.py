"""
VK-адаптер: ВКонтакте как источник клиентов.

Слушает сообщения сообщества через Bots Long Poll API (без внешних библиотек —
только aiohttp, который уже идёт с aiogram). Ведёт ту же анкету, что и Telegram
(имя -> телефон -> тип -> [авто] -> описание -> подтверждение) и отдаёт готовый
Lead в LeadService. Бизнес-логики здесь нет — только транспорт и сбор данных.

VK не даёт inline-callback как Telegram, поэтому тип запроса и подтверждение
выбираются текстом/цифрой. FSM-состояния храним в памяти процесса (по user_id).
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import aiohttp

from app.core.models import Lead
from app.core.service import LeadService
from app.core.validators import normalize_phone, parse_vehicle_freeform

log = logging.getLogger(__name__)

VK_API = "https://api.vk.com/method"
VK_API_VERSION = "5.199"

# Шаги анкеты (те же, что в Telegram).
S_NAME = "name"
S_PHONE = "phone"
S_TYPE = "request_type"
S_VEH_PARTS = "veh_parts"
S_DESCRIPTION = "description"
S_CONFIRM = "confirm"


class VkAdapter:
    """Реализация MessengerAdapter для ВКонтакте (Bots Long Poll)."""

    def __init__(
        self,
        token: str,
        service: LeadService,
        manager_peer_id: int | None = None,
    ) -> None:
        self._token = token
        self._service = service
        self._manager_peer_id = manager_peer_id
        self._group_id: int | None = None
        self._session: aiohttp.ClientSession | None = None
        # FSM в памяти: {user_id: {"state": str, "data": dict}}
        self._sessions: dict[int, dict[str, Any]] = {}

    # --- интерфейс MessengerAdapter ---

    async def listen(self) -> None:
        """Запустить Long Poll-цикл. Блокирует выполнение до остановки."""
        log.info("VkAdapter запущен, подключаюсь к Long Poll…")
        # ssl=False — у VK сертификат Минцифры (см. страницу про VkNotifier).
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            self._session = session
            self._group_id = await self._get_group_id()
            server = await self._get_long_poll_server()
            while True:
                try:
                    server = await self._poll_once(server)
                except Exception:
                    log.exception("VK Long Poll: ошибка цикла, переподключаюсь через 3с")
                    await asyncio.sleep(3)
                    server = await self._get_long_poll_server()

    async def send(self, chat_id: Any, text: str) -> None:
        """Отправить сообщение пользователю (для лички peer_id == user_id)."""
        await self._api("messages.send", {
            "access_token": self._token,
            "v": VK_API_VERSION,
            "peer_id": chat_id,
            "message": text,
            "random_id": random.randint(1, 2_000_000_000),
        })

    def normalize(self, raw: dict[str, Any]) -> Lead:
        """Собрать Lead из данных анкеты."""
        return Lead(
            name=str(raw.get("name", "")).strip(),
            phone=str(raw.get("phone", "")).strip(),
            request_text=str(raw.get("description", "")).strip(),
            request_type=str(raw.get("request_type", "question")),
            brand=str(raw.get("brand", "")).strip(),
            model=str(raw.get("model", "")).strip(),
            year=str(raw.get("year", "")).strip(),
            vin=str(raw.get("vin", "")).strip(),
            source="vk",
            external_user_id=str(raw.get("user_id")) if raw.get("user_id") else None,
            external_username=raw.get("username"),
            marketing_consent=bool(raw.get("marketing_consent", False)),
        )

    # --- VK API / Long Poll ---

    async def _api(self, method: str, params: dict[str, Any]) -> Any:
        url = f"{VK_API}/{method}"
        async with self._session.post(url, data=params) as resp:
            body = await resp.json()
        if "error" in body:
            log.error("VK API %s error: %s", method, body["error"])
            raise RuntimeError(body["error"])
        return body["response"]

    async def _get_group_id(self) -> int:
        resp = await self._api("groups.getById", {
            "access_token": self._token,
            "v": VK_API_VERSION,
        })
        # v5.199 возвращает {"groups": [...]}, старые версии — просто список.
        if isinstance(resp, dict) and "groups" in resp:
            return int(resp["groups"][0]["id"])
        return int(resp[0]["id"])

    async def _get_long_poll_server(self) -> dict[str, Any]:
        resp = await self._api("groups.getLongPollServer", {
            "access_token": self._token,
            "v": VK_API_VERSION,
            "group_id": self._group_id,
        })
        return {"server": resp["server"], "key": resp["key"], "ts": resp["ts"]}

    async def _poll_once(self, server: dict[str, Any]) -> dict[str, Any]:
        params = {"act": "a_check", "key": server["key"], "ts": server["ts"], "wait": 25}
        async with self._session.get(server["server"], params=params) as resp:
            data = await resp.json()

        # Long Poll протух: 1 — обновить ts; 2/3 — перезапросить ключ.
        if "failed" in data:
            if data["failed"] == 1:
                server["ts"] = data["ts"]
                return server
            return await self._get_long_poll_server()

        server["ts"] = data["ts"]
        for update in data.get("updates", []):
            if update.get("type") == "message_new":
                await self._handle_message(update)
        return server

    # --- диалог анкеты ---

    async def _handle_message(self, update: dict[str, Any]) -> None:
        # В API v5.x объект сообщения лежит в object.message.
        message = update["object"]["message"]
        peer_id = message["peer_id"]
        from_id = message["from_id"]
        text = (message.get("text") or "").strip()

        # Работаем только с личкой пользователя; сообщество/беседы и менеджера игнорируем.
        if from_id < 0 or from_id == self._manager_peer_id:
            return

        low = text.lower()
        if low in ("стоп", "отмена", "cancel"):
            self._sessions.pop(from_id, None)
            await self.send(peer_id, "Заявка отменена. Напишите что угодно, чтобы начать заново.")
            return

        session = self._sessions.get(from_id)
        if session is None:
            await self._start_dialog(from_id, peer_id)
            return

        await self._step(from_id, peer_id, text, session)

    async def _start_dialog(self, user_id: int, peer_id: int) -> None:
        self._sessions[user_id] = {"state": S_NAME, "data": {"user_id": user_id}}
        await self.send(
            peer_id,
            "Здравствуйте! Я помогу оформить заявку — это займёт 30 секунд.\n\n"
            "Как вас зовут?",
        )

    async def _step(self, user_id: int, peer_id: int, text: str, session: dict[str, Any]) -> None:
        state = session["state"]
        data = session["data"]

        if state == S_NAME:
            if not text:
                await self.send(peer_id, "Напишите, пожалуйста, ваше имя.")
                return
            data["name"] = text
            session["state"] = S_PHONE
            await self.send(peer_id, "Приятно! Оставьте номер телефона (например: +7 999 123-45-67).")
            return

        if state == S_PHONE:
            phone = normalize_phone(text)
            if phone is None:
                await self.send(peer_id, "Не похоже на номер 😅 Введите в формате +7 999 123-45-67.")
                return
            data["phone"] = phone
            session["state"] = S_TYPE
            await self.send(
                peer_id,
                "Спасибо! Что вас интересует? Ответьте цифрой:\n"
                "1 — 🔧 Запчасти\n"
                "2 — 🛠 Ремонт\n"
                "3 — ❓ Другой вопрос",
            )
            return

        if state == S_TYPE:
            mapping = {"1": "parts", "2": "repair", "3": "question"}
            req_type = mapping.get(text.strip())
            if req_type is None:
                low = text.lower()
                if "запчаст" in low:
                    req_type = "parts"
                elif "ремонт" in low:
                    req_type = "repair"
                elif "вопрос" in low or "друг" in low:
                    req_type = "question"
            if req_type is None:
                await self.send(peer_id, "Выберите цифрой: 1 — Запчасти, 2 — Ремонт, 3 — Другой вопрос.")
                return
            data["request_type"] = req_type
            if req_type == "repair":
                session["state"] = S_VEH_PARTS
                await self.send(
                    peer_id,
                    "Напишите авто одной строкой: марку, модель, поколение "
                    "(если есть) и год.\n"
                    "Например: Lada Priora 2014 или Toyota Camry 70 2022.",
                )
            elif req_type == "parts":
                session["state"] = S_VEH_PARTS
                await self.send(
                    peer_id,
                    "Подскажите авто для подбора запчастей.\n"
                    "Проще всего — VIN (17 символов), этого достаточно.\n"
                    "Если VIN нет — напишите марку, модель, поколение (если есть) и год "
                    "одной строкой.\n"
                    "Например: Lada Priora 2014 или Toyota Camry 70 2022.",
                )
            else:
                data.update(brand="", model="", year="", vin="")
                session["state"] = S_DESCRIPTION
                await self.send(peer_id, "Опишите, пожалуйста, суть вашего вопроса.")
            return

        if state == S_VEH_PARTS:
            parsed = parse_vehicle_freeform(text)
            data.update(
                brand=parsed["brand"],
                model=parsed["model"],
                year=parsed["year"],
                vin=parsed["vin"],
            )
            session["state"] = S_DESCRIPTION
            await self.send(peer_id, "Опишите, какие запчасти нужны (например: «Колодки передние и задние»).")
            return

        if state == S_DESCRIPTION:
            data["description"] = text
            preview = self.normalize(data)
            session["state"] = S_CONFIRM
            await self.send(
                peer_id,
                preview.as_confirmation()
                + "\n\nОтправляем? Напишите «да» для отправки или «заново», чтобы заполнить снова.",
            )
            return

        if state == S_CONFIRM:
            low = text.lower()
            if low in ("да", "отправить", "ок", "согласен", "+"):
                lead = self.normalize(data)
                try:
                    await self._service.register_lead(lead)
                    await self.send(
                        peer_id,
                        f"✅ Заявка №{lead.lead_number} отправлена!\n"
                        "Ожидайте, менеджер скоро свяжется с вами.",
                    )
                except Exception:
                    log.exception("VK: ошибка регистрации заявки")
                    await self.send(
                        peer_id,
                        "Техническая ошибка, мы уже разбираемся. Попробуйте ещё раз чуть позже.",
                    )
                finally:
                    self._sessions.pop(user_id, None)
            elif low in ("заново", "нет", "заполнить заново"):
                await self._start_dialog(user_id, peer_id)
            else:
                await self.send(peer_id, "Напишите «да» для отправки или «заново» для повторного заполнения.")
            return