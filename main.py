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

# Telegram Update input state
PENDING_UPDATE = {}

# Telegram polling protection
POLLING_LOCK = threading.Lock()


# ==================================================
# DEFAULT SETTINGS
# ==================================================

DEFAULT_SETTINGS = {
    "app_locked": True,

    "maintenance_mode": False,

    "maintenance_message": (
        "လက်ရှိတွင် App ကို ပြုပြင်ထိန်းသိမ်းနေပါသည်။"
    ),

    "latest_version": "1.1.0",

    "minimum_version": "1.1.0",

    "apk_url": "",

    "update_message": (
        "App ဗားရှင်းအသစ် ထွက်ရှိလာပါပြီ။ "
        "ဆက်လက်အသုံးပြုရန် Update လုပ်ပေးပါ။"
    ),

    "announcement": "",

    "updated_at": ""
}


# ==================================================
# VERSION VALIDATION
# ==================================================

def valid_version(version):
    if not isinstance(version, str):
        return False

    return bool(
        re.fullmatch(
            r"\d+(?:\.\d+)*",
            version.strip()
        )
    )


def version_tuple(version):
    return tuple(
        int(part)
        for part in version.strip().split(".")
    )


def compare_versions(version_a, version_b):
    """
    Version နှစ်ခုကို မှန်ကန်စွာ နှိုင်းယှဉ်ပေးသည်။

    ဥပမာ:
    1.2 == 1.2.0
    1.3 > 1.2.9
    2.0 > 1.99
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

    try:
        parsed = urlparse(url)

        return (
            parsed.scheme == "https"
            and bool(parsed.netloc)
            and not any(char.isspace() for char in url)
            and bool(parsed.hostname)
        )

    except Exception:
        return False


# ==================================================
# SETTINGS STORAGE
# ==================================================

def load_settings():
    with DATA_LOCK:
        try:
            with open(
                DATA_FILE,
                "r",
                encoding="utf-8"
            ) as file:
                saved = json.load(file)

            if not isinstance(saved, dict):
                saved = {}

            settings = DEFAULT_SETTINGS.copy()
            settings.update(saved)

            # Remove obsolete setting
            settings.pop(
                "fb_download_enabled",
                None
            )

            return settings

        except (
            FileNotFoundError,
            json.JSONDecodeError,
            OSError
        ):
            return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    with DATA_LOCK:
        temp_file = DATA_FILE + ".tmp"

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                settings,
                file,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temp_file,
            DATA_FILE
        )


def update_settings(changes):
    with DATA_LOCK:
        settings = load_settings()

        settings.update(changes)

        settings.pop(
            "fb_download_enabled",
            None
        )

        settings["updated_at"] = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.gmtime()
        )

        save_settings(settings)

        return settings


# ==================================================
# TELEGRAM API
# ==================================================

def send_telegram(
    text,
    chat_id=None,
    reply_markup=None
):
    if not BOT_TOKEN:
        print("Telegram Bot Token မရှိပါ။")
        return False

    target = str(
        chat_id or ADMIN_CHAT_ID
    )

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
            print(
                "Telegram sendMessage error:",
                response.text
            )

        return response.ok

    except requests.RequestException as error:
        print(
            "Telegram send error:",
            error
        )

        return False


def answer_callback(
    callback_id,
    text=""
):
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
        print(
            "Telegram callback error:",
            error
        )


def is_admin(chat_id):
    return (
        bool(ADMIN_CHAT_ID)
        and str(chat_id) == str(ADMIN_CHAT_ID)
    )


# ==================================================
# MAIN MENU KEYBOARD
# ==================================================

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
                }
            ],
            [
                {
                    "text": "🛠 Maintenance ဖွင့်",
                    "callback_data": "maintenance_on"
                },
                {
                    "text": "✅ Maintenance ပိတ်",
                    "callback_data": "maintenance_off"
                }
            ],
            [
                {
                    "text": "🔄 Update Settings",
                    "callback_data": "update_menu"
                }
            ]
        ]
    }


# ==================================================
# UPDATE MENU KEYBOARD
# ==================================================

def update_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "📝 Update စာသား",
                    "callback_data": "upd_msg"
                }
            ],
            [
                {
                    "text": "🔗 APK Download Link",
                    "callback_data": "upd_apk"
                }
            ],
            [
                {
                    "text": "🆕 Latest Version",
                    "callback_data": "upd_latest"
                },
                {
                    "text": "🛡 Minimum Version",
                    "callback_data": "upd_minimum"
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
    }


# ==================================================
# STATUS TEXT
# ==================================================

def status_text():
    settings = load_settings()

    lock_status = (
        "🔒 ပိတ်ဆို့ထားသည်"
        if settings["app_locked"]
        else "🔓 အသုံးပြုခွင့်ရှိသည်"
    )

    maintenance_status = (
        "🛠 ဖွင့်ထားသည်"
        if settings["maintenance_mode"]
        else "✅ ပိတ်ထားသည်"
    )

    return (
        "📊 KMT All Software အခြေအနေ\n\n"
        f"🔒 App Lock: {lock_status}\n"
        f"🛠 Maintenance: {maintenance_status}"
    )


def update_status_text():
    settings = load_settings()

    apk_url = (
        settings["apk_url"]
        if settings["apk_url"]
        else "မသတ်မှတ်ရသေးပါ"
    )

    update_message = settings.get(
        "update_message",
        "မသတ်မှတ်ရသေးပါ"
    )

    return (
        "🔄 KMT UPDATE SETTINGS\n\n"
        f"🆕 Latest Version:\n"
        f"{settings['latest_version']}\n\n"
        f"🛡 Minimum Version:\n"
        f"{settings['minimum_version']}\n\n"
        f"🔗 APK Download Link:\n"
        f"{apk_url}\n\n"
        f"📝 Update စာသား:\n"
        f"{update_message}\n\n"
        f"🕒 နောက်ဆုံးပြင်ဆင်ချိန်:\n"
        f"{settings['updated_at'] or 'မရှိသေးပါ'}"
    )


def update_menu_text():
    return (
        "🔄 KMT UPDATE SETTINGS\n\n"
        "ပြင်ဆင်လိုတဲ့အချက်ကို ရွေးချယ်ပါ။\n\n"
        "📝 Update စာသား\n"
        "🔗 APK Download Link\n"
        "🆕 Latest Version\n"
        "🛡 Minimum Version"
    )


# ==================================================
# UPDATE INPUT SYSTEM
# ==================================================

def ask_update_input(
    chat_id,
    action,
    prompt
):
    PENDING_UPDATE[str(chat_id)] = action

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "❌ မလုပ်တော့ပါ",
                    "callback_data": "cancel_input"
                }
            ],
            [
                {
                    "text": "↩️ Update Menu",
                    "callback_data": "update_menu"
                }
            ]
        ]
    }

    send_telegram(
        prompt,
        chat_id,
        keyboard
    )


def process_pending_update(
    chat_id,
    text
):
    key = str(chat_id)

    action = PENDING_UPDATE.get(key)

    if not action:
        return False

    if text == "/cancel":
        PENDING_UPDATE.pop(key, None)

        send_telegram(
            "❌ ပြင်ဆင်မှုကို ပယ်ဖျက်လိုက်ပါပြီ။",
            chat_id,
            update_keyboard()
        )

        return True

    # Allow bot commands while waiting for input
    if text.startswith("/"):
        return False

    value = text.strip()

    if not value:
        send_telegram(
            "❌ အချက်အလက်အလွတ် မထည့်ပါနဲ့။",
            chat_id
        )

        return True

    changes = {}

    # UPDATE MESSAGE
    if action == "update_message":
        changes["update_message"] = value

    # APK URL
    elif action == "apk_url":
        if not is_valid_apk_url(value):
            send_telegram(
                "❌ APK Link မမှန်ပါ။\n\n"
                "HTTPS Link ဖြစ်ရပါမယ်။\n\n"
                "ဥပမာ:\n"
                "https://example.com/app.apk",
                chat_id
            )

            return True

        changes["apk_url"] = value

    # VERSION INPUT
    elif action in (
        "latest_version",
        "minimum_version"
    ):
        if not valid_version(value):
            send_telegram(
                "❌ Version ပုံစံ မမှန်ပါ။\n\n"
                "ဥပမာ: 1.2.0",
                chat_id
            )

            return True

        settings = load_settings()

        latest = (
            value
            if action == "latest_version"
            else settings["latest_version"]
        )

        minimum = (
            value
            if action == "minimum_version"
            else settings["minimum_version"]
        )

        if compare_versions(minimum, latest) > 0:
            send_telegram(
                "❌ Minimum Version သည် Latest Version "
                "ထက် မကြီးရပါ။\n\n"
                f"Latest Version: {latest}\n"
                f"Minimum Version: {minimum}",
                chat_id
            )

            return True

        changes[action] = value

    else:
        PENDING_UPDATE.pop(key, None)
        return False

    try:
        update_settings(changes)

    except Exception as error:
        print(
            "Update settings save error:",
            error
        )

        send_telegram(
            "❌ သိမ်းဆည်းရာမှာ ပြဿနာဖြစ်သွားပါတယ်။ "
            "နောက်တစ်ကြိမ် ပြန်ကြိုးစားပါ။",
            chat_id
        )

        return True

    PENDING_UPDATE.pop(key, None)

    send_telegram(
        "✅ Update ဆက်တင် ပြောင်းလဲပြီးပါပြီ။\n\n"
        + update_status_text(),
        chat_id,
        update_keyboard()
    )

    return True


# ==================================================
# PUBLIC API
# ==================================================

@app.get("/")
def home():
    return {
        "message": (
            "KMT All Software Control API "
            "အလုပ်လုပ်နေပါသည်။"
        ),
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
def public_config(
    version: str = "1.1.0"
):
    settings = load_settings()

    if not valid_version(version):
        raise HTTPException(
            status_code=400,
            detail="Version ပုံစံ မမှန်ပါ။"
        )

    latest = settings["latest_version"]
    minimum = settings["minimum_version"]

    if not valid_version(latest):
        raise HTTPException(
            status_code=500,
            detail="Server latest_version မမှန်ပါ။"
        )

    if not valid_version(minimum):
        raise HTTPException(
            status_code=500,
            detail="Server minimum_version မမှန်ပါ။"
        )

    return {
        "app_locked": settings["app_locked"],

        "maintenance_mode": settings["maintenance_mode"],

        "maintenance_message": settings[
            "maintenance_message"
        ],

        "current_version": version,

        "latest_version": latest,

        "minimum_version": minimum,

        "update_available": (
            compare_versions(version, latest) < 0
        ),

        "force_update": (
            compare_versions(version, minimum) < 0
        ),

        "apk_url": settings["apk_url"],

        "update_message": settings["update_message"],

        "announcement": settings["announcement"],

        "updated_at": settings["updated_at"]
    }


# ==================================================
# ADMIN SETTINGS API
# ==================================================

class SettingsUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    app_locked: bool | None = None

    maintenance_mode: bool | None = None

    maintenance_message: str | None = None

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
            detail="ခွင့်ပြုချက်မရှိပါ။"
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
        exclude_none=True
    )

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

    if compare_versions(
        new_minimum,
        new_latest
    ) > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "minimum_version သည် latest_version "
                "ထက် မကြီးရပါ။"
            )
        )

    if "apk_url" in changes:
        if (
            changes["apk_url"]
            and not is_valid_apk_url(changes["apk_url"])
        ):
            raise HTTPException(
                status_code=400,
                detail="APK Link သည် HTTPS URL ဖြစ်ရပါမည်။"
            )

    return update_settings(changes)


# ==================================================
# TELEGRAM MESSAGE COMMANDS
# ==================================================

def process_message(message):
    chat_id = message.get(
        "chat",
        {}
    ).get("id")

    text = message.get(
        "text",
        ""
    ).strip()

    if not is_admin(chat_id):
        return

    if not text:
        return

    # Process selected Update input first
    if process_pending_update(
        chat_id,
        text
    ):
        return

    # MAIN MENU
    if text in (
        "/start",
        "/menu"
    ):
        send_telegram(
            "မင်္ဂလာပါ။ KMT All Software Control မှ "
            "ကြိုဆိုပါတယ်။\n\n"
            + status_text(),
            chat_id,
            telegram_keyboard()
        )

    # STATUS
    elif text == "/status":
        send_telegram(
            status_text(),
            chat_id,
            telegram_keyboard()
        )

    # UPDATE MENU
    elif text in (
        "/update",
        "/updatemenu"
    ):
        send_telegram(
            update_menu_text(),
            chat_id,
            update_keyboard()
        )

    # UPDATE STATUS
    elif text == "/updatestatus":
        send_telegram(
            update_status_text(),
            chat_id,
            update_keyboard()
        )

    # UPDATE MESSAGE
    elif (
        text == "/updatemsg"
        or text.startswith("/updatemsg ")
    ):
        value = text[
            len("/updatemsg"):
        ].strip()

        if not value:
            ask_update_input(
                chat_id,
                "update_message",
                "📝 Update စာသားအသစ် ပို့ပေးပါ။"
            )

            return

        update_settings({
            "update_message": value
        })

        send_telegram(
            "✅ Update စာသား ပြောင်းပြီးပါပြီ။\n\n"
            + update_status_text(),
            chat_id,
            update_keyboard()
        )

    # APK URL
    elif (
        text == "/apk"
        or text.startswith("/apk ")
    ):
        value = text[
            len("/apk"):
        ].strip()

        if not value:
            ask_update_input(
                chat_id,
                "apk_url",
                "🔗 APK Download Link ပို့ပေးပါ။\n\n"
                "HTTPS Link ဖြစ်ရပါမယ်။"
            )

            return

        if not is_valid_apk_url(value):
            send_telegram(
                "❌ မှန်ကန်တဲ့ HTTPS APK Link ထည့်ပါ။",
                chat_id
            )

            return

        update_settings({
            "apk_url": value
        })

        send_telegram(
            "✅ APK Link ပြောင်းပြီးပါပြီ။\n\n"
            + update_status_text(),
            chat_id,
            update_keyboard()
        )

    # VERSION
    elif (
        text == "/version"
        or text.startswith("/version ")
    ):
        parts = text.split()

        if len(parts) != 3:
            send_telegram(
                "အသုံးပြုပုံ:\n\n"
                "/version 1.2.0 1.1.0\n\n"
                "ပထမ = Latest Version\n"
                "ဒုတိယ = Minimum Version",
                chat_id
            )

            return

        latest = parts[1]
        minimum = parts[2]

        if (
            not valid_version(latest)
            or not valid_version(minimum)
        ):
            send_telegram(
                "❌ Version ပုံစံ မမှန်ပါ။",
                chat_id
            )

            return

        if compare_versions(
            minimum,
            latest
        ) > 0:
            send_telegram(
                "❌ Minimum Version သည် Latest Version "
                "ထက် မကြီးရပါ။",
                chat_id
            )

            return

        update_settings({
            "latest_version": latest,
            "minimum_version": minimum
        })

        send_telegram(
            "✅ Version ပြောင်းပြီးပါပြီ။\n\n"
            + update_status_text(),
            chat_id,
            update_keyboard()
        )

    # ANNOUNCEMENT
    elif (
        text.startswith("/notice ")
        or text.startswith("/announce ")
    ):
        _, _, notice = text.partition(" ")

        notice = notice.strip()

        if not notice:
            send_telegram(
                "အသုံးပြုပုံ:\n"
                "/notice ကြေညာချက်စာသား",
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

    # CANCEL
    elif text == "/cancel":
        PENDING_UPDATE.pop(
            str(chat_id),
            None
        )

        send_telegram(
            "❌ လုပ်ဆောင်မှုကို ပယ်ဖျက်လိုက်ပါပြီ။",
            chat_id,
            telegram_keyboard()
        )

    # HELP
    elif text == "/help":
        send_telegram(
            "📘 KMT Bot Commands\n\n"
            "/start - Main Menu\n"
            "/status - App အခြေအနေ\n"
            "/update - Update Menu\n"
            "/updatestatus - Update အချက်အလက်\n"
            "/updatemsg စာသား - Update စာသားပြောင်းရန်\n"
            "/apk HTTPS_LINK - APK Link ပြောင်းရန်\n"
            "/version LATEST MINIMUM - Version ပြောင်းရန်\n"
            "/notice စာသား - ကြေညာချက်ပြောင်းရန်\n"
            "/cancel - ပယ်ဖျက်ရန်",
            chat_id
        )


# ==================================================
# TELEGRAM CALLBACKS
# ==================================================

def process_callback(callback):
    chat_id = callback.get(
        "message",
        {}
    ).get(
        "chat",
        {}
    ).get("id")

    data = callback.get(
        "data",
        ""
    )

    callback_id = callback.get(
        "id",
        ""
    )

    if not is_admin(chat_id):
        answer_callback(
            callback_id,
            "ခွင့်ပြုချက်မရှိပါ။"
        )

        return

    # MAIN MENU
    if data == "main_menu":
        PENDING_UPDATE.pop(
            str(chat_id),
            None
        )

        send_telegram(
            "⚙️ KMT All Software Control\n\n"
            + status_text(),
            chat_id,
            telegram_keyboard()
        )

        answer_callback(
            callback_id,
            "Main Menu"
        )

    # UPDATE MENU
    elif data == "update_menu":
        PENDING_UPDATE.pop(
            str(chat_id),
            None
        )

        send_telegram(
            update_menu_text(),
            chat_id,
            update_keyboard()
        )

        answer_callback(
            callback_id,
            "Update Menu"
        )

    # UPDATE MESSAGE
    elif data == "upd_msg":
        ask_update_input(
            chat_id,
            "update_message",
            "📝 Update စာသားအသစ် ပို့ပေးပါ။\n\n"
            "ဥပမာ:\n"
            "Version အသစ် ထွက်ရှိလာပါပြီ။ "
            "Update လုပ်ပေးပါ။"
        )

        answer_callback(
            callback_id,
            "စာသားအသစ် ပို့ပေးပါ။"
        )

    # APK LINK
    elif data == "upd_apk":
        ask_update_input(
            chat_id,
            "apk_url",
            "🔗 APK Download Link ပို့ပေးပါ။\n\n"
            "ဥပမာ:\n"
            "https://example.com/app.apk"
        )

        answer_callback(
            callback_id,
            "APK Link ပို့ပေးပါ။"
        )

    # LATEST VERSION
    elif data == "upd_latest":
        ask_update_input(
            chat_id,
            "latest_version",
            "🆕 Latest Version အသစ် ပို့ပေးပါ။\n\n"
            "ဥပမာ: 1.2.0"
        )

        answer_callback(
            callback_id,
            "Latest Version ပို့ပေးပါ။"
        )

    # MINIMUM VERSION
    elif data == "upd_minimum":
        ask_update_input(
            chat_id,
            "minimum_version",
            "🛡 Minimum Version အသစ် ပို့ပေးပါ။\n\n"
            "ဥပမာ: 1.1.0"
        )

        answer_callback(
            callback_id,
            "Minimum Version ပို့ပေးပါ။"
        )

    # CANCEL INPUT
    elif data == "cancel_input":
        PENDING_UPDATE.pop(
            str(chat_id),
            None
        )

        send_telegram(
            "❌ ပြင်ဆင်မှုကို ပယ်ဖျက်လိုက်ပါပြီ။",
            chat_id,
            update_keyboard()
        )

        answer_callback(
            callback_id,
            "ပယ်ဖျက်ပြီးပါပြီ။"
        )

    # LOCK / MAINTENANCE
    elif data in (
        "lock",
        "unlock",
        "maintenance_on",
        "maintenance_off"
    ):
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
            }
        }

        messages = {
            "lock": "🔒 App ကို ပိတ်လိုက်ပါပြီ။",

            "unlock": "🔓 App ကို ဖွင့်လိုက်ပါပြီ။",

            "maintenance_on": (
                "🛠 Maintenance Mode ဖွင့်ပြီးပါပြီ။"
            ),

            "maintenance_off": (
                "✅ Maintenance Mode ပိတ်ပြီးပါပြီ။"
            )
        }

        update_settings(
            changes[data]
        )

        send_telegram(
            messages[data]
            + "\n\n"
            + status_text(),
            chat_id,
            telegram_keyboard()
        )

        answer_callback(
            callback_id,
            "ဆက်တင် ပြောင်းပြီးပါပြီ။"
        )

    # APP STATUS
    elif data == "status":
        send_telegram(
            status_text(),
            chat_id,
            telegram_keyboard()
        )

        answer_callback(
            callback_id,
            "App အခြေအနေ"
        )

    # UPDATE STATUS
    elif data == "update_status":
        send_telegram(
            update_status_text(),
            chat_id,
            update_keyboard()
        )

        answer_callback(
            callback_id,
            "Update အချက်အလက်"
        )

    else:
        answer_callback(
            callback_id,
            "မသိရှိသော ခလုတ်ဖြစ်ပါသည်။"
        )


# ==================================================
# TELEGRAM LONG POLLING
# ==================================================

def telegram_polling():
    if not BOT_TOKEN:
        print(
            "TELEGRAM_BOT_TOKEN မသတ်မှတ်ရသေးပါ။"
        )

        return

    # Prevent duplicate polling threads in this process
    if not POLLING_LOCK.acquire(
        blocking=False
    ):
        print(
            "Telegram polling thread ရှိပြီးသားဖြစ်သည်။"
        )

        return

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
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                    params=params,
                    timeout=35
                )

                response.raise_for_status()

                result = response.json()

                if not result.get("ok"):
                    print(
                        "Telegram getUpdates error:",
                        result
                    )

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
                print(
                    "Telegram Bot error:",
                    error
                )

                time.sleep(5)

    finally:
        POLLING_LOCK.release()


# ==================================================
# STARTUP
# ==================================================

@app.on_event("startup")
def startup_event():
    if BOT_TOKEN:
        thread = threading.Thread(
            target=telegram_polling,
            daemon=True
        )

        thread.start()

        print(
            "KMT Telegram Control Bot စတင်ပါပြီ။"
        )

    else:
        print(
            "Telegram Bot Token မရှိပါ။"
        )
