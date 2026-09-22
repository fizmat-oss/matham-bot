import asyncio
import copy
import html
import logging
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List

import aiohttp
import aioredis
from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
)
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient

# ============================================================
# CONFIG
# ============================================================

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("DEBUG", "0").lower() in ("1", "true", "yes") else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not configured")

ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://admin:password@localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "matham_bot")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

YEREVAN_TZ = timezone(timedelta(hours=4))
MSK_TZ = timezone(timedelta(hours=3))

CHANNEL_ID = os.environ.get("CHANNEL_ID", "@matham123456").strip() or "@matham123456"
TG_TEXT_LIMIT = 4000

# Глобальные объекты
mongo_client = AsyncIOMotorClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]
db_collection = mongo_db["catalog"]
submissions_collection = mongo_db["submissions"]
DB_DOC_ID = "catalog_main"

redis_client: Optional[aioredis.Redis] = None

bot = Bot(token=TOKEN)
dp = Dispatcher()
DATABASE = {}
BOT_USERNAME = ""
REMINDER_TASK = None

# ============================================================
# REDIS CACHE (для translation + других кэшей)
# ============================================================

async def init_redis():
    """Инициализировать Redis клиент."""
    global redis_client
    try:
        redis_client = await aioredis.from_url(REDIS_URL, encoding="utf8", decode_responses=True)
        await redis_client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis not available: %s. Using in-memory cache.", e)
        redis_client = None

async def get_cached_translation(text: str, lang: str) -> Optional[str]:
    """Получить перевод из кэша (Redis или in-memory)."""
    if not redis_client:
        return None
    key = f"trans:{lang}:{text[:100]}"
    try:
        return await redis_client.get(key)
    except Exception:
        return None

async def set_cached_translation(text: str, lang: str, translated: str):
    """Сохранить перевод в кэш."""
    if not redis_client:
        return
    key = f"trans:{lang}:{text[:100]}"
    try:
        await redis_client.setex(key, 86400 * 30, translated)  # 30 дней
    except Exception:
        pass

# ============================================================
# OPTIMIZED TRANSLATION (Google Translate + Redis cache)
# ============================================================

_MATH_PATTERNS = [
    re.compile(r"\$\$[\s\S]+?\$\$"),
    re.compile(r"\$[^\$\n]+?\$"),
    re.compile(r"\\[a-zA-Z]+(?:\{[^{}]*\})*"),
    re.compile(r"(?<![A-Za-zА-Яа-я0-9])[A-Za-z]\s*[\^_]\s*\{?[A-Za-z0-9]+"),
    re.compile(r"\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\}"),
]

def _protect_math(text: str) -> tuple:
    """Защитить LaTeX формулы от перевода."""
    protected = []
    def repl(m):
        protected.append(m.group(0))
        return f"<<M{len(protected) - 1}>>"
    for pat in _MATH_PATTERNS:
        text = pat.sub(repl, text)
    return text, protected

def _restore_math(text: str, protected: list) -> str:
    """Восстановить LaTeX формулы после перевода."""
    for i, orig in enumerate(protected):
        text = text.replace(f"<<M{i}>>", orig)
    return text

async def translate_text(text: str, target_lang: str) -> str:
    """Перевести текст (с кэшем через Redis)."""
    if not text or not text.strip():
        return text
    if target_lang not in ("ru", "en"):
        return text

    # Проверить кэш
    cached = await get_cached_translation(text, target_lang)
    if cached:
        return cached

    working, protected = _protect_math(text)
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            params = {
                "client": "gtx",
                "sl": "auto",
                "tl": target_lang,
                "dt": "t",
                "q": working
            }
            async with session.get("https://translate.googleapis.com/translate_a/single",
                                  params=params) as resp:
                data = await resp.json()
                parts = [seg[0] for seg in data[0] if seg and seg[0]]
                translated = "".join(parts)
    except Exception as e:
        logger.warning("Translation failed: %s", e)
        translated = working

    translated = _restore_math(translated, protected)
    
    # Сохранить в кэш
    await set_cached_translation(text, target_lang, translated)
    
    return translated

async def localize(text: str, user_id: int) -> str:
    """Локализовать текст по языку пользователя."""
    if not text or not text.strip():
        return text
    lang = get_user_lang(user_id)
    if lang == "ru":
        return text
    return await translate_text(text, lang)

async def localize_list(items: list, user_id: int) -> list:
    """Локализовать список."""
    return [await localize(x, user_id) for x in items]

# ============================================================
# LOCALIZATION TEXTS
# ============================================================

TEXTS = {
    "ru": {
        "welcome_back": "👋 <b>С возвращением, {nick}!</b>",
        "hello_new": "👋 Привет, {name}!\n\nДобро пожаловать в <b>MathAm</b>!",
        "choose_language": "🌐 <b>Выберите язык / Choose your language:</b>",
        "lang_set": "✅ Язык установлен: <b>Русский</b> 🇷🇺",
        "ask_nickname": "🪪 Напишите ваш <b>никнейм</b> — под ним вас будут видеть в рейтинге.",
        "nickname_bad_slash": "⚠️ Никнейм не может начинаться с «/». Напишите другой:",
        "nickname_bad_len": "⚠️ Никнейм должен быть от 2 до 30 символов. Попробуйте ещё раз:",
        "nickname_welcome": "✅ Приятно познакомиться, <b>{nick}</b>! 🎉",
        "menu_title": "🏠 <b>Главное меню</b>\nВыберите раздел:",
        "menu_catalog": "📚 Каталог",
        "menu_search": "🏷 Поиск по тегам",
        "menu_task": "🎯 Задача дня",
        "menu_archive": "🗄 Архив задач",
        "menu_mustread": "⭐ Must-read",
        "menu_fav": "❤️ Избранное",
        "menu_rating": "🏆 Рейтинг",
        "menu_random": "🎲 Случайный материал",
        "menu_links": "🔗 Полезные ссылки",
        "menu_submit": "📤 Предложить файл",
        "menu_admin": "👑 Админ-панель",
        "menu_lang": "🌐 Язык / Language",
        "cancel_done": "❌ Отменено. /start — главное меню.",
        "back_menu": "⬅️ Главное меню",
        # ... (все остальные тексты из оригинала)
    },
    "en": {
        # ... аналогично для английского
    }
}

def get_user_lang(user_id: int) -> str:
    """Получить язык пользователя."""
    uid_str = str(user_id)
    u = DATABASE.get("users", {}).get(uid_str, {})
    lang = u.get("language") or "ru"
    return lang if lang in TEXTS else "ru"

def t(user_id: int, key: str, **kwargs) -> str:
    """Получить локализованный текст."""
    lang = get_user_lang(user_id)
    text = TEXTS.get(lang, TEXTS["ru"]).get(key) or TEXTS["ru"].get(key, key)
    try:
        return text.format(**kwargs)
    except Exception:
        return text

def is_admin(user_id: int) -> bool:
    """Проверить, администратор ли пользователь."""
    return user_id in ADMIN_IDS

def get_yerevan_date() -> str:
    """Получить текущую дату в Ереване."""
    return datetime.now(YEREVAN_TZ).strftime("%Y-%m-%d")

# ============================================================
# OPTIMIZED DATABASE HELPERS
# ============================================================

def count_solved(uid_str: str) -> int:
    """Получить количество решённых задач (из профиля пользователя)."""
    user = DATABASE.get("users", {}).get(uid_str, {})
    return user.get("solved_count", 0)

async def increment_solved(uid_str: str):
    """Увеличить счётчик решённых задач."""
    user = DATABASE.get("users", {}).get(uid_str, {})
    if user:
        user["solved_count"] = user.get("solved_count", 0) + 1
        await db_collection.update_one(
            {"_id": DB_DOC_ID},
            {"$set": {f"data.users.{uid_str}.solved_count": user["solved_count"]}},
            upsert=True
        )

async def award_points(user_id: int, points: int):
    """Выдать очки пользователю."""
    uid_str = str(user_id)
    if uid_str not in DATABASE.get("users", {}):
        return
    user = DATABASE["users"][uid_str]
    user["score"] = user.get("score", 0) + points
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$inc": {f"data.users.{uid_str}.score": points}},
        upsert=True
    )

def get_file_by_uid(uid: str) -> dict:
    """Получить файл по uid."""
    for cat_data in DATABASE.get("categories", {}).values():
        for f in cat_data.get("files", []):
            if f.get("file_unique_id") == uid:
                return f
    return {}

def get_file_categories(uid: str) -> list:
    """Получить категории файла."""
    cats = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        for f in cat_data.get("files", []):
            if f.get("file_unique_id") == uid:
                cats.append(cat_data.get("title", cat_key))
                break
    return cats

def get_catalog_files_list() -> list:
    """Получить список всех файлов (дедублицированный)."""
    files_dict = {}
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        for f in cat_data.get("files", []):
            uid = f.get("file_unique_id")
            if not uid:
                continue
            if uid not in files_dict:
                files_dict[uid] = {
                    "uid": uid,
                    "file_id": f.get("file_id"),
                    "caption": f.get("caption", "—"),
                    "categories": [cat_data.get("title", cat_key)],
                    "summary": f.get("summary", ""),
                    "tags": list(f.get("tags", [])),
                    "difficulty": f.get("difficulty") or "medium",
                    "must_read": f.get("must_read", False),
                }
            else:
                item = files_dict[uid]
                cat_title = cat_data.get("title", cat_key)
                if cat_title not in item["categories"]:
                    item["categories"].append(cat_title)
                for tag in f.get("tags", []):
                    if tag not in item["tags"]:
                        item["tags"].append(tag)
    return list(files_dict.values())

def _split_text(text: str, limit: int) -> list:
    """Разбить текст по лимиту."""
    parts = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        split = remaining.rfind("\n", 0, limit)
        if split < limit // 2:
            split = limit
        parts.append(remaining[:split])
        remaining = remaining[split:].lstrip("\n")
    return parts

# ============================================================
# SAFE SEND/EDIT WITH PHOTO
# ============================================================

async def safe_send_or_edit(target, text: str, reply_markup=None, photo_id=None, 
                           parse_mode=ParseMode.HTML):
    """Безопасно отправить или отредактировать сообщение."""
    is_message = isinstance(target, types.Message)
    chat_id = target.chat.id if is_message else target.message.chat.id

    if photo_id:
        if len(text) <= 1024:
            if is_message:
                return await target.answer_photo(photo=photo_id, caption=text,
                                                 parse_mode=parse_mode, reply_markup=reply_markup)
            msg = target.message
            try:
                await msg.delete()
            except Exception:
                pass
            return await msg.answer_photo(photo=photo_id, caption=text,
                                          parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            if is_message:
                await target.answer_photo(photo=photo_id, caption="📄")
            else:
                msg = target.message
                try:
                    await msg.delete()
                except Exception:
                    pass
                await msg.answer_photo(photo=photo_id, caption="📄")
            parts = _split_text(text, TG_TEXT_LIMIT)
            for i, part in enumerate(parts):
                mk = reply_markup if i == len(parts) - 1 else None
                try:
                    await bot.send_message(chat_id, part, parse_mode=parse_mode, reply_markup=mk)
                except Exception:
                    logger.exception("Failed to send long text part")
            return None

    if len(text) <= TG_TEXT_LIMIT:
        if is_message:
            return await target.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
        msg = target.message
        if msg.photo or msg.document:
            try:
                await msg.delete()
            except Exception:
                pass
            return await msg.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
        try:
            return await msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            return await msg.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
    else:
        parts = _split_text(text, TG_TEXT_LIMIT)
        first, rest = parts[0], parts[1:]
        if is_message:
            await target.answer(first, parse_mode=parse_mode)
        else:
            msg = target.message
            if msg.photo or msg.document:
                try:
                    await msg.delete()
                except Exception:
                    pass
                await msg.answer(first, parse_mode=parse_mode)
            else:
                try:
                    await msg.edit_text(first, parse_mode=parse_mode)
                except Exception:
                    await msg.answer(first, parse_mode=parse_mode)
        for part in rest:
            try:
                await bot.send_message(chat_id, part, parse_mode=parse_mode)
            except Exception:
                logger.exception("Failed to send long text part")
        if reply_markup:
            try:
                return await bot.send_message(chat_id, "⬇️", reply_markup=reply_markup)
            except Exception:
                pass
        return None

# ============================================================
# USER TRACKING & ACTIVITY
# ============================================================

class UserActivityMiddleware(BaseMiddleware):
    """Middleware для отслеживания активности пользователя."""
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user:
            try:
                await track_user_activity(user.id, user.username or "", user.first_name or "")
            except Exception:
                logger.exception("Failed to track user activity")
        return await handler(event, data)

async def track_user_activity(user_id: int, username: str = "", first_name: str = ""):
    """Отслеживать активность пользователя (streak, дата последней активности)."""
    uid_str = str(user_id)
    today = get_yerevan_date()
    yesterday = (datetime.now(YEREVAN_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    DATABASE.setdefault("users", {})
    if uid_str not in DATABASE["users"]:
        user_data = {
            "username": username,
            "first_name": first_name,
            "nickname": "",
            "language": "ru",
            "created_at": datetime.now(YEREVAN_TZ).isoformat(),
            "streak": 1,
            "last_active": today,
            "score": 0,
            "solved_count": 0,  # ← НОВОЕ: кэш количества решённых
            "favorites": [],
            "personal_reminder_time": None,  # ← НОВОЕ: персональное напоминание
        }
        DATABASE["users"][uid_str] = user_data
        await db_collection.update_one(
            {"_id": DB_DOC_ID},
            {"$set": {f"data.users.{uid_str}": user_data}},
            upsert=True
        )
        return

    user = DATABASE["users"][uid_str]
    updates = {}
    
    if username and user.get("username") != username:
        user["username"] = username
        updates[f"data.users.{uid_str}.username"] = username
    if first_name and user.get("first_name") != first_name:
        user["first_name"] = first_name
        updates[f"data.users.{uid_str}.first_name"] = first_name

    user.setdefault("favorites", [])
    user.setdefault("nickname", "")
    user.setdefault("language", "ru")
    user.setdefault("solved_count", 0)
    user.setdefault("personal_reminder_time", None)

    if user.get("last_active") != today:
        if user.get("last_active") == yesterday:
            user["streak"] = user.get("streak", 0) + 1
        else:
            user["streak"] = 1
        user["last_active"] = today
        updates[f"data.users.{uid_str}.streak"] = user["streak"]
        updates[f"data.users.{uid_str}.last_active"] = today

    if updates:
        await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": updates})

# ============================================================
# BROADCAST WITH FLOOD CONTROL (asyncio.Semaphore)
# ============================================================

async def broadcast_to_users(users_dict: Dict, message_fn, rate_limit: int = 25):
    """Безопасно отправить сообщение всем пользователям с flood control."""
    semaphore = asyncio.Semaphore(rate_limit)  # Макс 25 одновременно
    
    async def send_with_limit(uid_str):
        async with semaphore:
            try:
                await message_fn(int(uid_str))
                return True
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                try:
                    await message_fn(int(uid_str))
                    return True
                except Exception as ex:
                    logger.debug("Send failed for user %s: %s", uid_str, ex)
                    return False
            except Exception as ex:
                logger.debug("Send failed for user %s: %s", uid_str, ex)
                return False
    
    tasks = [send_with_limit(uid) for uid in users_dict.keys()]
    results = await asyncio.gather(*tasks)
    sent = sum(1 for r in results if r)
    failed = len(results) - sent
    return sent, failed

# ============================================================
# FSM STATES
# ============================================================

class Registration(StatesGroup):
    choosing_language = State()
    waiting_for_nickname = State()

class TagSearch(StatesGroup):
    selecting = State()

class AdminUpload(StatesGroup):
    waiting_document = State()
    waiting_title = State()
    waiting_description = State()
    choosing_tags = State()
    choosing_difficulty = State()
    choosing_categories = State()

class TaskOfDayAdmin(StatesGroup):
    waiting_for_photo = State()
    waiting_for_task_text = State()
    waiting_for_solution = State()
    waiting_for_date = State()
    choosing_difficulty = State()  # ← НОВОЕ: выбор сложности
    choosing_tags = State()         # ← НОВОЕ: выбор тегов

class UserTaskSolution(StatesGroup):
    waiting_for_solution = State()

# [... остальные StateGroups как в оригинале ...]

# ============================================================
# DATABASE INIT & DEFAULTS
# ============================================================

DEFAULT_TAGS = [
    "#геометрия", "#планиметрия", "#стереометрия", "#алгебра", "#неравенства",
    "#уравнения", "#функции", "#теориячисел", "#делимость", "#комбинаторика",
    "#графы", "#инварианты", "#матанализ", "#олимпиаднаяматематика",
    "#начинающим", "#всерос", "#подготовка",
]

DEFAULT_STATE = {
    "categories": {
        "geometry": {"title": "📐 Геометрия", "files": []},
        "number_theory": {"title": "🔢 Теория чисел", "files": []},
        "algebra": {"title": "🧮 Алгебра", "files": []},
        "combinatorics": {"title": "🧩 Комбинаторика", "files": []},
        "higher_math": {"title": "🎓 Матанализ и высшая математика", "files": []},
    },
    "links": {
        "useful_links": {"title": "🔗 Полезные сайты", "items": []},
        "useful_videos": {"title": "🎥 Видеолекции", "items": []},
    },
    "must_read": {"title": "⭐ Must-read", "files": []},
    "daily_tasks": {},
    "tags": list(DEFAULT_TAGS),
    "users": {},
    "settings": {"reminder": {"enabled": True, "time": "19:00"}},
}

async def load_db():
    """Загрузить БД из MongoDB."""
    doc = await db_collection.find_one({"_id": DB_DOC_ID})
    if doc is None:
        data = copy.deepcopy(DEFAULT_STATE)
        await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": data}}, upsert=True)
        return data

    data = doc.get("data", copy.deepcopy(DEFAULT_STATE))
    
    # Миграция: если daily_tasks — список вместо dict, преобразовать
    for date_str, group in list(data.get("daily_tasks", {}).items()):
        if isinstance(group, list):
            data["daily_tasks"][date_str] = {"tasks": group}
        else:
            group.setdefault("tasks", [])
        
        for task in group.get("tasks", []):
            task.setdefault("task_id", uuid.uuid4().hex[:10])
            task.setdefault("text", "")
            task.setdefault("photo_file_id", None)
            task.setdefault("solution", "")
            task.setdefault("solution_photo_file_id", None)
            task.setdefault("solution_document_file_id", None)
            task.setdefault("difficulty", "medium")  # ← можно выбирать
            task.setdefault("tags", [])  # ← теги к задачам
            task.setdefault("source", "admin")
            task.setdefault("created_at", get_yerevan_date())
            task.setdefault("user_solutions", {})
            
            for uid_str, sol in task["user_solutions"].items():
                sol.setdefault("text", "")
                sol.setdefault("photo_file_id", None)
                sol.setdefault("document_file_id", None)
                sol.setdefault("username", "")
                sol.setdefault("first_name", "")
                sol.setdefault("nickname", "")
                sol.setdefault("status", "approved")
                sol.setdefault("grade", None)
                sol.setdefault("submitted_at", get_yerevan_date())
    
    # Миграция: нормализовать файлы
    for cat_key, cat_data in data.get("categories", {}).items():
        if cat_key not in DEFAULT_STATE["categories"]:
            continue
        cat_data.setdefault("title", DEFAULT_STATE["categories"][cat_key]["title"])
        cat_data.setdefault("files", [])
        for f in cat_data["files"]:
            f.setdefault("file_unique_id", str(uuid.uuid4()))
            f.setdefault("file_id", None)
            f.setdefault("caption", "—")
            f.setdefault("summary", "")
            f.setdefault("tags", [])
            f.setdefault("difficulty", "medium")
            f.setdefault("must_read", False)
            f.setdefault("added_at", get_yerevan_date())

    # Миграция: нормализовать пользователей
    for uid, user in data.get("users", {}).items():
        user.setdefault("username", "")
        user.setdefault("first_name", "")
        user.setdefault("nickname", "")
        user.setdefault("language", "ru")
        user.setdefault("created_at", datetime.now(YEREVAN_TZ).isoformat())
        user.setdefault("streak", 1)
        user.setdefault("last_active", get_yerevan_date())
        user.setdefault("score", 0)
        user.setdefault("solved_count", 0)  # ← НОВОЕ
        user.setdefault("favorites", [])
        user.setdefault("personal_reminder_time", None)  # ← НОВОЕ

    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": data}}, upsert=True)
    return data

async def save_db(db_data):
    """Сохранить БД в MongoDB."""
    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": db_data}}, upsert=True)

# ============================================================
# STARTUP & ENTRY POINT
# ============================================================

async def on_startup(bot: Bot):
    """На старт бота."""
    global DATABASE, BOT_USERNAME, REMINDER_TASK
    
    await init_redis()
    DATABASE = await load_db()
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    
    commands = [
        BotCommand(command="start", description="🏠 Menu"),
        BotCommand(command="catalog", description="📚 Catalog"),
        BotCommand(command="language", description="🌐 Language"),
        BotCommand(command="cancel", description="❌ Cancel"),
    ]
    await bot.set_my_commands(commands)
    
    total_files = sum(len(c.get("files", [])) for c in DATABASE.get("categories", {}).values())
    logger.info("Bot started: %s users, %s files, %s tags", 
                len(DATABASE.get("users", {})), total_files, len(DATABASE.get("tags", [])))

def register_middlewares():
    """Зарегистрировать middleware."""
    dp.message.outer_middleware(UserActivityMiddleware())
    dp.callback_query.outer_middleware(UserActivityMiddleware())
    dp.inline_query.outer_middleware(UserActivityMiddleware())

async def run_polling():
    """Запустить bot polling."""
    register_middlewares()
    dp.startup.register(on_startup)
    await bot.delete_webhook(drop_pending_updates=True)
    
    port = os.environ.get("PORT")
    if port:
        async def health(request: web.Request) -> web.Response:
            return web.json_response({"status": "ok", "bot": BOT_USERNAME})
        
        app = web.Application()
        app.router.add_get("/", health)
        app.router.add_get("/health", health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=int(port))
        await site.start()
        logger.info("Health-check on 0.0.0.0:%s", port)
    
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(run_polling())
