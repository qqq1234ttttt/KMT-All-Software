import os
import json
import threading
import time
import requests

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="KMT All Software Control")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

DATA_FILE = "data.json"
DATA_LOCK = threading.Lock()

DEFAULT_SETTINGS = {
    "app_locked": False,
    "maintenance_mode": False,
    "maintenance_message": "လက်ရှိတွင် App ကို ပြုပြင်ထိန်းသိမ်းနေပါသည်။",
    "fb_download_enabled": True,
    "latest_version": "1.1.0",
    "minimum_version": "1.1.0",
    "apk_url": "",
    "announcement": "",
    "updated_at": ""
}


def load_settings():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            saved = json.load(file)
            return {**DEFAULT_SETTINGS, **saved}
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    with DATA_LOCK:
        temp_file = DATA_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=2)
        os.replace(temp_file, DATA_FILE)


def update_settings(changes):
    settings = load_settings()
    settings.update(changes)
    settings["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    save_settings(settings)
    return settings


def send_telegram(text, chat_id=None):
    if not BOT_TOKEN:
        return False

    target = str(chat_id or ADMIN_CHAT_ID)
    if not target:
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": target, "text": text},
            timeout=15
        )
        return response.ok
    except requests.RequestException:
        return False


def is_admin(chat_id):
    return bool(ADMIN_CHAT_ID) and str(chat_id) == str(ADMIN_CHAT_ID)


def telegram_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "📊 အခြေအနေ", "callback_data": "status"},
                {"text": "🔒 App ပိတ်", "callback_data": "lock"}
            ],
            [
                {"text": "🔓 App ဖွင့်", "callback_data": "unlock"},
                {"text": "🛠 Maintenance ဖွင့်", "callback_data": "maintenance_on"}
            ],
            [
                {"text": "✅ Maintenance ပိတ်", "callback_data": "maintenance_off"}
            ],
            [
                {"text": "📥 FB Download ဖွင့်", "callback_data": "fb_on"},
                {"text": "⛔ FB Download ပိတ်", "callback_data": "fb_off"}
            ]
        ]
    }


def status_text():
    s = load_settings()
    return (
        "📊 KMT All Software အခြေအနေ\n\n"
        f"🔒 App Lock: {'ဖွင့်ထားသည်' if s['app_locked'] else 'ပိတ်ထားသည်'}\n"
        f"🛠 Maintenance: {'ဖွင့်ထားသည်' if s['maintenance_mode'] else 'ပိတ်ထားသည်'}\n"
        f"📥 FB Download: {'ဖွင့်ထားသည်' if s['fb_download_enabled'] else 'ပိတ်ထားသည်'}\n"
        f"🔄 နောက်ဆုံး Version: {s['latest_version']}\n"
        f"📱 အနည်းဆုံး Version: {s['minimum_version']}\n"
        f"📢 ကြေညာချက်: {s['announcement'] or 'မရှိသေးပါ'}"
    )


@app.get("/")
def home():
    return {
        "message": "KMT All Software Control API အလုပ်လုပ်နေပါသည်။",
        "health": "/health",
        "config": "/config?version=1.1.0"
    }


@app.get("/health")
def health():
    return {"ok": True, "service": "KMT All Software Control"}


@app.get("/config")
def public_config(version: str = "1.1.0"):
    s = load_settings()

    try:
        current = tuple(int(x) for x in version.split("."))
        minimum = tuple(int(x) for x in s["minimum_version"].split("."))
        latest = tuple(int(x) for x in s["latest_version"].split("."))
    except (ValueError, AttributeError):
        current = (0,)
        minimum = (1,)
        latest = (1,)

    return {
        "app_locked": s["app_locked"],
        "maintenance_mode": s["maintenance_mode"],
        "maintenance_message": s["maintenance_message"],
        "fb_download_enabled": s["fb_download_enabled"],
        "current_version": version,
        "latest_version": s["latest_version"],
        "minimum_version": s["minimum_version"],
        "update_available": current < latest,
        "force_update": current < minimum,
        "apk_url": s["apk_url"],
        "announcement": s["announcement"],
        "updated_at": s["updated_at"]
    }


class SettingsUpdate(BaseModel):
    app_locked: bool | None = None
    maintenance_mode: bool | None = None
    maintenance_message: str | None = None
    fb_download_enabled: bool | None = None
    latest_version: str | None = None
    minimum_version: str | None = None
    apk_url: str | None = None
    announcement: str | None = None


def require_admin(x_admin_key):
    if not ADMIN_API_KEY or x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="ခွင့်ပြုချက်မရှိပါ။")


@app.get("/admin/status")
def admin_status(x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    return load_settings()


@app.post("/admin/settings")
def admin_settings(
    body: SettingsUpdate,
    x_admin_key: str = Header(default="")
):
    require_admin(x_admin_key)
    changes = body.model_dump(exclude_none=True)
    return update_settings(changes)


def telegram_polling():
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN မသတ်မှတ်ရသေးပါ။")
        return

    offset = None

    while True:
        try:
            response = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"timeout": 25, "offset": offset},
                timeout=35
            )
            result = response.json()

            if not result.get("ok"):
                time.sleep(5)
                continue

            for item in result.get("result", []):
                offset = item["update_id"] + 1

                message = item.get("message")
                if message:
                    chat_id = message.get("chat", {}).get("id")
                    text = message.get("text", "").strip()

                    if not is_admin(chat_id):
                        continue

                    if text in ("/start", "/menu"):
                        send_telegram(
                            "မင်္ဂလာပါ။ KMT All Software Control မှ ကြိုဆိုပါတယ်။\n"
                            "အောက်ပါခလုတ်များကို အသုံးပြုပါ။\n\n"
                            + status_text(),
                            chat_id
                        )
                        requests.post(
                            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                            json={
                                "chat_id": chat_id,
                                "text": "ထိန်းချုပ်မှု Menu",
                                "reply_markup": telegram_keyboard()
                            },
                            timeout=15
                        )

                    elif text == "/status":
                        send_telegram(status_text(), chat_id)

                    elif text.startswith("/notice "):
                        notice = text[len("/notice "):].strip()
                        update_settings({"announcement": notice})
                        send_telegram("✅ ကြေညာချက် သိမ်းဆည်းပြီးပါပြီ။", chat_id)

                    elif text.startswith("/announce "):
                        notice = text[len("/announce "):].strip()
                        update_settings({"announcement": notice})
                        send_telegram(
                            "📢 ကြေညာချက်ကို API ထဲတွင် သိမ်းဆည်းပြီးပါပြီ။",
                            chat_id
                        )

                    elif text.startswith("/version "):
                        parts = text.split(maxsplit=3)
                        if len(parts) >= 3:
                            changes = {
                                "latest_version": parts[1],
                                "minimum_version": parts[2]
                            }
                            if len(parts) == 4:
                                changes["apk_url"] = parts[3]
                            update_settings(changes)
                            send_telegram("✅ Version ဆက်တင် ပြောင်းပြီးပါပြီ။", chat_id)
                        else:
                            send_telegram(
                                "အသုံးပြုပုံ:\n/version 1.2.0 1.1.0 https://example.com/app.apk",
                                chat_id
                            )

                    elif text.startswith("/apk "):
                        url = text[len("/apk "):].strip()
                        update_settings({"apk_url": url})
                        send_telegram("✅ APK လင့်ခ် သိမ်းဆည်းပြီးပါပြီ။", chat_id)

                callback = item.get("callback_query")
                if callback:
                    chat_id = callback.get("message", {}).get("chat", {}).get("id")
                    data = callback.get("data", "")

                    if not is_admin(chat_id):
                        continue

                    changes = {
                        "lock": {"app_locked": True},
                        "unlock": {"app_locked": False},
                        "maintenance_on": {"maintenance_mode": True},
                        "maintenance_off": {"maintenance_mode": False},
                        "fb_on": {"fb_download_enabled": True},
                        "fb_off": {"fb_download_enabled": False}
                    }

                                        if data in changes:
                        update_settings(changes[data])

                        messages = {
                            "lock": "🔒 App ကို ပိတ်လိုက်ပါပြီ။",
                            "unlock": "🔓 App ကို ပြန်ဖွင့်လိုက်ပါပြီ။",
                            "maintenance_on": "🛠 Maintenance Mode ကို ဖွင့်လိုက်ပါပြီ။",
                            "maintenance_off": "✅ Maintenance Mode ကို ပိတ်လိုက်ပါပြီ။",
                            "fb_on": "📥 FB Download ကို ဖွင့်လိုက်ပါပြီ။",
                            "fb_off": "⛔ FB Download ကို ပိတ်လိုက်ပါပြီ။"
                        }

                        send_telegram(
                            messages[data] + "\n\n" + status_text(),
                            chat_id
                        )

                    elif data == "status":
                        send_telegram(status_text(), chat_id)

                    requests.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": callback["id"]},
                        timeout=10
                    )

        except Exception as error:
            print("Telegram Bot error:", error)
            time.sleep(5)


@app.on_event("startup")
def startup_event():
    if BOT_TOKEN:
        thread = threading.Thread(target=telegram_polling, daemon=True)
        thread.start()
