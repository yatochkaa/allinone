import logging

import aiohttp

from app.core.models import Lead
from app.notify.base import Notifier

log = logging.getLogger(__name__)

MAX_API = "https://platform-api.max.ru"


def _md(text: str) -> str:
    """Экранировать спецсимволы MAX-markdown в пользовательских значениях.

    Кривой markdown в MAX обычно не роняет отправку, но «страшно рисует»
    имя/текст со звёздочками, подчёркиваниями и т.п.
    """
    if not text:
        return ""
    for ch in ("\\", "`", "*", "_", "[", "]", "(", ")", "~"):
        text = text.replace(ch, "\\" + ch)
    return text


class MaxNotifier(Notifier):
    """Отправляет уведомление менеджеру через MAX. Тот же интерфейс, что у TelegramNotifier."""

    def __init__(self, token: str, manager_user_id: int) -> None:
        self.token = token
        self.manager_user_id = manager_user_id

    async def notify_new_lead(self, lead: Lead) -> bool:
        if not self.token or not self.manager_user_id:
            log.warning("MAX: нет токена или id менеджера — пропускаю отправку")
            return False
        return await self._send(self._format(lead))

    async def _send(self, text: str) -> bool:
        url = f"{MAX_API}/messages"
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }
        params = {"user_id": self.manager_user_id}
        payload = {"text": text, "format": "markdown"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, params=params, headers=headers, json=payload
                ) as response:
                    if response.status != 200:
                        body = await response.text()
                        log.error("MAX send failed [%s]: %s", response.status, body)
                        return False
                    return True
        except Exception as e:
            log.exception("MAX send error: %s", e)
            return False

    @staticmethod
    def _format(lead) -> str:
        # Авто: марка + модель + год — собираем только заполненное
        car = " ".join(
            str(x) for x in (lead.brand, lead.model, lead.year)
            if x not in (None, "")
        )
        type_labels = {
            "parts": "🔧 Запчасти",
            "repair": "🛠 Ремонт",
            "question": "❓ Вопрос",
        }

        lines = [
            f"🔔 **Новая заявка №{lead.lead_number}**",
            "",
            f"📲 **Источник:** {lead.source}",
            f"👤 **Имя:** {_md(lead.name)}",
            f"📞 **Телефон:** `{lead.phone}`",
        ]
        if car:
            lines.append(f"🚗 **Авто:** {_md(car)}")
        if lead.vin:
            lines.append(f"🔢 **VIN:** `{lead.vin}`")
        if lead.request_type in type_labels:
            lines.append(f"🏷 **Тип:** {type_labels[lead.request_type]}")

        lines += [
            "",
            "📝 **Запрос:**",
            f"_{_md(lead.request_text)}_",
        ]
        return "\n".join(lines)