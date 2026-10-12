import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
# Multiple administrator personal Telegram IDs. ADMIN_CHAT_IDS accepts comma-separated IDs.
# Backward compatibility: a single legacy ADMIN_CHAT_ID is also accepted.
ADMIN_CHAT_IDS_RAW = os.getenv("ADMIN_CHAT_IDS", "").strip()
if not ADMIN_CHAT_IDS_RAW:
    ADMIN_CHAT_IDS_RAW = os.getenv("ADMIN_CHAT_ID", "").strip()
try:
    ADMIN_CHAT_IDS = {
        int(part.strip())
        for part in ADMIN_CHAT_IDS_RAW.split(",")
        if part.strip()
    }
except ValueError as exc:
    raise ValueError("ADMIN_CHAT_IDS must contain numeric Telegram IDs separated by commas.") from exc
ADMIN_CHAT_ID: Optional[int] = next(iter(ADMIN_CHAT_IDS), None)  # legacy compatibility only

DB_PATH = BASE_DIR / "data" / "support.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("gladiator_helpbot")

WAITING_FOR_REQUEST = 1
WAITING_FOR_TICKET_CODE = 2
WAITING_FOR_SUPPORT_MESSAGE = 3
WAITING_FOR_TICKET_SELECTION = 4
WAITING_FOR_RATING = 5
WAITING_FOR_ADMIN_REPLY = 6

# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------
T = {
    "fa": {
        "start": "⚔️ GLADIATOR GAMES\n━━━━━━━━━━━━━━━━━━\nسلام {name}، خوش اومدی! 👋\n\nبه مرکز پشتیبانی رسمی Gladiator خوش آمدی.\nاینجا می‌تونی درخواست ثبت کنی، وضعیت تیکت‌هات رو ببینی و با تیم پشتیبانی در ارتباط باشی.\n\n✨ برای شروع، یکی از گزینه‌های زیر رو انتخاب کن.",
        "register": "📝 ثبت درخواست", "track": "🔎 پیگیری درخواست",
        "my_tickets": "📂 درخواست‌های من", "my_profile": "👤 پروفایل من",
        "faq": "❓ سؤالات متداول", "rate": "⭐ امتیازدهی به سایت",
        "language": "🌐 English", "support": "🎧 ارتباط با پشتیبان",
        "cancel": "❌ لغو عملیات", "home": "🏠 منوی اصلی", "back": "⬅️ بازگشت",
        "menu_mode": "🖥️ حالت نمایش منو", "inline_mode": "دکمه‌های داخل پیام",
        "keyboard_mode": "کیبورد پایین صفحه", "mode_saved_inline": "✅ حالت دکمه‌های داخل پیام فعال شد.",
        "mode_saved_keyboard": "✅ کیبورد پایین صفحه فعال شد.", "admin_menu": "🛡️ پنل مدیریت",
        "admin_new": "📥 درخواست‌های در انتظار", "admin_all": "📋 همه درخواست‌ها",
        "admin_back": "⬅️ بازگشت به پنل مدیریت", "admin_empty": "درخواستی برای نمایش وجود ندارد.",
        "admin_choose": "درخواست موردنظر را انتخاب کن:",
        "admin_ticket": "🎫 تیکت: {code}\n👤 کاربر: {name}\n🔹 نام کاربری: {username}\n🆔 شناسه: {uid}\n📂 موضوع: {category}\n📌 وضعیت: {status}\n🕒 ثبت: {created}\n\n📝 متن درخواست:\n{message}",
        "admin_answer": "✍️ پاسخ خود را برای تیکت {code} بنویس. برای لغو از دکمه لغو استفاده کن.",
        "admin_reply_cancelled": "عملیات پاسخ لغو شد.", "admin_reply_sent": "✅ پاسخ برای کاربر ارسال و در سابقه ذخیره شد.",
        "admin_reply_saved_failed": "⚠️ پاسخ ذخیره شد، اما ارسال پیام به کاربر ناموفق بود. ممکن است کاربر ربات را مسدود کرده باشد.",
        "admin_only": "⛔ این بخش فقط برای مدیر ربات است.",
        "choose_request": "لطفاً مشکل خود را در یک پیام بنویس.\n\nمثال: هنگام ورود به حساب کاربری با خطا مواجه می‌شوم.",
        "choose_code": "شماره پیگیری درخواستت را وارد کن.\nمثال: A1B2C3D4",
        "choose_support": "پیامت را برای پشتیبانی بنویس. این پیام به‌عنوان یک درخواست ثبت می‌شود.",
        "too_short": "لطفاً پیام را کمی دقیق‌تر بنویس.",
        "too_long": "پیامت بیش از حد طولانی است؛ لطفاً آن را کوتاه‌تر کن.",
        "saved": "✅ درخواستت ثبت شد.\n\n🎫 شماره پیگیری: {code}\n📌 وضعیت: در انتظار بررسی\n\nاین شماره را نگه دار. می‌توانی از بخش «درخواست‌های من» سابقه و پاسخ‌ها را ببینی.",
        "not_found": "❌ این شماره پیگیری برای حساب تو پیدا نشد. شماره را بررسی کن و دوباره بفرست.",
        "no_tickets": "هنوز درخواستی ثبت نکرده‌ای.",
        "choose_ticket": "یکی از شماره‌های زیر را انتخاب کن تا جزئیات درخواست و پاسخ‌ها را ببینی.",
        "ticket_header": "🎫 درخواست {code}\n📌 وضعیت: {status}\n📂 موضوع: {category}\n🕒 ثبت: {created}\n\n📝 پیام اولیه:\n{message}",
        "no_replies": "\n\n💬 هنوز پاسخی از پشتیبان ثبت نشده است.",
        "replies_header": "\n\n💬 پاسخ‌های پشتیبان:", "reply_line": "\n[{date}] {message}",
        "profile_text": "👤 پروفایل کاربر\n\nنام: {name}\nنام کاربری: {username}\nشناسه تلگرام: {uid}\nزبان: فارسی\nتعداد درخواست‌ها: {total}\nپاسخ‌های پشتیبان: {replies}",
        "faq_title": "❓ سؤالات متداول\nیک سؤال را انتخاب کن:",
        "faq_q1": "چطور درخواست ثبت کنم؟", "faq_a1": "از بخش «ثبت درخواست» استفاده کن و مشکلت را با جزئیات بنویس. شماره پیگیری دریافت می‌کنی.",
        "faq_q2": "چطور درخواست را پیگیری کنم؟", "faq_a2": "از بخش «پیگیری درخواست» شماره پیگیری را وارد کن؛ یا از «درخواست‌های من» سوابق را ببین.",
        "faq_q3": "پاسخ پشتیبان کجا می‌آید؟", "faq_a3": "پاسخ مستقیماً در همین ربات برایت ارسال می‌شود و در سابقه درخواست هم می‌ماند.",
        "faq_q4": "چقدر طول می‌کشد پاسخ بگیرم؟", "faq_a4": "زمان پاسخ به تعداد درخواست‌ها و پیچیدگی مشکل بستگی دارد.",
        "faq_q5": "اگر مشکل حل نشد چه کنم؟", "faq_a5": "یک پیام جدید برای پشتیبانی ثبت کن و در صورت امکان شماره تیکت قبلی را هم بنویس.",
        "rate_prompt": "به تجربه استفاده از سایت از ۱ تا ۵ ستاره امتیاز بده.",
        "rate_saved": "✅ ممنون از امتیازت ({rating}/5). امتیاز ذخیره شد.",
        "rate_invalid": "لطفاً یکی از گزینه‌های ۱ تا ۵ ستاره را انتخاب کن.",
        "lang_changed": "✅ زبان ربات به فارسی تغییر کرد.", "cancelled": "عملیات لغو شد. از منوی اصلی انتخاب کن.",
        "unknown": "لطفاً یکی از گزینه‌های منو را انتخاب کن یا /start را بفرست.",
        "status_open": "🟡 در انتظار بررسی", "status_progress": "🔵 در حال بررسی",
        "status_answered": "🟢 پاسخ داده شده", "status_closed": "⚫ بسته شده",
        "admin_not_configured": "درخواست ثبت شد، اما ADMIN_CHAT_IDS تنظیم نشده است.",
        "support_saved": "✅ پیام تو ثبت شد.\n🎫 شماره پیگیری: {code}\nپاسخ پشتیبان در همین ربات برایت ارسال می‌شود.",
        "help": "از دکمه‌های منو استفاده کن. برای شروع دوباره /start را بفرست.",
        "id_text": "شناسه تلگرام تو: {uid}",
        "keyboard_removed": "حالت نمایش منو تغییر کرد.",
    },
    "en": {
        "start": "⚔️ GLADIATOR GAMES\n━━━━━━━━━━━━━━━━━━\nWelcome, {name}! 👋\n\nYou are at the official Gladiator Support Center.\nSubmit a request, track your tickets, or contact our support team from the menu below.\n\n✨ Choose an option to get started.",
        "register": "📝 Submit a request", "track": "🔎 Track a request",
        "my_tickets": "📂 My requests", "my_profile": "👤 My profile",
        "faq": "❓ FAQs", "rate": "⭐ Rate the website", "language": "🌐 فارسی",
        "support": "🎧 Contact support", "cancel": "❌ Cancel operation",
        "home": "🏠 Main menu", "back": "⬅️ Back", "menu_mode": "🖥️ Menu display mode",
        "inline_mode": "Inline message buttons", "keyboard_mode": "Bottom keyboard",
        "mode_saved_inline": "✅ Inline message buttons are enabled.", "mode_saved_keyboard": "✅ Bottom keyboard is enabled.",
        "admin_menu": "🛡️ Admin panel", "admin_new": "📥 Pending requests", "admin_all": "📋 All requests",
        "admin_back": "⬅️ Back to admin panel", "admin_empty": "There are no requests to show.",
        "admin_choose": "Choose a request:",
        "admin_ticket": "🎫 Ticket: {code}\n👤 User: {name}\n🔹 Username: {username}\n🆔 ID: {uid}\n📂 Category: {category}\n📌 Status: {status}\n🕒 Created: {created}\n\n📝 Request:\n{message}",
        "admin_answer": "✍️ Write your reply for ticket {code}. Use Cancel to stop.",
        "admin_reply_cancelled": "Reply operation cancelled.", "admin_reply_sent": "✅ Reply sent and saved to the ticket history.",
        "admin_reply_saved_failed": "⚠️ Reply was saved, but Telegram could not deliver it. The user may have blocked the bot.",
        "admin_only": "⛔ This section is only for the bot administrator.",
        "choose_request": "Please describe your problem in one message.\n\nExample: I receive an error when signing in.",
        "choose_code": "Enter your ticket tracking code.\nExample: A1B2C3D4",
        "choose_support": "Write your message to support. It will be saved as a support request.",
        "too_short": "Please provide a little more detail.", "too_long": "Your message is too long. Please shorten it.",
        "saved": "✅ Your request has been saved.\n\n🎫 Tracking code: {code}\n📌 Status: Waiting for review\n\nKeep this code. You can view its history and replies in My requests.",
        "not_found": "❌ No ticket with that code was found for your account. Check the code and try again.",
        "no_tickets": "You haven't submitted any requests yet.", "choose_ticket": "Choose a ticket code to view its details and replies.",
        "ticket_header": "🎫 Ticket {code}\n📌 Status: {status}\n📂 Category: {category}\n🕒 Created: {created}\n\n📝 Original message:\n{message}",
        "no_replies": "\n\n💬 No support reply has been added yet.", "replies_header": "\n\n💬 Support replies:",
        "reply_line": "\n[{date}] {message}",
        "profile_text": "👤 User profile\n\nName: {name}\nUsername: {username}\nTelegram ID: {uid}\nLanguage: English\nRequests: {total}\nSupport replies: {replies}",
        "faq_title": "❓ FAQs\nChoose a question:",
        "faq_q1": "How do I submit a request?", "faq_a1": "Choose Submit a request, describe the problem, and keep the tracking code.",
        "faq_q2": "How do I track a request?", "faq_a2": "Use Track a request and enter the tracking code, or open My requests.",
        "faq_q3": "Where will the reply arrive?", "faq_a3": "The reply is sent to you in this bot and saved in the ticket history.",
        "faq_q4": "How long will a reply take?", "faq_a4": "It depends on the current queue and complexity of the issue.",
        "faq_q5": "What if the issue is not resolved?", "faq_a5": "Submit another support message and include the previous ticket code if possible.",
        "rate_prompt": "Rate your experience with the website from 1 to 5 stars.",
        "rate_saved": "✅ Thanks for your rating ({rating}/5). It has been saved.",
        "rate_invalid": "Please choose one of the 1–5 star options.", "lang_changed": "✅ The bot language is now English.",
        "cancelled": "Operation cancelled. Choose from the main menu.", "unknown": "Please choose an option from the menu or send /start.",
        "status_open": "🟡 Waiting for review", "status_progress": "🔵 In progress", "status_answered": "🟢 Answered", "status_closed": "⚫ Closed",
        "admin_not_configured": "Your request was saved, but ADMIN_CHAT_IDS is not configured.",
        "support_saved": "✅ Your message has been saved.\n🎫 Tracking code: {code}\nThe support reply will be sent to you in this bot.",
        "help": "Use the menu buttons. Send /start to return to the main menu.", "id_text": "Your Telegram ID: {uid}",
        "keyboard_removed": "Menu display mode changed.",
    },
}

MENU_KEYS = ("register", "track", "my_tickets", "my_profile", "faq", "rate", "language", "support", "cancel", "home", "back", "menu_mode", "admin_menu")


def tr(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in T else "fa"
    return T[lang][key].format(**kwargs)


def label_values(key: str):
    return [T[language][key] for language in ("fa", "en")]


def label_filter(key: str):
    values = sorted(set(label_values(key)), key=len, reverse=True)
    pattern = r"^(?:" + "|".join(re.escape(value) for value in values) + r")$"
    return filters.Regex(pattern)


def any_menu_label_filter():
    values = sorted({value for key in MENU_KEYS for value in label_values(key)}, key=len, reverse=True)
    pattern = r"^(?:" + "|".join(re.escape(value) for value in values) + r")$"
    return filters.Regex(pattern)


def is_admin(user_id: Optional[int]) -> bool:
    return user_id is not None and user_id in ADMIN_CHAT_IDS


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Create new tables and add only missing columns; existing tickets are preserved."""
    with get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
            language TEXT NOT NULL DEFAULT 'fa', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        user_columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "menu_mode" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN menu_mode TEXT NOT NULL DEFAULT 'keyboard'")
        conn.execute("""CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_code TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL, username TEXT, full_name TEXT,
            category TEXT NOT NULL DEFAULT 'General', message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open', admin_reply TEXT,
            created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT ''
        )""")
        ticket_columns = {r["name"] for r in conn.execute("PRAGMA table_info(tickets)")}
        migrations = {
            "ticket_code": "TEXT", "user_id": "INTEGER", "username": "TEXT", "full_name": "TEXT",
            "category": "TEXT NOT NULL DEFAULT 'General'", "message": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'open'", "admin_reply": "TEXT",
            "created_at": "TEXT NOT NULL DEFAULT ''", "updated_at": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in migrations.items():
            if column not in ticket_columns:
                conn.execute(f"ALTER TABLE tickets ADD COLUMN {column} {definition}")
        conn.execute("""CREATE TABLE IF NOT EXISTS ticket_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_code TEXT NOT NULL,
            sender_type TEXT NOT NULL, sender_id INTEGER, message TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ticket_messages_code ON ticket_messages(ticket_code)")
        conn.execute("""CREATE TABLE IF NOT EXISTS ratings (
            user_id INTEGER PRIMARY KEY, rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5), updated_at TEXT NOT NULL
        )""")
        # Import legacy admin_reply text into the detailed message history if not already present.
        old_replies = conn.execute("SELECT ticket_code, admin_reply, updated_at FROM tickets WHERE admin_reply IS NOT NULL AND TRIM(admin_reply) != ''").fetchall()
        for row in old_replies:
            exists = conn.execute("SELECT 1 FROM ticket_messages WHERE ticket_code=? AND sender_type='admin' AND message=? LIMIT 1", (row["ticket_code"], row["admin_reply"])).fetchone()
            if not exists:
                conn.execute("INSERT INTO ticket_messages(ticket_code, sender_type, sender_id, message, created_at) VALUES (?, 'admin', NULL, ?, ?)", (row["ticket_code"], row["admin_reply"], row["updated_at"] or now_utc()))


def upsert_user(user):
    if not user:
        return
    now = now_utc()
    with get_connection() as conn:
        conn.execute("""INSERT INTO users(user_id, username, first_name, last_name, language, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'fa', ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
            first_name=excluded.first_name, last_name=excluded.last_name, updated_at=excluded.updated_at""",
            (user.id, user.username, user.first_name, user.last_name, now, now))


def get_language(user_id: int) -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT language FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row["language"] if row and row["language"] in T else "fa"


def get_menu_mode(user_id: int) -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT menu_mode FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row["menu_mode"] if row and row["menu_mode"] in ("inline", "keyboard") else "keyboard"


def set_menu_mode(user_id: int, mode: str):
    if mode not in ("inline", "keyboard"):
        mode = "keyboard"
    with get_connection() as conn:
        conn.execute("UPDATE users SET menu_mode=?, updated_at=? WHERE user_id=?", (mode, now_utc(), user_id))


def set_language(user_id: int, language: str):
    if language not in T:
        language = "fa"
    with get_connection() as conn:
        conn.execute("UPDATE users SET language=?, updated_at=? WHERE user_id=?", (language, now_utc(), user_id))


def create_ticket(user, category: str, message: str) -> str:
    now = now_utc()
    with get_connection() as conn:
        code = secrets.token_hex(4).upper()
        while conn.execute("SELECT 1 FROM tickets WHERE ticket_code=?", (code,)).fetchone():
            code = secrets.token_hex(4).upper()
        conn.execute("INSERT INTO tickets(ticket_code,user_id,username,full_name,category,message,status,created_at,updated_at) VALUES (?,?,?,?,?,?,'open',?,?)",
                     (code, user.id, user.username, user.full_name, category, message, now, now))
        conn.execute("INSERT INTO ticket_messages(ticket_code,sender_type,sender_id,message,created_at) VALUES (?,'user',?,?,?)", (code, user.id, message, now))
    return code


def get_ticket(ticket_code: str, user_id: int):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM tickets WHERE UPPER(ticket_code)=? AND user_id=?", (ticket_code.strip().upper(), user_id)).fetchone()


def get_ticket_admin(ticket_code: str):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM tickets WHERE UPPER(ticket_code)=?", (ticket_code.strip().upper(),)).fetchone()


def list_tickets(user_id: int, limit: int = 10):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()


def list_admin_tickets(pending: bool = False, limit: int = 20):
    with get_connection() as conn:
        if pending:
            return conn.execute("SELECT * FROM tickets WHERE status IN ('open','in_progress') ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return conn.execute("SELECT * FROM tickets ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def list_ticket_messages(ticket_code: str):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM ticket_messages WHERE ticket_code=? ORDER BY id ASC", (ticket_code,)).fetchall()


def ticket_stats(user_id: int):
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM tickets WHERE user_id=?", (user_id,)).fetchone()["n"]
        replies = conn.execute("SELECT COUNT(*) AS n FROM ticket_messages m JOIN tickets t ON t.ticket_code=m.ticket_code WHERE t.user_id=? AND m.sender_type='admin'", (user_id,)).fetchone()["n"]
    return total, replies


def save_rating(user_id: int, rating: int):
    with get_connection() as conn:
        conn.execute("INSERT INTO ratings(user_id,rating,updated_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET rating=excluded.rating, updated_at=excluded.updated_at", (user_id, rating, now_utc()))


def status_text(lang: str, status: str) -> str:
    return tr(lang, {"open": "status_open", "in_progress": "status_progress", "answered": "status_answered", "closed": "status_closed"}.get(status, "status_open"))


def keyboard_main(lang: str, admin: bool = False) -> ReplyKeyboardMarkup:
    # Keep the administrator menu separate from the normal user menu.
    if admin:
        rows = [
            [tr(lang, "admin_menu")],
            [tr(lang, "menu_mode"), tr(lang, "language")],
        ]
    else:
        rows = [
            [tr(lang, "register"), tr(lang, "track")],
            [tr(lang, "my_tickets"), tr(lang, "my_profile")],
            [tr(lang, "faq"), tr(lang, "rate")],
            [tr(lang, "support")],
            [tr(lang, "menu_mode"), tr(lang, "language")],
        ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def keyboard_cancel(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[tr(lang, "cancel"), tr(lang, "home")]], resize_keyboard=True, is_persistent=True)


def keyboard_rating(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["⭐ 1", "⭐ 2", "⭐ 3", "⭐ 4", "⭐ 5"], [tr(lang, "cancel"), tr(lang, "home")]], resize_keyboard=True, is_persistent=True)


def main_inline_keyboard(lang: str, admin: bool = False) -> InlineKeyboardMarkup:
    # Administrators see only management actions, never the regular user menu.
    if admin:
        return admin_inline_keyboard(lang)
    rows = [
        [InlineKeyboardButton(tr(lang, "register"), callback_data="user:register"), InlineKeyboardButton(tr(lang, "track"), callback_data="user:track")],
        [InlineKeyboardButton(tr(lang, "my_tickets"), callback_data="user:tickets"), InlineKeyboardButton(tr(lang, "my_profile"), callback_data="user:profile")],
        [InlineKeyboardButton(tr(lang, "faq"), callback_data="user:faq"), InlineKeyboardButton(tr(lang, "rate"), callback_data="user:rate")],
        [InlineKeyboardButton(tr(lang, "support"), callback_data="user:support")],
        [InlineKeyboardButton(tr(lang, "menu_mode"), callback_data="user:mode"), InlineKeyboardButton(tr(lang, "language"), callback_data="user:language")],
    ]
    return InlineKeyboardMarkup(rows)


def admin_inline_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(lang, "admin_new"), callback_data="admin:list:pending")],
        [InlineKeyboardButton(tr(lang, "admin_all"), callback_data="admin:list:all")],
        [InlineKeyboardButton(tr(lang, "menu_mode"), callback_data="user:mode"),
         InlineKeyboardButton(tr(lang, "language"), callback_data="user:language")],
        [InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")],
    ])


def mode_inline_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(lang, "inline_mode"), callback_data="mode:inline")],
        [InlineKeyboardButton(tr(lang, "keyboard_mode"), callback_data="mode:keyboard")],
        [InlineKeyboardButton(tr(lang, "back"), callback_data="user:home")],
    ])


def home_markup(user_id: int, lang: str):
    return main_inline_keyboard(lang, is_admin(user_id)) if get_menu_mode(user_id) == "inline" else keyboard_main(lang, is_admin(user_id))


async def ensure_user(update: Update) -> str:
    user = update.effective_user
    if user:
        upsert_user(user)
        return get_language(user.id)
    return "fa"


async def remember_screen(context: ContextTypes.DEFAULT_TYPE, message):
    """Remember the latest bot screen so the next menu action can replace it."""
    if message is not None:
        context.user_data["last_screen_message_id"] = message.message_id


async def clear_previous_screen(update: Update, context: ContextTypes.DEFAULT_TYPE, *, remove_keyboard: bool = False):
    """Delete the previous bot screen and the tapped reply-keyboard message when possible."""
    chat = update.effective_chat
    message = update.effective_message
    if not chat:
        return
    old_id = context.user_data.pop("last_screen_message_id", None)
    if old_id:
        try:
            await context.bot.delete_message(chat_id=chat.id, message_id=old_id)
        except TelegramError:
            # Telegram may refuse deletion for old messages; navigation should still work.
            pass
    if message and message.from_user and not message.from_user.is_bot:
        try:
            await context.bot.delete_message(chat_id=chat.id, message_id=message.message_id)
        except TelegramError:
            pass
    if remove_keyboard:
        try:
            notice = await context.bot.send_message(
                chat_id=chat.id,
                text="‎",
                reply_markup=ReplyKeyboardRemove(),
            )
            context.user_data["last_screen_message_id"] = notice.message_id
        except TelegramError:
            pass


async def send_home(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: Optional[str] = None):
    user = update.effective_user
    if user:
        lang = lang or get_language(user.id)
    else:
        lang = lang or "fa"
    admin = bool(user and is_admin(user.id))
    text = tr(lang, "start", name=(user.first_name if user and user.first_name else ""))
    mode = get_menu_mode(user.id) if user else "keyboard"
    # Telegram cannot attach a reply-keyboard removal and an inline keyboard to the same message.
    # In inline mode, remove the old keyboard first, then show the message with inline buttons.
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        edited = await query.edit_message_text(text, reply_markup=main_inline_keyboard(lang, admin))
        context.user_data["last_screen_message_id"] = edited.message_id
    elif update.effective_message:
        if mode == "inline":
            sent = await update.effective_message.reply_text(text, reply_markup=main_inline_keyboard(lang, admin))
        else:
            sent = await update.effective_message.reply_text(text, reply_markup=keyboard_main(lang, admin))
        await remember_screen(context, sent)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        await ensure_user(update)
        # This log makes ID mismatches easy to diagnose without exposing the bot token.
        logger.info(
            "Role check on /start: user_id=%s, configured_admin_id=%s, is_admin=%s",
            user.id,
            sorted(ADMIN_CHAT_IDS) if ADMIN_CHAT_IDS else "NOT_SET",
            is_admin(user.id),
        )
    await send_home(update, context)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = await ensure_user(update) if user else "fa"
    context.user_data.pop("pending_admin_ticket", None)
    context.user_data.pop("pending_user_action", None)
    await send_home(update, context, lang)
    return ConversationHandler.END


async def show_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket, lang: str):
    messages = list_ticket_messages(ticket["ticket_code"])
    body = tr(lang, "ticket_header", code=ticket["ticket_code"], status=status_text(lang, ticket["status"]),
              category=ticket["category"], created=ticket["created_at"], message=ticket["message"] or "—")
    replies = [m for m in messages if m["sender_type"] == "admin"]
    if not replies:
        body += tr(lang, "no_replies")
    else:
        body += tr(lang, "replies_header")
        for reply in replies[-5:]:
            body += tr(lang, "reply_line", date=reply["created_at"], message=reply["message"])
    markup = main_inline_keyboard(lang, is_admin(update.effective_user.id)) if get_menu_mode(update.effective_user.id) == "inline" else keyboard_main(lang, is_admin(update.effective_user.id))
    sent = await update.effective_message.reply_text(body[:3900], reply_markup=markup)
    await remember_screen(context, sent)


# ---------------------------------------------------------------------------
# User actions - reply-keyboard mode
# ---------------------------------------------------------------------------
async def begin_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    context.user_data["ticket_category"] = "پشتیبانی عمومی" if lang == "fa" else "General support"
    sent = await update.effective_message.reply_text(tr(lang, "choose_request"), reply_markup=keyboard_cancel(lang))
    await remember_screen(context, sent)
    return WAITING_FOR_REQUEST


async def save_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    message = update.effective_message.text.strip()
    if message in label_values("cancel") or message in label_values("home"):
        return await cancel(update, context)
    if len(message) < 5:
        await update.effective_message.reply_text(tr(lang, "too_short")); return WAITING_FOR_REQUEST
    if len(message) > 3500:
        await update.effective_message.reply_text(tr(lang, "too_long")); return WAITING_FOR_REQUEST
    category = context.user_data.get("ticket_category", "General")
    code = create_ticket(update.effective_user, category, message)
    context.user_data.pop("ticket_category", None)
    await notify_admins_new_ticket(context, code)
    await update.effective_message.reply_text(tr(lang, "saved", code=code), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))
    return ConversationHandler.END


async def begin_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    sent = await update.effective_message.reply_text(tr(lang, "choose_code"), reply_markup=keyboard_cancel(lang))
    await remember_screen(context, sent)
    return WAITING_FOR_TICKET_CODE


async def track_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    code = update.effective_message.text.strip().upper()
    if code in label_values("cancel") or code in label_values("home"):
        return await cancel(update, context)
    ticket = get_ticket(code, update.effective_user.id)
    if not ticket:
        await update.effective_message.reply_text(tr(lang, "not_found")); return WAITING_FOR_TICKET_CODE
    await show_ticket(update, context, ticket, lang)
    return ConversationHandler.END


async def begin_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    context.user_data["ticket_category"] = "ارتباط با پشتیبان" if lang == "fa" else "Contact support"
    sent = await update.effective_message.reply_text(tr(lang, "choose_support"), reply_markup=keyboard_cancel(lang))
    await remember_screen(context, sent)
    return WAITING_FOR_SUPPORT_MESSAGE


async def save_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    message = update.effective_message.text.strip()
    if message in label_values("cancel") or message in label_values("home"):
        return await cancel(update, context)
    if len(message) < 3:
        await update.effective_message.reply_text(tr(lang, "too_short")); return WAITING_FOR_SUPPORT_MESSAGE
    if len(message) > 3500:
        await update.effective_message.reply_text(tr(lang, "too_long")); return WAITING_FOR_SUPPORT_MESSAGE
    category = context.user_data.get("ticket_category", "Contact support")
    code = create_ticket(update.effective_user, category, message)
    context.user_data.pop("ticket_category", None)
    await notify_admins_new_ticket(context, code)
    await update.effective_message.reply_text(tr(lang, "support_saved", code=code), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))
    return ConversationHandler.END


async def begin_my_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    tickets = list_tickets(update.effective_user.id)
    if not tickets:
        sent = await update.effective_message.reply_text(tr(lang, "no_tickets"), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))
        await remember_screen(context, sent)
        return ConversationHandler.END
    context.user_data["ticket_codes"] = [row["ticket_code"] for row in tickets]
    rows = [[row["ticket_code"]] for row in tickets]
    rows.append([tr(lang, "back"), tr(lang, "home")])
    sent = await update.effective_message.reply_text(tr(lang, "choose_ticket"), reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True))
    await remember_screen(context, sent)
    return WAITING_FOR_TICKET_SELECTION


async def select_my_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    code = update.effective_message.text.strip().upper()
    if code in label_values("home") or code in label_values("back"):
        return await cancel(update, context)
    if code not in context.user_data.get("ticket_codes", []):
        await update.effective_message.reply_text(tr(lang, "not_found")); return WAITING_FOR_TICKET_SELECTION
    ticket = get_ticket(code, update.effective_user.id)
    if not ticket:
        await update.effective_message.reply_text(tr(lang, "not_found"), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))
        return ConversationHandler.END
    await show_ticket(update, context, ticket, lang)
    context.user_data.pop("ticket_codes", None)
    return ConversationHandler.END


async def begin_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    sent = await update.effective_message.reply_text(tr(lang, "rate_prompt"), reply_markup=keyboard_rating(lang))
    await remember_screen(context, sent)
    return WAITING_FOR_RATING


async def save_rating_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    match = re.search(r"([1-5])", update.effective_message.text)
    if not match:
        await update.effective_message.reply_text(tr(lang, "rate_invalid")); return WAITING_FOR_RATING
    rating = int(match.group(1))
    save_rating(update.effective_user.id, rating)
    await update.effective_message.reply_text(tr(lang, "rate_saved", rating=rating), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))
    return ConversationHandler.END


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    user = update.effective_user
    username = f"@{user.username}" if user.username else ("ندارد" if lang == "fa" else "Not set")
    total, replies = ticket_stats(user.id)
    caption = tr(lang, "profile_text", name=user.full_name or "—", username=username, uid=user.id, total=total, replies=replies)
    try:
        photos = await context.bot.get_user_profile_photos(user_id=user.id, limit=1)
        if photos.total_count and photos.photos:
            profile_markup = main_inline_keyboard(lang, is_admin(user.id)) if get_menu_mode(user.id) == "inline" else keyboard_main(lang, is_admin(user.id))
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photos.photos[0][-1].file_id,
                                         caption=caption[:1000], reply_markup=profile_markup)
            return
    except TelegramError:
        logger.exception("Could not retrieve profile photo for user %s", user.id)
    profile_markup = main_inline_keyboard(lang, is_admin(user.id)) if get_menu_mode(user.id) == "inline" else keyboard_main(lang, is_admin(user.id))
    sent = await update.effective_message.reply_text(caption, reply_markup=profile_markup)
    await remember_screen(context, sent)


async def show_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    rows = [[InlineKeyboardButton(tr(lang, f"faq_q{i}"), callback_data=f"faq:{i}")] for i in range(1, 6)]
    rows.append([InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")])
    await update.effective_message.reply_text(tr(lang, "faq_title"), reply_markup=InlineKeyboardMarkup(rows))


async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = await ensure_user(update)
    new_lang = "en" if current == "fa" else "fa"
    set_language(update.effective_user.id, new_lang)
    mode = get_menu_mode(update.effective_user.id)
    await update.effective_message.reply_text(tr(new_lang, "lang_changed"), reply_markup=keyboard_main(new_lang, is_admin(update.effective_user.id)))
    if mode == "inline":
        await update.effective_message.reply_text(tr(new_lang, "start", name=update.effective_user.first_name or ""), reply_markup=main_inline_keyboard(new_lang, is_admin(update.effective_user.id)))


async def begin_menu_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    sent = await update.effective_message.reply_text(tr(lang, "menu_mode"), reply_markup=mode_inline_keyboard(lang))
    await remember_screen(context, sent)
    return ConversationHandler.END


async def route_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Replace the previous screen and stale reply keyboard when a menu button is tapped."""
    text = (update.effective_message.text or "").strip()
    user = update.effective_user
    if user and get_menu_mode(user.id) == "keyboard":
        await clear_previous_screen(update, context, remove_keyboard=True)
    if text in label_values("cancel") or text in label_values("home") or text in label_values("back"):
        return await cancel(update, context)
    if text in label_values("register"):
        return await begin_request(update, context)
    if text in label_values("track"):
        return await begin_tracking(update, context)
    if text in label_values("support"):
        return await begin_support(update, context)
    if text in label_values("my_tickets"):
        return await begin_my_tickets(update, context)
    if text in label_values("rate"):
        return await begin_rating(update, context)
    if text in label_values("my_profile"):
        await show_profile(update, context); return ConversationHandler.END
    if text in label_values("faq"):
        await show_faq(update, context); return ConversationHandler.END
    if text in label_values("language"):
        await change_language(update, context); return ConversationHandler.END
    if text in label_values("menu_mode"):
        return await begin_menu_mode(update, context)
    if text in label_values("admin_menu"):
        await admin_home(update, context); return ConversationHandler.END
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    await update.effective_message.reply_text(tr(lang, "help"), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    await update.effective_message.reply_text(tr(lang, "id_text", uid=update.effective_user.id))


# ---------------------------------------------------------------------------
# Notify all configured administrators when a ticket is created
# ---------------------------------------------------------------------------
async def notify_admins_new_ticket(context: ContextTypes.DEFAULT_TYPE, code: str):
    if not ADMIN_CHAT_IDS:
        logger.warning("No ADMIN_CHAT_IDS configured; ticket %s was saved without admin notification.", code)
        return
    ticket = get_ticket_admin(code)
    if not ticket:
        logger.error("Cannot notify administrators: ticket %s was not found after creation.", code)
        return
    name = ticket["full_name"] or "—"
    username = f'@{ticket["username"]}' if ticket["username"] else "—"
    text = (
        "📥 درخواست پشتیبانی جدید\n\n"
        f'🎫 تیکت: {ticket["ticket_code"]}\n'
        f'👤 کاربر: {name}\n'
        f'🔹 نام کاربری: {username}\n'
        f'🆔 شناسه: {ticket["user_id"]}\n'
        f'📂 موضوع: {ticket["category"]}\n\n'
        f'📝 متن درخواست:\n{(ticket["message"] or "—")[:2500]}'
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✍️ مشاهده و پاسخ", callback_data=f'admin:ticket:{ticket["ticket_code"]}')]])
    for admin_id in sorted(ADMIN_CHAT_IDS):
        try:
            await context.bot.send_message(chat_id=admin_id, text=text[:3900], reply_markup=markup)
        except TelegramError:
            logger.exception("Could not notify administrator %s about ticket %s", admin_id, code)


# ---------------------------------------------------------------------------
# Admin panel and replying to a selected ticket
# ---------------------------------------------------------------------------
async def admin_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        if update.callback_query:
            await update.callback_query.answer(tr(lang, "admin_only"), show_alert=True)
        else:
            await update.effective_message.reply_text(tr(lang, "admin_only"))
        return ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🛡️ پنل مدیریت\nدرخواست‌ها را انتخاب کن:", reply_markup=admin_inline_keyboard(lang))
    else:
        await update.effective_message.reply_text("🛡️ پنل مدیریت\nدرخواست‌ها را انتخاب کن:", reply_markup=admin_inline_keyboard(lang))
    return ConversationHandler.END


async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE, pending: bool):
    query = update.callback_query
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        await query.answer(tr(lang, "admin_only"), show_alert=True); return
    await query.answer()
    tickets = list_admin_tickets(pending=pending)
    if not tickets:
        await query.edit_message_text(tr(lang, "admin_empty"), reply_markup=admin_inline_keyboard(lang)); return
    rows = []
    for ticket in tickets:
        status = status_text(lang, ticket["status"])
        rows.append([InlineKeyboardButton(f'{ticket["ticket_code"]} · {status}'[:64], callback_data=f'admin:ticket:{ticket["ticket_code"]}')])
    rows.append([InlineKeyboardButton(tr(lang, "admin_back"), callback_data="admin:home")])
    await query.edit_message_text(tr(lang, "admin_choose"), reply_markup=InlineKeyboardMarkup(rows))


async def admin_show_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    query = update.callback_query
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        await query.answer(tr(lang, "admin_only"), show_alert=True); return
    ticket = get_ticket_admin(code)
    await query.answer()
    if not ticket:
        await query.edit_message_text("Ticket not found.", reply_markup=admin_inline_keyboard(lang)); return
    name = ticket["full_name"] or "—"
    username = f'@{ticket["username"]}' if ticket["username"] else "—"
    body = tr(lang, "admin_ticket", code=ticket["ticket_code"], name=name, username=username,
               uid=ticket["user_id"], category=ticket["category"], status=status_text(lang, ticket["status"]),
               created=ticket["created_at"], message=ticket["message"] or "—")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ پاسخ به کاربر" if lang == "fa" else "✍️ Reply to user", callback_data=f'admin:reply:{ticket["ticket_code"]}')],
        [InlineKeyboardButton("⬅️ فهرست درخواست‌ها" if lang == "fa" else "⬅️ Request list", callback_data="admin:list:all")],
        [InlineKeyboardButton(tr(lang, "admin_back"), callback_data="admin:home")],
    ])
    await query.edit_message_text(body[:3900], reply_markup=markup)


async def begin_admin_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        await query.answer(tr(lang, "admin_only"), show_alert=True)
        return ConversationHandler.END
    code = query.data.rsplit(":", 1)[-1]
    ticket = get_ticket_admin(code)
    await query.answer()
    if not ticket:
        await query.message.reply_text("Ticket not found.")
        return ConversationHandler.END
    context.user_data["pending_admin_ticket"] = ticket["ticket_code"]
    if get_menu_mode(user.id) == "inline":
        await context.bot.send_message(chat_id=update.effective_chat.id, text=tr(lang, "keyboard_removed"), reply_markup=ReplyKeyboardRemove())
        await query.message.reply_text(tr(lang, "admin_answer", code=ticket["ticket_code"]), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(tr(lang, "cancel"), callback_data="admin:cancel_reply")]
        ]))
    else:
        await query.message.reply_text(tr(lang, "admin_answer", code=ticket["ticket_code"]), reply_markup=keyboard_cancel(lang))
    return WAITING_FOR_ADMIN_REPLY


async def cancel_admin_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        await query.answer(tr(lang, "admin_only"), show_alert=True)
        return ConversationHandler.END
    context.user_data.pop("pending_admin_ticket", None)
    await query.answer()
    await query.edit_message_text(tr(lang, "admin_reply_cancelled"))
    await context.bot.send_message(chat_id=update.effective_chat.id, text="🛡️ پنل مدیریت", reply_markup=admin_inline_keyboard(lang))
    return ConversationHandler.END


async def admin_reply_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        return ConversationHandler.END
    message = (update.effective_message.text or "").strip()
    if message in label_values("cancel") or message in label_values("home"):
        context.user_data.pop("pending_admin_ticket", None)
        await update.effective_message.reply_text(tr(lang, "admin_reply_cancelled"), reply_markup=home_markup(user.id, lang))
        return ConversationHandler.END
    if not message:
        await update.effective_message.reply_text(tr(lang, "too_short")); return WAITING_FOR_ADMIN_REPLY
    if len(message) > 3500:
        await update.effective_message.reply_text(tr(lang, "too_long")); return WAITING_FOR_ADMIN_REPLY
    code = context.user_data.get("pending_admin_ticket")
    ticket = get_ticket_admin(code or "")
    if not ticket:
        context.user_data.pop("pending_admin_ticket", None)
        await update.effective_message.reply_text("Ticket not found.", reply_markup=home_markup(user.id, lang))
        return ConversationHandler.END
    stamp = now_utc()
    with get_connection() as conn:
        conn.execute("INSERT INTO ticket_messages(ticket_code,sender_type,sender_id,message,created_at) VALUES (?,'admin',?,?,?)", (code, user.id, message, stamp))
        conn.execute("UPDATE tickets SET admin_reply=?,status='answered',updated_at=? WHERE ticket_code=?", (message, stamp, code))
    context.user_data.pop("pending_admin_ticket", None)
    recipient_lang = get_language(ticket["user_id"])
    if recipient_lang == "fa":
        delivered = f"💬 پاسخ پشتیبان به درخواست تو\n\n🎫 شماره تیکت: {code}\n\n{message}\n\nبرای دیدن تمام سوابق، بخش درخواست‌های من را باز کن."
    else:
        delivered = f"💬 Support replied to your request\n\n🎫 Ticket: {code}\n\n{message}\n\nOpen My requests to view the full history."
    try:
        await context.bot.send_message(chat_id=ticket["user_id"], text=delivered)
        await update.effective_message.reply_text(tr(lang, "admin_reply_sent"), reply_markup=home_markup(user.id, lang))
    except TelegramError:
        logger.exception("Could not deliver reply for ticket %s", code)
        await update.effective_message.reply_text(tr(lang, "admin_reply_saved_failed"), reply_markup=home_markup(user.id, lang))
    return ConversationHandler.END


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    user = update.effective_user
    if not user:
        await query.answer(); return
    await ensure_user(update)
    lang = get_language(user.id)

    if data.startswith("mode:"):
        mode = data.split(":", 1)[1]
        set_menu_mode(user.id, mode)
        await query.answer()
        if mode == "inline":
            # Telegram requires a separate message to remove a reply keyboard before showing inline buttons.
            await context.bot.send_message(chat_id=update.effective_chat.id, text=tr(lang, "keyboard_removed"), reply_markup=ReplyKeyboardRemove())
            await context.bot.send_message(chat_id=update.effective_chat.id, text=tr(lang, "mode_saved_inline") + "\n\n" + tr(lang, "start", name=user.first_name or ""), reply_markup=main_inline_keyboard(lang, is_admin(user.id)))
        else:
            await query.edit_message_text(tr(lang, "mode_saved_keyboard"))
            await context.bot.send_message(chat_id=update.effective_chat.id, text=tr(lang, "start", name=user.first_name or ""), reply_markup=keyboard_main(lang, is_admin(user.id)))
        return

    if data == "user:cancel_action":
        await query.answer()
        context.user_data.pop("pending_user_action", None)
        context.user_data.pop("ticket_category", None)
        await query.edit_message_text(tr(lang, "cancelled"), reply_markup=main_inline_keyboard(lang, is_admin(user.id)))
        return

    if data.startswith("rating:"):
        await query.answer()
        rating = int(data.split(":", 1)[1])
        if rating < 1 or rating > 5:
            await query.edit_message_text(tr(lang, "rate_invalid")); return
        save_rating(user.id, rating)
        context.user_data.pop("pending_user_action", None)
        await query.edit_message_text(tr(lang, "rate_saved", rating=rating), reply_markup=main_inline_keyboard(lang, is_admin(user.id)))
        return

    if data.startswith("faq:"):
        index = int(data.split(":", 1)[1])
        await query.answer()
        await query.edit_message_text(f"{tr(lang, f'faq_q{index}')}\n\n{tr(lang, f'faq_a{index}')}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(tr(lang, "back"), callback_data="user:faq")],
            [InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")],
        ]))
        return

    if data == "admin:cancel_reply":
        await query.answer()
        context.user_data.pop("pending_admin_ticket", None)
        await query.edit_message_text(tr(lang, "admin_reply_cancelled"))
        await context.bot.send_message(chat_id=update.effective_chat.id, text="🛡️ پنل مدیریت", reply_markup=admin_inline_keyboard(lang))
        return

    if data.startswith("admin:"):
        if not is_admin(user.id):
            await query.answer(tr(lang, "admin_only"), show_alert=True); return
        if data == "admin:home":
            await admin_home(update, context)
        elif data == "admin:list:pending":
            await admin_list(update, context, pending=True)
        elif data == "admin:list:all":
            await admin_list(update, context, pending=False)
        elif data.startswith("admin:ticket:"):
            await admin_show_ticket(update, context, data.split(":", 2)[2])
        return

    if data == "user:home":
        await query.answer()
        try:
            await query.edit_message_text(
                tr(lang, "start", name=user.first_name or ""),
                reply_markup=main_inline_keyboard(lang, is_admin(user.id)),
            )
        except BadRequest as exc:
            # The user may tap Home while the exact same home screen is already shown.
            # Ignore only this harmless Telegram response; propagate other API errors.
            if "Message is not modified" not in str(exc):
                raise
        return
    if data == "user:mode":
        await query.answer()
        await query.edit_message_text(tr(lang, "menu_mode"), reply_markup=mode_inline_keyboard(lang)); return
    if data == "user:language":
        await query.answer()
        title = "🌐 انتخاب زبان / Choose your language" if lang == "fa" else "🌐 Choose your language / انتخاب زبان"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇮🇷 فارسی", callback_data="language:fa"),
             InlineKeyboardButton("🇬🇧 English", callback_data="language:en")],
            [InlineKeyboardButton(tr(lang, "back"), callback_data="user:home")],
        ])
        await query.edit_message_text(title, reply_markup=markup)
        return

    if data.startswith("language:"):
        new_lang = data.split(":", 1)[1]
        if new_lang not in T:
            await query.answer()
            return
        set_language(user.id, new_lang)
        await query.answer("زبان تغییر کرد" if new_lang == "fa" else "Language updated")
        await query.edit_message_text(
            tr(new_lang, "lang_changed") + "\\n\\n" + tr(new_lang, "start", name=user.first_name or ""),
            reply_markup=main_inline_keyboard(new_lang, is_admin(user.id)),
        )
        return
    if data == "user:faq":
        await query.answer()
        rows = [[InlineKeyboardButton(tr(lang, f"faq_q{i}"), callback_data=f"faq:{i}")] for i in range(1, 6)]
        rows.append([InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")])
        await query.edit_message_text(tr(lang, "faq_title"), reply_markup=InlineKeyboardMarkup(rows)); return
    if data == "user:profile":
        await query.answer()
        username = f"@{user.username}" if user.username else ("ندارد" if lang == "fa" else "Not set")
        total, replies = ticket_stats(user.id)
        caption = "👤  پروفایل کاربری\\n━━━━━━━━━━━━━━━━━━\\n\\n" + tr(
            lang, "profile_text", name=user.full_name or "—", username=username,
            uid=user.id, total=total, replies=replies
        )
        profile_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ بازگشت به منوی اصلی" if lang == "fa" else "⬅️ Back to main menu",
                                  callback_data="user:home")]
        ])
        # Edit the existing menu message so navigation stays on one clean screen.
        try:
            await query.edit_message_text(caption[:3900], reply_markup=profile_markup)
        except BadRequest as exc:
            if "Message is not modified" not in str(exc):
                raise
        return
    if data == "user:tickets":
        await query.answer()
        tickets = list_tickets(user.id)
        if not tickets:
            await query.message.reply_text(tr(lang, "no_tickets")); return
        rows = [[InlineKeyboardButton(row["ticket_code"], callback_data=f"user:ticket:{row['ticket_code']}")] for row in tickets]
        rows.append([InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")])
        await query.edit_message_text(tr(lang, "choose_ticket"), reply_markup=InlineKeyboardMarkup(rows)); return
    if data.startswith("user:ticket:"):
        code = data.split(":", 2)[2]
        ticket = get_ticket(code, user.id)
        await query.answer()
        if not ticket:
            await query.edit_message_text(tr(lang, "not_found")); return
        messages = list_ticket_messages(code)
        body = tr(lang, "ticket_header", code=code, status=status_text(lang, ticket["status"]), category=ticket["category"], created=ticket["created_at"], message=ticket["message"] or "—")
        replies = [m for m in messages if m["sender_type"] == "admin"]
        if not replies:
            body += tr(lang, "no_replies")
        else:
            body += tr(lang, "replies_header")
            for reply in replies[-5:]:
                body += tr(lang, "reply_line", date=reply["created_at"], message=reply["message"])
        await query.edit_message_text(body[:3900], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")]])); return

    action_map = {"user:register": "register", "user:track": "track", "user:support": "support", "user:rate": "rate"}
    action = action_map.get(data)
    if action:
        await query.answer()
        context.user_data["pending_user_action"] = action
        if action == "register":
            context.user_data["ticket_category"] = "پشتیبانی عمومی" if lang == "fa" else "General support"
            prompt = tr(lang, "choose_request")
        elif action == "support":
            context.user_data["ticket_category"] = "ارتباط با پشتیبان" if lang == "fa" else "Contact support"
            prompt = tr(lang, "choose_support")
        elif action == "track":
            prompt = tr(lang, "choose_code")
        else:
            prompt = tr(lang, "rate_prompt")
        if action == "rate":
            rating_rows = [[InlineKeyboardButton(f"⭐ {i}", callback_data=f"rating:{i}") for i in range(1, 6)]]
            rating_rows.append([InlineKeyboardButton(tr(lang, "cancel"), callback_data="user:cancel_action")])
            await query.message.reply_text(prompt, reply_markup=InlineKeyboardMarkup(rating_rows))
        else:
            await query.message.reply_text(prompt, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(tr(lang, "cancel"), callback_data="user:cancel_action")]
            ]))
        return


async def process_inline_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the next text after an inline-menu action was selected."""
    action = context.user_data.get("pending_user_action")
    if not action or not update.effective_message or not update.effective_message.text:
        return False
    lang = await ensure_user(update)
    text = update.effective_message.text.strip()
    if text in label_values("cancel") or text in label_values("home"):
        context.user_data.pop("pending_user_action", None)
        context.user_data.pop("ticket_category", None)
        await send_home(update, context, lang)
        return True
    if action in ("register", "support"):
        minimum = 5 if action == "register" else 3
        if len(text) < minimum:
            await update.effective_message.reply_text(tr(lang, "too_short")); return True
        if len(text) > 3500:
            await update.effective_message.reply_text(tr(lang, "too_long")); return True
        category = context.user_data.pop("ticket_category", "General")
        code = create_ticket(update.effective_user, category, text)
        context.user_data.pop("pending_user_action", None)
        await notify_admins_new_ticket(context, code)
        key = "saved" if action == "register" else "support_saved"
        await update.effective_message.reply_text(tr(lang, key, code=code), reply_markup=main_inline_keyboard(lang, is_admin(update.effective_user.id)))
        return True
    if action == "track":
        ticket = get_ticket(text.upper(), update.effective_user.id)
        if not ticket:
            await update.effective_message.reply_text(tr(lang, "not_found")); return True
        context.user_data.pop("pending_user_action", None)
        await show_ticket(update, context, ticket, lang)
        return True
    if action == "rate":
        match = re.search(r"([1-5])", text)
        if not match:
            await update.effective_message.reply_text(tr(lang, "rate_invalid")); return True
        rating = int(match.group(1)); save_rating(update.effective_user.id, rating)
        context.user_data.pop("pending_user_action", None)
        await update.effective_message.reply_text(tr(lang, "rate_saved", rating=rating), reply_markup=main_inline_keyboard(lang, is_admin(update.effective_user.id)))
        return True
    return False


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_message:
        return
    if await process_inline_user_text(update, context):
        return
    lang = await ensure_user(update)
    await update.effective_message.reply_text(tr(lang, "unknown"), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))


async def set_commands(application: Application):
    try:
        await application.bot.set_my_commands([
            BotCommand("start", "Open the main menu"),
            BotCommand("help", "Show help"),
            BotCommand("id", "Show your Telegram ID"),
        ])
    except TelegramError:
        logger.exception("Could not register Telegram slash-command suggestions.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled update error: %s", context.error, exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Check the .env file next to bot.py.")
    init_database()

    # Keyboard-mode conversation flow for users.
    user_conversation = ConversationHandler(
        entry_points=[
            MessageHandler(label_filter("register"), begin_request),
            MessageHandler(label_filter("track"), begin_tracking),
            MessageHandler(label_filter("support"), begin_support),
            MessageHandler(label_filter("my_tickets"), begin_my_tickets),
            MessageHandler(label_filter("rate"), begin_rating),
        ],
        states={
            WAITING_FOR_REQUEST: [MessageHandler(any_menu_label_filter(), route_menu_button), MessageHandler(filters.TEXT & ~filters.COMMAND, save_request)],
            WAITING_FOR_TICKET_CODE: [MessageHandler(any_menu_label_filter(), route_menu_button), MessageHandler(filters.TEXT & ~filters.COMMAND, track_ticket)],
            WAITING_FOR_SUPPORT_MESSAGE: [MessageHandler(any_menu_label_filter(), route_menu_button), MessageHandler(filters.TEXT & ~filters.COMMAND, save_support_message)],
            WAITING_FOR_TICKET_SELECTION: [MessageHandler(any_menu_label_filter(), route_menu_button), MessageHandler(filters.TEXT & ~filters.COMMAND, select_my_ticket)],
            WAITING_FOR_RATING: [MessageHandler(any_menu_label_filter(), route_menu_button), MessageHandler(filters.TEXT & ~filters.COMMAND, save_rating_handler)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("help", help_command),
            MessageHandler(label_filter("cancel"), cancel),
            MessageHandler(label_filter("home"), cancel),
            MessageHandler(label_filter("back"), cancel),
        ],
        allow_reentry=True,
        conversation_timeout=None,
    )

    # This conversation is entered from the administrator's selected ticket button.
    admin_reply_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(begin_admin_reply_callback, pattern=r"^admin:reply:")],
        states={WAITING_FOR_ADMIN_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reply_text)]},
        fallbacks=[
            CallbackQueryHandler(cancel_admin_reply_callback, pattern=r"^admin:cancel_reply$"),
            CommandHandler("start", start),
            MessageHandler(label_filter("cancel"), cancel),
            MessageHandler(label_filter("home"), cancel),
        ],
        allow_reentry=True,
        conversation_timeout=None,
    )

    app = (
        Application.builder().token(BOT_TOKEN)
        .connect_timeout(30).read_timeout(45).write_timeout(30).pool_timeout(30)
        .post_init(set_commands).build()
    )
    # Specific admin conversation must be registered before the general callback handler.
    app.add_handler(admin_reply_conversation)
    app.add_handler(user_conversation)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(MessageHandler(label_filter("my_profile"), show_profile))
    app.add_handler(MessageHandler(label_filter("faq"), show_faq))
    app.add_handler(MessageHandler(label_filter("language"), change_language))
    app.add_handler(MessageHandler(label_filter("menu_mode"), begin_menu_mode))
    app.add_handler(MessageHandler(label_filter("admin_menu"), admin_home))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))
    app.add_error_handler(error_handler)

    logger.info("GladiatorHelpBot starting; database: %s", DB_PATH)
    logger.info("Configured administrator IDs: %s", sorted(ADMIN_CHAT_IDS) if ADMIN_CHAT_IDS else "NOT_SET")
    if not ADMIN_CHAT_IDS:
        logger.warning("ADMIN_CHAT_IDS is not configured. Admin menu and reply delivery are disabled.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
# Multiple administrator personal Telegram IDs. ADMIN_CHAT_IDS accepts comma-separated IDs.
# Backward compatibility: a single legacy ADMIN_CHAT_ID is also accepted.
ADMIN_CHAT_IDS_RAW = os.getenv("ADMIN_CHAT_IDS", "").strip()
if not ADMIN_CHAT_IDS_RAW:
    ADMIN_CHAT_IDS_RAW = os.getenv("ADMIN_CHAT_ID", "").strip()
try:
    ADMIN_CHAT_IDS = {
        int(part.strip())
        for part in ADMIN_CHAT_IDS_RAW.split(",")
        if part.strip()
    }
except ValueError as exc:
    raise ValueError("ADMIN_CHAT_IDS must contain numeric Telegram IDs separated by commas.") from exc
ADMIN_CHAT_ID: Optional[int] = next(iter(ADMIN_CHAT_IDS), None)  # legacy compatibility only

DB_PATH = BASE_DIR / "data" / "support.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("gladiator_helpbot")

WAITING_FOR_REQUEST = 1
WAITING_FOR_TICKET_CODE = 2
WAITING_FOR_SUPPORT_MESSAGE = 3
WAITING_FOR_TICKET_SELECTION = 4
WAITING_FOR_RATING = 5
WAITING_FOR_ADMIN_REPLY = 6

# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------
T = {
    "fa": {
        "start": "⚔️ GLADIATOR GAMES\n━━━━━━━━━━━━━━━━━━\nسلام {name}، خوش اومدی! 👋\n\nبه مرکز پشتیبانی رسمی Gladiator خوش آمدی.\nاینجا می‌تونی درخواست ثبت کنی، وضعیت تیکت‌هات رو ببینی و با تیم پشتیبانی در ارتباط باشی.\n\n✨ برای شروع، یکی از گزینه‌های زیر رو انتخاب کن.",
        "register": "📝 ثبت درخواست", "track": "🔎 پیگیری درخواست",
        "my_tickets": "📂 درخواست‌های من", "my_profile": "👤 پروفایل من",
        "faq": "❓ سؤالات متداول", "rate": "⭐ امتیازدهی به سایت",
        "language": "🌐 English", "support": "🎧 ارتباط با پشتیبان",
        "cancel": "❌ لغو عملیات", "home": "🏠 منوی اصلی", "back": "⬅️ بازگشت",
        "menu_mode": "🖥️ حالت نمایش منو", "inline_mode": "دکمه‌های داخل پیام",
        "keyboard_mode": "کیبورد پایین صفحه", "mode_saved_inline": "✅ حالت دکمه‌های داخل پیام فعال شد.",
        "mode_saved_keyboard": "✅ کیبورد پایین صفحه فعال شد.", "admin_menu": "🛡️ پنل مدیریت",
        "admin_new": "📥 درخواست‌های در انتظار", "admin_all": "📋 همه درخواست‌ها",
        "admin_back": "⬅️ بازگشت به پنل مدیریت", "admin_empty": "درخواستی برای نمایش وجود ندارد.",
        "admin_choose": "درخواست موردنظر را انتخاب کن:",
        "admin_ticket": "🎫 تیکت: {code}\n👤 کاربر: {name}\n🔹 نام کاربری: {username}\n🆔 شناسه: {uid}\n📂 موضوع: {category}\n📌 وضعیت: {status}\n🕒 ثبت: {created}\n\n📝 متن درخواست:\n{message}",
        "admin_answer": "✍️ پاسخ خود را برای تیکت {code} بنویس. برای لغو از دکمه لغو استفاده کن.",
        "admin_reply_cancelled": "عملیات پاسخ لغو شد.", "admin_reply_sent": "✅ پاسخ برای کاربر ارسال و در سابقه ذخیره شد.",
        "admin_reply_saved_failed": "⚠️ پاسخ ذخیره شد، اما ارسال پیام به کاربر ناموفق بود. ممکن است کاربر ربات را مسدود کرده باشد.",
        "admin_only": "⛔ این بخش فقط برای مدیر ربات است.",
        "choose_request": "لطفاً مشکل خود را در یک پیام بنویس.\n\nمثال: هنگام ورود به حساب کاربری با خطا مواجه می‌شوم.",
        "choose_code": "شماره پیگیری درخواستت را وارد کن.\nمثال: A1B2C3D4",
        "choose_support": "پیامت را برای پشتیبانی بنویس. این پیام به‌عنوان یک درخواست ثبت می‌شود.",
        "too_short": "لطفاً پیام را کمی دقیق‌تر بنویس.",
        "too_long": "پیامت بیش از حد طولانی است؛ لطفاً آن را کوتاه‌تر کن.",
        "saved": "✅ درخواستت ثبت شد.\n\n🎫 شماره پیگیری: {code}\n📌 وضعیت: در انتظار بررسی\n\nاین شماره را نگه دار. می‌توانی از بخش «درخواست‌های من» سابقه و پاسخ‌ها را ببینی.",
        "not_found": "❌ این شماره پیگیری برای حساب تو پیدا نشد. شماره را بررسی کن و دوباره بفرست.",
        "no_tickets": "هنوز درخواستی ثبت نکرده‌ای.",
        "choose_ticket": "یکی از شماره‌های زیر را انتخاب کن تا جزئیات درخواست و پاسخ‌ها را ببینی.",
        "ticket_header": "🎫 درخواست {code}\n📌 وضعیت: {status}\n📂 موضوع: {category}\n🕒 ثبت: {created}\n\n📝 پیام اولیه:\n{message}",
        "no_replies": "\n\n💬 هنوز پاسخی از پشتیبان ثبت نشده است.",
        "replies_header": "\n\n💬 پاسخ‌های پشتیبان:", "reply_line": "\n[{date}] {message}",
        "profile_text": "👤 پروفایل کاربر\n\nنام: {name}\nنام کاربری: {username}\nشناسه تلگرام: {uid}\nزبان: فارسی\nتعداد درخواست‌ها: {total}\nپاسخ‌های پشتیبان: {replies}",
        "faq_title": "❓ سؤالات متداول\nیک سؤال را انتخاب کن:",
        "faq_q1": "چطور درخواست ثبت کنم؟", "faq_a1": "از بخش «ثبت درخواست» استفاده کن و مشکلت را با جزئیات بنویس. شماره پیگیری دریافت می‌کنی.",
        "faq_q2": "چطور درخواست را پیگیری کنم؟", "faq_a2": "از بخش «پیگیری درخواست» شماره پیگیری را وارد کن؛ یا از «درخواست‌های من» سوابق را ببین.",
        "faq_q3": "پاسخ پشتیبان کجا می‌آید؟", "faq_a3": "پاسخ مستقیماً در همین ربات برایت ارسال می‌شود و در سابقه درخواست هم می‌ماند.",
        "faq_q4": "چقدر طول می‌کشد پاسخ بگیرم؟", "faq_a4": "زمان پاسخ به تعداد درخواست‌ها و پیچیدگی مشکل بستگی دارد.",
        "faq_q5": "اگر مشکل حل نشد چه کنم؟", "faq_a5": "یک پیام جدید برای پشتیبانی ثبت کن و در صورت امکان شماره تیکت قبلی را هم بنویس.",
        "rate_prompt": "به تجربه استفاده از سایت از ۱ تا ۵ ستاره امتیاز بده.",
        "rate_saved": "✅ ممنون از امتیازت ({rating}/5). امتیاز ذخیره شد.",
        "rate_invalid": "لطفاً یکی از گزینه‌های ۱ تا ۵ ستاره را انتخاب کن.",
        "lang_changed": "✅ زبان ربات به فارسی تغییر کرد.", "cancelled": "عملیات لغو شد. از منوی اصلی انتخاب کن.",
        "unknown": "لطفاً یکی از گزینه‌های منو را انتخاب کن یا /start را بفرست.",
        "status_open": "🟡 در انتظار بررسی", "status_progress": "🔵 در حال بررسی",
        "status_answered": "🟢 پاسخ داده شده", "status_closed": "⚫ بسته شده",
        "admin_not_configured": "درخواست ثبت شد، اما ADMIN_CHAT_IDS تنظیم نشده است.",
        "support_saved": "✅ پیام تو ثبت شد.\n🎫 شماره پیگیری: {code}\nپاسخ پشتیبان در همین ربات برایت ارسال می‌شود.",
        "help": "از دکمه‌های منو استفاده کن. برای شروع دوباره /start را بفرست.",
        "id_text": "شناسه تلگرام تو: {uid}",
        "keyboard_removed": "حالت نمایش منو تغییر کرد.",
    },
    "en": {
        "start": "⚔️ GLADIATOR GAMES\n━━━━━━━━━━━━━━━━━━\nWelcome, {name}! 👋\n\nYou are at the official Gladiator Support Center.\nSubmit a request, track your tickets, or contact our support team from the menu below.\n\n✨ Choose an option to get started.",
        "register": "📝 Submit a request", "track": "🔎 Track a request",
        "my_tickets": "📂 My requests", "my_profile": "👤 My profile",
        "faq": "❓ FAQs", "rate": "⭐ Rate the website", "language": "🌐 فارسی",
        "support": "🎧 Contact support", "cancel": "❌ Cancel operation",
        "home": "🏠 Main menu", "back": "⬅️ Back", "menu_mode": "🖥️ Menu display mode",
        "inline_mode": "Inline message buttons", "keyboard_mode": "Bottom keyboard",
        "mode_saved_inline": "✅ Inline message buttons are enabled.", "mode_saved_keyboard": "✅ Bottom keyboard is enabled.",
        "admin_menu": "🛡️ Admin panel", "admin_new": "📥 Pending requests", "admin_all": "📋 All requests",
        "admin_back": "⬅️ Back to admin panel", "admin_empty": "There are no requests to show.",
        "admin_choose": "Choose a request:",
        "admin_ticket": "🎫 Ticket: {code}\n👤 User: {name}\n🔹 Username: {username}\n🆔 ID: {uid}\n📂 Category: {category}\n📌 Status: {status}\n🕒 Created: {created}\n\n📝 Request:\n{message}",
        "admin_answer": "✍️ Write your reply for ticket {code}. Use Cancel to stop.",
        "admin_reply_cancelled": "Reply operation cancelled.", "admin_reply_sent": "✅ Reply sent and saved to the ticket history.",
        "admin_reply_saved_failed": "⚠️ Reply was saved, but Telegram could not deliver it. The user may have blocked the bot.",
        "admin_only": "⛔ This section is only for the bot administrator.",
        "choose_request": "Please describe your problem in one message.\n\nExample: I receive an error when signing in.",
        "choose_code": "Enter your ticket tracking code.\nExample: A1B2C3D4",
        "choose_support": "Write your message to support. It will be saved as a support request.",
        "too_short": "Please provide a little more detail.", "too_long": "Your message is too long. Please shorten it.",
        "saved": "✅ Your request has been saved.\n\n🎫 Tracking code: {code}\n📌 Status: Waiting for review\n\nKeep this code. You can view its history and replies in My requests.",
        "not_found": "❌ No ticket with that code was found for your account. Check the code and try again.",
        "no_tickets": "You haven't submitted any requests yet.", "choose_ticket": "Choose a ticket code to view its details and replies.",
        "ticket_header": "🎫 Ticket {code}\n📌 Status: {status}\n📂 Category: {category}\n🕒 Created: {created}\n\n📝 Original message:\n{message}",
        "no_replies": "\n\n💬 No support reply has been added yet.", "replies_header": "\n\n💬 Support replies:",
        "reply_line": "\n[{date}] {message}",
        "profile_text": "👤 User profile\n\nName: {name}\nUsername: {username}\nTelegram ID: {uid}\nLanguage: English\nRequests: {total}\nSupport replies: {replies}",
        "faq_title": "❓ FAQs\nChoose a question:",
        "faq_q1": "How do I submit a request?", "faq_a1": "Choose Submit a request, describe the problem, and keep the tracking code.",
        "faq_q2": "How do I track a request?", "faq_a2": "Use Track a request and enter the tracking code, or open My requests.",
        "faq_q3": "Where will the reply arrive?", "faq_a3": "The reply is sent to you in this bot and saved in the ticket history.",
        "faq_q4": "How long will a reply take?", "faq_a4": "It depends on the current queue and complexity of the issue.",
        "faq_q5": "What if the issue is not resolved?", "faq_a5": "Submit another support message and include the previous ticket code if possible.",
        "rate_prompt": "Rate your experience with the website from 1 to 5 stars.",
        "rate_saved": "✅ Thanks for your rating ({rating}/5). It has been saved.",
        "rate_invalid": "Please choose one of the 1–5 star options.", "lang_changed": "✅ The bot language is now English.",
        "cancelled": "Operation cancelled. Choose from the main menu.", "unknown": "Please choose an option from the menu or send /start.",
        "status_open": "🟡 Waiting for review", "status_progress": "🔵 In progress", "status_answered": "🟢 Answered", "status_closed": "⚫ Closed",
        "admin_not_configured": "Your request was saved, but ADMIN_CHAT_IDS is not configured.",
        "support_saved": "✅ Your message has been saved.\n🎫 Tracking code: {code}\nThe support reply will be sent to you in this bot.",
        "help": "Use the menu buttons. Send /start to return to the main menu.", "id_text": "Your Telegram ID: {uid}",
        "keyboard_removed": "Menu display mode changed.",
    },
}

MENU_KEYS = ("register", "track", "my_tickets", "my_profile", "faq", "rate", "language", "support", "cancel", "home", "back", "menu_mode", "admin_menu")


def tr(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in T else "fa"
    return T[lang][key].format(**kwargs)


def label_values(key: str):
    return [T[language][key] for language in ("fa", "en")]


def label_filter(key: str):
    values = sorted(set(label_values(key)), key=len, reverse=True)
    pattern = r"^(?:" + "|".join(re.escape(value) for value in values) + r")$"
    return filters.Regex(pattern)


def any_menu_label_filter():
    values = sorted({value for key in MENU_KEYS for value in label_values(key)}, key=len, reverse=True)
    pattern = r"^(?:" + "|".join(re.escape(value) for value in values) + r")$"
    return filters.Regex(pattern)


def is_admin(user_id: Optional[int]) -> bool:
    return user_id is not None and user_id in ADMIN_CHAT_IDS


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Create new tables and add only missing columns; existing tickets are preserved."""
    with get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
            language TEXT NOT NULL DEFAULT 'fa', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        user_columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "menu_mode" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN menu_mode TEXT NOT NULL DEFAULT 'keyboard'")
        conn.execute("""CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_code TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL, username TEXT, full_name TEXT,
            category TEXT NOT NULL DEFAULT 'General', message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open', admin_reply TEXT,
            created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT ''
        )""")
        ticket_columns = {r["name"] for r in conn.execute("PRAGMA table_info(tickets)")}
        migrations = {
            "ticket_code": "TEXT", "user_id": "INTEGER", "username": "TEXT", "full_name": "TEXT",
            "category": "TEXT NOT NULL DEFAULT 'General'", "message": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'open'", "admin_reply": "TEXT",
            "created_at": "TEXT NOT NULL DEFAULT ''", "updated_at": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in migrations.items():
            if column not in ticket_columns:
                conn.execute(f"ALTER TABLE tickets ADD COLUMN {column} {definition}")
        conn.execute("""CREATE TABLE IF NOT EXISTS ticket_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_code TEXT NOT NULL,
            sender_type TEXT NOT NULL, sender_id INTEGER, message TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ticket_messages_code ON ticket_messages(ticket_code)")
        conn.execute("""CREATE TABLE IF NOT EXISTS ratings (
            user_id INTEGER PRIMARY KEY, rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5), updated_at TEXT NOT NULL
        )""")
        # Import legacy admin_reply text into the detailed message history if not already present.
        old_replies = conn.execute("SELECT ticket_code, admin_reply, updated_at FROM tickets WHERE admin_reply IS NOT NULL AND TRIM(admin_reply) != ''").fetchall()
        for row in old_replies:
            exists = conn.execute("SELECT 1 FROM ticket_messages WHERE ticket_code=? AND sender_type='admin' AND message=? LIMIT 1", (row["ticket_code"], row["admin_reply"])).fetchone()
            if not exists:
                conn.execute("INSERT INTO ticket_messages(ticket_code, sender_type, sender_id, message, created_at) VALUES (?, 'admin', NULL, ?, ?)", (row["ticket_code"], row["admin_reply"], row["updated_at"] or now_utc()))


def upsert_user(user):
    if not user:
        return
    now = now_utc()
    with get_connection() as conn:
        conn.execute("""INSERT INTO users(user_id, username, first_name, last_name, language, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'fa', ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
            first_name=excluded.first_name, last_name=excluded.last_name, updated_at=excluded.updated_at""",
            (user.id, user.username, user.first_name, user.last_name, now, now))


def get_language(user_id: int) -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT language FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row["language"] if row and row["language"] in T else "fa"


def get_menu_mode(user_id: int) -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT menu_mode FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row["menu_mode"] if row and row["menu_mode"] in ("inline", "keyboard") else "keyboard"


def set_menu_mode(user_id: int, mode: str):
    if mode not in ("inline", "keyboard"):
        mode = "keyboard"
    with get_connection() as conn:
        conn.execute("UPDATE users SET menu_mode=?, updated_at=? WHERE user_id=?", (mode, now_utc(), user_id))


def set_language(user_id: int, language: str):
    if language not in T:
        language = "fa"
    with get_connection() as conn:
        conn.execute("UPDATE users SET language=?, updated_at=? WHERE user_id=?", (language, now_utc(), user_id))


def create_ticket(user, category: str, message: str) -> str:
    now = now_utc()
    with get_connection() as conn:
        code = secrets.token_hex(4).upper()
        while conn.execute("SELECT 1 FROM tickets WHERE ticket_code=?", (code,)).fetchone():
            code = secrets.token_hex(4).upper()
        conn.execute("INSERT INTO tickets(ticket_code,user_id,username,full_name,category,message,status,created_at,updated_at) VALUES (?,?,?,?,?,?,'open',?,?)",
                     (code, user.id, user.username, user.full_name, category, message, now, now))
        conn.execute("INSERT INTO ticket_messages(ticket_code,sender_type,sender_id,message,created_at) VALUES (?,'user',?,?,?)", (code, user.id, message, now))
    return code


def get_ticket(ticket_code: str, user_id: int):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM tickets WHERE UPPER(ticket_code)=? AND user_id=?", (ticket_code.strip().upper(), user_id)).fetchone()


def get_ticket_admin(ticket_code: str):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM tickets WHERE UPPER(ticket_code)=?", (ticket_code.strip().upper(),)).fetchone()


def list_tickets(user_id: int, limit: int = 10):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()


def list_admin_tickets(pending: bool = False, limit: int = 20):
    with get_connection() as conn:
        if pending:
            return conn.execute("SELECT * FROM tickets WHERE status IN ('open','in_progress') ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return conn.execute("SELECT * FROM tickets ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def list_ticket_messages(ticket_code: str):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM ticket_messages WHERE ticket_code=? ORDER BY id ASC", (ticket_code,)).fetchall()


def ticket_stats(user_id: int):
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM tickets WHERE user_id=?", (user_id,)).fetchone()["n"]
        replies = conn.execute("SELECT COUNT(*) AS n FROM ticket_messages m JOIN tickets t ON t.ticket_code=m.ticket_code WHERE t.user_id=? AND m.sender_type='admin'", (user_id,)).fetchone()["n"]
    return total, replies


def save_rating(user_id: int, rating: int):
    with get_connection() as conn:
        conn.execute("INSERT INTO ratings(user_id,rating,updated_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET rating=excluded.rating, updated_at=excluded.updated_at", (user_id, rating, now_utc()))


def status_text(lang: str, status: str) -> str:
    return tr(lang, {"open": "status_open", "in_progress": "status_progress", "answered": "status_answered", "closed": "status_closed"}.get(status, "status_open"))


def keyboard_main(lang: str, admin: bool = False) -> ReplyKeyboardMarkup:
    # Keep the administrator menu separate from the normal user menu.
    if admin:
        rows = [
            [tr(lang, "admin_menu")],
            [tr(lang, "menu_mode"), tr(lang, "language")],
        ]
    else:
        rows = [
            [tr(lang, "register"), tr(lang, "track")],
            [tr(lang, "my_tickets"), tr(lang, "my_profile")],
            [tr(lang, "faq"), tr(lang, "rate")],
            [tr(lang, "support")],
            [tr(lang, "menu_mode"), tr(lang, "language")],
        ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def keyboard_cancel(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[tr(lang, "cancel"), tr(lang, "home")]], resize_keyboard=True, is_persistent=True)


def keyboard_rating(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["⭐ 1", "⭐ 2", "⭐ 3", "⭐ 4", "⭐ 5"], [tr(lang, "cancel"), tr(lang, "home")]], resize_keyboard=True, is_persistent=True)


def main_inline_keyboard(lang: str, admin: bool = False) -> InlineKeyboardMarkup:
    # Administrators see only management actions, never the regular user menu.
    if admin:
        return admin_inline_keyboard(lang)
    rows = [
        [InlineKeyboardButton(tr(lang, "register"), callback_data="user:register"), InlineKeyboardButton(tr(lang, "track"), callback_data="user:track")],
        [InlineKeyboardButton(tr(lang, "my_tickets"), callback_data="user:tickets"), InlineKeyboardButton(tr(lang, "my_profile"), callback_data="user:profile")],
        [InlineKeyboardButton(tr(lang, "faq"), callback_data="user:faq"), InlineKeyboardButton(tr(lang, "rate"), callback_data="user:rate")],
        [InlineKeyboardButton(tr(lang, "support"), callback_data="user:support")],
        [InlineKeyboardButton(tr(lang, "menu_mode"), callback_data="user:mode"), InlineKeyboardButton(tr(lang, "language"), callback_data="user:language")],
    ]
    return InlineKeyboardMarkup(rows)


def admin_inline_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(lang, "admin_new"), callback_data="admin:list:pending")],
        [InlineKeyboardButton(tr(lang, "admin_all"), callback_data="admin:list:all")],
        [InlineKeyboardButton(tr(lang, "menu_mode"), callback_data="user:mode"),
         InlineKeyboardButton(tr(lang, "language"), callback_data="user:language")],
        [InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")],
    ])


def mode_inline_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(lang, "inline_mode"), callback_data="mode:inline")],
        [InlineKeyboardButton(tr(lang, "keyboard_mode"), callback_data="mode:keyboard")],
        [InlineKeyboardButton(tr(lang, "back"), callback_data="user:home")],
    ])


def home_markup(user_id: int, lang: str):
    return main_inline_keyboard(lang, is_admin(user_id)) if get_menu_mode(user_id) == "inline" else keyboard_main(lang, is_admin(user_id))


async def ensure_user(update: Update) -> str:
    user = update.effective_user
    if user:
        upsert_user(user)
        return get_language(user.id)
    return "fa"


async def remember_screen(context: ContextTypes.DEFAULT_TYPE, message):
    """Remember the latest bot screen so the next menu action can replace it."""
    if message is not None:
        context.user_data["last_screen_message_id"] = message.message_id


async def clear_previous_screen(update: Update, context: ContextTypes.DEFAULT_TYPE, *, remove_keyboard: bool = False):
    """Delete the previous bot screen and the tapped reply-keyboard message when possible."""
    chat = update.effective_chat
    message = update.effective_message
    if not chat:
        return
    old_id = context.user_data.pop("last_screen_message_id", None)
    if old_id:
        try:
            await context.bot.delete_message(chat_id=chat.id, message_id=old_id)
        except TelegramError:
            # Telegram may refuse deletion for old messages; navigation should still work.
            pass
    if message and message.from_user and not message.from_user.is_bot:
        try:
            await context.bot.delete_message(chat_id=chat.id, message_id=message.message_id)
        except TelegramError:
            pass
    if remove_keyboard:
        try:
            notice = await context.bot.send_message(
                chat_id=chat.id,
                text="‎",
                reply_markup=ReplyKeyboardRemove(),
            )
            context.user_data["last_screen_message_id"] = notice.message_id
        except TelegramError:
            pass


async def send_home(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: Optional[str] = None):
    user = update.effective_user
    if user:
        lang = lang or get_language(user.id)
    else:
        lang = lang or "fa"
    admin = bool(user and is_admin(user.id))
    text = tr(lang, "start", name=(user.first_name if user and user.first_name else ""))
    mode = get_menu_mode(user.id) if user else "keyboard"
    # Telegram cannot attach a reply-keyboard removal and an inline keyboard to the same message.
    # In inline mode, remove the old keyboard first, then show the message with inline buttons.
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        edited = await query.edit_message_text(text, reply_markup=main_inline_keyboard(lang, admin))
        context.user_data["last_screen_message_id"] = edited.message_id
    elif update.effective_message:
        if mode == "inline":
            sent = await update.effective_message.reply_text(text, reply_markup=main_inline_keyboard(lang, admin))
        else:
            sent = await update.effective_message.reply_text(text, reply_markup=keyboard_main(lang, admin))
        await remember_screen(context, sent)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        await ensure_user(update)
        # This log makes ID mismatches easy to diagnose without exposing the bot token.
        logger.info(
            "Role check on /start: user_id=%s, configured_admin_id=%s, is_admin=%s",
            user.id,
            sorted(ADMIN_CHAT_IDS) if ADMIN_CHAT_IDS else "NOT_SET",
            is_admin(user.id),
        )
    await send_home(update, context)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = await ensure_user(update) if user else "fa"
    context.user_data.pop("pending_admin_ticket", None)
    context.user_data.pop("pending_user_action", None)
    await send_home(update, context, lang)
    return ConversationHandler.END


async def show_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket, lang: str):
    messages = list_ticket_messages(ticket["ticket_code"])
    body = tr(lang, "ticket_header", code=ticket["ticket_code"], status=status_text(lang, ticket["status"]),
              category=ticket["category"], created=ticket["created_at"], message=ticket["message"] or "—")
    replies = [m for m in messages if m["sender_type"] == "admin"]
    if not replies:
        body += tr(lang, "no_replies")
    else:
        body += tr(lang, "replies_header")
        for reply in replies[-5:]:
            body += tr(lang, "reply_line", date=reply["created_at"], message=reply["message"])
    markup = main_inline_keyboard(lang, is_admin(update.effective_user.id)) if get_menu_mode(update.effective_user.id) == "inline" else keyboard_main(lang, is_admin(update.effective_user.id))
    sent = await update.effective_message.reply_text(body[:3900], reply_markup=markup)
    await remember_screen(context, sent)


# ---------------------------------------------------------------------------
# User actions - reply-keyboard mode
# ---------------------------------------------------------------------------
async def begin_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    context.user_data["ticket_category"] = "پشتیبانی عمومی" if lang == "fa" else "General support"
    sent = await update.effective_message.reply_text(tr(lang, "choose_request"), reply_markup=keyboard_cancel(lang))
    await remember_screen(context, sent)
    return WAITING_FOR_REQUEST


async def save_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    message = update.effective_message.text.strip()
    if message in label_values("cancel") or message in label_values("home"):
        return await cancel(update, context)
    if len(message) < 5:
        await update.effective_message.reply_text(tr(lang, "too_short")); return WAITING_FOR_REQUEST
    if len(message) > 3500:
        await update.effective_message.reply_text(tr(lang, "too_long")); return WAITING_FOR_REQUEST
    category = context.user_data.get("ticket_category", "General")
    code = create_ticket(update.effective_user, category, message)
    context.user_data.pop("ticket_category", None)
    await notify_admins_new_ticket(context, code)
    await update.effective_message.reply_text(tr(lang, "saved", code=code), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))
    return ConversationHandler.END


async def begin_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    sent = await update.effective_message.reply_text(tr(lang, "choose_code"), reply_markup=keyboard_cancel(lang))
    await remember_screen(context, sent)
    return WAITING_FOR_TICKET_CODE


async def track_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    code = update.effective_message.text.strip().upper()
    if code in label_values("cancel") or code in label_values("home"):
        return await cancel(update, context)
    ticket = get_ticket(code, update.effective_user.id)
    if not ticket:
        await update.effective_message.reply_text(tr(lang, "not_found")); return WAITING_FOR_TICKET_CODE
    await show_ticket(update, context, ticket, lang)
    return ConversationHandler.END


async def begin_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    context.user_data["ticket_category"] = "ارتباط با پشتیبان" if lang == "fa" else "Contact support"
    sent = await update.effective_message.reply_text(tr(lang, "choose_support"), reply_markup=keyboard_cancel(lang))
    await remember_screen(context, sent)
    return WAITING_FOR_SUPPORT_MESSAGE


async def save_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    message = update.effective_message.text.strip()
    if message in label_values("cancel") or message in label_values("home"):
        return await cancel(update, context)
    if len(message) < 3:
        await update.effective_message.reply_text(tr(lang, "too_short")); return WAITING_FOR_SUPPORT_MESSAGE
    if len(message) > 3500:
        await update.effective_message.reply_text(tr(lang, "too_long")); return WAITING_FOR_SUPPORT_MESSAGE
    category = context.user_data.get("ticket_category", "Contact support")
    code = create_ticket(update.effective_user, category, message)
    context.user_data.pop("ticket_category", None)
    await notify_admins_new_ticket(context, code)
    await update.effective_message.reply_text(tr(lang, "support_saved", code=code), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))
    return ConversationHandler.END


async def begin_my_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    tickets = list_tickets(update.effective_user.id)
    if not tickets:
        sent = await update.effective_message.reply_text(tr(lang, "no_tickets"), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))
        await remember_screen(context, sent)
        return ConversationHandler.END
    context.user_data["ticket_codes"] = [row["ticket_code"] for row in tickets]
    rows = [[row["ticket_code"]] for row in tickets]
    rows.append([tr(lang, "back"), tr(lang, "home")])
    sent = await update.effective_message.reply_text(tr(lang, "choose_ticket"), reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True))
    await remember_screen(context, sent)
    return WAITING_FOR_TICKET_SELECTION


async def select_my_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    code = update.effective_message.text.strip().upper()
    if code in label_values("home") or code in label_values("back"):
        return await cancel(update, context)
    if code not in context.user_data.get("ticket_codes", []):
        await update.effective_message.reply_text(tr(lang, "not_found")); return WAITING_FOR_TICKET_SELECTION
    ticket = get_ticket(code, update.effective_user.id)
    if not ticket:
        await update.effective_message.reply_text(tr(lang, "not_found"), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))
        return ConversationHandler.END
    await show_ticket(update, context, ticket, lang)
    context.user_data.pop("ticket_codes", None)
    return ConversationHandler.END


async def begin_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    sent = await update.effective_message.reply_text(tr(lang, "rate_prompt"), reply_markup=keyboard_rating(lang))
    await remember_screen(context, sent)
    return WAITING_FOR_RATING


async def save_rating_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    match = re.search(r"([1-5])", update.effective_message.text)
    if not match:
        await update.effective_message.reply_text(tr(lang, "rate_invalid")); return WAITING_FOR_RATING
    rating = int(match.group(1))
    save_rating(update.effective_user.id, rating)
    await update.effective_message.reply_text(tr(lang, "rate_saved", rating=rating), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))
    return ConversationHandler.END


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    user = update.effective_user
    username = f"@{user.username}" if user.username else ("ندارد" if lang == "fa" else "Not set")
    total, replies = ticket_stats(user.id)
    caption = tr(lang, "profile_text", name=user.full_name or "—", username=username, uid=user.id, total=total, replies=replies)
    try:
        photos = await context.bot.get_user_profile_photos(user_id=user.id, limit=1)
        if photos.total_count and photos.photos:
            profile_markup = main_inline_keyboard(lang, is_admin(user.id)) if get_menu_mode(user.id) == "inline" else keyboard_main(lang, is_admin(user.id))
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photos.photos[0][-1].file_id,
                                         caption=caption[:1000], reply_markup=profile_markup)
            return
    except TelegramError:
        logger.exception("Could not retrieve profile photo for user %s", user.id)
    profile_markup = main_inline_keyboard(lang, is_admin(user.id)) if get_menu_mode(user.id) == "inline" else keyboard_main(lang, is_admin(user.id))
    sent = await update.effective_message.reply_text(caption, reply_markup=profile_markup)
    await remember_screen(context, sent)


async def show_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    rows = [[InlineKeyboardButton(tr(lang, f"faq_q{i}"), callback_data=f"faq:{i}")] for i in range(1, 6)]
    rows.append([InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")])
    await update.effective_message.reply_text(tr(lang, "faq_title"), reply_markup=InlineKeyboardMarkup(rows))


async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = await ensure_user(update)
    new_lang = "en" if current == "fa" else "fa"
    set_language(update.effective_user.id, new_lang)
    mode = get_menu_mode(update.effective_user.id)
    await update.effective_message.reply_text(tr(new_lang, "lang_changed"), reply_markup=keyboard_main(new_lang, is_admin(update.effective_user.id)))
    if mode == "inline":
        await update.effective_message.reply_text(tr(new_lang, "start", name=update.effective_user.first_name or ""), reply_markup=main_inline_keyboard(new_lang, is_admin(update.effective_user.id)))


async def begin_menu_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    sent = await update.effective_message.reply_text(tr(lang, "menu_mode"), reply_markup=mode_inline_keyboard(lang))
    await remember_screen(context, sent)
    return ConversationHandler.END


async def route_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Replace the previous screen and stale reply keyboard when a menu button is tapped."""
    text = (update.effective_message.text or "").strip()
    user = update.effective_user
    if user and get_menu_mode(user.id) == "keyboard":
        await clear_previous_screen(update, context, remove_keyboard=True)
    if text in label_values("cancel") or text in label_values("home") or text in label_values("back"):
        return await cancel(update, context)
    if text in label_values("register"):
        return await begin_request(update, context)
    if text in label_values("track"):
        return await begin_tracking(update, context)
    if text in label_values("support"):
        return await begin_support(update, context)
    if text in label_values("my_tickets"):
        return await begin_my_tickets(update, context)
    if text in label_values("rate"):
        return await begin_rating(update, context)
    if text in label_values("my_profile"):
        await show_profile(update, context); return ConversationHandler.END
    if text in label_values("faq"):
        await show_faq(update, context); return ConversationHandler.END
    if text in label_values("language"):
        await change_language(update, context); return ConversationHandler.END
    if text in label_values("menu_mode"):
        return await begin_menu_mode(update, context)
    if text in label_values("admin_menu"):
        await admin_home(update, context); return ConversationHandler.END
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    await update.effective_message.reply_text(tr(lang, "help"), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await ensure_user(update)
    await update.effective_message.reply_text(tr(lang, "id_text", uid=update.effective_user.id))


# ---------------------------------------------------------------------------
# Notify all configured administrators when a ticket is created
# ---------------------------------------------------------------------------
async def notify_admins_new_ticket(context: ContextTypes.DEFAULT_TYPE, code: str):
    if not ADMIN_CHAT_IDS:
        logger.warning("No ADMIN_CHAT_IDS configured; ticket %s was saved without admin notification.", code)
        return
    ticket = get_ticket_admin(code)
    if not ticket:
        logger.error("Cannot notify administrators: ticket %s was not found after creation.", code)
        return
    name = ticket["full_name"] or "—"
    username = f'@{ticket["username"]}' if ticket["username"] else "—"
    text = (
        "📥 درخواست پشتیبانی جدید\n\n"
        f'🎫 تیکت: {ticket["ticket_code"]}\n'
        f'👤 کاربر: {name}\n'
        f'🔹 نام کاربری: {username}\n'
        f'🆔 شناسه: {ticket["user_id"]}\n'
        f'📂 موضوع: {ticket["category"]}\n\n'
        f'📝 متن درخواست:\n{(ticket["message"] or "—")[:2500]}'
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✍️ مشاهده و پاسخ", callback_data=f'admin:ticket:{ticket["ticket_code"]}')]])
    for admin_id in sorted(ADMIN_CHAT_IDS):
        try:
            await context.bot.send_message(chat_id=admin_id, text=text[:3900], reply_markup=markup)
        except TelegramError:
            logger.exception("Could not notify administrator %s about ticket %s", admin_id, code)


# ---------------------------------------------------------------------------
# Admin panel and replying to a selected ticket
# ---------------------------------------------------------------------------
async def admin_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        if update.callback_query:
            await update.callback_query.answer(tr(lang, "admin_only"), show_alert=True)
        else:
            await update.effective_message.reply_text(tr(lang, "admin_only"))
        return ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🛡️ پنل مدیریت\nدرخواست‌ها را انتخاب کن:", reply_markup=admin_inline_keyboard(lang))
    else:
        await update.effective_message.reply_text("🛡️ پنل مدیریت\nدرخواست‌ها را انتخاب کن:", reply_markup=admin_inline_keyboard(lang))
    return ConversationHandler.END


async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE, pending: bool):
    query = update.callback_query
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        await query.answer(tr(lang, "admin_only"), show_alert=True); return
    await query.answer()
    tickets = list_admin_tickets(pending=pending)
    if not tickets:
        await query.edit_message_text(tr(lang, "admin_empty"), reply_markup=admin_inline_keyboard(lang)); return
    rows = []
    for ticket in tickets:
        status = status_text(lang, ticket["status"])
        rows.append([InlineKeyboardButton(f'{ticket["ticket_code"]} · {status}'[:64], callback_data=f'admin:ticket:{ticket["ticket_code"]}')])
    rows.append([InlineKeyboardButton(tr(lang, "admin_back"), callback_data="admin:home")])
    await query.edit_message_text(tr(lang, "admin_choose"), reply_markup=InlineKeyboardMarkup(rows))


async def admin_show_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    query = update.callback_query
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        await query.answer(tr(lang, "admin_only"), show_alert=True); return
    ticket = get_ticket_admin(code)
    await query.answer()
    if not ticket:
        await query.edit_message_text("Ticket not found.", reply_markup=admin_inline_keyboard(lang)); return
    name = ticket["full_name"] or "—"
    username = f'@{ticket["username"]}' if ticket["username"] else "—"
    body = tr(lang, "admin_ticket", code=ticket["ticket_code"], name=name, username=username,
               uid=ticket["user_id"], category=ticket["category"], status=status_text(lang, ticket["status"]),
               created=ticket["created_at"], message=ticket["message"] or "—")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ پاسخ به کاربر" if lang == "fa" else "✍️ Reply to user", callback_data=f'admin:reply:{ticket["ticket_code"]}')],
        [InlineKeyboardButton("⬅️ فهرست درخواست‌ها" if lang == "fa" else "⬅️ Request list", callback_data="admin:list:all")],
        [InlineKeyboardButton(tr(lang, "admin_back"), callback_data="admin:home")],
    ])
    await query.edit_message_text(body[:3900], reply_markup=markup)


async def begin_admin_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        await query.answer(tr(lang, "admin_only"), show_alert=True)
        return ConversationHandler.END
    code = query.data.rsplit(":", 1)[-1]
    ticket = get_ticket_admin(code)
    await query.answer()
    if not ticket:
        await query.message.reply_text("Ticket not found.")
        return ConversationHandler.END
    context.user_data["pending_admin_ticket"] = ticket["ticket_code"]
    if get_menu_mode(user.id) == "inline":
        await context.bot.send_message(chat_id=update.effective_chat.id, text=tr(lang, "keyboard_removed"), reply_markup=ReplyKeyboardRemove())
        await query.message.reply_text(tr(lang, "admin_answer", code=ticket["ticket_code"]), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(tr(lang, "cancel"), callback_data="admin:cancel_reply")]
        ]))
    else:
        await query.message.reply_text(tr(lang, "admin_answer", code=ticket["ticket_code"]), reply_markup=keyboard_cancel(lang))
    return WAITING_FOR_ADMIN_REPLY


async def cancel_admin_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        await query.answer(tr(lang, "admin_only"), show_alert=True)
        return ConversationHandler.END
    context.user_data.pop("pending_admin_ticket", None)
    await query.answer()
    await query.edit_message_text(tr(lang, "admin_reply_cancelled"))
    await context.bot.send_message(chat_id=update.effective_chat.id, text="🛡️ پنل مدیریت", reply_markup=admin_inline_keyboard(lang))
    return ConversationHandler.END


async def admin_reply_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_language(user.id) if user else "fa"
    if not user or not is_admin(user.id):
        return ConversationHandler.END
    message = (update.effective_message.text or "").strip()
    if message in label_values("cancel") or message in label_values("home"):
        context.user_data.pop("pending_admin_ticket", None)
        await update.effective_message.reply_text(tr(lang, "admin_reply_cancelled"), reply_markup=home_markup(user.id, lang))
        return ConversationHandler.END
    if not message:
        await update.effective_message.reply_text(tr(lang, "too_short")); return WAITING_FOR_ADMIN_REPLY
    if len(message) > 3500:
        await update.effective_message.reply_text(tr(lang, "too_long")); return WAITING_FOR_ADMIN_REPLY
    code = context.user_data.get("pending_admin_ticket")
    ticket = get_ticket_admin(code or "")
    if not ticket:
        context.user_data.pop("pending_admin_ticket", None)
        await update.effective_message.reply_text("Ticket not found.", reply_markup=home_markup(user.id, lang))
        return ConversationHandler.END
    stamp = now_utc()
    with get_connection() as conn:
        conn.execute("INSERT INTO ticket_messages(ticket_code,sender_type,sender_id,message,created_at) VALUES (?,'admin',?,?,?)", (code, user.id, message, stamp))
        conn.execute("UPDATE tickets SET admin_reply=?,status='answered',updated_at=? WHERE ticket_code=?", (message, stamp, code))
    context.user_data.pop("pending_admin_ticket", None)
    recipient_lang = get_language(ticket["user_id"])
    if recipient_lang == "fa":
        delivered = f"💬 پاسخ پشتیبان به درخواست تو\n\n🎫 شماره تیکت: {code}\n\n{message}\n\nبرای دیدن تمام سوابق، بخش درخواست‌های من را باز کن."
    else:
        delivered = f"💬 Support replied to your request\n\n🎫 Ticket: {code}\n\n{message}\n\nOpen My requests to view the full history."
    try:
        await context.bot.send_message(chat_id=ticket["user_id"], text=delivered)
        await update.effective_message.reply_text(tr(lang, "admin_reply_sent"), reply_markup=home_markup(user.id, lang))
    except TelegramError:
        logger.exception("Could not deliver reply for ticket %s", code)
        await update.effective_message.reply_text(tr(lang, "admin_reply_saved_failed"), reply_markup=home_markup(user.id, lang))
    return ConversationHandler.END


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    user = update.effective_user
    if not user:
        await query.answer(); return
    await ensure_user(update)
    lang = get_language(user.id)

    if data.startswith("mode:"):
        mode = data.split(":", 1)[1]
        set_menu_mode(user.id, mode)
        await query.answer()
        if mode == "inline":
            # Telegram requires a separate message to remove a reply keyboard before showing inline buttons.
            await context.bot.send_message(chat_id=update.effective_chat.id, text=tr(lang, "keyboard_removed"), reply_markup=ReplyKeyboardRemove())
            await context.bot.send_message(chat_id=update.effective_chat.id, text=tr(lang, "mode_saved_inline") + "\n\n" + tr(lang, "start", name=user.first_name or ""), reply_markup=main_inline_keyboard(lang, is_admin(user.id)))
        else:
            await query.edit_message_text(tr(lang, "mode_saved_keyboard"))
            await context.bot.send_message(chat_id=update.effective_chat.id, text=tr(lang, "start", name=user.first_name or ""), reply_markup=keyboard_main(lang, is_admin(user.id)))
        return

    if data == "user:cancel_action":
        await query.answer()
        context.user_data.pop("pending_user_action", None)
        context.user_data.pop("ticket_category", None)
        await query.edit_message_text(tr(lang, "cancelled"), reply_markup=main_inline_keyboard(lang, is_admin(user.id)))
        return

    if data.startswith("rating:"):
        await query.answer()
        rating = int(data.split(":", 1)[1])
        if rating < 1 or rating > 5:
            await query.edit_message_text(tr(lang, "rate_invalid")); return
        save_rating(user.id, rating)
        context.user_data.pop("pending_user_action", None)
        await query.edit_message_text(tr(lang, "rate_saved", rating=rating), reply_markup=main_inline_keyboard(lang, is_admin(user.id)))
        return

    if data.startswith("faq:"):
        index = int(data.split(":", 1)[1])
        await query.answer()
        await query.edit_message_text(f"{tr(lang, f'faq_q{index}')}\n\n{tr(lang, f'faq_a{index}')}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(tr(lang, "back"), callback_data="user:faq")],
            [InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")],
        ]))
        return

    if data == "admin:cancel_reply":
        await query.answer()
        context.user_data.pop("pending_admin_ticket", None)
        await query.edit_message_text(tr(lang, "admin_reply_cancelled"))
        await context.bot.send_message(chat_id=update.effective_chat.id, text="🛡️ پنل مدیریت", reply_markup=admin_inline_keyboard(lang))
        return

    if data.startswith("admin:"):
        if not is_admin(user.id):
            await query.answer(tr(lang, "admin_only"), show_alert=True); return
        if data == "admin:home":
            await admin_home(update, context)
        elif data == "admin:list:pending":
            await admin_list(update, context, pending=True)
        elif data == "admin:list:all":
            await admin_list(update, context, pending=False)
        elif data.startswith("admin:ticket:"):
            await admin_show_ticket(update, context, data.split(":", 2)[2])
        return

    if data == "user:home":
        await query.answer()
        try:
            await query.edit_message_text(
                tr(lang, "start", name=user.first_name or ""),
                reply_markup=main_inline_keyboard(lang, is_admin(user.id)),
            )
        except BadRequest as exc:
            # The user may tap Home while the exact same home screen is already shown.
            # Ignore only this harmless Telegram response; propagate other API errors.
            if "Message is not modified" not in str(exc):
                raise
        return
    if data == "user:mode":
        await query.answer()
        await query.edit_message_text(tr(lang, "menu_mode"), reply_markup=mode_inline_keyboard(lang)); return
    if data == "user:language":
        await query.answer()
        title = "🌐 انتخاب زبان / Choose your language" if lang == "fa" else "🌐 Choose your language / انتخاب زبان"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇮🇷 فارسی", callback_data="language:fa"),
             InlineKeyboardButton("🇬🇧 English", callback_data="language:en")],
            [InlineKeyboardButton(tr(lang, "back"), callback_data="user:home")],
        ])
        await query.edit_message_text(title, reply_markup=markup)
        return

    if data.startswith("language:"):
        new_lang = data.split(":", 1)[1]
        if new_lang not in T:
            await query.answer()
            return
        set_language(user.id, new_lang)
        await query.answer("زبان تغییر کرد" if new_lang == "fa" else "Language updated")
        await query.edit_message_text(
            tr(new_lang, "lang_changed") + "\\n\\n" + tr(new_lang, "start", name=user.first_name or ""),
            reply_markup=main_inline_keyboard(new_lang, is_admin(user.id)),
        )
        return
    if data == "user:faq":
        await query.answer()
        rows = [[InlineKeyboardButton(tr(lang, f"faq_q{i}"), callback_data=f"faq:{i}")] for i in range(1, 6)]
        rows.append([InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")])
        await query.edit_message_text(tr(lang, "faq_title"), reply_markup=InlineKeyboardMarkup(rows)); return
    if data == "user:profile":
        await query.answer()
        username = f"@{user.username}" if user.username else ("ندارد" if lang == "fa" else "Not set")
        total, replies = ticket_stats(user.id)
        caption = "👤  پروفایل کاربری\\n━━━━━━━━━━━━━━━━━━\\n\\n" + tr(
            lang, "profile_text", name=user.full_name or "—", username=username,
            uid=user.id, total=total, replies=replies
        )
        profile_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ بازگشت به منوی اصلی" if lang == "fa" else "⬅️ Back to main menu",
                                  callback_data="user:home")]
        ])
        # Edit the existing menu message so navigation stays on one clean screen.
        try:
            await query.edit_message_text(caption[:3900], reply_markup=profile_markup)
        except BadRequest as exc:
            if "Message is not modified" not in str(exc):
                raise
        return
    if data == "user:tickets":
        await query.answer()
        tickets = list_tickets(user.id)
        if not tickets:
            await query.message.reply_text(tr(lang, "no_tickets")); return
        rows = [[InlineKeyboardButton(row["ticket_code"], callback_data=f"user:ticket:{row['ticket_code']}")] for row in tickets]
        rows.append([InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")])
        await query.edit_message_text(tr(lang, "choose_ticket"), reply_markup=InlineKeyboardMarkup(rows)); return
    if data.startswith("user:ticket:"):
        code = data.split(":", 2)[2]
        ticket = get_ticket(code, user.id)
        await query.answer()
        if not ticket:
            await query.edit_message_text(tr(lang, "not_found")); return
        messages = list_ticket_messages(code)
        body = tr(lang, "ticket_header", code=code, status=status_text(lang, ticket["status"]), category=ticket["category"], created=ticket["created_at"], message=ticket["message"] or "—")
        replies = [m for m in messages if m["sender_type"] == "admin"]
        if not replies:
            body += tr(lang, "no_replies")
        else:
            body += tr(lang, "replies_header")
            for reply in replies[-5:]:
                body += tr(lang, "reply_line", date=reply["created_at"], message=reply["message"])
        await query.edit_message_text(body[:3900], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(tr(lang, "home"), callback_data="user:home")]])); return

    action_map = {"user:register": "register", "user:track": "track", "user:support": "support", "user:rate": "rate"}
    action = action_map.get(data)
    if action:
        await query.answer()
        context.user_data["pending_user_action"] = action
        if action == "register":
            context.user_data["ticket_category"] = "پشتیبانی عمومی" if lang == "fa" else "General support"
            prompt = tr(lang, "choose_request")
        elif action == "support":
            context.user_data["ticket_category"] = "ارتباط با پشتیبان" if lang == "fa" else "Contact support"
            prompt = tr(lang, "choose_support")
        elif action == "track":
            prompt = tr(lang, "choose_code")
        else:
            prompt = tr(lang, "rate_prompt")
        if action == "rate":
            rating_rows = [[InlineKeyboardButton(f"⭐ {i}", callback_data=f"rating:{i}") for i in range(1, 6)]]
            rating_rows.append([InlineKeyboardButton(tr(lang, "cancel"), callback_data="user:cancel_action")])
            await query.message.reply_text(prompt, reply_markup=InlineKeyboardMarkup(rating_rows))
        else:
            await query.message.reply_text(prompt, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(tr(lang, "cancel"), callback_data="user:cancel_action")]
            ]))
        return


async def process_inline_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the next text after an inline-menu action was selected."""
    action = context.user_data.get("pending_user_action")
    if not action or not update.effective_message or not update.effective_message.text:
        return False
    lang = await ensure_user(update)
    text = update.effective_message.text.strip()
    if text in label_values("cancel") or text in label_values("home"):
        context.user_data.pop("pending_user_action", None)
        context.user_data.pop("ticket_category", None)
        await send_home(update, context, lang)
        return True
    if action in ("register", "support"):
        minimum = 5 if action == "register" else 3
        if len(text) < minimum:
            await update.effective_message.reply_text(tr(lang, "too_short")); return True
        if len(text) > 3500:
            await update.effective_message.reply_text(tr(lang, "too_long")); return True
        category = context.user_data.pop("ticket_category", "General")
        code = create_ticket(update.effective_user, category, text)
        context.user_data.pop("pending_user_action", None)
        await notify_admins_new_ticket(context, code)
        key = "saved" if action == "register" else "support_saved"
        await update.effective_message.reply_text(tr(lang, key, code=code), reply_markup=main_inline_keyboard(lang, is_admin(update.effective_user.id)))
        return True
    if action == "track":
        ticket = get_ticket(text.upper(), update.effective_user.id)
        if not ticket:
            await update.effective_message.reply_text(tr(lang, "not_found")); return True
        context.user_data.pop("pending_user_action", None)
        await show_ticket(update, context, ticket, lang)
        return True
    if action == "rate":
        match = re.search(r"([1-5])", text)
        if not match:
            await update.effective_message.reply_text(tr(lang, "rate_invalid")); return True
        rating = int(match.group(1)); save_rating(update.effective_user.id, rating)
        context.user_data.pop("pending_user_action", None)
        await update.effective_message.reply_text(tr(lang, "rate_saved", rating=rating), reply_markup=main_inline_keyboard(lang, is_admin(update.effective_user.id)))
        return True
    return False


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_message:
        return
    if await process_inline_user_text(update, context):
        return
    lang = await ensure_user(update)
    await update.effective_message.reply_text(tr(lang, "unknown"), reply_markup=keyboard_main(lang, is_admin(update.effective_user.id)))


async def set_commands(application: Application):
    try:
        await application.bot.set_my_commands([
            BotCommand("start", "Open the main menu"),
            BotCommand("help", "Show help"),
            BotCommand("id", "Show your Telegram ID"),
        ])
    except TelegramError:
        logger.exception("Could not register Telegram slash-command suggestions.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled update error: %s", context.error, exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Check the .env file next to bot.py.")
    init_database()

    # Keyboard-mode conversation flow for users.
    user_conversation = ConversationHandler(
        entry_points=[
            MessageHandler(label_filter("register"), begin_request),
            MessageHandler(label_filter("track"), begin_tracking),
            MessageHandler(label_filter("support"), begin_support),
            MessageHandler(label_filter("my_tickets"), begin_my_tickets),
            MessageHandler(label_filter("rate"), begin_rating),
        ],
        states={
            WAITING_FOR_REQUEST: [MessageHandler(any_menu_label_filter(), route_menu_button), MessageHandler(filters.TEXT & ~filters.COMMAND, save_request)],
            WAITING_FOR_TICKET_CODE: [MessageHandler(any_menu_label_filter(), route_menu_button), MessageHandler(filters.TEXT & ~filters.COMMAND, track_ticket)],
            WAITING_FOR_SUPPORT_MESSAGE: [MessageHandler(any_menu_label_filter(), route_menu_button), MessageHandler(filters.TEXT & ~filters.COMMAND, save_support_message)],
            WAITING_FOR_TICKET_SELECTION: [MessageHandler(any_menu_label_filter(), route_menu_button), MessageHandler(filters.TEXT & ~filters.COMMAND, select_my_ticket)],
            WAITING_FOR_RATING: [MessageHandler(any_menu_label_filter(), route_menu_button), MessageHandler(filters.TEXT & ~filters.COMMAND, save_rating_handler)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("help", help_command),
            MessageHandler(label_filter("cancel"), cancel),
            MessageHandler(label_filter("home"), cancel),
            MessageHandler(label_filter("back"), cancel),
        ],
        allow_reentry=True,
        conversation_timeout=None,
    )

    # This conversation is entered from the administrator's selected ticket button.
    admin_reply_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(begin_admin_reply_callback, pattern=r"^admin:reply:")],
        states={WAITING_FOR_ADMIN_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reply_text)]},
        fallbacks=[
            CallbackQueryHandler(cancel_admin_reply_callback, pattern=r"^admin:cancel_reply$"),
            CommandHandler("start", start),
            MessageHandler(label_filter("cancel"), cancel),
            MessageHandler(label_filter("home"), cancel),
        ],
        allow_reentry=True,
        conversation_timeout=None,
    )

    app = (
        Application.builder().token(BOT_TOKEN)
        .connect_timeout(30).read_timeout(45).write_timeout(30).pool_timeout(30)
        .post_init(set_commands).build()
    )
    # Specific admin conversation must be registered before the general callback handler.
    app.add_handler(admin_reply_conversation)
    app.add_handler(user_conversation)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(MessageHandler(label_filter("my_profile"), show_profile))
    app.add_handler(MessageHandler(label_filter("faq"), show_faq))
    app.add_handler(MessageHandler(label_filter("language"), change_language))
    app.add_handler(MessageHandler(label_filter("menu_mode"), begin_menu_mode))
    app.add_handler(MessageHandler(label_filter("admin_menu"), admin_home))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))
    app.add_error_handler(error_handler)

    logger.info("GladiatorHelpBot starting; database: %s", DB_PATH)
    logger.info("Configured administrator IDs: %s", sorted(ADMIN_CHAT_IDS) if ADMIN_CHAT_IDS else "NOT_SET")
    if not ADMIN_CHAT_IDS:
        logger.warning("ADMIN_CHAT_IDS is not configured. Admin menu and reply delivery are disabled.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
