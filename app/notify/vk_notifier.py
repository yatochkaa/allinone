import logging
import random

import aiohttp

from app.core.models import Lead
from app.notify.base import Notifier

log = logging.getLogger(__name__)

VK_API = "https://api.vk.com/method"
VK_API_VERSION = "5.199"


class VkNotifier(Notifier):
    """Уведомление менеджеру во ВКонтакте. Тот же интерфейс, что у TelegramNotifier/MaxNotifier."""

    def __init__(self, token: str, manager_peer_id: int) -> None:
        self.token = token
        self.manager_peer_id = manager_peer_id

    async def notify_new_lead(self, lead: Lead) -> None:
        if not self.token or not self.manager_peer_id:
            log.warning("VK: нет токена или peer_id менеджера — пропускаю отправку")
            return
        await self._send(self._format(lead))

    async def _send(self, text: str) -> None:
        url = f"{VK_API}/messages.send"
        params = {
            "access_token": self.token,
            "v": VK_API_VERSION,
            "peer_id": self.manager_peer_id,
            "message": text,
            "random_id": random.randint(1, 2_000_000_000),  # VK требует уникальный random_id
        }
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(url, data=params) as response:
                    body = await response.json()
                    if "error" in body:
                        log.error("VK send failed: %s", body["error"])
        except Exception:
            # Уведомление вторично: упало — логируем, но заявку не роняем.
            log.exception("Не удалось отправить уведомление менеджеру в VK")

    @staticmethod
    def _format(lead: Lead) -> str:
        # ВАЖНО: обычные сообщения VK НЕ рендерят markdown/HTML — шлём чистый текст.
        car = " ".join(
            str(x) for x in (lead.brand, lead.model, lead.year) if x not in (None, "")
        )
        type_labels = {"parts": "🔧 Запчасти", "repair": "🛠 Ремонт", "question": "❓ Вопрос"}
        lines = [
            f"🔔 Новая заявка №{lead.lead_number}",
            "",
            f"📲 Источник: {lead.source}",
            f"👤 Имя: {lead.name}",
            f"📞 Телефон: {lead.phone}",
        ]
        if car:
            lines.append(f"🚗 Авто: {car}")
        if lead.vin:
            lines.append(f"🔢 VIN: {lead.vin}")
        if lead.request_type in type_labels:
            lines.append(f"🏷 Тип: {type_labels[lead.request_type]}")
        lines += ["", "📝 Запрос:", lead.request_text]
        return "\n".join(lines)