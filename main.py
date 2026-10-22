import os
import json
import re
import time
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict


# ==========================================
# KMT ALL SOFTWARE CONTROL
# ==========================================

app = FastAPI(title="KMT All Software Control")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

DATA_FILE = os.getenv("DATA_FILE", "data.json")

DATA_LOCK = threading.RLock()
POLLING_LOCK = threading.Lock()

PENDING_UPDATE = {}
PENDING_LOCK = threading.Lock()


# ==========================================
# DEFAULT SETTINGS
# ==========================================

DEFAULT_SETTINGS = {
    "app_locked": True,

    "maintenance_mode": False,

    "maintenance_message":
        "လက်ရှိတွင် App ကို ပြုပြင်ထိန်းသိမ်းနေပါသည်။",

    "update_enabled": False,

    "latest_version": "1.1.0",

    "minimum_version": "1.1.0",

    "apk_url": "",

    "update_message":
        "App ဗားရှင်းအသစ် ထွက်ရှိလာပါပြီ။ "
        "ဆက်လက်အသုံးပြုရန် Update လုပ်ပေးပါ။",

    "announcement": "",

    "updated_at": ""
}


# ==========================================
# VERSION FUNCTIONS
# ==========================================

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


def compare_versions(version_a, version_b):
    """
    1.2 နှင့် 1.2.0 ကို Version တူညီသည်ဟု သတ်မှတ်သည်။
    """

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

        if os.path.exists(DATA_FILE):

            try:
                with open(
                    DATA_FILE,
                    "r",
                    encoding="utf-8"
                ) as file:

                    saved = json.load(file)

                if isinstance(saved, dict):

                    settings.update(saved)

            except Exception as error:

                print(
                    "Load settings error:",
                    error
                )

        settings.pop("fb_download_enabled", None)

        return settings


def save_settings(settings):
    with DATA_LOCK:

        directory = os.path.dirname(
            os.path.abspath(DATA_FILE)
        )

        os.makedirs(
            directory,
            exist_ok=True
        )

        temporary_file = DATA_FILE + ".tmp"

        with open(
            temporary_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                settings,
                file,
                ensure_ascii=False,
                indent=4
            )

        os.replace(
            temporary_file,
            DATA_FILE
        )


def update_settings(changes):
    with DATA_LOCK:

        settings = load_settings()

        settings.update(changes)

        settings["updated_at"] = (
            datetime.now(timezone.utc)
            .isoformat()
        )

        save_settings(settings)

        return settings


# ==========================================
# TELEGRAM FUNCTIONS
# ==========================================

def send_telegram(text, keyboard=None):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        print("Telegram configuration is missing.")
        return None

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": ADMIN_CHAT_ID,
        "text": text
    }

    if keyboard is not None:

        payload["reply_markup"] = {
            "inline_keyboard": keyboard
        }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=20
        )

        response.raise_for_status()

        result = response.json()

        if not result.get("ok"):
            print("Telegram API error:", result)

        return result

    except Exception as error:

        print(
            "Telegram send error:",
            error
        )

        return None


def answer_callback(callback_id, text=""):
    if not BOT_TOKEN:
        return

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/answerCallbackQuery"
    )

    try:

        requests.post(
            url,
            json={
                "callback_query_id": callback_id,
                "text": text
            },
            timeout=10
        )

    except Exception as error:

        print(
            "Callback error:",
            error
        )


def is_admin(chat_id):
    return (
        ADMIN_CHAT_ID != ""
        and str(chat_id) == str(ADMIN_CHAT_ID)
    )


# ==========================================
# MAIN MENU
# ==========================================

def telegram_keyboard():

    return [

        [
            {
                "text": "📊 အခြေအနေ",
                "callback_data": "status"
            }
        ],

        [
            {
                "text": "🔓 App Unlock",
                "callback_data": "unlock"
            },
            {
                "text": "🔒 App Lock",
                "callback_data": "lock"
            }
        ],

        [
            {
                "text": "🟢 Maintenance ဖွင့်",
                "callback_data": "maintenance_on"
            },
            {
                "text": "🔴 Maintenance ပိတ်",
                "callback_data": "maintenance_off"
            }
        ],

        [
            {
                "text": "🆕 Update Settings",
                "callback_data": "update_menu"
            }
        ]

    ]


# ==========================================
# UPDATE MENU
# ==========================================

def update_keyboard():

    settings = load_settings()

    if settings.get("update_enabled", False):

        toggle_buttons = [
            {
                "text": "🔴 Update ပိတ်ရန်",
                "callback_data": "update_off"
            }
        ]

    else:

        toggle_buttons = [
            {
                "text": "🟢 Update ဖွင့်ရန်",
                "callback_data": "update_on"
            }
        ]

    return [

        toggle_buttons,

        [
            {
                "text": "🆕 Latest Version",
                "callback_data": "set_latest"
            },
            {
                "text": "🛡 Minimum Version",
                "callback_data": "set_minimum"
            }
        ],

        [
            {
                "text": "🔗 APK Download Link",
                "callback_data": "set_apk"
            }
        ],

        [
            {
                "text": "📝 Update စာသား",
                "callback_data": "set_update_message"
            }
        ],

        [
            {
                "text": "📢 Announcement",
                "callback_data": "set_announcement"
            }
        ],

        [
            {
                "text": "📊 Update အခြေအနေ",
                "callback_data": "update_status"
            }
        ],

        [
            {
                "text": "↩️ Main Menu",
                "callback_data": "main_menu"
            }
        ]

    ]


# ==========================================
# STATUS TEXT
# ==========================================

def status_text():

    settings = load_settings()

    lock_status = (
        "🔒 LOCKED"
        if settings["app_locked"]
        else "🔓 UNLOCKED"
    )

    maintenance_status = (
        "🟢 ON"
        if settings["maintenance_mode"]
        else "🔴 OFF"
    )

    update_status = (
        "🟢 ON"
        if settings["update_enabled"]
        else "🔴 OFF"
    )

    return (
        "📊 KMT ALL SOFTWARE CONTROL\n\n"
        f"App Lock: {lock_status}\n"
        f"Maintenance: {maintenance_status}\n"
        f"Update: {update_status}\n\n"
        f"Latest Version: "
        f"{settings['latest_version']}\n"
        f"Minimum Version: "
        f"{settings['minimum_version']}"
    )


def update_status_text():

    settings = load_settings()

    enabled = (
        "🟢 ဖွင့်ထားသည်"
        if settings["update_enabled"]
        else "🔴 ပိတ်ထားသည်"
    )

    apk_url = settings["apk_url"] or "မသတ်မှတ်ရသေးပါ"

    announcement = (
        settings["announcement"]
        or "မရှိပါ"
    )

    return (
        "🆕 UPDATE SETTINGS\n\n"
        f"Update အခြေအနေ: {enabled}\n\n"
        f"Latest Version: "
        f"{settings['latest_version']}\n"
        f"Minimum Version: "
        f"{settings['minimum_version']}\n\n"
        f"APK Link:\n{apk_url}\n\n"
        f"Update စာသား:\n"
        f"{settings['update_message']}\n\n"
        f"Announcement:\n{announcement}\n\n"
        f"နောက်ဆုံးပြင်ဆင်ချိန်:\n"
        f"{settings['updated_at'] or 'မရှိသေးပါ'}"
    )


# ==========================================
# INPUT VALIDATION
# ==========================================

def validate_version_settings(
    latest_version,
    minimum_version
):

    if not valid_version(latest_version):
        return False

    if not valid_version(minimum_version):
        return False

    return (
        compare_versions(
            minimum_version,
            latest_version
        ) <= 0
    )


# ==========================================
# PENDING UPDATE INPUT
# ==========================================

def ask_update_input(chat_id, action, message):

    with PENDING_LOCK:
        PENDING_UPDATE[str(chat_id)] = action

    send_telegram(
        message
        + "\n\n"
        + "❌ ပယ်ဖျက်လိုပါက /cancel ကိုနှိပ်ပါ။"
    )


def process_pending_update(chat_id, text):

    key = str(chat_id)

    with PENDING_LOCK:

        action = PENDING_UPDATE.get(key)

    if not action:
        return False

    if text.strip() == "/cancel":

        with PENDING_LOCK:
            PENDING_UPDATE.pop(key, None)

        send_telegram(
            "❌ လုပ်ဆောင်ချက်ကို ပယ်ဖျက်လိုက်ပါပြီ။",
            update_keyboard()
        )

        return True

    settings = load_settings()

    text = text.strip()

    if action == "set_latest":

        if not valid_version(text):

            send_telegram(
                "❌ Version မှားနေပါတယ်။\n"
                "ဥပမာ: 1.2.0"
            )

            return True

        if compare_versions(
            text,
            settings["minimum_version"]
        ) < 0:

            send_telegram(
                "❌ Latest Version ဟာ "
                "Minimum Version ထက် မနိမ့်ရပါဘူး။"
            )

            return True

        update_settings({
            "latest_version": text
        })

        result = (
            "✅ Latest Version သိမ်းပြီးပါပြီ။\n\n"
            + update_status_text()
        )

    elif action == "set_minimum":

        if not valid_version(text):

            send_telegram(
                "❌ Version မှားနေပါတယ်။\n"
                "ဥပမာ: 1.1.0"
            )

            return True

        if compare_versions(
            text,
            settings["latest_version"]
        ) > 0:

            send_telegram(
                "❌ Minimum Version ဟာ "
                "Latest Version ထက် မမြင့်ရပါဘူး။"
            )

            return True

        update_settings({
            "minimum_version": text
        })

        result = (
            "✅ Minimum Version သိမ်းပြီးပါပြီ။\n\n"
            + update_status_text()
        )

    elif action == "set_apk":

        if not is_valid_apk_url(text):

            send_telegram(
                "❌ HTTPS Link အမှန် ထည့်ပေးပါ။\n\n"
                "ဥပမာ:\n"
                "https://example.com/app.apk"
            )

            return True

        update_settings({
            "apk_url": text
        })

        result = (
            "✅ APK Download Link သိမ်းပြီးပါပြီ။\n\n"
            + update_status_text()
        )

    elif action == "set_update_message":

        if len(text) > 3500:

            send_telegram(
                "❌ စာသားရှည်လွန်းနေပါတယ်။"
            )

            return True

        update_settings({
            "update_message": text
        })

        result = (
            "✅ Update စာသား သိမ်းပြီးပါပြီ။\n\n"
            + update_status_text()
        )

    elif action == "set_announcement":

        if len(text) > 3500:

            send_telegram(
                "❌ Announcement ရှည်လွန်းနေပါတယ်။"
            )

            return True

        update_settings({
            "announcement": text
        })

        result = (
            "✅ Announcement သိမ်းပြီးပါပြီ။\n\n"
            + update_status_text()
        )

    else:

        with PENDING_LOCK:
            PENDING_UPDATE.pop(key, None)

        return False

    with PENDING_LOCK:
        PENDING_UPDATE.pop(key, None)

    send_telegram(
        result,
        update_keyboard()
    )

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
        "status": "ok"
    }


@app.get("/config")
def get_config(version: str = "1.1.0"):

    settings = load_settings()

    if not valid_version(version):

        raise HTTPException(
            status_code=400,
            detail="Invalid version format"
        )

    current_version = version

    latest_version = settings["latest_version"]

    minimum_version = settings["minimum_version"]

    enabled = bool(
        settings["update_enabled"]
    )

    apk_ready = is_valid_apk_url(
        settings["apk_url"]
    ) and bool(settings["apk_url"])

    update_available = (
        enabled
        and apk_ready
        and compare_versions(
            current_version,
            latest_version
        ) < 0
    )

    force_update = (
        enabled
        and apk_ready
        and compare_versions(
            current_version,
            minimum_version
        ) < 0
    )

    return {

        "app_locked":
            settings["app_locked"],

        "maintenance_mode":
            settings["maintenance_mode"],

        "maintenance_message":
            settings["maintenance_message"],

        "update_enabled":
            enabled,

        "current_version":
            current_version,

        "latest_version":
            latest_version,

        "minimum_version":
            minimum_version,

        "update_available":
            update_available,

        "force_update":
            force_update,

        "apk_url":
            settings["apk_url"],

        "update_message":
            settings["update_message"],

        "announcement":
            settings["announcement"],

        "updated_at":
            settings["updated_at"]

    }


# ==========================================
# ADMIN API
# ==========================================

class SettingsUpdate(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    app_locked: bool | None = None

    maintenance_mode: bool | None = None

    maintenance_message: str | None = None

    update_enabled: bool | None = None

    latest_version: str | None = None

    minimum_version: str | None = None

    apk_url: str | None = None

    update_message: str | None = None

    announcement: str | None = None


def require_admin(x_admin_key):

    if (
        not ADMIN_API_KEY
        or x_admin_key != ADMIN_API_KEY
    ):

        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )


@app.get("/admin/status")
def admin_status(
    x_admin_key: str = Header(default="")
):

    require_admin(x_admin_key)

    return load_settings()


@app.post("/admin/settings")
def admin_settings(
    body: SettingsUpdate,
    x_admin_key: str = Header(default="")
):

    require_admin(x_admin_key)

    changes = body.model_dump(
        exclude_unset=True
    )

    settings = load_settings()

    candidate = settings.copy()

    candidate.update(changes)

    latest = candidate["latest_version"]

    minimum = candidate["minimum_version"]

    if not validate_version_settings(
        latest,
        minimum
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid version settings. "
                "Minimum Version must not exceed "
                "Latest Version."
            )
        )

    if not is_valid_apk_url(
        candidate["apk_url"]
    ):

        raise HTTPException(
            status_code=400,
            detail="APK URL must be a valid HTTPS URL."
        )

    for field in [
        "maintenance_message",
        "update_message",
        "announcement"
    ]:

        value = candidate.get(field)

        if value is not None and len(value) > 3500:

            raise HTTPException(
                status_code=400,
                detail=f"{field} is too long."
            )

    return update_settings(changes)


# ==========================================
# TELEGRAM MESSAGE HANDLER
# ==========================================

def process_message(message):

    chat = message.get("chat", {})

    chat_id = chat.get("id")

    text = message.get("text", "")

    if chat_id is None:
        return

    if not is_admin(chat_id):

        send_telegram(
            "⛔ ခွင့်ပြုချက်မရှိပါ။"
        )

        return

    if not text:
        return

    if process_pending_update(chat_id, text):
        return

    command = text.strip().split()[0].lower()

    if command.startswith("/start") or command.startswith("/menu"):

        send_telegram(
            "👋 KMT All Software Control\n\n"
            "လိုချင်တဲ့ လုပ်ဆောင်ချက်ကို ရွေးချယ်ပါ။",
            telegram_keyboard()
        )

    elif command.startswith("/status"):

        send_telegram(
            status_text(),
            telegram_keyboard()
        )

    elif command.startswith("/updatemenu"):

        send_telegram(
            update_status_text(),
            update_keyboard()
        )

    elif command.startswith("/updatestatus"):

        send_telegram(
            update_status_text(),
            update_keyboard()
        )

    elif command.startswith("/update"):

        send_telegram(
            update_status_text(),
            update_keyboard()
        )

    elif command.startswith("/updatemsg"):

        ask_update_input(
            chat_id,
            "set_update_message",
            "📝 Update စာသားအသစ်ကို ပို့ပေးပါ။"
        )

    elif command.startswith("/apk"):

        ask_update_input(
            chat_id,
            "set_apk",
            "🔗 HTTPS APK Download Link ကို ပို့ပေးပါ။"
        )

    elif command.startswith("/version"):

        ask_update_input(
            chat_id,
            "set_latest",
            "🆕 Latest Version ထည့်ပါ။\n"
            "ဥပမာ: 1.2.0"
        )

    elif command.startswith("/notice"):

        ask_update_input(
            chat_id,
            "set_announcement",
            "📢 Announcement စာသားကို ပို့ပေးပါ။"
        )

    elif command.startswith("/cancel"):

        with PENDING_LOCK:
            PENDING_UPDATE.pop(str(chat_id), None)

        send_telegram(
            "❌ ပယ်ဖျက်ပြီးပါပြီ။",
            telegram_keyboard()
        )

    elif command.startswith("/help"):

        send_telegram(
            "📖 COMMANDS\n\n"
            "/start - Main Menu\n"
            "/menu - Main Menu\n"
            "/status - App Status\n"
            "/update - Update Menu\n"
            "/updatemenu - Update Settings\n"
            "/updatestatus - Update Status\n"
            "/version - Set Latest Version\n"
            "/apk - Set APK Link\n"
            "/updatemsg - Set Update Message\n"
            "/notice - Set Announcement\n"
            "/cancel - Cancel Input",
            telegram_keyboard()
        )

    else:

        send_telegram(
            "မသိသော Command ဖြစ်ပါတယ်။\n"
            "/start ကိုနှိပ်ပါ။",
            telegram_keyboard()
        )


# ==========================================
# TELEGRAM CALLBACK HANDLER
# ==========================================

def process_callback(callback):

    callback_id = callback.get("id")

    data = callback.get("data", "")

    message = callback.get("message", {})

    chat = message.get("chat", {})

    chat_id = chat.get("id")

    if chat_id is None:
        return

    if not is_admin(chat_id):

        answer_callback(
            callback_id,
            "ခွင့်ပြုချက်မရှိပါ။"
        )

        return

    answer_callback(
        callback_id,
        "လုပ်ဆောင်နေပါသည်..."
    )

    if data == "main_menu":

        with PENDING_LOCK:
            PENDING_UPDATE.pop(str(chat_id), None)

        send_telegram(
            "🏠 Main Menu",
            telegram_keyboard()
        )

    elif data == "status":

        send_telegram(
            status_text(),
            telegram_keyboard()
        )

    elif data == "lock":

        update_settings({
            "app_locked": True
        })

        send_telegram(
            "🔒 App ကို Lock လုပ်ပြီးပါပြီ။",
            telegram_keyboard()
        )

    elif data == "unlock":

        update_settings({
            "app_locked": False
        })

        send_telegram(
            "🔓 App ကို Unlock လုပ်ပြီးပါပြီ။",
            telegram_keyboard()
        )

    elif data == "maintenance_on":

        update_settings({
            "maintenance_mode": True
        })

        send_telegram(
            "🛠️ Maintenance ဖွင့်ပြီးပါပြီ။",
            telegram_keyboard()
        )

    elif data == "maintenance_off":

        update_settings({
            "maintenance_mode": False
        })

        send_telegram(
            "✅ Maintenance ပိတ်ပြီးပါပြီ။",
            telegram_keyboard()
        )

    elif data == "update_menu":

        with PENDING_LOCK:
            PENDING_UPDATE.pop(str(chat_id), None)

        send_telegram(
            update_status_text(),
            update_keyboard()
        )

    elif data == "update_on":

        update_settings({
            "update_enabled": True
        })

        send_telegram(
            "🟢 Update ဖွင့်ပြီးပါပြီ။\n\n"
            + update_status_text(),
            update_keyboard()
        )

    elif data == "update_off":

        update_settings({
            "update_enabled": False
        })

        send_telegram(
            "🔴 Update ပိတ်ပြီးပါပြီ။\n\n"
            "Update အသိပေးမှုကို ပိတ်ထားပါတယ်။\n"
            "Version၊ APK Link နဲ့ စာသားတွေကို "
            "မဖျက်ထားပါဘူး။\n\n"
            + update_status_text(),
            update_keyboard()
        )

    elif data == "set_latest":

        ask_update_input(
            chat_id,
            "set_latest",
            "🆕 Latest Version ထည့်ပါ။\n"
            "ဥပမာ: 1.2.0"
        )

    elif data == "set_minimum":

        ask_update_input(
            chat_id,
            "set_minimum",
            "🛡 Minimum Version ထည့်ပါ။\n"
            "ဥပမာ: 1.1.0"
        )

    elif data == "set_apk":

        ask_update_input(
            chat_id,
            "set_apk",
            "🔗 HTTPS APK Download Link ထည့်ပါ။"
        )

    elif data == "set_update_message":

        ask_update_input(
            chat_id,
            "set_update_message",
            "📝 Update စာသားအသစ် ပို့ပေးပါ။"
        )

    elif data == "set_announcement":

        ask_update_input(
            chat_id,
            "set_announcement",
            "📢 Announcement အသစ် ပို့ပေးပါ။"
        )

    elif data == "update_status":

        send_telegram(
            update_status_text(),
            update_keyboard()
        )


# ==========================================
# TELEGRAM POLLING
# ==========================================

def telegram_polling():

    if not BOT_TOKEN:

        print(
            "TELEGRAM_BOT_TOKEN မသတ်မှတ်ရသေးပါ။"
        )

        return

    if not ADMIN_CHAT_ID:

        print(
            "TELEGRAM_ADMIN_CHAT_ID မသတ်မှတ်ရသေးပါ။"
        )

        return

    if not POLLING_LOCK.acquire(blocking=False):

        print(
            "Telegram polling thread already running."
        )

        return

    print("Telegram polling started.")

    offset = None

    try:

        while True:

            try:

                params = {
                    "timeout": 25
                }

                if offset is not None:
                    params["offset"] = offset

                response = requests.get(
                    "https://api.telegram.org/bot"
                    + BOT_TOKEN
                    + "/getUpdates",
                    params=params,
                    timeout=35
                )

                if response.status_code == 409:

                    print(
                        "Telegram 409 Conflict: "
                        "အခြား Instance တစ်ခုက "
                        "Bot Update များကို ဖတ်နေပါသည်။"
                    )

                    time.sleep(10)

                    continue

                response.raise_for_status()

                result = response.json()

                if not result.get("ok"):

                    print(
                        "Telegram polling error:",
                        result
                    )

                    time.sleep(5)

                    continue

                for item in result.get("result", []):

                    offset = item["update_id"] + 1

                    try:

                        if "message" in item:

                            process_message(
                                item["message"]
                            )

                        elif "callback_query" in item:

                            process_callback(
                                item["callback_query"]
                            )

                    except Exception as error:

                        print(
                            "Update processing error:",
                            error
                        )

            except Exception as error:

                print(
                    "Telegram polling error:",
                    error
                )

                time.sleep(5)

    finally:

        POLLING_LOCK.release()


# ==========================================
# STARTUP
# ==========================================

@app.on_event("startup")
def startup_event():

    settings = load_settings()

    save_settings(settings)

    thread = threading.Thread(
        target=telegram_polling,
        daemon=True
    )

    thread.start()
