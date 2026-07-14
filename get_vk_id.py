"""Одноразовый помощник: узнать VK_MANAGER_PEER_ID.
Перед запуском менеджер должен написать сообществу любое сообщение."""
import asyncio

import aiohttp

VK_TOKEN = "vk1.a.9yNuy5ciGKAw9OhXQl58zUMw-xUXZlynnWRkbAhy2MQ_-uNr0y5KostT99lBpXLXWxVpB5Fto7DkbXnmWyZJz66dZGUmroCAZXBZu4WcTSaVYkw5yOP8-mNTh-h2ranqS8SglZKkp1Hf6gaXXI6p5oqoF4vjVr_omuXP7cxQVggYMTk87lHfav9eFZoaJPFke_M3vgJzBBiREgHDXAhI4Q"
VK_API = "https://api.vk.com/method"
VK_API_VERSION = "5.199"


async def main() -> None:
    url = f"{VK_API}/messages.getConversations"
    params = {"access_token": VK_TOKEN, "v": VK_API_VERSION, "count": 20}
    # ssl=False — обходим проверку сертификата VK (см. примечание про Минцифры ниже)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.post(url, data=params) as resp:
            data = await resp.json()

    if "error" in data:
        print("Ошибка VK:", data["error"])
        return

    items = data["response"]["items"]
    if not items:
        print("Никто ещё не писал сообществу. Напишите боту и запустите снова.")
        return

    print("Кто недавно писал сообществу (peer_id — это и есть VK_MANAGER_PEER_ID):")
    for it in items:
        peer = it["conversation"]["peer"]
        text = it.get("last_message", {}).get("text", "")
        print(f"  peer_id = {peer['id']}   (тип: {peer['type']})   последнее: {text!r}")


if __name__ == "__main__":
    asyncio.run(main())