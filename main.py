import os
import json
import re
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict


# ==========================================
# KMT ALL SOFTWARE CONTROL (WEBHOOK VERSION)
# ==========================================

app = FastAPI(title="KMT All Software Control")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()

DATA_FILE = os.getenv("DATA_FILE", "data.json")

DATA_LOCK = threading.RLock()
PENDING_LOCK = threading.RLock()

PENDING_UPDATE = {}


# ==========================================
# DEFAULT SETTINGS
# ==========================================

DEFAULT_SETTINGS = {
    "app_locked": False,
    "maintenance_mode": False,
    "maintenance_message": "လက်ရှိတွင် App ကို ပြုပြင်ထိန်းသိမ်းနေပါသည်။",
    "update_enabled": False,
    "latest_version": "1.0",
    "apk_url": "",
    "update_message": "App ဗားရှင်းအသစ် ထွက်ရှိလာပါပြီ။ ဆက်လက်အသုံးပြုရန် Update လုပ်ပေးပါ။",
    "announcement": "",
    "updated_at": ""
}


# ==========================================
# TIME FUNCTION
# ==========================================

def current_time():
    return datetime.now(timezone.utc).isoformat()


# ==========================================
# VERSION FUNCTIONS
# ==========================================

def valid_version(version):
    if not isinstance(version, str):
        return False
    return bool(re.fullmatch(r"\d+(?:\.\d+)*", version.strip()))


def version_tuple(version):
    return tuple(int(part) for part in version.strip().split("."))


def compare_versions(version_a, version_b):
    a = list(version_tuple(version_a))
    b = list(version_tuple(version_b))
    length = max(len(a), len(b))
    a.extend([0] * (length - len(a)))
    b.extend([0] * (length - len(b)))
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


# ==========================================
# APK URL VALIDATION
# ==========================================

def is_valid_apk_url(url):
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not url:
        return True
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and bool(parsed.netloc)
            and not parsed.username
            and not parsed.password
        )
    except Exception:
        return False


# ==========================================
# DATA STORAGE
# ==========================================

def load_settings():
    with DATA_LOCK:
        settings = DEFAULT_SETTINGS.copy()
        if os.path.isfile(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as file:
                    saved = json.load(file)
                if isinstance(saved, dict):
                    saved.pop("minimum_version", None)
                    saved.pop("fb_download_enabled", None)
                    for key in DEFAULT_SETTINGS:
                        if key in saved:
                            settings[key] = saved[key]
            except Exception as error:
                print("Load settings error:", error)

        if not valid_version(settings.get("latest_version")):
            settings["latest_version"] = DEFAULT_SETTINGS["latest_version"]
        if not isinstance(settings.get("apk_url"), str):
            settings["apk_url"] = ""
        if not isinstance(settings.get("update_enabled"), bool):
            settings["update_enabled"] = False
        return settings


def save_settings(settings):
    with DATA_LOCK:
        clean_settings = {}
        for key, default_value in DEFAULT_SETTINGS.items():
            clean_settings[key] = settings.get(key, default_value)
        clean_settings["updated_at"] = settings.get("updated_at") or current_time()

        directory = os.path.dirname(os.path.abspath(DATA_FILE))
        os.makedirs(directory, exist_ok=True)
        temporary_file = DATA_FILE + ".tmp"

        with open(temporary_file, "w", encoding="utf-8") as file:
            json.dump(clean_settings, file, ensure_ascii=False, indent=4)
        os.replace(temporary_file, DATA_FILE)


def update_settings(changes):
    with DATA_LOCK:
        settings = load_settings()
        for key, value in changes.items():
            if key in DEFAULT_SETTINGS:
                settings[key] = value
        settings["updated_at"] = current_time()
        save_settings(settings)
        return load_settings()


# ==========================================
# TELEGRAM FUNCTIONS
# ==========================================

def telegram_request(method, payload, timeout=20):
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN မရှိပါ။")
        return None

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            print("Telegram API error:", result)
        return result
    except Exception as error:
        print("Telegram request error:", error)
        return None


def send_telegram(text, keyboard=None):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        print("Telegram configuration မပြည့်စုံပါ။")
        return None

    payload = {
        "chat_id": ADMIN_CHAT_ID,
        "text": str(text)[:4000]
    }
    if keyboard is not None:
        payload["reply_markup"] = {
            "inline_keyboard": keyboard
        }
    return telegram_request("sendMessage", payload)


def answer_callback(callback_id, text=""):
    if not callback_id:
        return
    telegram_request(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": str(text)[:180]
        },
        timeout=10
    )


def is_admin(chat_id):
    return bool(ADMIN_CHAT_ID) and str(chat_id) == str(ADMIN_CHAT_ID)


# ==========================================
# MAIN MENU
# ==========================================

def telegram_keyboard():
    return [
        [{"text": "📊 အခြေအနေ", "callback_data": "status"}],
        [{"text": "🔓 App Unlock", "callback_data": "unlock"}, {"text": "🔒 App Lock", "callback_data": "lock"}],
        [{"text": "🟢 Maintenance ဖွင့်", "callback_data": "maintenance_on"}, {"text": "🔴 Maintenance ပိတ်", "callback_data": "maintenance_off"}],
        [{"text": "🆕 Update Settings", "callback_data": "update_menu"}]
    ]


# ==========================================
# UPDATE MENU
# ==========================================

def update_keyboard():
    settings = load_settings()
    toggle_button = {
        "text": "🔴 Update ပိတ်ရန်" if settings["update_enabled"] else "🟢 Update ဖွင့်ရန်",
        "callback_data": "update_off" if settings["update_enabled"] else "update_on"
    }
    return [
        [toggle_button],
        [{"text": "🆕 Latest Version", "callback_data": "set_latest"}],
        [{"text": "🔗 APK Download Link", "callback_data": "set_apk"}],
        [{"text": "📝 Update စာသား", "callback_data": "set_update_message"}],
        [{"text": "📢 Announcement", "callback_data": "set_announcement"}],
        [{"text": "📊 Update အခြေအနေ", "callback_data": "update_status"}],
        [{"text": "↩️ Main Menu", "callback_data": "main_menu"}]
    ]


# ==========================================
# STATUS TEXT
# ==========================================

def status_text():
    settings = load_settings()
    lock_status = "🔒 LOCKED" if settings["app_locked"] else "🔓 UNLOCKED"
    maintenance_status = "🟢 ON" if settings["maintenance_mode"] else "🔴 OFF"
    update_status = "🟢 ON" if settings["update_enabled"] else "🔴 OFF"

    return (
        "📊 KMT ALL SOFTWARE CONTROL\n\n"
        f"App Lock: {lock_status}\n"
        f"Maintenance: {maintenance_status}\n"
        f"Update: {update_status}\n\n"
        f"Latest Version: {settings['latest_version']}\n\n"
        f"Updated At: {settings['updated_at'] or 'မရှိသေးပါ'}"
    )


def update_status_text():
    settings = load_settings()
    enabled = "🟢 ဖွင့်ထားသည်" if settings["update_enabled"] else "🔴 ပိတ်ထားသည်"
    apk_url = settings["apk_url"] or "မသတ်မှတ်ရသေးပါ"
    announcement = settings["announcement"] or "မရှိပါ"

    return (
        "🆕 UPDATE SETTINGS\n\n"
        f"Update အခြေအနေ: {enabled}\n\n"
        f"Latest Version: {settings['latest_version']}\n\n"
        f"APK Link:\n{apk_url}\n\n"
        f"Update စာသား:\n{settings['update_message']}\n\n"
        f"Announcement:\n{announcement}\n\n"
        f"နောက်ဆုံးပြင်ဆင်ချိန်:\n{settings['updated_at'] or 'မရှိသေးပါ'}"
    )


# ==========================================
# PENDING INPUT
# ==========================================

def ask_update_input(chat_id, action, message):
    with PENDING_LOCK:
        PENDING_UPDATE[str(chat_id)] = action
    send_telegram(message + "\n\nပယ်ဖျက်လိုပါက /cancel ရိုက်ပါ။")


def process_pending_update(chat_id, text):
    key = str(chat_id)
    with PENDING_LOCK:
        action = PENDING_UPDATE.get(key)

    if not action:
        return False

    text = text.strip()

    if text.lower() == "/cancel":
        with PENDING_LOCK:
            PENDING_UPDATE.pop(key, None)
        send_telegram("❌ လုပ်ဆောင်ချက်ကို ပယ်ဖျက်ပြီးပါပြီ။", update_keyboard())
        return True

    if action == "set_latest":
        if not valid_version(text):
            send_telegram("❌ Version ပုံစံမမှန်ပါ။\n\nဥပမာ: 1.1\nဥပမာ: 1.2.0")
            return True
        update_settings({"latest_version": text})
        result = f"✅ Latest Version ကို {text} သို့ ပြောင်းပြီးပါပြီ။\n\n" + update_status_text()

    elif action == "set_apk":
        if not text or not is_valid_apk_url(text):
            send_telegram("❌ HTTPS Download Link အမှန် ထည့်ပါ။\n\nဥပမာ:\nhttps://example.com/app.apk")
            return True
        update_settings({"apk_url": text})
        result = "✅ APK Download Link သိမ်းပြီးပါပြီ။\n\n" + update_status_text()

    elif action == "set_update_message":
        if len(text) > 3500:
            send_telegram("❌ Update စာသားရှည်လွန်းနေပါတယ်။")
            return True
        update_settings({"update_message": text})
        result = "✅ Update စာသား သိမ်းပြီးပါပြီ။\n\n" + update_status_text()

    elif action == "set_announcement":
        if len(text) > 3500:
            send_telegram("❌ Announcement ရှည်လွန်းနေပါတယ်။")
            return True
        update_settings({"announcement": text})
        result = "✅ Announcement သိမ်းပြီးပါပြီ።\n\n" + update_status_text()

    else:
        with PENDING_LOCK:
            PENDING_UPDATE.pop(key, None)
        return False

    with PENDING_LOCK:
        PENDING_UPDATE.pop(key, None)

    send_telegram(result, update_keyboard())
    return True


# ==========================================
# PUBLIC API
# ==========================================

@app.get("/")
def home():
    return {
        "app": "KMT All Software Control",
        "status": "online"
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "time": current_time()
    }


@app.get("/config")
def get_config(version: str = "1.0"):
    if not valid_version(version):
        raise HTTPException(status_code=400, detail="Invalid version format")

    settings = load_settings()
    current_version = version.strip()
    latest_version = settings["latest_version"]
    update_enabled = bool(settings["update_enabled"])
    apk_ready = bool(settings["apk_url"]) and is_valid_apk_url(settings["apk_url"])

    update_available = (
        update_enabled
        and apk_ready
        and compare_versions(current_version, latest_version) < 0
    )
    force_update = update_available

    return {
        "app_locked": settings["app_locked"],
        "maintenance_mode": settings["maintenance_mode"],
        "maintenance_message": settings["maintenance_message"],
        "update_enabled": update_enabled,
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": update_available,
        "force_update": force_update,
        "apk_url": settings["apk_url"],
        "update_message": settings["update_message"],
        "announcement": settings["announcement"],
        "updated_at": settings["updated_at"]
    }


# ==========================================
# ADMIN API MODEL
# ==========================================

class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    app_locked: bool | None = None
    maintenance_mode: bool | None = None
    maintenance_message: str | None = None
    update_enabled: bool | None = None
    latest_version: str | None = None
    apk_url: str | None = None
    update_message: str | None = None
    announcement: str | None = None


# ==========================================
# ADMIN AUTHENTICATION
# ==========================================

def require_admin(x_admin_key):
    if not ADMIN_API_KEY or x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/admin/status")
def admin_status(x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    return load_settings()


@app.post("/admin/settings")
def admin_settings(body: SettingsUpdate, x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    changes = body.model_dump(exclude_unset=True)

    if "latest_version" in changes and changes["latest_version"] is not None and not valid_version(changes["latest_version"]):
        raise HTTPException(status_code=400, detail="Invalid latest_version")

    if "apk_url" in changes and changes["apk_url"] is not None and not is_valid_apk_url(changes["apk_url"]):
        raise HTTPException(status_code=400, detail="APK URL must use HTTPS")

    for field in ("maintenance_message", "update_message", "announcement"):
        value = changes.get(field)
        if value is not None and len(value) > 3500:
            raise HTTPException(status_code=400, detail=f"{field} is too long")

    return {
        "ok": True,
        "settings": update_settings(changes)
    }


# ==========================================
# TELEGRAM MESSAGE & CALLBACK HANDLERS
# ==========================================

def process_message(message):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text", "").strip()

    if chat_id is None or not text or not is_admin(chat_id):
        return

    if process_pending_update(chat_id, text):
        return

    command = text.split()[0].lower()

    if command in ("/start", "/menu"):
        send_telegram("👋 KMT All Software Control\n\nလုပ်ဆောင်ချက်ကို ရွေးချယ်ပါ။", telegram_keyboard())
    elif command == "/status":
        send_telegram(status_text(), telegram_keyboard())
    elif command in ("/update", "/updatemenu", "/updatestatus"):
        send_telegram(update_status_text(), update_keyboard())
    elif command == "/version":
        ask_update_input(chat_id, "set_latest", "🆕 Latest Version ထည့်ပါ။\nဥပမာ: 1.1")
    elif command == "/apk":
        ask_update_input(chat_id, "set_apk", "🔗 HTTPS APK Download Link ထည့်ပါ။")
    elif command == "/updatemsg":
        ask_update_input(chat_id, "set_update_message", "📝 Update Message အသစ် ထည့်ပါ။")
    elif command == "/notice":
        ask_update_input(chat_id, "set_announcement", "📢 Announcement အသစ် ထည့်ပါ။")
    elif command == "/cancel":
        with PENDING_LOCK:
            PENDING_UPDATE.pop(str(chat_id), None)
        send_telegram("❌ ပယ်ဖျက်ပြီးပါပြီ။", telegram_keyboard())
    elif command == "/help":
        send_telegram(
            "📖 COMMANDS\n\n/start - Main Menu\n/menu - Main Menu\n/status - App Status\n/update - Update Menu\n/version - Set Latest Version\n/apk - Set APK Link\n/updatemsg - Set Update Message\n/notice - Set Announcement\n/cancel - Cancel Input",
            telegram_keyboard()
        )
    else:
        send_telegram("မသိသော Command ဖြစ်ပါတယ်။\n/start ကို အသုံးပြုပါ။", telegram_keyboard())


def process_callback(callback):
    callback_id = callback.get("id")
    data = callback.get("data", "")
    message = callback.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if chat_id is None or not is_admin(chat_id):
        answer_callback(callback_id, "ခွင့်ပြုချက်မရှိပါ။")
        return

    answer_callback(callback_id, "လုပ်ဆောင်နေပါသည်...")

    if data == "main_menu":
        with PENDING_LOCK:
            PENDING_UPDATE.pop(str(chat_id), None)
        send_telegram("🏠 Main Menu", telegram_keyboard())
    elif data == "status":
        send_telegram(status_text(), telegram_keyboard())
    elif data == "lock":
        update_settings({"app_locked": True})
        send_telegram("🔒 App ကို Lock လုပ်ပြီးပါပြီ။", telegram_keyboard())
    elif data == "unlock":
        update_settings({"app_locked": False})
        send_telegram("🔓 App ကို Unlock လုပ်ပြီးပါပြီ။", telegram_keyboard())
    elif data == "maintenance_on":
        update_settings({"maintenance_mode": True})
        send_telegram("🛠 Maintenance ဖွင့်ပြီးပါပြီ။", telegram_keyboard())
    elif data == "maintenance_off":
        update_settings({"maintenance_mode": False})
        send_telegram("✅ Maintenance ပိတ်ပြီးပါပြီ။", telegram_keyboard())
    elif data == "update_menu":
        with PENDING_LOCK:
            PENDING_UPDATE.pop(str(chat_id), None)
        send_telegram(update_status_text(), update_keyboard())
    elif data == "update_on":
        update_settings({"update_enabled": True})
        send_telegram("🟢 Update ဖွင့်ပြီးပါပြီ።\n\n" + update_status_text(), update_keyboard())
    elif data == "update_off":
        update_settings({"update_enabled": False})
        send_telegram("🔴 Update ပိတ်ပြီးပါပြီ။\n\n" + update_status_text(), update_keyboard())
    elif data == "set_latest":
        ask_update_input(chat_id, "set_latest", "🆕 Latest Version ထည့်ပါ။\nဥပမာ: 1.1")
    elif data == "set_apk":
        ask_update_input(chat_id, "set_apk", "🔗 HTTPS APK Download Link ထည့်ပါ။")
    elif data == "set_update_message":
        ask_update_input(chat_id, "set_update_message", "📝 Update Message အသစ် ထည့်ပါ။")
    elif data == "set_announcement":
        ask_update_input(chat_id, "set_announcement", "📢 Announcement အသစ် ထည့်ပါ။")
    elif data == "update_status":
        send_telegram(update_status_text(), update_keyboard())


# ==========================================
# TELEGRAM WEBHOOK ENDPOINT
# ==========================================

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        if "message" in data:
            process_message(data["message"])
        elif "callback_query" in data:
            process_callback(data["callback_query"])
    except Exception as error:
        print("Webhook error:", error)
    return {"ok": True}


# ==========================================
# STARTUP
# ==========================================

@app.on_event("startup")
def startup_event():
    settings = load_settings()
    save_settings(settings)
    print("KMT All Software Control Started with Webhook Support.")
