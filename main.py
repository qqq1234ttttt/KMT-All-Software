import os
import json
import threading
import time
import re
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict


app = FastAPI(title="KMT All Software Control")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

DATA_FILE = "data.json"
DATA_LOCK = threading.RLock()

DEFAULT_SETTINGS = {
    "app_locked": True,
    "maintenance_mode": False,
    "maintenance_message": "လက်ရှိတွင် App ကို ပြုပြင်ထိန်းသိမ်းနေပါသည်။",

    "latest_version": "1.1.0",
    "minimum_version": "1.1.0",

    "apk_url": "",
    "update_message": "App ဗားရှင်းအသစ် ထွက်ရှိလာပါပြီ။ ဆက်လက်အသုံးပြုရန် Update လုပ်ပေးပါ။",

    "announcement": "",
    "updated_at": ""
}


# -------------------------
# VERSION VALIDATION
# -------------------------

def valid_version(version):
    if not isinstance(version, str):
        return False

    return bool(
        re.fullmatch(r"\d+(?:\.\d+)*", version.strip())
    )


def version_tuple(version):
    return tuple(
        int(part)
        for part in version.strip().split(".")
    )


def is_valid_apk_url(url):
    if not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url.strip())

        return (
            parsed.scheme == "https"
            and bool(parsed.netloc)
            and not any(
                char.isspace()
                for char in url.strip()
            )
        )

    except Exception:
        return False


# -------------------------
# SETTINGS
# -------------------------

def load_settings():
    with DATA_LOCK:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as file:
                saved = json.load(file)

            if not isinstance(saved, dict):
                saved = {}

            settings = DEFAULT_SETTINGS.copy()
            settings.update(saved)

            # Remove the old FB Download setting.
            settings.pop("fb_download_enabled", None)

            return settings

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
    with DATA_LOCK:
        settings = load_settings()
        settings.update(changes)

        # Never retain the old FB Download setting.
        settings.pop("fb_download_enabled", None)

        settings["updated_at"] = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.gmtime()
        )

        save_settings(settings)

        return settings


# -------------------------
# TELEGRAM
# -------------------------

def send_telegram(text, chat_id=None, reply_markup=None):
    if not BOT_TOKEN:
        return False

    target = str(chat_id or ADMIN_CHAT_ID)

    if not target:
        return False

    payload = {
        "chat_id": target,
        "text": str(text)
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
                    "text": "🔄 Update အချက်အလက်",
                    "callback_data": "update_status"
                }
            ]
        ]
    }


# -------------------------
# STATUS
# -------------------------

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

    return (
        "📊 KMT All Software အခြေအနေ\n\n"
        f"🔒 App Lock: {app_lock_status}\n"
        f"🛠 Maintenance: {maintenance_status}"
    )


def update_status_text():
    settings = load_settings()

    return (
        "🔄 KMT Update Settings\n\n"
        f"📦 Latest Version: {settings['latest_version']}\n"
        f"📱 Minimum Version: {settings['minimum_version']}\n\n"
        f"🔗 APK Download Link:\n"
        f"{settings['apk_url'] or 'မသတ်မှတ်ရသေးပါ'}\n\n"
        f"📝 Update စာသား:\n"
        f"{settings.get('update_message', 'မသတ်မှတ်ရသေးပါ')}"
    )

# -------------------------
# API ROUTES
# -------------------------

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

    if not valid_version(version):
        raise HTTPException(
            status_code=400,
            detail="Version ပုံစံ မမှန်ပါ။"
        )

    if not valid_version(settings["latest_version"]):
        raise HTTPException(
            status_code=500,
            detail="Server latest_version မမှန်ပါ။"
        )

    if not valid_version(settings["minimum_version"]):
        raise HTTPException(
            status_code=500,
            detail="Server minimum_version မမှန်ပါ။"
        )

    current = version_tuple(version)
    minimum = version_tuple(settings["minimum_version"])
    latest = version_tuple(settings["latest_version"])

    return {
        "app_locked": settings["app_locked"],

        "maintenance_mode": settings["maintenance_mode"],
        "maintenance_message": settings["maintenance_message"],

        "current_version": version,
        "latest_version": settings["latest_version"],
        "minimum_version": settings["minimum_version"],

        "update_available": current < latest,
        "force_update": current < minimum,

        "apk_url": settings["apk_url"],
        "update_message": settings["update_message"],

        "announcement": settings["announcement"],
        "updated_at": settings["updated_at"]
    }


# -------------------------
# ADMIN SETTINGS API
# -------------------------

class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_locked: bool | None = None

    maintenance_mode: bool | None = None
    maintenance_message: str | None = None

    latest_version: str | None = None
    minimum_version: str | None = None

    apk_url: str | None = None
    update_message: str | None = None

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

    current = load_settings()

    new_latest = changes.get(
        "latest_version",
        current["latest_version"]
    )

    new_minimum = changes.get(
        "minimum_version",
        current["minimum_version"]
    )

    if not valid_version(new_latest):
        raise HTTPException(
            status_code=400,
            detail="latest_version မမှန်ပါ။"
        )

    if not valid_version(new_minimum):
        raise HTTPException(
            status_code=400,
            detail="minimum_version မမှန်ပါ။"
        )

    if version_tuple(new_minimum) > version_tuple(new_latest):
        raise HTTPException(
            status_code=400,
            detail="minimum_version သည် latest_version ထက် မကြီးရပါ။"
        )

    if "apk_url" in changes:
        if changes["apk_url"] and not is_valid_apk_url(changes["apk_url"]):
            raise HTTPException(
                status_code=400,
                detail="APK Link သည် HTTPS URL ဖြစ်ရပါမည်။"
            )

    return update_settings(changes)


# -------------------------
# TELEGRAM COMMANDS
# -------------------------

def process_message(message):
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not is_admin(chat_id):
        return

    # MAIN MENU
    if text in ("/start", "/menu"):
        send_telegram(
            "မင်္ဂလာပါ။ KMT All Software Control မှ ကြိုဆိုပါတယ်။\n\n"
            + status_text(),
            chat_id
        )

        send_telegram(
            "⚙️ ထိန်းချုပ်မှု Menu",
            chat_id,
            telegram_keyboard()
        )

    # LOCK STATUS ONLY
    elif text == "/status":
        send_telegram(status_text(), chat_id)

    # UPDATE STATUS ONLY
    elif text in ("/updatestatus", "/updatestatus@"):
        send_telegram(update_status_text(), chat_id)

    # UPDATE MESSAGE ONLY
    elif text == "/updatemsg" or text.startswith("/updatemsg "):
        update_message = text[len("/updatemsg"):].strip()

        if not update_message:
            send_telegram(
                "📝 Update စာသားပြောင်းရန်:\n\n"
                "/updatemsg ကိုကြိုက်တဲ့စာသားရေးပါ\n\n"
                "ဥပမာ:\n"
                "/updatemsg App ဗားရှင်းအသစ်ထွက်ပါပြီ။ Update လုပ်ပေးပါ။",
                chat_id
            )
            return

        update_settings({
            "update_message": update_message
        })

        send_telegram(
            "✅ Update စာသား ပြောင်းပြီးပါပြီ။\n\n"
            + update_status_text(),
            chat_id
        )

    # APK LINK ONLY
    elif text == "/apk" or text.startswith("/apk "):
        apk_url = text[len("/apk"):].strip()

        if not apk_url:
            send_telegram(
                "🔗 APK Link ထည့်ရန်:\n\n"
                "/apk https://example.com/app.apk",
                chat_id
            )
            return

        from urllib.parse import urlparse

        parsed = urlparse(apk_url)

        if parsed.scheme != "https" or not parsed.netloc:
            send_telegram(
                "❌ မှန်ကန်တဲ့ HTTPS Download Link ထည့်ပါ။",
                chat_id
            )
            return

        update_settings({
            "apk_url": apk_url
        })

        send_telegram(
            "✅ APK Download Link ပြောင်းပြီးပါပြီ။\n\n"
            + update_status_text(),
            chat_id
        )

    # VERSION ONLY
    elif text == "/version" or text.startswith("/version "):
        parts = text.split()

        if len(parts) != 3:
            send_telegram(
                "အသုံးပြုပုံ:\n\n"
                "/version 1.2.0 1.2.0\n\n"
                "ပထမ Version = Latest Version\n"
                "ဒုတိယ Version = Minimum Version",
                chat_id
            )
            return

        latest_version = parts[1]
        minimum_version = parts[2]

        import re

        version_pattern = r"\d+(?:\.\d+)*"

        if not re.fullmatch(version_pattern, latest_version):
            send_telegram("❌ Latest Version ပုံစံ မမှန်ပါ။", chat_id)
            return

        if not re.fullmatch(version_pattern, minimum_version):
            send_telegram("❌ Minimum Version ပုံစံ မမှန်ပါ။", chat_id)
            return

        def parse_version(value):
            return tuple(int(part) for part in value.split("."))

        if parse_version(minimum_version) > parse_version(latest_version):
            send_telegram(
                "❌ Minimum Version သည် Latest Version ထက် မကြီးရပါ။",
                chat_id
            )
            return

        update_settings({
            "latest_version": latest_version,
            "minimum_version": minimum_version
        })

        send_telegram(
            "✅ Version ပြောင်းပြီးပါပြီ။\n\n"
            + update_status_text(),
            chat_id
        )

    # ANNOUNCEMENT ONLY
    elif text.startswith("/notice ") or text.startswith("/announce "):
        _, _, notice = text.partition(" ")
        notice = notice.strip()

        if not notice:
            send_telegram(
                "အသုံးပြုပုံ:\n/notice ကြေညာချက်စာသား",
                chat_id
            )
            return

        update_settings({
            "announcement": notice
        })

        send_telegram(
            "✅ ကြေညာချက် သိမ်းဆည်းပြီးပါပြီ။",
            chat_id
        )

    # HELP
    elif text == "/help":
        send_telegram(
            "📘 KMT Bot Commands\n\n"
            "/start - Menu\n"
            "/status - App Lock အခြေအနေ\n"
            "/updatestatus - Update ဆက်တင်များ\n"
            "/updatemsg စာသား - Update စာသားပြောင်းရန်\n"
            "/apk HTTPS_LINK - APK Link ပြောင်းရန်\n"
            "/version LATEST MINIMUM - Version ပြောင်းရန်\n"
            "/notice စာသား - ကြေညာချက်ပြောင်းရန်",
            chat_id
        )
    # Full update configuration:
    # /update <latest> <minimum> <apk_url> <message>
    elif text == "/update" or text.startswith("/update "):
        parts = text.split(maxsplit=3)

        if len(parts) < 4:
            send_telegram(
                "အသုံးပြုပုံ:\n"
                "/update 1.2.0 1.2.0 https://example.com/app.apk App ဗားရှင်းအသစ် ထွက်ပါပြီ။ Update လုပ်ပေးပါ။\n\n"
                "1. ပထမ Version = Latest Version\n"
                "2. ဒုတိယ Version = Minimum Version\n"
                "3. တတိယ = HTTPS APK Link\n"
                "4. ကျန်စာသားအားလုံး = Update Message\n\n"
                "မဖြစ်မနေ Update လုပ်စေလိုပါက Minimum Version ကို Latest Version နဲ့ တူအောင်ထားပါ။",
                chat_id
            )
            return

        values = parts[1].split(maxsplit=2)

        # split(maxsplit=3) keeps the whole message in parts[3].
        latest_version = parts[1]
        minimum_version = parts[2]
        apk_url = parts[3].split(maxsplit=1)[0] if len(parts) >= 4 else ""
        update_message = (
            parts[3].split(maxsplit=1)[1].strip()
            if len(parts) >= 4 and len(parts[3].split(maxsplit=1)) > 1
            else ""
        )

        if not valid_version(latest_version):
            send_telegram("❌ Latest Version ပုံစံ မမှန်ပါ။ ဥပမာ 1.2.0", chat_id)
            return

        if not valid_version(minimum_version):
            send_telegram("❌ Minimum Version ပုံစံ မမှန်ပါ။ ဥပမာ 1.2.0", chat_id)
            return

        if version_tuple(minimum_version) > version_tuple(latest_version):
            send_telegram("❌ Minimum Version သည် Latest Version ထက် မကြီးရပါ။", chat_id)
            return

        if not is_valid_apk_url(apk_url):
            send_telegram("❌ APK Link မှန်ကန်သော HTTPS Link ဖြစ်ရပါမည်။", chat_id)
            return

        if not update_message:
            send_telegram("❌ Update စာသား ထည့်ပေးပါ။", chat_id)
            return

        update_settings({
            "latest_version": latest_version,
            "minimum_version": minimum_version,
            "apk_url": apk_url,
            "update_message": update_message
        })

        send_telegram(
            "✅ Update ဆက်တင်အားလုံး သိမ်းဆည်းပြီးပါပြီ။\n\n"
            + status_text(),
            chat_id
        )

    # Change only the update message.
    elif text == "/updatemsg" or text.startswith("/updatemsg "):
        message_text = text[len("/updatemsg"):].strip()

        if not message_text:
            send_telegram(
                "အသုံးပြုပုံ:\n/updatemsg ကိုကြိုက်တဲ့ Update စာသား",
                chat_id
            )
            return

        update_settings({"update_message": message_text})

        send_telegram(
            "✅ Update စာသား ပြောင်းပြီးပါပြီ။\n\n"
            + status_text(),
            chat_id
        )

    # Change only APK URL.
    elif text.startswith("/apk "):
        url = text[len("/apk "):].strip()

        if not is_valid_apk_url(url):
            send_telegram(
                "❌ HTTPS APK Link ထည့်ပါ။\n"
                "ဥပမာ: /apk https://example.com/app.apk",
                chat_id
            )
            return

        update_settings({"apk_url": url})

        send_telegram(
            "✅ APK Link ပြောင်းပြီးပါပြီ။\n\n" + status_text(),
            chat_id
        )

    # Change versions without changing message.
    elif text.startswith("/version"):
        parts = text.split()

        if len(parts) not in (3, 4):
            send_telegram(
                "အသုံးပြုပုံ:\n"
                "/version 1.2.0 1.2.0\n"
                "/version 1.2.0 1.2.0 https://example.com/app.apk",
                chat_id
            )
            return

        latest_version = parts[1]
        minimum_version = parts[2]

        if not valid_version(latest_version) or not valid_version(minimum_version):
            send_telegram("❌ Version ပုံစံ မမှန်ပါ။", chat_id)
            return

        if version_tuple(minimum_version) > version_tuple(latest_version):
            send_telegram("❌ Minimum Version သည် Latest Version ထက် မကြီးရပါ။", chat_id)
            return

        changes = {
            "latest_version": latest_version,
            "minimum_version": minimum_version
        }

        if len(parts) == 4:
            if not is_valid_apk_url(parts[3]):
                send_telegram("❌ HTTPS APK Link ထည့်ပါ။", chat_id)
                return

            changes["apk_url"] = parts[3]

        update_settings(changes)

        send_telegram(
            "✅ Version ဆက်တင် ပြောင်းပြီးပါပြီ။\n\n"
            + status_text(),
            chat_id
        )

    elif text == "/help":
        send_telegram(
            "📘 KMT Update Commands\n\n"
            "/start - Menu ဖွင့်ရန်\n"
            "/status - လက်ရှိအခြေအနေ\n"
            "/update - Version၊ APK Link၊ စာသားအားလုံးပြောင်းရန်\n"
            "/updatemsg စာသား - Update စာသားပြောင်းရန်\n"
            "/apk HTTPS_LINK - APK Link ပြောင်းရန်\n"
            "/version LATEST MINIMUM - Version ပြောင်းရန်\n"
            "/notice စာသား - ကြေညာချက်ပြောင်းရန်",
            chat_id
        )


# -------------------------
# TELEGRAM BUTTON CALLBACKS
# -------------------------

def process_callback(callback):
    chat_id = callback.get("message", {}).get(
        "chat", {}
    ).get("id")

    data = callback.get("data", "")
    callback_id = callback.get("id", "")

    if not is_admin(chat_id):
        answer_callback(callback_id, "ခွင့်ပြုချက်မရှိပါ။")
        return

    changes = {
        "lock": {"app_locked": True},
        "unlock": {"app_locked": False},
        "maintenance_on": {"maintenance_mode": True},
        "maintenance_off": {"maintenance_mode": False}
    }

    messages = {
        "lock": "🔒 App ကို ပိတ်လိုက်ပါပြီ။",
        "unlock": "🔓 App ကို ဖွင့်လိုက်ပါပြီ။",
        "maintenance_on": "🛠 Maintenance Mode ကို ဖွင့်လိုက်ပါပြီ။",
        "maintenance_off": "✅ Maintenance Mode ကို ပိတ်လိုက်ပါပြီ။"
    }

    if data in changes:
        update_settings(changes[data])

        send_telegram(
            messages[data] + "\n\n" + status_text(),
            chat_id
        )

        answer_callback(callback_id, "✅ ဆက်တင် ပြောင်းပြီးပါပြီ။")

    elif data in ("status", "update_status"):
        send_telegram(status_text(), chat_id)

        answer_callback(callback_id, "📊 အချက်အလက် ပြသပြီးပါပြီ။")

    else:
        answer_callback(callback_id, "မသိရှိသော ခလုတ်ဖြစ်ပါသည်။")


# -------------------------
# TELEGRAM LONG POLLING
# -------------------------

def telegram_polling():
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN မသတ်မှတ်ရသေးပါ။")
        return

    offset = None

    while True:
        try:
            params = {"timeout": 25}

            if offset is not None:
                params["offset"] = offset

            response = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params=params,
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
