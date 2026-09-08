import asyncio
import copy
import html
import logging
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedDocument,
    InputTextMessageContent,
)
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient

# ============================================================
# CONFIG & LOGGING
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

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "matham_bot")
YEREVAN_TZ = timezone(timedelta(hours=4))

# Канал для авто-публикации задач и новых файлов (бот должен быть админом канала!)
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@matham123456").strip() or "@matham123456"

# ============================================================
# BOT + DATABASE
# ============================================================

mongo_client = AsyncIOMotorClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]
db_collection = mongo_db["catalog"]
submissions_collection = mongo_db["submissions"]
DB_DOC_ID = "catalog_main"

bot = Bot(token=TOKEN)
dp = Dispatcher()
DATABASE = {}
BOT_USERNAME = ""

# ============================================================
# DEFAULT DATABASE STATE
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
        "titu": {"title": "📘 Titu Andreescu", "files": []},
    },
    "links": {
        "useful_links": {"title": "🔗 Полезные сайты и базы задач", "items": []},
        "useful_videos": {"title": "🎥 Видеолекции и каналы", "items": []},
    },
    "must_read": {"title": "⭐ Must-read", "files": []},
    "daily_tasks": {},
    "tags": list(DEFAULT_TAGS),
    "users": {},
    "settings": {},
}

# ============================================================
# USER ACTIVITY MIDDLEWARE
# ============================================================

class UserActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user:
            try:
                await track_user_activity(user.id, user.username or "", user.first_name or "")
            except Exception:
                logger.exception("Failed to track user activity")
        return await handler(event, data)

# ============================================================
# HELPERS
# ============================================================

def get_yerevan_date() -> str:
    return datetime.now(YEREVAN_TZ).strftime("%Y-%m-%d")

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_file_by_uid(uid: str) -> dict:
    for cat_data in DATABASE.get("categories", {}).values():
        for f in cat_data.get("files", []):
            if f.get("file_unique_id") == uid:
                return f
    return {}

def get_file_categories(uid: str) -> list:
    cats = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        for f in cat_data.get("files", []):
            if f.get("file_unique_id") == uid:
                cats.append(cat_data.get("title", cat_key))
                break
    return cats

def get_catalog_files_list() -> list:
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
                    "caption": f.get("caption", "Без названия"),
                    "category": cat_data.get("title", cat_key),
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

async def safe_send_or_edit(target, text: str, reply_markup=None, photo_id=None, parse_mode=ParseMode.HTML):
    is_message = isinstance(target, types.Message)
    if is_message:
        if photo_id:
            return await target.answer_photo(photo=photo_id, caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
        return await target.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)

    msg = target.message
    if photo_id:
        try:
            await msg.delete()
        except Exception:
            pass
        return await msg.answer_photo(photo=photo_id, caption=text, parse_mode=parse_mode, reply_markup=reply_markup)

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

async def track_user_activity(user_id: int, username: str = "", first_name: str = ""):
    uid_str = str(user_id)
    today = get_yerevan_date()
    yesterday = (datetime.now(YEREVAN_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    DATABASE.setdefault("users", {})
    if uid_str not in DATABASE["users"]:
        user_data = {
            "username": username,
            "first_name": first_name,
            "nickname": "",
            "created_at": datetime.now(YEREVAN_TZ).isoformat(),
            "streak": 1,
            "last_active": today,
            "score": 0,
            "favorites": [],
        }
        DATABASE["users"][uid_str] = user_data
        await db_collection.update_one(
            {"_id": DB_DOC_ID},
            {"$set": {f"data.users.{uid_str}": user_data}},
            upsert=True,
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

async def award_points(user_id: int, points: int):
    uid_str = str(user_id)
    if uid_str not in DATABASE.get("users", {}):
        await track_user_activity(user_id, "", "")
    if uid_str not in DATABASE.get("users", {}):
        return
    DATABASE["users"][uid_str]["score"] = DATABASE["users"][uid_str].get("score", 0) + points
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {f"data.users.{uid_str}.score": DATABASE["users"][uid_str]["score"]}},
    )

def get_nickname(uid_str: str) -> str:
    u = DATABASE.get("users", {}).get(uid_str, {})
    return u.get("nickname") or u.get("username") or u.get("first_name") or f"id{uid_str}"

def user_display(uid_str: str) -> str:
    """Ник + TG-имя (HTML) для рейтинга и статистики."""
    u = DATABASE.get("users", {}).get(uid_str, {})
    nick = u.get("nickname") or u.get("username") or f"id{uid_str}"
    tg = u.get("first_name") or ""
    uname = u.get("username") or ""
    parts = []
    if tg:
        parts.append(html.escape(tg))
    if uname:
        parts.append("@" + html.escape(uname))
    suffix = f" <i>({', '.join(parts)})</i>" if parts else ""
    return f"{html.escape(nick)}{suffix}"

def sol_display(s: dict, uid_str: str) -> str:
    """Ник + TG-имя (HTML) для карточки решения."""
    u = DATABASE.get("users", {}).get(uid_str, {})
    nick = s.get("nickname") or u.get("nickname") or f"id{uid_str}"
    tg = s.get("first_name") or u.get("first_name") or ""
    uname = s.get("username") or u.get("username") or ""
    parts = []
    if tg:
        parts.append(html.escape(tg))
    if uname:
        parts.append("@" + html.escape(uname))
    suffix = f" <i>({', '.join(parts)})</i>" if parts else ""
    return f"{html.escape(nick)}{suffix}"

def sol_button_name(s: dict, uid_str: str) -> str:
    u = DATABASE.get("users", {}).get(uid_str, {})
    return s.get("nickname") or u.get("nickname") or f"id{uid_str}"

def get_task(date_str: str, idx: int) -> dict:
    group = DATABASE.get("daily_tasks", {}).get(date_str, {})
    tasks = group.get("tasks", [])
    if 0 <= idx < len(tasks):
        return tasks[idx]
    return {}

def get_dates_sorted() -> list:
    return sorted(DATABASE.get("daily_tasks", {}).keys(), reverse=True)

def count_solved(uid_str: str) -> int:
    n = 0
    for group in DATABASE.get("daily_tasks", {}).values():
        for task in group.get("tasks", []):
            s = (task.get("user_solutions") or {}).get(uid_str)
            if s and s.get("status") == "approved":
                n += 1
    return n

def update_file_field(uid: str, field: str, value) -> int:
    count = 0
    for cat_data in DATABASE.get("categories", {}).values():
        for f in cat_data.get("files", []):
            if f.get("file_unique_id") == uid:
                f[field] = value
                count += 1
    return count

def normalize_tags_input(raw: str) -> list:
    tags = []
    for part in re.split(r"[,;\n]", raw):
        tag = re.sub(r"[^#\wа-яА-ЯёЁ-]", "", part.strip().replace(" ", "-"))
        if tag and not tag.startswith("#"):
            tag = "#" + tag
        if tag and 2 <= len(tag) <= 40 and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag)
    return tags[:10]

# ============================================================
# DATABASE LOAD & MIGRATIONS
# ============================================================

async def load_db():
    doc = await db_collection.find_one({"_id": DB_DOC_ID})
    if doc is None:
        logger.info("MongoDB empty - creating DEFAULT_STATE")
        data = copy.deepcopy(DEFAULT_STATE)
        await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": data}}, upsert=True)
        return data

    data = doc.get("data", copy.deepcopy(DEFAULT_STATE))
    for key, value in DEFAULT_STATE.items():
        if key not in data:
            data[key] = copy.deepcopy(value)

    for cat_key, default_cat in DEFAULT_STATE["categories"].items():
        if cat_key not in data["categories"]:
            data["categories"][cat_key] = copy.deepcopy(default_cat)
        cat_data = data["categories"][cat_key]
        cat_data.setdefault("title", default_cat["title"])
        cat_data.setdefault("files", [])
        for f in cat_data["files"]:
            f.setdefault("file_unique_id", str(uuid.uuid4()))
            f.setdefault("file_id", None)
            f.setdefault("caption", "Без названия")
            f.setdefault("summary", "")
            f.setdefault("tags", [])
            f.setdefault("difficulty", "medium")
            f.setdefault("must_read", False)
            f.setdefault("added_at", get_yerevan_date())

    for sec_key, default_sec in DEFAULT_STATE["links"].items():
        if sec_key not in data["links"]:
            data["links"][sec_key] = copy.deepcopy(default_sec)
        data["links"][sec_key].setdefault("title", default_sec["title"])
        data["links"][sec_key].setdefault("items", [])

    if not data.get("tags"):
        data["tags"] = list(DEFAULT_TAGS)

    for uid, user in data["users"].items():
        user.setdefault("username", "")
        user.setdefault("first_name", "")
        user.setdefault("nickname", "")
        user.setdefault("created_at", datetime.now(YEREVAN_TZ).isoformat())
        user.setdefault("streak", 1)
        user.setdefault("last_active", get_yerevan_date())
        user.setdefault("score", 0)
        user.setdefault("favorites", [])

    for date_str, group in list(data["daily_tasks"].items()):
        if isinstance(group, list) or (isinstance(group, dict) and "tasks" not in group):
            group = {"tasks": [group] if isinstance(group, dict) else group}
            data["daily_tasks"][date_str] = group
        group.setdefault("tasks", [])
        for i, task in enumerate(group["tasks"]):
            task.setdefault("task_id", uuid.uuid4().hex[:10])
            task.setdefault("text", "")
            task.setdefault("photo_file_id", None)
            task.setdefault("solution", "")
            task.setdefault("solution_photo_file_id", None)
            task.setdefault("solution_document_file_id", None)
            task.setdefault("difficulty", "medium")
            task.setdefault("tags", [])
            task.setdefault("source", "admin")
            task.setdefault("created_at", get_yerevan_date())
            task.setdefault("user_solutions", {})
            task["number"] = i + 1
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

    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": data}}, upsert=True)
    return data

async def save_db(db_data):
    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": db_data}}, upsert=True)

async def save_submission(sub_id: str, data: dict):
    await submissions_collection.update_one({"_id": sub_id}, {"$set": data}, upsert=True)

async def get_submission(sub_id: str) -> dict:
    doc = await submissions_collection.find_one({"_id": sub_id})
    return doc if doc else {}

# ============================================================
# FSM STATES
# ============================================================

class Registration(StatesGroup):
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

class UserSubmit(StatesGroup):
    waiting_file = State()
    waiting_title = State()
    choosing_tags = State()

class AddTag(StatesGroup):
    waiting_for_text = State()

class AddLink(StatesGroup):
    waiting_for_text = State()

class EditFile(StatesGroup):
    waiting_for_document = State()
    waiting_for_title = State()
    waiting_for_tags = State()

class TaskOfDayAdmin(StatesGroup):
    waiting_for_photo = State()
    waiting_for_task_text = State()
    waiting_for_solution = State()
    waiting_for_date = State()

class UserTaskSolution(StatesGroup):
    waiting_for_solution = State()

class BroadcastAdmin(StatesGroup):
    waiting_for_message = State()

# ============================================================
# KEYBOARDS
# ============================================================

DIFF_NAMES = {
    "easy": "🟢 Easy (Базовый)",
    "medium": "🟡 Medium (Регион)",
    "hard": "🔴 Hard (Всерос / Финал)",
    "imo": "🔥 IMO (Международный)",
}

def get_main_menu_keyboard(user_id: int):
    builder = [
        [InlineKeyboardButton(text="📚 Каталог", callback_data="menu:catalog"),
         InlineKeyboardButton(text="🏷 Поиск по тегам", callback_data="search:main")],
        [InlineKeyboardButton(text="🎯 Задача дня", callback_data="task:show"),
         InlineKeyboardButton(text="🗄 Архив задач", callback_data="task:archive")],
        [InlineKeyboardButton(text="⭐ Must-read", callback_data="mustread:main"),
         InlineKeyboardButton(text="❤️ Избранное", callback_data="favorites:main")],
        [InlineKeyboardButton(text="🏆 Рейтинг", callback_data="rating:main"),
         InlineKeyboardButton(text="🎲 Случайный материал", callback_data="challenge:main")],
        [InlineKeyboardButton(text="🔗 Полезные ссылки", callback_data="links:main")],
        [InlineKeyboardButton(text="📤 Предложить файл", callback_data="submit:start")],
    ]
    if is_admin(user_id):
        builder.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_catalog_keyboard():
    builder = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        count = len(cat_data.get("files", []))
        builder.append([InlineKeyboardButton(
            text=f"{cat_data['title']} ({count})",
            callback_data=f"cat:{cat_key}",
        )])
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_file_view_keyboard(uid: str, user_id: int):
    uid_str = str(user_id)
    user_favs = DATABASE.get("users", {}).get(uid_str, {}).get("favorites", [])
    is_fav = uid in user_favs
    fav_text = "💔 Убрать из избранного" if is_fav else "❤️ В избранное"

    rows = [
        [InlineKeyboardButton(text="📥 Получить файл", callback_data=f"file:get:{uid}")],
        [InlineKeyboardButton(text=fav_text, callback_data=f"fav:toggle:{uid}")],
    ]
    if is_admin(user_id):
        rows.append([
            InlineKeyboardButton(text="✏️ Изменить", callback_data=f"admin:edit_file:{uid}"),
            InlineKeyboardButton(text="⭐ Must-read", callback_data=f"mustread:toggle:{uid}"),
        ])
        rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:del_file:{uid}")])
    rows.append([InlineKeyboardButton(text="⬅️ Каталог", callback_data="menu:catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_task_keyboard(date_str: str, task_idx: int, user_id: int):
    task = get_task(date_str, task_idx)
    if not task:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
    uid_str = str(user_id)
    sol = (task.get("user_solutions") or {}).get(uid_str)
    rows = []
    if sol is None or sol.get("status") == "rejected":
        rows.append([InlineKeyboardButton(text="📝 Отправить решение", callback_data=f"task:solve:{date_str}:{task_idx}")])
    elif sol.get("status") == "pending":
        rows.append([InlineKeyboardButton(text="⏳ Решение на проверке", callback_data="noop")])
    else:
        grade = sol.get("grade")
        label = f"✅ Зачтено · {grade}/10" if grade else "✅ Зачтено"
        rows.append([InlineKeyboardButton(text=label, callback_data="noop")])

    if task.get("solution") or task.get("solution_photo_file_id") or task.get("solution_document_file_id"):
        rows.append([InlineKeyboardButton(text="💡 Решение автора", callback_data=f"task:show_sol:{date_str}:{task_idx}")])

    # Раздел решений участников — виден ВСЕГДА
    approved = [s for s in (task.get("user_solutions") or {}).values() if s.get("status") == "approved"]
    rows.append([InlineKeyboardButton(text=f"👥 Решения участников ({len(approved)})",
                                      callback_data=f"task:sols:{date_str}:{task_idx}")])

    if is_admin(user_id):
        rows.append([InlineKeyboardButton(text="📢 Разослать задачу", callback_data=f"task:bcast:{date_str}:{task_idx}")])

    tasks_total = len(DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", []))
    nav = []
    if task_idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"task:view:{date_str}:{task_idx - 1}"))
    if task_idx < tasks_total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"task:view:{date_str}:{task_idx + 1}"))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(text="🗄 Архив", callback_data="task:archive"),
        InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_tag_toggle_keyboard(selected: list, prefix: str, done_cb: str,
                            skip_text: str = None, skip_cb: str = None):
    tags = DATABASE.get("tags", [])
    rows, row = [], []
    for i, tag in enumerate(tags):
        mark = "✅ " if tag in selected else ""
        row.append(InlineKeyboardButton(text=f"{mark}{tag}", callback_data=f"{prefix}:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    done_row = [InlineKeyboardButton(text="💾 Далее", callback_data=done_cb)]
    if skip_text and skip_cb:
        done_row.append(InlineKeyboardButton(text=skip_text, callback_data=skip_cb))
    rows.append(done_row)
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_category_toggle_keyboard(selected: list, publish_cb: str = "upl:publish"):
    rows = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        mark = "✅ " if cat_key in selected else "▫️ "
        rows.append([InlineKeyboardButton(text=f"{mark}{cat_data.get('title', cat_key)}",
                                          callback_data=f"upl:cat:{cat_key}")])
    rows.append([InlineKeyboardButton(text="✅ Опубликовать", callback_data=publish_cb)])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_links_keyboard():
    builder = []
    for sec_key, sec_data in DATABASE.get("links", {}).items():
        builder.append([InlineKeyboardButton(text=sec_data.get("title", sec_key),
                                             callback_data=f"links:sec:{sec_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_links_section_keyboard(sec_key: str, user_id: int):
    sec = DATABASE.get("links", {}).get(sec_key, {})
    items = sec.get("items", [])
    builder = []
    for idx, item in enumerate(items):
        builder.append([InlineKeyboardButton(text=item.get("title", f"Ссылка #{idx + 1}"),
                                             url=item.get("url", ""))])
        if is_admin(user_id):
            builder.append([InlineKeyboardButton(text=f"🗑 Удалить #{idx + 1}",
                                                 callback_data=f"links:del:{sec_key}:{idx}")])
    if is_admin(user_id):
        builder.append([InlineKeyboardButton(text="➕ Добавить ссылку", callback_data=f"links:add:{sec_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="links:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_admin_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Загрузить материал", callback_data="admin:upload")],
        [InlineKeyboardButton(text="🎯 Добавить задачу дня", callback_data="admin:add_task")],
        [InlineKeyboardButton(text="🏷 Управление тегами", callback_data="admin:tags")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📥 Заявки на файлы", callback_data="admin:submissions")],
        [InlineKeyboardButton(text="🧩 Решения на проверку", callback_data="admin:pending_sols")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")],
    ])

# ============================================================
# RENDER HELPERS
# ============================================================

def format_file_info(f: dict, cats: list) -> str:
    lines = [f"📖 <b>{html.escape(f.get('caption') or 'Без названия')}</b>"]
    if cats:
        lines.append(f"📂 Раздел: {html.escape(' · '.join(cats))}")
    lines.append(f"🎯 Уровень: {DIFF_NAMES.get(f.get('difficulty') or 'medium', DIFF_NAMES['medium'])}")
    tags = " ".join(f.get("tags") or [])
    if tags:
        lines.append(f"🏷 {html.escape(tags)}")
    summary = (f.get("summary") or "").strip()  # описание необязательное
    if summary:
        lines.append(f"\n📝 {html.escape(summary)}")
    return "\n".join(lines)

async def show_file_card(target, uid: str, user_id: int) -> bool:
    f = get_file_by_uid(uid)
    if not f:
        return False
    await safe_send_or_edit(target, format_file_info(f, get_file_categories(uid)),
                            reply_markup=get_file_view_keyboard(uid, user_id))
    return True

async def show_task(target, date_str: str, task_idx: int):
    task = get_task(date_str, task_idx)
    total = len(DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", []))
    if not task:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
        await safe_send_or_edit(target, "🎯 Задача не найдена.", reply_markup=markup)
        return
    text = (
        f"🎯 <b>Задача дня</b> · {date_str}\n"
        f"<i>№ {task_idx + 1} из {total}</i>\n\n"
        f"{html.escape(task.get('text') or 'Текст задачи — на фото.')}"
    )
    await safe_send_or_edit(target, text,
                            reply_markup=get_task_keyboard(date_str, task_idx, target.from_user.id),
                            photo_id=task.get("photo_file_id"))

async def render_mustread(target, user_id: int):
    files = [f for f in get_catalog_files_list() if f.get("must_read")]
    builder = []
    if files:
        for f in files:
            builder.append([InlineKeyboardButton(text=f"⭐ {f['caption'][:55]}",
                                                 callback_data=f"file:view:{f['uid']}")])
            if is_admin(user_id):
                builder.append([InlineKeyboardButton(text="✩ Убрать из must-read",
                                                     callback_data=f"mustread:toggle:{f['uid']}")])
        text = "⭐ <b>Must-read</b>\nМатериалы, которые стоит изучить каждому олимпиаднику:"
    else:
        text = "⭐ <b>Must-read</b>\n\nСписок пока пуст."
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    await safe_send_or_edit(target, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))

async def show_links_section(target, sec_key: str, user_id: int):
    sec = DATABASE.get("links", {}).get(sec_key, {})
    items = sec.get("items", [])
    title = html.escape(sec.get("title", sec_key))
    if items:
        lines = [f"🔗 <b>{title}</b>\n"]
        for i, item in enumerate(items, 1):
            url = html.escape(item.get("url", ""))
            name = html.escape(item.get("title") or item.get("url", "Ссылка"))
            lines.append(f"{i}. <a href=\"{url}\">{name}</a>")
        text = "\n".join(lines)
    else:
        text = f"🔗 <b>{title}</b>\n\nВ этом разделе пока нет ссылок."
    await safe_send_or_edit(target, text, reply_markup=get_links_section_keyboard(sec_key, user_id))

ARCHIVE_PAGE_SIZE = 8

async def render_archive(target, page: int):
    dates = get_dates_sorted()
    markup_empty = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
    if not dates:
        await safe_send_or_edit(target, "🗄 <b>Архив задач</b>\n\nЗадач пока нет.", reply_markup=markup_empty)
        return
    total_pages = (len(dates) + ARCHIVE_PAGE_SIZE - 1) // ARCHIVE_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    chunk = dates[page * ARCHIVE_PAGE_SIZE:(page + 1) * ARCHIVE_PAGE_SIZE]
    rows = []
    for d in chunk:
        n = len(DATABASE.get("daily_tasks", {}).get(d, {}).get("tasks", []))
        rows.append([InlineKeyboardButton(text=f"📅 {d} · {n} зад.", callback_data=f"task:view:{d}:0")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"arch:page:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"arch:page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🎯 Сегодня", callback_data="task:show")])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    text = (f"🗄 <b>Архив задач</b>\nДней с задачами: {len(dates)}\n"
            f"Страница {page + 1} из {total_pages}")
    await safe_send_or_edit(target, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

# ============================================================
# TASK BROADCAST (users + channel)
# ============================================================

async def broadcast_task(date_str: str, task_idx: int, report_msg: types.Message = None):
    task = get_task(date_str, task_idx)
    if not task:
        return
    tasks_total = len(DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", []))
    text = (
        f"🎯 <b>Задача дня</b> · {date_str}\n"
        f"<i>№ {task_idx + 1} из {tasks_total}</i>\n\n"
        f"{html.escape((task.get('text') or 'Текст задачи — на фото.')[:850])}"
    )
    if BOT_USERNAME:
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🤖 Решить в боте",
                                 url=f"https://t.me/{BOT_USERNAME}?start=task_{date_str}_{task_idx}")
        ]])
    else:
        markup = None

    channel_ok = True
    try:
        if task.get("photo_file_id"):
            await bot.send_photo(CHANNEL_ID, photo=task["photo_file_id"],
                                 caption=text, parse_mode=ParseMode.HTML, reply_markup=markup)
        else:
            await bot.send_message(CHANNEL_ID, text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception as e:
        channel_ok = False
        logger.warning("Channel post failed: %s", e)

    sent, failed = 0, 0
    for uid_str in list(DATABASE.get("users", {}).keys()):
        try:
            if task.get("photo_file_id"):
                await bot.send_photo(int(uid_str), photo=task["photo_file_id"],
                                     caption=text, parse_mode=ParseMode.HTML, reply_markup=markup)
            else:
                await bot.send_message(int(uid_str), text, parse_mode=ParseMode.HTML, reply_markup=markup)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                if task.get("photo_file_id"):
                    await bot.send_photo(int(uid_str), photo=task["photo_file_id"],
                                         caption=text, parse_mode=ParseMode.HTML, reply_markup=markup)
                else:
                    await bot.send_message(int(uid_str), text, parse_mode=ParseMode.HTML, reply_markup=markup)
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    if report_msg:
        report = f"✅ Задача опубликована.\n👥 Доставлено: {sent} · Ошибок: {failed}."
        if not channel_ok:
            report += "\n⚠️ Не удалось отправить в канал — добавьте бота администратором канала."
        await report_msg.answer(report)

# ============================================================
# FILE ANNOUNCE TO CHANNEL (каждый новый файл)
# ============================================================

async def announce_file_to_channel(entry: dict, cat_titles: list):
    if not entry.get("file_id"):
        return
    tags = " ".join(entry.get("tags", []))
    lines = [
        "📚 <b>Новый материал в библиотеке MathAm</b>",
        "",
        f"📖 <b>{html.escape(entry.get('caption') or 'Без названия')}</b>",
        f"📂 Раздел: {html.escape(' · '.join(cat_titles) or '—')}",
    ]
    if tags:
        lines.append(f"🏷 {html.escape(tags)}")
    summary = (entry.get("summary") or "").strip()
    if summary:
        lines.append(f"\n📝 {html.escape(summary[:500])}")
    text = "\n".join(lines)
    markup = None
    if BOT_USERNAME:
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🤖 Открыть в боте",
                                 url=f"https://t.me/{BOT_USERNAME}?start=file_{entry['file_unique_id']}")
        ]])
    try:
        await bot.send_document(CHANNEL_ID, document=entry["file_id"],
                                caption=text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception as e:
        logger.warning("Channel file post failed: %s", e)
        try:
            await bot.send_message(CHANNEL_ID, text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            logger.warning("Channel file message also failed")

# ============================================================
# TAG TOGGLE (shared)
# ============================================================

async def toggle_tag_by_index(callback: types.CallbackQuery, state: FSMContext):
    try:
        i = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("Ошибка", show_alert=True)
        return None
    tags = DATABASE.get("tags", [])
    if not (0 <= i < len(tags)):
        await callback.answer("Тег не найден", show_alert=True)
        return None
    tag = tags[i]
    data = await state.get_data()
    selected = list(data.get("selected_tags", []))
    if tag in selected:
        selected.remove(tag)
        removed = True
    else:
        selected.append(tag)
        removed = False
    await state.update_data(selected_tags=selected)
    return selected, tag, removed

# ============================================================
# COMMANDS
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    await track_user_activity(message.from_user.id, message.from_user.username or "",
                              message.from_user.first_name or "")

    # Deep links: task_YYYY-MM-DD_idx / file_uid
    args = (command.args or "").strip()
    target = None
    if args.startswith("task_"):
        parts = args[5:].split("_")
        date_str = parts[0] if parts else ""
        try:
            idx = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            idx = 0
        if get_task(date_str, idx):
            target = ("task", date_str, idx)
    elif args.startswith("file_"):
        fuid = args[5:]
        if get_file_by_uid(fuid):
            target = ("file", fuid)

    uid_str = str(message.from_user.id)
    user = DATABASE.get("users", {}).get(uid_str, {})

    # Каждый новый пользователь обязан указать никнейм
    if not user.get("nickname"):
        await state.set_state(Registration.waiting_for_nickname)
        await state.update_data(after_register=target)
        await message.answer(
            f"👋 Привет, {html.escape(message.from_user.first_name)}!\n\n"
            "Добро пожаловать в <b>MathAm</b>! Прежде чем начать, представьтесь: "
            "напишите ваш <b>никнейм</b> — под ним вас будут видеть в рейтинге, "
            "ваших решениях и заявках на файлы."
        )
        return

    greeting = f"👋 <b>С возвращением, {html.escape(user.get('nickname'))}!</b>"
    if target:
        await message.answer(greeting)
        if target[0] == "task":
            await show_task(message, target[1], target[2])
        else:
            await show_file_card(message, target[1], message.from_user.id)
        return

    welcome_text = (
        f"{greeting}\n\n"
        "📚 Каталог и поиск по тегам\n"
        "🎯 Задача дня и 🗄 архив задач\n"
        "✍️ Отправляйте решения — админы проверят и поставят оценку"
    )
    await safe_send_or_edit(message, welcome_text, reply_markup=get_main_menu_keyboard(message.from_user.id))

@dp.message(StateFilter(Registration.waiting_for_nickname), F.text)
async def process_nickname(message: types.Message, state: FSMContext):
    nick = message.text.strip()
    if nick.startswith("/"):
        await message.answer("⚠️ Никнейм не может начинаться с «/». Напишите другой:")
        return
    if not (2 <= len(nick) <= 30):
        await message.answer("⚠️ Никнейм должен быть от 2 до 30 символов. Попробуйте ещё раз:")
        return
    uid_str = str(message.from_user.id)
    DATABASE.setdefault("users", {}).setdefault(uid_str, {})
    DATABASE["users"][uid_str]["nickname"] = nick
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {f"data.users.{uid_str}.nickname": nick}},
        upsert=True,
    )
    data = await state.get_data()
    target = data.get("after_register")
    await state.clear()
    await message.answer(f"✅ Приятно познакомиться, <b>{html.escape(nick)}</b>! 🎉")
    if target:
        if target[0] == "task" and get_task(target[1], target[2]):
            await show_task(message, target[1], target[2])
        elif target[0] == "file":
            await show_file_card(message, target[1], message.from_user.id)
        return
    await message.answer(
        "📚 Каталог и поиск по тегам\n"
        "🎯 Задача дня и 🗄 архив задач\n"
        "✍️ Отправляйте решения — админы проверят и поставят оценку",
        reply_markup=get_main_menu_keyboard(message.from_user.id),
    )

@dp.message(StateFilter(Registration.waiting_for_nickname))
async def process_nickname_any(message: types.Message, state: FSMContext):
    await message.answer("⚠️ Отправьте никнейм обычным текстом:")

@dp.message(Command("catalog"))
async def cmd_catalog(message: types.Message, state: FSMContext):
    await state.clear()
    await track_user_activity(message.from_user.id, message.from_user.username or "",
                              message.from_user.first_name or "")
    await safe_send_or_edit(message, "📚 <b>Каталог материалов по разделам:</b>",
                            reply_markup=get_catalog_keyboard())

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено. /start — главное меню.",
                         reply_markup=get_main_menu_keyboard(message.from_user.id))

# ============================================================
# MAIN MENU
# ============================================================

@dp.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_send_or_edit(callback, "🏠 <b>Главное меню</b>\nВыберите раздел:",
                            reply_markup=get_main_menu_keyboard(callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data == "menu:catalog")
async def cb_catalog(callback: types.CallbackQuery):
    await safe_send_or_edit(callback, "📚 <b>Каталог материалов по разделам:</b>",
                            reply_markup=get_catalog_keyboard())
    await callback.answer()

# ============================================================
# CATALOG & FILES
# ============================================================

@dp.callback_query(F.data.startswith("cat:"))
async def cb_category(callback: types.CallbackQuery):
    cat_key = callback.data.split(":", 1)[1]
    cat_data = DATABASE.get("categories", {}).get(cat_key)
    if not cat_data:
        await callback.answer("Раздел не найден.", show_alert=True)
        return
    files = cat_data.get("files", [])
    builder = []
    for f in files:
        builder.append([InlineKeyboardButton(
            text=f"📖 {(f.get('caption') or 'Без названия')[:55]}",
            callback_data=f"file:view:{f.get('file_unique_id')}",
        )])
    builder.append([InlineKeyboardButton(text="⬅️ Каталог", callback_data="menu:catalog")])
    text = f"<b>{html.escape(cat_data.get('title', cat_key))}</b>\nМатериалов: {len(files)}"
    await safe_send_or_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(F.data.startswith("file:view:"))
async def cb_file_view(callback: types.CallbackQuery):
    uid = callback.data.split(":", 2)[2]
    if not await show_file_card(callback, uid, callback.from_user.id):
        await callback.answer("Файл не найден.", show_alert=True)
        return
    await callback.answer()

@dp.callback_query(F.data.startswith("file:get:"))
async def cb_file_get(callback: types.CallbackQuery):
    uid = callback.data.split(":", 2)[2]
    f = get_file_by_uid(uid)
    if not f:
        await callback.answer("Файл не найден.", show_alert=True)
        return
    try:
        await callback.message.answer_document(
            document=f.get("file_id"),
            caption=f"📖 <b>{html.escape(f.get('caption') or 'Материал')}</b>",
            parse_mode=ParseMode.HTML,
        )
        await callback.answer("Файл отправлен ✅")
    except Exception as e:
        logger.exception("Failed to send file %s: %s", uid, e)
        await callback.answer("Не удалось отправить файл.", show_alert=True)

@dp.callback_query(F.data.startswith("fav:toggle:"))
async def cb_fav_toggle(callback: types.CallbackQuery):
    uid = callback.data.split(":", 2)[2]
    uid_str = str(callback.from_user.id)
    user = DATABASE.get("users", {}).get(uid_str)
    if user is None:
        await track_user_activity(callback.from_user.id, callback.from_user.username or "",
                                  callback.from_user.first_name or "")
        user = DATABASE.get("users", {}).get(uid_str)
    if user is None:
        await callback.answer("Ошибка, попробуйте позже.", show_alert=True)
        return
    favs = user.setdefault("favorites", [])
    if uid in favs:
        favs.remove(uid)
        msg = "💔 Удалено из избранного"
    else:
        favs.append(uid)
        msg = "❤️ Добавлено в избранное"
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {f"data.users.{uid_str}.favorites": favs}},
        upsert=True,
    )
    if await show_file_card(callback, uid, callback.from_user.id):
        await callback.answer(msg)
    else:
        await callback.answer("Файл не найден.", show_alert=True)

# ============================================================
# TAG SEARCH (simple, by tags from tag database)
# ============================================================

@dp.callback_query(F.data == "search:main")
async def cb_search_main(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(TagSearch.selecting)
    await state.update_data(selected_tags=[])
    markup = get_tag_toggle_keyboard([], "search:tag", "search:go", "♻️ Сброс", "search:reset")
    await safe_send_or_edit(
        callback,
        "🏷 <b>Поиск по тегам</b>\n\n"
        "Выберите один или несколько тегов и нажмите «🔎 Искать».\n"
        "Или просто напишите тег/слово текстом.",
        reply_markup=markup,
    )
    await callback.answer()

@dp.callback_query(StateFilter(TagSearch.selecting), F.data.startswith("search:tag:"))
async def cb_search_tag(callback: types.CallbackQuery, state: FSMContext):
    res = await toggle_tag_by_index(callback, state)
    if not res:
        return
    selected, tag, removed = res
    markup = get_tag_toggle_keyboard(selected, "search:tag", "search:go", "♻️ Сброс", "search:reset")
    await safe_send_or_edit(callback, f"🏷 <b>Поиск по тегам</b>\nВыбрано тегов: {len(selected)}",
                            reply_markup=markup)
    await callback.answer("Тег снят" if removed else "Тег выбран")

@dp.callback_query(F.data == "search:reset")
async def cb_search_reset(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(selected_tags=[])
    markup = get_tag_toggle_keyboard([], "search:tag", "search:go", "♻️ Сброс", "search:reset")
    await safe_send_or_edit(callback, "🏷 <b>Поиск по тегам</b>\nВыбор сброшен.", reply_markup=markup)
    await callback.answer()

async def show_search_results(target, results, header: str):
    if results:
        text = f"{header}\n\nНайдено материалов: <b>{len(results)}</b>"
        rows = [[InlineKeyboardButton(text=f"📖 {f['caption'][:55]}",
                                      callback_data=f"file:view:{f['uid']}")] for f in results[:20]]
    else:
        text = f"{header}\n\n😔 Ничего не найдено. Попробуйте другие теги."
        rows = []
    rows.append([InlineKeyboardButton(text="🏷 Новый поиск", callback_data="search:main")])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    await safe_send_or_edit(target, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data == "search:go")
async def cb_search_go(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_tags", [])
    if not selected:
        await callback.answer("Выберите хотя бы один тег!", show_alert=True)
        return
    files = get_catalog_files_list()
    sel_lower = {t.lower() for t in selected}
    scored = []
    for f in files:
        matches = len(sel_lower & {t.lower() for t in f.get("tags", [])})
        if matches:
            scored.append((matches, f))
    scored.sort(key=lambda x: -x[0])
    results = [f for _, f in scored]
    await show_search_results(callback, results,
                              f"🔎 <b>Результаты по тегам:</b> {html.escape(' '.join(selected))}")
    await callback.answer()

@dp.message(StateFilter(TagSearch.selecting), F.text)
async def process_search_text(message: types.Message, state: FSMContext):
    q = message.text.strip().lower().lstrip("#")
    if not q:
        await message.answer("Напишите тег или слово для поиска.")
        return
    files = get_catalog_files_list()
    results = []
    for f in files:
        hay = (f["caption"] + " " + " ".join(f.get("tags", [])) + " " + (f.get("summary") or "")).lower()
        if q in hay:
            results.append(f)
    await state.clear()
    await show_search_results(message, results, f"🔎 <b>Результаты по запросу:</b> "
                                                 f"<i>{html.escape(message.text.strip())}</i>")

# ============================================================
# TAG DATABASE (admin manages, users see in search)
# ============================================================

async def render_tag_manager(target):
    tags = DATABASE.get("tags", [])
    rows = []
    for i, tag in enumerate(tags):
        rows.append([InlineKeyboardButton(text=f"🗑 {tag}", callback_data=f"tagdel:{i}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить тег", callback_data="tagadd")])
    rows.append([InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin:main")])
    text = (f"🏷 <b>База тегов</b> (всего: {len(tags)})\n\n"
            f"Нажмите на тег, чтобы удалить его.\n"
            f"Эти теги видят все пользователи в «Поиске по тегам».")
    await safe_send_or_edit(target, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data == "admin:tags")
async def cb_admin_tags(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.clear()
    await render_tag_manager(callback)
    await callback.answer()

@dp.callback_query(F.data == "tagadd")
async def cb_tagadd(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.set_state(AddTag.waiting_for_text)
    await callback.message.answer("🏷 Отправьте новый тег (можно с # или без, можно несколько через запятую):")
    await callback.answer()

@dp.message(StateFilter(AddTag.waiting_for_text), F.text)
async def process_add_tag(message: types.Message, state: FSMContext):
    tags = DATABASE.setdefault("tags", [])
    added = []
    for tag in normalize_tags_input(message.text):
        if tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag)
            added.append(tag)
    await save_db(DATABASE)
    await state.clear()
    if added:
        await message.answer(f"✅ Добавлены теги: {html.escape(' '.join(added))}")
    else:
        await message.answer("⚠️ Новых тегов нет (пусто или дубликаты).")

@dp.callback_query(F.data.startswith("tagdel:"))
async def cb_tagdel(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    try:
        i = int(callback.data.split(":")[1])
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    tags = DATABASE.get("tags", [])
    if 0 <= i < len(tags):
        removed = tags.pop(i)
        await save_db(DATABASE)
        await render_tag_manager(callback)
        await callback.answer(f"Удалён {removed}")
    else:
        await callback.answer("Тег не найден.", show_alert=True)

# ============================================================
# FAVORITES / RATING / MUST-READ / RANDOM
# ============================================================

@dp.callback_query(F.data == "favorites:main")
async def cb_favorites(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    uid_str = str(callback.from_user.id)
    favs = DATABASE.get("users", {}).get(uid_str, {}).get("favorites", [])
    builder = []
    for fuid in favs:
        f = get_file_by_uid(fuid)
        if f:
            builder.append([InlineKeyboardButton(text=f"❤️ {(f.get('caption') or 'Материал')[:55]}",
                                                 callback_data=f"file:view:{fuid}")])
    text = "❤️ <b>Избранное</b>"
    if not builder:
        text += "\n\nПока пусто. Откройте материал в каталоге и нажмите «❤️ В избранное»."
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    await safe_send_or_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(F.data == "rating:main")
async def cb_rating(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    users = DATABASE.get("users", {})
    ranked = [kv for kv in sorted(users.items(),
                                   key=lambda kv: (kv[1].get("score", 0), kv[1].get("streak", 0)),
                                   reverse=True) if kv[1].get("score", 0) > 0][:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Рейтинг MathAm</b>\n<i>Очки — за зачтённые решения задач дня</i>\n"]
    if not ranked:
        lines.append("Пока никто не набрал очки. Решите задачу дня первым!")
    for i, (uid_str, u) in enumerate(ranked, 1):
        medal = medals[i - 1] if i <= 3 else f"{i}."
        solved = count_solved(uid_str)
        lines.append(f"{medal} {user_display(uid_str)} — {u.get('score', 0)} очк. · "
                     f"✅ {solved} · 🔥 {u.get('streak', 1)} дн.")
    me = users.get(str(callback.from_user.id), {})
    lines.append(f"\n👤 Вы: 🪪 <b>{html.escape(me.get('nickname') or '—')}</b> — "
                 f"{me.get('score', 0)} очк. · ✅ {count_solved(str(callback.from_user.id))} "
                 f"· ❤️ {len(me.get('favorites', []))}")
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
    await safe_send_or_edit(callback, "\n".join(lines), reply_markup=markup)
    await callback.answer()

@dp.callback_query(F.data == "mustread:main")
async def cb_mustread(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_mustread(callback, callback.from_user.id)
    await callback.answer()

@dp.callback_query(F.data.startswith("mustread:toggle:"))
async def cb_mustread_toggle(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов.", show_alert=True)
        return
    uid = callback.data.split(":", 2)[2]
    new_val = None
    count = 0
    for cat_data in DATABASE.get("categories", {}).values():
        for f in cat_data.get("files", []):
            if f.get("file_unique_id") == uid:
                f["must_read"] = not f.get("must_read", False)
                new_val = f["must_read"]
                count += 1
    if not count:
        await callback.answer("Файл не найден.", show_alert=True)
        return
    await save_db(DATABASE)
    if new_val:
        await show_file_card(callback, uid, callback.from_user.id)
        await callback.answer("⭐ Добавлено в must-read")
    else:
        await render_mustread(callback, callback.from_user.id)
        await callback.answer("Убрано из must-read")

@dp.callback_query(F.data == "challenge:main")
async def cb_challenge(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    files = get_catalog_files_list()
    if not files:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
        await safe_send_or_edit(callback, "🎲 В библиотеке пока нет материалов.", reply_markup=markup)
        await callback.answer()
        return
    chosen = random.choice(files)
    await show_file_card(callback, chosen["uid"], callback.from_user.id)
    await callback.answer(f"🎲 {chosen['caption'][:50]}")

# ============================================================
# DAILY TASKS: VIEW / ARCHIVE / SOLVE / SOLUTIONS
# ============================================================

@dp.callback_query(F.data == "task:show")
async def cb_task_show(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    daily = DATABASE.get("daily_tasks", {})
    today = get_yerevan_date()
    if today in daily and daily[today].get("tasks"):
        date_str = today
    else:
        dates = get_dates_sorted()
        date_str = dates[0] if dates else None
    if not date_str:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
        await safe_send_or_edit(callback, "🎯 <b>Задача дня</b>\n\nЗадачи пока не опубликованы.", reply_markup=markup)
        await callback.answer()
        return
    await show_task(callback, date_str, 0)
    await callback.answer()

@dp.callback_query(F.data.startswith("task:view:"))
async def cb_task_view(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка", show_alert=True)
        return
    try:
        idx = int(parts[3])
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    await show_task(callback, parts[2], idx)
    await callback.answer()

@dp.callback_query(F.data == "task:archive")
async def cb_task_archive(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_archive(callback, 0)
    await callback.answer()

@dp.callback_query(F.data.startswith("arch:page:"))
async def cb_archive_page(callback: types.CallbackQuery):
    try:
        page = int(callback.data.split(":")[2])
    except ValueError:
        page = 0
    await render_archive(callback, page)
    await callback.answer()

@dp.callback_query(F.data.startswith("task:bcast:"))
async def cb_task_bcast(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка", show_alert=True)
        return
    date_str, idx = parts[2], int(parts[3])
    await callback.answer("⏳ Рассылаю...")
    await broadcast_task(date_str, idx, report_msg=callback.message)

@dp.callback_query(F.data.startswith("task:show_sol:"))
async def cb_task_show_sol(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка", show_alert=True)
        return
    date_str, idx = parts[2], int(parts[3])
    task = get_task(date_str, idx)
    if not task:
        await callback.answer("Задача не найдена.", show_alert=True)
        return
    sol_text = (task.get("solution") or "").strip()
    photo_id = task.get("solution_photo_file_id")
    doc_id = task.get("solution_document_file_id")
    if not sol_text and not photo_id and not doc_id:
        await callback.answer("Решение пока не добавлено.", show_alert=True)
        return
    text = f"💡 <b>Решение автора</b> (задача №{idx + 1}, {date_str})\n\n{html.escape(sol_text)}"
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="⬅️ К задаче", callback_data=f"task:view:{date_str}:{idx}")]])
    await safe_send_or_edit(callback, text, reply_markup=markup, photo_id=photo_id)
    if doc_id:
        try:
            await callback.message.answer_document(document=doc_id)
        except Exception:
            logger.exception("Failed to send solution document")
    await callback.answer()

# --- Отправка решения пользователем ---

@dp.callback_query(F.data.startswith("task:solve:"))
async def cb_task_solve(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка", show_alert=True)
        return
    date_str, idx = parts[2], int(parts[3])
    if not get_task(date_str, idx):
        await callback.answer("Задача не найдена.", show_alert=True)
        return
    await state.set_state(UserTaskSolution.waiting_for_solution)
    await state.update_data(task_date=date_str, task_idx=idx)
    await callback.message.answer("✍️ Отправьте ваше решение (текстом, фото или файлом).\n"
                                  "Оно уйдёт администраторам на проверку. /cancel — отмена.")
    await callback.answer()

@dp.message(StateFilter(UserTaskSolution.waiting_for_solution))
async def process_user_solution(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date_str, idx = data.get("task_date"), data.get("task_idx", -1)
    task = get_task(date_str, idx) if date_str else {}
    if not task:
        await state.clear()
        await message.answer("⚠️ Задача не найдена. /start")
        return
    uid_str = str(message.from_user.id)
    u = DATABASE.get("users", {}).get(uid_str, {})
    entry = {
        "text": (message.text or message.caption or "").strip(),
        "photo_file_id": message.photo[-1].file_id if message.photo else None,
        "document_file_id": message.document.file_id if message.document else None,
        "nickname": u.get("nickname") or "",
        "first_name": message.from_user.first_name or "",
        "username": message.from_user.username or "",
        "status": "pending",
        "grade": None,
        "submitted_at": datetime.now(YEREVAN_TZ).isoformat(),
    }
    if not entry["text"] and not entry["photo_file_id"] and not entry["document_file_id"]:
        await message.answer("⚠️ Отправьте решение текстом, фото или файлом.")
        return
    task.setdefault("user_solutions", {})[uid_str] = entry
    await save_db(DATABASE)
    await state.clear()
    await message.answer("✅ <b>Решение отправлено!</b>\n"
                         "Администраторы проверят его и поставят оценку — результат придёт вам в личку.")

    nick = u.get("nickname") or "—"
    tg = message.from_user.first_name or ""
    uname = message.from_user.username or ""
    context = (
        f"🧩 <b>Новое решение</b>\n"
        f"Задача: {date_str} · №{idx + 1}\n"
        f"🪪 Ник: <b>{html.escape(nick)}</b>\n"
        f"👤 TG: {html.escape(tg)}"
        + (f" · @{html.escape(uname)}" if uname else "")
        + "\n\n"
    )
    body = html.escape(entry["text"][:600])
    review_markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Засчитать", callback_data=f"solrev:ok:{date_str}:{idx}:{uid_str}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"solrev:no:{date_str}:{idx}:{uid_str}"),
    ]])
    for admin_id in ADMIN_IDS:
        try:
            if entry["photo_file_id"]:
                await bot.send_photo(admin_id, photo=entry["photo_file_id"],
                                     caption=context + body, parse_mode=ParseMode.HTML,
                                     reply_markup=review_markup)
            elif entry["document_file_id"]:
                await bot.send_document(admin_id, document=entry["document_file_id"],
                                        caption=context + body, parse_mode=ParseMode.HTML,
                                        reply_markup=review_markup)
            else:
                await bot.send_message(admin_id, context + body, parse_mode=ParseMode.HTML,
                                       reply_markup=review_markup)
        except Exception:
            logger.exception("Failed to notify admin %s", admin_id)
    await show_task(message, date_str, idx)

# --- Решения участников (всегда доступны из карточки задачи) ---

@dp.callback_query(F.data.startswith("task:sols:"))
async def cb_task_sols(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка", show_alert=True)
        return
    date_str, idx = parts[2], int(parts[3])
    task = get_task(date_str, idx)
    if not task:
        await callback.answer("Задача не найдена.", show_alert=True)
        return
    approved = [(u, s) for u, s in (task.get("user_solutions") or {}).items()
                if s.get("status") == "approved"]
    lines = [f"👥 <b>Решения участников</b> (задача №{idx + 1}, {date_str})\n"]
    builder = []
    if not approved:
        lines.append("Пока нет проверенных решений. Отправьте своё — "
                     "и, возможно, оно появится здесь первым! 🚀")
    else:
        approved.sort(key=lambda kv: -(kv[1].get("grade") or 0))
        for uid_str, s in approved:
            grade = s.get("grade")
            g = f"{grade}/10" if grade else "✓"
            snippet = (s.get("text") or "").strip()
            if s.get("photo_file_id"):
                snippet = (snippet + " [📷 фото]").strip()
            if s.get("document_file_id"):
                snippet = (snippet + " [📎 файл]").strip()
            lines.append(f"⭐ <b>{sol_display(s, uid_str)}</b> — {g}\n"
                         f"<i>{html.escape(snippet[:150])}</i>\n")
            builder.append([InlineKeyboardButton(
                text=f"👀 {sol_button_name(s, uid_str)} · {g}",
                callback_data=f"solfull:{date_str}:{idx}:{uid_str}")])
    builder.append([InlineKeyboardButton(text="⬅️ К задаче", callback_data=f"task:view:{date_str}:{idx}")])
    await safe_send_or_edit(callback, "\n".join(lines),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(F.data.startswith("solfull:"))
async def cb_solfull(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка", show_alert=True)
        return
    date_str, idx, uid_str = parts[1], int(parts[2]), parts[3]
    task = get_task(date_str, idx)
    sol = (task.get("user_solutions") or {}).get(uid_str, {})
    if not sol:
        await callback.answer("Решение не найдено.", show_alert=True)
        return
    if sol.get("status") != "approved" and not is_admin(callback.from_user.id):
        await callback.answer("Решение ещё на проверке.", show_alert=True)
        return
    grade = sol.get("grade")
    header = f"🪪 <b>{sol_display(sol, uid_str)}</b>"
    header += f" — ⭐ {grade}/10" if grade else " — ✅"
    text = sol.get("text") or ""
    caption = header + (f"\n\n{html.escape(text[:800])}" if text else "")
    try:
        if sol.get("photo_file_id"):
            await callback.message.answer_photo(photo=sol["photo_file_id"],
                                                caption=caption, parse_mode=ParseMode.HTML)
        elif sol.get("document_file_id"):
            await callback.message.answer_document(document=sol["document_file_id"],
                                                   caption=caption, parse_mode=ParseMode.HTML)
        elif text:
            await callback.message.answer(caption, parse_mode=ParseMode.HTML)
        else:
            await callback.answer("Решение без содержимого.", show_alert=True)
            return
        await callback.answer()
    except Exception:
        logger.exception("Failed to show solution")
        await callback.answer("Не удалось показать решение.", show_alert=True)

# --- Проверка решений админами (зачесть/отклонить + оценка кнопками) ---

@dp.callback_query(F.data.startswith("solrev:"))
async def cb_solrev(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("Ошибка", show_alert=True)
        return
    action, date_str, idx_s, uid_str = parts[1], parts[2], parts[3], parts[4]
    try:
        idx = int(idx_s)
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    task = get_task(date_str, idx)
    sol = (task.get("user_solutions") or {}).get(uid_str)
    if not sol:
        await callback.answer("Решение не найдено.", show_alert=True)
        return

    if action == "no":
        sol["status"] = "rejected"
        sol["grade"] = None
        sol["reviewed_at"] = datetime.now(YEREVAN_TZ).isoformat()
        await save_db(DATABASE)
        try:
            await bot.send_message(int(uid_str),
                                   f"❌ Ваше решение задачи {date_str} (№{idx + 1}) не зачтено. "
                                   f"Попробуйте ещё раз!")
        except Exception:
            pass
        await callback.message.answer("❌ Отклонено.")
        await callback.answer("Отклонено")
        return

    sol["status"] = "approved"
    sol["reviewed_at"] = datetime.now(YEREVAN_TZ).isoformat()
    await save_db(DATABASE)
    name = sol.get("nickname") or get_nickname(uid_str)
    rows = []
    for start in (1, 6):
        rows.append([InlineKeyboardButton(text=str(n), callback_data=f"grade:{n}:{date_str}:{idx}:{uid_str}")
                     for n in range(start, start + 5)])
    rows.append([InlineKeyboardButton(text="✓ Без оценки", callback_data=f"grade:0:{date_str}:{idx}:{uid_str}")])
    await callback.message.answer(f"✅ Решение от 🪪 <b>{html.escape(name)}</b> зачтено.\n"
                                  f"⭐ Поставьте оценку (очки = оценка):",
                                  parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer("Засчитано")

@dp.callback_query(F.data.startswith("grade:"))
async def cb_grade(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("Ошибка", show_alert=True)
        return
    try:
        n = int(parts[1])
        idx = int(parts[3])
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    date_str, uid_str = parts[2], parts[4]
    if not (0 <= n <= 10):
        await callback.answer("Ошибка", show_alert=True)
        return
    task = get_task(date_str, idx)
    sol = (task.get("user_solutions") or {}).get(uid_str)
    if not sol or sol.get("status") != "approved":
        await callback.answer("Решение не найдено или не зачтено.", show_alert=True)
        return

    prev_grade = sol.get("grade") or 0
    new_grade = n
    sol["grade"] = new_grade if new_grade > 0 else None
    await save_db(DATABASE)

    delta = new_grade - prev_grade
    if delta != 0:
        await award_points(int(uid_str), delta)

    name = sol.get("nickname") or get_nickname(uid_str)
    try:
        if new_grade > 0:
            if prev_grade:
                await bot.send_message(int(uid_str),
                                       f"⭐ Оценка вашего решения (задача {date_str}, №{idx + 1}) "
                                       f"обновлена: {new_grade}/10 (очки: {new_grade}).")
            else:
                await bot.send_message(int(uid_str),
                                       f"✅ Ваше решение задачи {date_str} (№{idx + 1}) зачтено!\n"
                                       f"⭐ Оценка: {new_grade}/10 (+{new_grade} очков)\n"
                                       f"Теперь его могут увидеть другие участники.")
        else:
            await bot.send_message(int(uid_str),
                                   f"✅ Ваше решение задачи {date_str} (№{idx + 1}) зачтено!\n"
                                   f"Теперь его могут увидеть другие участники.")
    except Exception:
        pass

    label = f"{new_grade}/10" if new_grade > 0 else "без оценки"
    await callback.message.answer(f"⭐ Оценка для 🪪 <b>{html.escape(name)}</b>: <b>{label}</b>. "
                                  f"Решение теперь видно всем участникам.",
                                  parse_mode=ParseMode.HTML)
    await callback.answer("Оценка сохранена")

# ============================================================
# LINKS
# ============================================================

@dp.callback_query(F.data == "links:main")
async def cb_links_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_send_or_edit(callback, "🔗 <b>Полезные ресурсы</b>\nВыберите раздел:",
                            reply_markup=get_links_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("links:sec:"))
async def cb_links_section(callback: types.CallbackQuery):
    sec_key = callback.data.split(":", 2)[2]
    if sec_key not in DATABASE.get("links", {}):
        await callback.answer("Раздел не найден.", show_alert=True)
        return
    await show_links_section(callback, sec_key, callback.from_user.id)
    await callback.answer()

@dp.callback_query(F.data.startswith("links:del:"))
async def cb_links_del(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только администратор.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка", show_alert=True)
        return
    sec_key, idx = parts[2], int(parts[3])
    items = DATABASE.get("links", {}).get(sec_key, {}).get("items", [])
    if 0 <= idx < len(items):
        removed = items.pop(idx)
        await save_db(DATABASE)
        await show_links_section(callback, sec_key, callback.from_user.id)
        await callback.answer(f"Удалено: {(removed.get('title') or '')[:40]}")
    else:
        await callback.answer("Элемент не найден.", show_alert=True)

@dp.callback_query(F.data.startswith("links:add:"))
async def cb_links_add(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только администратор.", show_alert=True)
        return
    sec_key = callback.data.split(":", 2)[2]
    await state.set_state(AddLink.waiting_for_text)
    await state.update_data(section=sec_key)
    await callback.message.answer("🔗 Отправьте ссылку в формате:\n"
                                  "<code>Название - https://example.com</code>")
    await callback.answer()

@dp.message(StateFilter(AddLink.waiting_for_text), F.text)
async def process_add_link(message: types.Message, state: FSMContext):
    text = message.text.strip()
    m = re.search(r"(https?://\S+)", text)
    if not m:
        await message.answer("⚠️ Не нашёл URL. Попробуйте ещё раз.")
        return
    url = m.group(1).rstrip(".,);")
    title = text.replace(m.group(1), "").strip(" \t-—|:,")
    if not title:
        title = re.sub(r"^https?://", "", url)[:60]
    data = await state.get_data()
    sec_key = data.get("section")
    if sec_key not in DATABASE.get("links", {}):
        await state.clear()
        await message.answer("⚠️ Раздел не найден.")
        return
    DATABASE["links"][sec_key].setdefault("items", []).append({"title": title, "url": url})
    await save_db(DATABASE)
    await state.clear()
    await message.answer(f"✅ Ссылка добавлена в «{DATABASE['links'][sec_key].get('title', sec_key)}».")

# ============================================================
# USER FILE SUBMISSIONS
# ============================================================

@dp.callback_query(F.data == "submit:start")
async def cb_submit_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserSubmit.waiting_file)
    await state.update_data(sub_file_id=None, sub_file_name=None, sub_title="", selected_tags=[])
    await callback.message.answer("📤 Отправьте файл (лучше PDF) для публикации в библиотеку.\n"
                                  "Он попадёт в каталог и в канал после проверки администратором.")
    await callback.answer()

@dp.message(StateFilter(UserSubmit.waiting_file), F.document | F.photo)
async def process_submit_file(message: types.Message, state: FSMContext):
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "material"
    else:
        file_id = message.photo[-1].file_id
        file_name = "photo.jpg"
    await state.update_data(sub_file_id=file_id, sub_file_name=file_name)
    await state.set_state(UserSubmit.waiting_title)
    await message.answer("✏️ Как называется материал? Отправьте название:")

@dp.message(StateFilter(UserSubmit.waiting_title), F.text)
async def process_submit_title(message: types.Message, state: FSMContext):
    await state.update_data(sub_title=message.text.strip()[:200])
    await state.set_state(UserSubmit.choosing_tags)
    await message.answer("🏷 Выберите теги:",
                         reply_markup=get_tag_toggle_keyboard([], "sub:tag", "sub:tags_done",
                                                              "⏭ Без тегов", "sub:tags_skip"))

@dp.callback_query(StateFilter(UserSubmit.choosing_tags), F.data.startswith("sub:tag:"))
async def cb_sub_tag(callback: types.CallbackQuery, state: FSMContext):
    res = await toggle_tag_by_index(callback, state)
    if not res:
        return
    selected, tag, removed = res
    await safe_send_or_edit(callback, f"🏷 Выберите теги (выбрано: {len(selected)}):",
                            reply_markup=get_tag_toggle_keyboard(selected, "sub:tag", "sub:tags_done",
                                                                 "⏭ Без тегов", "sub:tags_skip"))
    await callback.answer("Тег снят" if removed else "Тег выбран")

async def render_submit_preview(target, state: FSMContext):
    data = await state.get_data()
    text = ("📋 <b>Заявка на публикацию</b>\n\n"
            f"📖 Название: {html.escape(data.get('sub_title') or '—')}\n"
            f"📄 Файл: {html.escape(data.get('sub_file_name') or '—')}\n"
            f"🏷 Теги: {html.escape(' '.join(data.get('selected_tags', [])) or '—')}")
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Отправить", callback_data="submit:confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="submit:cancel"),
    ]])
    await safe_send_or_edit(target, text, reply_markup=markup)

@dp.callback_query(F.data == "sub:tags_done", StateFilter(UserSubmit.choosing_tags))
async def cb_sub_tags_done(callback: types.CallbackQuery, state: FSMContext):
    await render_submit_preview(callback, state)
    await callback.answer()

@dp.callback_query(F.data == "sub:tags_skip", StateFilter(UserSubmit.choosing_tags))
async def cb_sub_tags_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(selected_tags=[])
    await render_submit_preview(callback, state)
    await callback.answer()

@dp.callback_query(F.data == "submit:confirm", StateFilter(UserSubmit.choosing_tags))
async def cb_submit_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("sub_file_id"):
        await callback.answer("Сначала отправьте файл!", show_alert=True)
        return
    uid_str = str(callback.from_user.id)
    u = DATABASE.get("users", {}).get(uid_str, {})
    sub_id = uuid.uuid4().hex[:12]
    payload = {
        "user_id": callback.from_user.id,
        "username": callback.from_user.username or "",
        "first_name": callback.from_user.first_name or "",
        "nickname": u.get("nickname") or "",
        "file_id": data["sub_file_id"],
        "file_name": data.get("sub_file_name") or "",
        "title": data.get("sub_title") or "",
        "tags": data.get("selected_tags", []),
        "status": "pending",
        "created_at": datetime.now(YEREVAN_TZ).isoformat(),
    }
    await save_submission(sub_id, payload)
    await state.clear()
    notify_text = (
        "📥 <b>Новая заявка на файл</b>\n\n"
        f"🪪 Ник: <b>{html.escape(payload['nickname'] or '—')}</b>\n"
        f"👤 TG: {html.escape(payload['first_name'] or '')}"
        + (f" · @{html.escape(payload['username'])}" if payload["username"] else "")
        + "\n\n"
        f"📖 {html.escape(payload['title'] or '—')}\n"
        f"📄 {html.escape(payload['file_name'] or '—')}\n"
        f"🏷 {html.escape(' '.join(payload['tags']) or '—')}"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"admin:sub_accept:{sub_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin:sub_reject:{sub_id}")],
    ])
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_document(admin_id, document=payload["file_id"], caption=notify_text,
                                    parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            logger.exception("Failed to notify admin %s", admin_id)
    await callback.message.answer("✅ Заявка отправлена! Мы сообщим, когда материал попадёт в каталог.")
    await callback.answer()

@dp.callback_query(F.data == "submit:confirm")
async def cb_submit_confirm_stale(callback: types.CallbackQuery):
    await callback.answer("Заявка устарела. Начните заново: /start → «📤 Предложить файл».", show_alert=True)

@dp.callback_query(F.data == "submit:cancel")
async def cb_submit_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Отправка отменена. /start — главное меню.")
    await callback.answer()

# ============================================================
# ADMIN: PANEL, MANUAL UPLOAD (без AI)
# ============================================================

@dp.callback_query(F.data == "admin:main")
async def cb_admin_main(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.clear()
    await safe_send_or_edit(callback, "👑 <b>Админ-панель MathAm</b>\nВыберите действие:",
                            reply_markup=get_admin_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin:upload")
async def cb_admin_upload(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.set_state(AdminUpload.waiting_document)
    await state.update_data(file_id=None, file_name="", title="", description="",
                            selected_tags=[], difficulty="medium", upl_cats=[])
    await callback.message.answer("📤 Отправьте файл (PDF):")
    await callback.answer()

@dp.message(StateFilter(AdminUpload.waiting_document), F.document | F.photo)
async def process_upl_document(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "material"
    else:
        file_id = message.photo[-1].file_id
        file_name = "photo.jpg"
    await state.update_data(file_id=file_id, file_name=file_name)
    await state.set_state(AdminUpload.waiting_title)
    await message.answer("✏️ Отправьте название материала:")

@dp.message(StateFilter(AdminUpload.waiting_title), F.text)
async def process_upl_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip()[:200])
    await state.set_state(AdminUpload.waiting_description)
    await message.answer("📝 Отправьте описание (необязательно) или напишите «пропустить»:")

@dp.message(StateFilter(AdminUpload.waiting_description), F.text)
async def process_upl_description(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    if raw.lower() in ("пропустить", "skip", "-"):
        raw = ""
    await state.update_data(description=raw[:1200])
    await state.set_state(AdminUpload.choosing_tags)
    await message.answer("🏷 Выберите теги:",
                         reply_markup=get_tag_toggle_keyboard([], "upl:tag", "upl:tags_done",
                                                              "⏭ Без тегов", "upl:tags_skip"))

@dp.callback_query(StateFilter(AdminUpload.choosing_tags), F.data.startswith("upl:tag:"))
async def cb_upl_tag(callback: types.CallbackQuery, state: FSMContext):
    res = await toggle_tag_by_index(callback, state)
    if not res:
        return
    selected, tag, removed = res
    await safe_send_or_edit(callback, f"🏷 Выберите теги (выбрано: {len(selected)}):",
                            reply_markup=get_tag_toggle_keyboard(selected, "upl:tag", "upl:tags_done",
                                                                 "⏭ Без тегов", "upl:tags_skip"))
    await callback.answer("Тег снят" if removed else "Тег выбран")

@dp.callback_query(F.data == "upl:tags_done", StateFilter(AdminUpload.choosing_tags))
async def cb_upl_tags_done(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminUpload.choosing_difficulty)
    builder = [[InlineKeyboardButton(text=name, callback_data=f"upl:diff:{level}")]
               for level, name in DIFF_NAMES.items()]
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu:main")])
    await safe_send_or_edit(callback, "🎯 Выберите уровень сложности:",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(F.data == "upl:tags_skip", StateFilter(AdminUpload.choosing_tags))
async def cb_upl_tags_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(selected_tags=[])
    await state.set_state(AdminUpload.choosing_difficulty)
    builder = [[InlineKeyboardButton(text=name, callback_data=f"upl:diff:{level}")]
               for level, name in DIFF_NAMES.items()]
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu:main")])
    await safe_send_or_edit(callback, "🎯 Выберите уровень сложности (теги пропущены):",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(StateFilter(AdminUpload.choosing_difficulty), F.data.startswith("upl:diff:"))
async def cb_upl_diff(callback: types.CallbackQuery, state: FSMContext):
    level = callback.data.split(":", 2)[2]
    if level in DIFF_NAMES:
        await state.update_data(difficulty=level)
    await state.set_state(AdminUpload.choosing_categories)
    data = await state.get_data()
    await safe_send_or_edit(callback, "📂 Выберите разделы (можно несколько):",
                            reply_markup=get_category_toggle_keyboard(data.get("upl_cats", [])))
    await callback.answer("Уровень выбран")

@dp.callback_query(StateFilter(AdminUpload.choosing_categories), F.data.startswith("upl:cat:"))
async def cb_upl_cat(callback: types.CallbackQuery, state: FSMContext):
    cat_key = callback.data.split(":", 2)[2]
    if cat_key not in DATABASE.get("categories", {}):
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    data = await state.get_data()
    cats = list(data.get("upl_cats", []))
    if cat_key in cats:
        cats.remove(cat_key)
        selected = False
    else:
        cats.append(cat_key)
        selected = True
    await state.update_data(upl_cats=cats)
    await safe_send_or_edit(callback, "📂 Выберите разделы (можно несколько):",
                            reply_markup=get_category_toggle_keyboard(cats))
    await callback.answer("Раздел выбран" if selected else "Раздел снят")

@dp.callback_query(F.data == "upl:publish", StateFilter(AdminUpload.choosing_categories))
async def cb_upl_publish(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    data = await state.get_data()
    if not data.get("file_id"):
        await callback.answer("Сначала отправьте файл!", show_alert=True)
        return
    cats = [c for c in data.get("upl_cats", []) if c in DATABASE.get("categories", {})]
    if not cats:
        await callback.answer("Выберите хотя бы один раздел!", show_alert=True)
        return
    entry = {
        "file_unique_id": str(uuid.uuid4()),
        "file_id": data["file_id"],
        "file_name": data.get("file_name", ""),
        "caption": data.get("title") or "Без названия",
        "summary": data.get("description", ""),   # описание необязательное
        "tags": data.get("selected_tags", []),
        "difficulty": data.get("difficulty", "medium"),
        "must_read": False,
        "added_at": get_yerevan_date(),
    }
    titles = []
    for cat_key in cats:
        DATABASE["categories"][cat_key].setdefault("files", []).append(copy.deepcopy(entry))
        titles.append(DATABASE["categories"][cat_key].get("title", cat_key))
    await save_db(DATABASE)
    await state.clear()
    await callback.message.answer(
        f"✅ Материал опубликован!\n📖 <b>{html.escape(entry['caption'])}</b>\n"
        f"📂 {html.escape(', '.join(titles))}\n⏳ Отправляю файл в канал...",
        parse_mode=ParseMode.HTML,
    )
    await announce_file_to_channel(entry, titles)
    await callback.answer("Сохранено ✅")

@dp.callback_query(F.data == "upl:publish")
async def cb_upl_publish_stale(callback: types.CallbackQuery):
    await callback.answer("Загрузка устарела. Начните заново.", show_alert=True)

# ============================================================
# ADMIN: ADD DAILY TASK (+ авто-рассылка и пост в канал)
# ============================================================

@dp.callback_query(F.data == "admin:add_task")
async def cb_add_task(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.set_state(TaskOfDayAdmin.waiting_for_photo)
    await state.update_data(task_photo=None, task_text="", solution_text="",
                            solution_photo=None, solution_document=None)
    await callback.message.answer("📸 Отправьте фото задачи, либо напишите «пропустить».")
    await callback.answer()

@dp.message(StateFilter(TaskOfDayAdmin.waiting_for_photo))
async def process_task_photo(message: types.Message, state: FSMContext):
    if message.photo:
        await state.update_data(task_photo=message.photo[-1].file_id)
    elif message.text and message.text.strip().lower() in ("пропустить", "skip", "-"):
        await state.update_data(task_photo=None)
    else:
        await message.answer("📸 Отправьте фото задачи или напишите «пропустить».")
        return
    await state.set_state(TaskOfDayAdmin.waiting_for_task_text)
    await message.answer("✍️ Отправьте текст задачи (или «пропустить», если всё на фото):")

@dp.message(StateFilter(TaskOfDayAdmin.waiting_for_task_text), F.text)
async def process_task_text(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    if raw.lower() in ("пропустить", "skip", "-"):
        raw = ""
    await state.update_data(task_text=raw)
    await state.set_state(TaskOfDayAdmin.waiting_for_solution)
    await message.answer("💡 Отправьте решение (текстом, фото с подписью или «пропустить»):")

@dp.message(StateFilter(TaskOfDayAdmin.waiting_for_solution))
async def process_task_solution(message: types.Message, state: FSMContext):
    if message.photo:
        await state.update_data(solution_photo=message.photo[-1].file_id)
        if message.caption:
            await state.update_data(solution_text=message.caption.strip())
    elif message.document:
        await state.update_data(solution_document=message.document.file_id)
    elif message.text and message.text.strip().lower() in ("пропустить", "skip", "-"):
        await state.update_data(solution_text="", solution_photo=None, solution_document=None)
    elif message.text:
        await state.update_data(solution_text=message.text.strip())
    else:
        await message.answer("Отправьте текст, фото, документ или «пропустить».")
        return
    await state.set_state(TaskOfDayAdmin.waiting_for_date)
    await message.answer("📅 На какую дату опубликовать задачу?\n"
                         "Формат: <code>ГГГГ-ММ-ДД</code>, либо «сегодня» / «завтра»:")

@dp.message(StateFilter(TaskOfDayAdmin.waiting_for_date), F.text)
async def process_task_date(message: types.Message, state: FSMContext):
    raw = message.text.strip().lower()
    if raw in ("сегодня", "today"):
        date_str = get_yerevan_date()
    elif raw in ("завтра", "tomorrow"):
        date_str = (datetime.now(YEREVAN_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        try:
            date_str = datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            await message.answer("⚠️ Неверный формат. Отправьте дату как <code>2025-06-01</code> или «сегодня».")
            return
    data = await state.get_data()
    group = DATABASE.setdefault("daily_tasks", {}).setdefault(date_str, {"tasks": []})
    group.setdefault("tasks", [])
    task = {
        "task_id": uuid.uuid4().hex[:10],
        "text": data.get("task_text", ""),
        "photo_file_id": data.get("task_photo"),
        "solution": data.get("solution_text", ""),
        "solution_photo_file_id": data.get("solution_photo"),
        "solution_document_file_id": data.get("solution_document"),
        "difficulty": "medium",
        "tags": [],
        "source": "admin",
        "user_solutions": {},
        "created_at": get_yerevan_date(),
        "number": len(group["tasks"]) + 1,
    }
    group["tasks"].append(task)
    await save_db(DATABASE)
    await state.clear()
    await message.answer(f"✅ Задача добавлена на <b>{date_str}</b> (№ {task['number']}).\n"
                         f"⏳ Автоматически рассылаю всем пользователям и публикую в канал...",
                         parse_mode=ParseMode.HTML)
    await broadcast_task(date_str, len(group["tasks"]) - 1, report_msg=message)

# ============================================================
# ADMIN: STATS / SUBMISSIONS / PENDING SOLUTIONS / BROADCAST
# ============================================================

@dp.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.clear()
    users = DATABASE.get("users", {})
    total_files = sum(len(c.get("files", [])) for c in DATABASE.get("categories", {}).values())
    tasks_total = sum(len(g.get("tasks", [])) for g in DATABASE.get("daily_tasks", {}).values())
    pending_sols = 0
    for group in DATABASE.get("daily_tasks", {}).values():
        for task in group.get("tasks", []):
            pending_sols += sum(1 for s in (task.get("user_solutions") or {}).values()
                                if s.get("status") == "pending")
    pending_subs = await submissions_collection.count_documents({"status": "pending"})
    top = sorted(users.items(), key=lambda kv: kv[1].get("score", 0), reverse=True)[:5]
    top_lines = "\n".join(
        f"  {i}. 🪪 {html.escape(u.get('nickname') or u.get('username') or f'id{uid_str}')} — "
        f"{html.escape(u.get('first_name') or '')}"
        + (f" (@{html.escape(u.get('username'))})" if u.get("username") else "")
        + f" — {u.get('score', 0)} очк."
        for i, (uid_str, u) in enumerate(top, 1)
    ) or "  —"
    text = (
        "📊 <b>Статистика MathAm</b>\n\n"
        f"👥 Пользователей: {len(users)}\n"
        f"📚 Файлов в каталоге: {total_files}\n"
        f"🏷 Тегов в базе: {len(DATABASE.get('tags', []))}\n"
        f"🎯 Задач опубликовано: {tasks_total}\n"
        f"🧩 Решений на проверке: {pending_sols}\n"
        f"📥 Заявок на файлы: {pending_subs}\n\n"
        f"<b>Топ по очкам (ник · TG):</b>\n{top_lines}"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin:main")]])
    await safe_send_or_edit(callback, text, reply_markup=markup)
    await callback.answer()

@dp.callback_query(F.data == "admin:submissions")
async def cb_admin_submissions(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.clear()
    subs = []
    async for s in submissions_collection.find({"status": "pending"}).sort("created_at", -1):
        subs.append(s)
        if len(subs) >= 10:
            break
    if not subs:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin:main")]])
        await safe_send_or_edit(callback, "📥 <b>Заявки на файлы</b>\n\nНовых заявок нет.", reply_markup=markup)
        await callback.answer()
        return
    lines = ["📥 <b>Заявки на файлы</b>\n"]
    builder = []
    for s in subs:
        sid = s["_id"]
        title = html.escape(s.get("title") or s.get("file_name") or "Без названия")
        nick = html.escape(s.get("nickname") or "—")
        tg = html.escape(s.get("first_name") or "")
        uname = s.get("username") or ""
        lines.append(f"• <b>{title}</b>\n   🪪 {nick} · 👤 {tg}"
                     + (f" · @{html.escape(uname)}" if uname else ""))
        builder.append([
            InlineKeyboardButton(text="✅ Принять", callback_data=f"admin:sub_accept:{sid}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin:sub_reject:{sid}"),
        ])
    builder.append([InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin:main")])
    await safe_send_or_edit(callback, "\n".join(lines),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(F.data.startswith("admin:sub_accept:"))
async def cb_sub_accept(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    sub_id = callback.data.split(":", 2)[2]
    sub = await get_submission(sub_id)
    if not sub or sub.get("status") != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return
    await save_submission(sub_id, {"status": "accepted",
                                   "processed_at": datetime.now(YEREVAN_TZ).isoformat()})
    rows = [[InlineKeyboardButton(text=cat_data.get("title", cat_key),
                                  callback_data=f"subcat:{sub_id}:{cat_key}")]
            for cat_key, cat_data in DATABASE.get("categories", {}).items()]
    rows.append([InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin:main")])
    await callback.message.answer("📂 Выберите раздел для публикации:",
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()

@dp.callback_query(F.data.startswith("subcat:"))
async def cb_subcat(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка", show_alert=True)
        return
    sub_id, cat_key = parts[1], parts[2]
    sub = await get_submission(sub_id)
    if not sub:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    if sub.get("status") == "published":
        await callback.answer("Уже опубликовано.", show_alert=True)
        return
    if cat_key not in DATABASE.get("categories", {}):
        await callback.answer("Раздел не найден.", show_alert=True)
        return
    entry = {
        "file_unique_id": str(uuid.uuid4()),
        "file_id": sub.get("file_id"),
        "file_name": sub.get("file_name") or "",
        "caption": sub.get("title") or "Без названия",
        "summary": "",  # описание необязательное
        "tags": sub.get("tags", []),
        "difficulty": "medium",
        "must_read": False,
        "added_at": get_yerevan_date(),
    }
    DATABASE["categories"][cat_key].setdefault("files", []).append(entry)
    await save_db(DATABASE)
    await save_submission(sub_id, {"status": "published"})
    cat_title = DATABASE["categories"][cat_key].get("title", cat_key)
    try:
        await bot.send_message(sub.get("user_id"),
                               f"✅ Ваш материал «{entry['caption']}» добавлен в каталог и опубликован в канале! Спасибо 🙌")
    except Exception:
        logger.warning("Failed to notify user %s", sub.get("user_id"))
    await callback.message.answer(
        f"✅ Опубликовано в «{html.escape(cat_title)}».\n⏳ Отправляю файл в канал..."
    )
    await announce_file_to_channel(entry, [cat_title])
    await callback.answer("Опубликовано")

@dp.callback_query(F.data.startswith("admin:sub_reject:"))
async def cb_sub_reject(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    sub_id = callback.data.split(":", 2)[2]
    sub = await get_submission(sub_id)
    if not sub or sub.get("status") != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return
    await save_submission(sub_id, {"status": "rejected",
                                   "processed_at": datetime.now(YEREVAN_TZ).isoformat()})
    try:
        await bot.send_message(sub.get("user_id"),
                               "❌ К сожалению, ваш материал не подошёл для каталога. Спасибо, что поделились!")
    except Exception:
        pass
    await callback.message.answer("❌ Заявка отклонена.")
    await callback.answer("Отклонено")

@dp.callback_query(F.data == "admin:pending_sols")
async def cb_pending_sols(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.clear()
    lines = ["🧩 <b>Решения на проверку</b>\n"]
    builder = []
    found = 0
    stop = False
    for date_str in get_dates_sorted():
        if stop:
            break
        group = DATABASE["daily_tasks"][date_str]
        for idx, task in enumerate(group.get("tasks", [])):
            if stop:
                break
            for uid_str, s in (task.get("user_solutions") or {}).items():
                if s.get("status") != "pending":
                    continue
                found += 1
                lines.append(f"• {date_str} · №{task['number']} — 🪪 "
                             f"{html.escape(s.get('nickname') or get_nickname(uid_str))} · "
                             f"👤 {html.escape(s.get('first_name') or '')}")
                builder.append([
                    InlineKeyboardButton(text="👀", callback_data=f"solfull:{date_str}:{idx}:{uid_str}"),
                    InlineKeyboardButton(text="✅", callback_data=f"solrev:ok:{date_str}:{idx}:{uid_str}"),
                    InlineKeyboardButton(text="❌", callback_data=f"solrev:no:{date_str}:{idx}:{uid_str}"),
                ])
                if found >= 10:
                    stop = True
                    break
    if not found:
        lines.append("\nНет решений на проверку. 🎉")
    else:
        lines.append(f"\nВсего на проверке показано: {found}")
    builder.append([InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin:main")])
    await safe_send_or_edit(callback, "\n".join(lines),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.set_state(BroadcastAdmin.waiting_for_message)
    await callback.message.answer("📢 Отправьте сообщение для рассылки всем пользователям "
                                  "(текст, фото, любой контент).\n/cancel — отмена.")
    await callback.answer()

@dp.message(StateFilter(BroadcastAdmin.waiting_for_message))
async def process_broadcast(message: types.Message, state: FSMContext):
    await message.answer("⏳ Рассылка запущена...")
    users = DATABASE.get("users", {})
    sent, failed = 0, 0
    for uid_str in list(users.keys()):
        try:
            await message.copy_to(int(uid_str))
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await message.copy_to(int(uid_str))
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await state.clear()
    await message.answer(f"✅ Рассылка завершена.\nДоставлено: {sent} · Ошибок: {failed}")

# ============================================================
# ADMIN: EDIT / DELETE FILE
# ============================================================

@dp.callback_query(F.data.startswith("admin:edit_file:"))
async def cb_edit_file(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    uid = callback.data.split(":", 2)[2]
    f = get_file_by_uid(uid)
    if not f:
        await callback.answer("Файл не найден.", show_alert=True)
        return
    await state.clear()
    await state.update_data(edit_uid=uid)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Заменить файл", callback_data="admin:efile:doc")],
        [InlineKeyboardButton(text="✏️ Название", callback_data="admin:efile:title"),
         InlineKeyboardButton(text="🏷 Теги", callback_data="admin:efile:tags")],
        [InlineKeyboardButton(text="⬅️ Назад к файлу", callback_data=f"file:view:{uid}")],
    ])
    await safe_send_or_edit(callback, f"⚙️ <b>Редактирование</b>\n📖 {html.escape(f.get('caption') or '')}",
                            reply_markup=markup)
    await callback.answer()

@dp.callback_query(F.data == "admin:efile:doc")
async def cb_efile_doc(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.set_state(EditFile.waiting_for_document)
    await callback.message.answer("📄 Отправьте новый файл-документ (заменит текущий):")
    await callback.answer()

@dp.message(StateFilter(EditFile.waiting_for_document), F.document | F.photo)
async def process_efile_doc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("edit_uid")
    if not uid:
        await state.clear()
        return
    new_id = message.document.file_id if message.document else message.photo[-1].file_id
    n = update_file_field(uid, "file_id", new_id)
    await save_db(DATABASE)
    await state.clear()
    await message.answer(f"✅ Файл заменён (обновлено записей: {n}).")

@dp.callback_query(F.data == "admin:efile:title")
async def cb_efile_title(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.set_state(EditFile.waiting_for_title)
    await callback.message.answer("✏️ Отправьте новое название материала:")
    await callback.answer()

@dp.message(StateFilter(EditFile.waiting_for_title), F.text)
async def process_efile_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("edit_uid")
    if not uid:
        await state.clear()
        return
    n = update_file_field(uid, "caption", message.text.strip()[:200])
    await save_db(DATABASE)
    await state.clear()
    await message.answer(f"✅ Название обновлено (записей: {n}).")
    await show_file_card(message, uid, message.from_user.id)

@dp.callback_query(F.data == "admin:efile:tags")
async def cb_efile_tags(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await state.set_state(EditFile.waiting_for_tags)
    await callback.message.answer("🏷 Отправьте теги через запятую (или «очистить»):\n"
                                  "Новые теги автоматически попадут в базу тегов.")
    await callback.answer()

@dp.message(StateFilter(EditFile.waiting_for_tags), F.text)
async def process_efile_tags(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("edit_uid")
    if not uid:
        await state.clear()
        return
    raw = message.text.strip()
    if raw.lower() == "очистить":
        tags = []
    else:
        tags = normalize_tags_input(raw)
        db_tags = DATABASE.setdefault("tags", [])
        for tag in tags:
            if tag.lower() not in {t.lower() for t in db_tags}:
                db_tags.append(tag)
    n = update_file_field(uid, "tags", tags)
    await save_db(DATABASE)
    await state.clear()
    await message.answer(f"✅ Теги обновлены (записей: {n}).")
    await show_file_card(message, uid, message.from_user.id)

@dp.callback_query(F.data.startswith("admin:del_file:"))
async def cb_del_file(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    uid = callback.data.split(":", 2)[2]
    f = get_file_by_uid(uid)
    if not f:
        await callback.answer("Файл не найден.", show_alert=True)
        return
    await state.clear()
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"admin:del_file_yes:{uid}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"file:view:{uid}")],
    ])
    await safe_send_or_edit(callback,
                            f"⚠️ Удалить «{html.escape(f.get('caption') or '')}» из всех разделов?",
                            reply_markup=markup)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin:del_file_yes:"))
async def cb_del_file_yes(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно.", show_alert=True)
        return
    uid = callback.data.split(":", 2)[2]
    removed = 0
    for cat_data in DATABASE.get("categories", {}).values():
        files = cat_data.get("files", [])
        new_files = [f for f in files if f.get("file_unique_id") != uid]
        removed += len(files) - len(new_files)
        cat_data["files"] = new_files
    for u in DATABASE.get("users", {}).values():
        favs = u.get("favorites", [])
        if uid in favs:
            favs.remove(uid)
    await save_db(DATABASE)
    await callback.message.answer(f"🗑 Удалено записей: {removed}.")
    await callback.answer("Удалено")

# ============================================================
# INLINE MODE (simple catalog search)
# ============================================================

@dp.inline_query()
async def inline_catalog_search(query: InlineQuery):
    q = (query.query or "").strip().lower().lstrip("#")
    files = get_catalog_files_list()
    if q:
        def matches(f):
            hay = (f["caption"] + " " + " ".join(f.get("tags", [])) + " "
                   + (f.get("summary") or "")).lower()
            return q in hay
        files = [f for f in files if matches(f)]
    results = []
    for f in files[:10]:
        try:
            results.append(InlineQueryResultCachedDocument(
                id=f["uid"],
                title=f["caption"] or "Материал",
                document_file_id=f["file_id"],
                description=(f.get("summary") or f.get("category") or "Материал MathAm")[:200],
                caption=f"📖 <b>{html.escape(f['caption'])}</b>",
                parse_mode=ParseMode.HTML,
            ))
        except Exception:
            continue
    if not results:
        results = [InlineQueryResultArticle(
            id="not_found",
            title="🔎 Ничего не найдено",
            description="Откройте бота и попробуйте поиск по тегам",
            input_message_content=InputTextMessageContent(
                message_text="🤖 Откройте бота MathAm: /start"
            ),
        )]
    try:
        await query.answer(results, is_personal=True, cache_time=30)
    except Exception:
        logger.exception("Inline answer failed")

# ============================================================
# FALLBACK HANDLERS (must stay last)
# ============================================================

@dp.message(F.text)
async def fallback_text(message: types.Message, state: FSMContext):
    state_name = await state.get_state()
    if state_name == UserSubmit.waiting_file:
        await message.answer("📤 Ожидаю файл. Отправьте документ или /cancel.")
    elif state_name == AdminUpload.waiting_document:
        await message.answer("📄 Ожидаю файл. Отправьте документ или /cancel.")
    else:
        await message.answer("🤖 Не совсем понял. Откройте /start и воспользуйтесь меню.")

@dp.callback_query()
async def cb_unhandled(callback: types.CallbackQuery):
    await callback.answer()

# ============================================================
# STARTUP & ENTRY POINT
# ============================================================

async def on_startup(bot: Bot):
    global DATABASE, BOT_USERNAME
    DATABASE = await load_db()
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="catalog", description="📚 Каталог материалов"),
        BotCommand(command="cancel", description="❌ Отменить действие"),
    ]
    await bot.set_my_commands(commands)
    total_files = sum(len(c.get("files", [])) for c in DATABASE.get("categories", {}).values())
    logger.info("Startup complete: %s users, %s files, %s tags, channel=%s",
                len(DATABASE.get("users", {})), total_files,
                len(DATABASE.get("tags", [])), CHANNEL_ID)

def register_middlewares():
    dp.message.outer_middleware(UserActivityMiddleware())
    dp.callback_query.outer_middleware(UserActivityMiddleware())
    dp.inline_query.outer_middleware(UserActivityMiddleware())

async def run_polling():
    register_middlewares()
    dp.startup.register(on_startup)
    await bot.delete_webhook(drop_pending_updates=True)

    # PaaS-хостинги (Render и т.п.) ждут, что веб-сервис откроет порт.
    # Поднимаем лёгкий health-check сервер рядом с polling.
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
        logger.info("Health-check server listening on 0.0.0.0:%s", port)

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

def run_webhook():
    webhook_url = os.environ.get("WEBHOOK_URL", "").strip().rstrip("/")
    webhook_path = os.environ.get("WEBHOOK_PATH", "/tgbot").strip() or "/tgbot"

    async def set_webhook(bot: Bot):
        await bot.set_webhook(webhook_url + webhook_path, drop_pending_updates=True)
        logger.info("Webhook set: %s", webhook_url + webhook_path)

    register_middlewares()
    dp.startup.register(on_startup)
    dp.startup.register(set_webhook)
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=webhook_path)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))

if __name__ == "__main__":
    if os.environ.get("WEBHOOK_URL", "").strip():
        run_webhook()
    else:
        asyncio.run(run_polling())
