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
    with DATA_LOCK:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as file:
                saved = json.load(file)

            if not isinstance(saved, dict):
                return DEFAULT_SETTINGS.copy()

            return {**DEFAULT_SETTINGS, **saved}

        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    with DATA_LOCK:
        temp_file = DATA_FILE + ".tmp"

        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(
                settings,
                file,
                ensure_ascii=False,
                indent=2
            )

        os.replace(temp_file, DATA_FILE)


def update_settings(changes):
    settings = load_settings()
    settings.update(changes)

    settings["updated_at"] = time.strftime(
        "%Y-%m-%d %H:%M:%S",
        time.gmtime()
    )

    save_settings(settings)
    return settings


def send_telegram(text, chat_id=None, reply_markup=None):
    if not BOT_TOKEN:
        return False

    target = str(chat_id or ADMIN_CHAT_ID)

    if not target:
        return False

    payload = {
        "chat_id": target,
        "text": text
    }

    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=15
        )

        if not response.ok:
            print("Telegram sendMessage error:", response.text)

        return response.ok

    except requests.RequestException as error:
        print("Telegram send error:", error)
        return False


def answer_callback(callback_id, text=""):
    if not BOT_TOKEN:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
            json={
                "callback_query_id": callback_id,
                "text": text
            },
            timeout=10
        )

    except requests.RequestException as error:
        print("Telegram callback error:", error)


def is_admin(chat_id):
    return (
        bool(ADMIN_CHAT_ID)
        and str(chat_id) == str(ADMIN_CHAT_ID)
    )


def telegram_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "📊 အခြေအနေ",
                    "callback_data": "status"
                },
                {
                    "text": "🔒 App ပိတ်",
                    "callback_data": "lock"
                }
            ],
            [
                {
                    "text": "🔓 App ဖွင့်",
                    "callback_data": "unlock"
                },
                {
                    "text": "🛠 Maintenance ဖွင့်",
                    "callback_data": "maintenance_on"
                }
            ],
            [
                {
                    "text": "✅ Maintenance ပိတ်",
                    "callback_data": "maintenance_off"
                }
            ],
            [
                {
                    "text": "📥 FB Download ဖွင့်",
                    "callback_data": "fb_on"
                },
                {
                    "text": "⛔ FB Download ပိတ်",
                    "callback_data": "fb_off"
                }
            ]
        ]
    }


def status_text():
    settings = load_settings()

    app_lock_status = (
        "🔒 ပိတ်ဆို့ထားသည်"
        if settings["app_locked"]
        else "🔓 အသုံးပြုခွင့်ရှိသည်"
    )

    maintenance_status = (
        "ဖွင့်ထားသည်"
        if settings["maintenance_mode"]
        else "ပိတ်ထားသည်"
    )

    fb_status = (
        "ဖွင့်ထားသည်"
        if settings["fb_download_enabled"]
        else "ပိတ်ထားသည်"
    )

    return (
        "📊 KMT All Software အခြေအနေ\n\n"
        f"🔒 App Lock: {app_lock_status}\n"
        f"🛠 Maintenance: {maintenance_status}\n"
        f"📥 FB Download: {fb_status}\n"
        f"🔄 နောက်ဆုံး Version: {settings['latest_version']}\n"
        f"📱 အနည်းဆုံး Version: {settings['minimum_version']}\n"
        f"📢 ကြေညာချက်: "
        f"{settings['announcement'] or 'မရှိသေးပါ'}"
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
    return {
        "ok": True,
        "service": "KMT All Software Control"
    }


@app.get("/config")
def public_config(version: str = "1.1.0"):
    settings = load_settings()

    try:
        current = tuple(
            int(part) for part in version.split(".")
        )

        minimum = tuple(
            int(part)
            for part in settings["minimum_version"].split(".")
        )

        latest = tuple(
            int(part)
            for part in settings["latest_version"].split(".")
        )

    except (ValueError, AttributeError):
        current = (0,)
        minimum = (1,)
        latest = (1,)

    return {
        "app_locked": settings["app_locked"],
        "maintenance_mode": settings["maintenance_mode"],
        "maintenance_message": settings["maintenance_message"],
        "fb_download_enabled": settings["fb_download_enabled"],
        "current_version": version,
        "latest_version": settings["latest_version"],
        "minimum_version": settings["minimum_version"],
        "update_available": current < latest,
        "force_update": current < minimum,
        "apk_url": settings["apk_url"],
        "announcement": settings["announcement"],
        "updated_at": settings["updated_at"]
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
        raise HTTPException(
            status_code=401,
            detail="ခွင့်ပြုချက်မရှိပါ။"
        )


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


def process_message(message):
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not is_admin(chat_id):
        return

    if text in ("/start", "/menu"):
        send_telegram(
            "မင်္ဂလာပါ။ KMT All Software Control မှ "
            "ကြိုဆိုပါတယ်။\n\n"
            + status_text(),
            chat_id
        )

        send_telegram(
            "⚙️ ထိန်းချုပ်မှု Menu",
            chat_id,
            telegram_keyboard()
        )

    elif text == "/status":
        send_telegram(status_text(), chat_id)

    elif text.startswith("/notice "):
        notice = text[len("/notice "):].strip()

        if not notice:
            send_telegram(
                "အသုံးပြုပုံ: /notice ကြေညာချက်စာသား",
                chat_id
            )
            return

        update_settings({"announcement": notice})

        send_telegram(
            "✅ ကြေညာချက် သိမ်းဆည်းပြီးပါပြီ။",
            chat_id
        )

    elif text.startswith("/announce "):
        notice = text[len("/announce "):].strip()

        if not notice:
            send_telegram(
                "အသုံးပြုပုံ: /announce ကြေညာချက်စာသား",
                chat_id
            )
            return

        update_settings({"announcement": notice})

        send_telegram(
            "📢 ကြေညာချက်ကို API ထဲတွင် "
            "သိမ်းဆည်းပြီးပါပြီ။",
            chat_id
        )

    elif text.startswith("/version"):
        parts = text.split(maxsplit=3)

        if len(parts) < 3:
            send_telegram(
                "အသုံးပြုပုံ:\n"
                "/version 1.2.0 1.1.0 https://example.com/app.apk\n\n"
                "ပထမ Version = နောက်ဆုံး Version\n"
                "ဒုတိယ Version = အနည်းဆုံး Version\n"
                "APK URL = မဖြစ်မနေ မလိုပါ။",
                chat_id
            )
            return

        latest_version = parts[1]
        minimum_version = parts[2]

        changes = {
            "latest_version": latest_version,
            "minimum_version": minimum_version
        }

        if len(parts) == 4:
            changes["apk_url"] = parts[3]

        update_settings(changes)

        send_telegram(
            "✅ Version ဆက်တင် ပြောင်းပြီးပါပြီ။\n\n"
            + status_text(),
            chat_id
        )

    elif text.startswith("/apk "):
        url = text[len("/apk "):].strip()

        if not url:
            send_telegram(
                "အသုံးပြုပုံ: /apk https://example.com/app.apk",
                chat_id
            )
            return

        update_settings({"apk_url": url})

        send_telegram(
            "✅ APK လင့်ခ် သိမ်းဆည်းပြီးပါပြီ။",
            chat_id
        )


def process_callback(callback):
    chat_id = callback.get("message", {}).get(
        "chat", {}
    ).get("id")

    data = callback.get("data", "")
    callback_id = callback.get("id", "")

    if not is_admin(chat_id):
        answer_callback(
            callback_id,
            "ခွင့်ပြုချက်မရှိပါ။"
        )
        return

    changes = {
        "lock": {
            "app_locked": True
        },
        "unlock": {
            "app_locked": False
        },
        "maintenance_on": {
            "maintenance_mode": True
        },
        "maintenance_off": {
            "maintenance_mode": False
        },
        "fb_on": {
            "fb_download_enabled": True
        },
        "fb_off": {
            "fb_download_enabled": False
        }
    }

    messages = {
        "lock": "🔒 App ကို ပိတ်လိုက်ပါပြီ။",
        "unlock": "🔓 App ကို ဖွင့်လိုက်ပါပြီ။",
        "maintenance_on": "🛠 Maintenance Mode ကို ဖွင့်လိုက်ပါပြီ။",
        "maintenance_off": "✅ Maintenance Mode ကို ပိတ်လိုက်ပါပြီ။",
        "fb_on": "📥 FB Download ကို ဖွင့်လိုက်ပါပြီ။",
        "fb_off": "⛔ FB Download ကို ပိတ်လိုက်ပါပြီ။"
    }
    }

    if data in changes:
        update_settings(changes[data])

        send_telegram(
            messages[data] + "\n\n" + status_text(),
            chat_id
        )

        answer_callback(
            callback_id,
            "✅ ဆက်တင် ပြောင်းပြီးပါပြီ။"
        )

    elif data == "status":
        send_telegram(status_text(), chat_id)

        answer_callback(
            callback_id,
            "📊 လက်ရှိအခြေအနေ ပြသပြီးပါပြီ။"
        )

    else:
        answer_callback(
            callback_id,
            "မသိရှိသော ခလုတ်ဖြစ်ပါသည်။"
        )


def telegram_polling():
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN မသတ်မှတ်ရသေးပါ။")
        return

    offset = None

    while True:
        try:
            response = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={
                    "timeout": 25,
                    "offset": offset
                },
                timeout=35
            )

            response.raise_for_status()
            result = response.json()

            if not result.get("ok"):
                print("Telegram getUpdates error:", result)
                time.sleep(5)
                continue

            for item in result.get("result", []):
                offset = item["update_id"] + 1

                message = item.get("message")

                if message:
                    process_message(message)

                callback = item.get("callback_query")

                if callback:
                    process_callback(callback)

        except Exception as error:
            print("Telegram Bot error:", error)
            time.sleep(5)


@app.on_event("startup")
def startup_event():
    if BOT_TOKEN:
        thread = threading.Thread(
            target=telegram_polling,
            daemon=True
        )
        thread.start()
    else:
        print("Telegram Bot Token မရှိပါ။")
