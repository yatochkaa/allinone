import os
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("MAX_BOT_TOKEN", "").strip()
BASE = "https://platform-api.max.ru"

if not TOKEN:
    print("❌ MAX_BOT_TOKEN пустой — впиши токен в .env и запусти снова")
    raise SystemExit(1)


def fetch(use_header: bool):
    if use_header:
        url = f"{BASE}/updates?timeout=30"
        req = urllib.request.Request(url, headers={"Authorization": TOKEN})
    else:
        url = f"{BASE}/updates?timeout=30&access_token={TOKEN}"
        req = urllib.request.Request(url)

    with urllib.request.urlopen(req, timeout=45) as r:
        return r.status, r.read().decode("utf-8")


def try_mode(use_header: bool):
    mode = "header Authorization" if use_header else "query access_token"
    print(f"\n→ Пробую авторизацию: {mode}")
    try:
        status, body = fetch(use_header)
        print("Статус:", status)
        print("Ответ:", body[:2000])
        return body
    except urllib.error.HTTPError as e:
        print("HTTP error:", e.code)
        try:
            print(e.read().decode("utf-8")[:2000])
        except Exception:
            pass
        return None
    except Exception as e:
        print("Ошибка запроса:", e)
        return None


body = try_mode(True) or try_mode(False)

if not body:
    print("\nОтвета нет. Проверь токен и интернет.")
    raise SystemExit(1)

data = json.loads(body)
updates = data.get("updates", [])

if not updates:
    print("\nОбновлений нет.")
    print("Порядок такой: 1) напиши боту в MAX любое слово, 2) СРАЗУ запусти этот скрипт.")
    raise SystemExit(0)

print("\nЕсть обновления — вот они целиком (ищи поле user_id):")
for u in updates:
    print("\n--- update ---")
    print(json.dumps(u, ensure_ascii=False, indent=2))