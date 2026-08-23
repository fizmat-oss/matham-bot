import logging

import random

import os

import copy

import uuid

import asyncio

from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, types

from aiogram.filters import Command, StateFilter

from aiogram.types import (

    BotCommand,

    InlineKeyboardMarkup,

    InlineKeyboardButton,

    InlineQuery,

    InlineQueryResultCachedDocument,

    InlineQueryResultArticle,

    InputTextMessageContent,

)

from aiogram.exceptions import TelegramRetryAfter

from aiogram.fsm.context import FSMContext

from aiogram.fsm.state import State, StatesGroup

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

TOKEN = os.environ.get("BOT_TOKEN")

ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")

ADMIN_IDS = [

    int(x.strip())

    for x in ADMIN_IDS_RAW.split(",")

    if x.strip().isdigit()

]

MONGO_URI = os.environ.get("MONGO_URI", "")

MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "matham_bot")

YEREVAN_TZ = timezone(timedelta(hours=4))

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

# ============================================================

# DEFAULT DATABASE

# ============================================================

DEFAULT_STATE = {

    "categories": {

        "geometry": {

            "title": "📐 Геометрия",

            "title_en": "📐 Geometry",

            "files": []

        },

        "number_theory": {

            "title": "🔢 Теория чисел",

            "title_en": "🔢 Number Theory",

            "files": []

        },

        "algebra": {

            "title": "🧮 Алгебра",

            "title_en": "🧮 Algebra",

            "files": []

        },

        "combinatorics": {

            "title": "🧩 Комбинаторика",

            "title_en": "🧩 Combinatorics",

            "files": []

        },

        "higher_math": {

            "title": "🎓 Матанализ и высшая математика",

            "title_en": "🎓 Calculus & Higher Mathematics",

            "files": []

        },

        "titu": {

            "title": "📘 Titu Andreescu",

            "title_en": "📘 Titu Andreescu",

            "files": []

        }

    },

    "links": {

        "useful_links": {

            "title": "🔗 Полезные ссылки",

            "title_en": "🔗 Useful Links",

            "items": []

        },

        "useful_videos": {

            "title": "🎥 Полезные видео",

            "title_en": "🎥 Useful Videos",

            "items": []

        }

    },

    "must_read": {

        "title": "⭐ Must-read",

        "files": []

    },

    "task_of_day": {

        "file_id": None,

        "caption": "",

        "votes": {}

    },

    "daily_tasks": {},

    "users": {},

    "settings": {}

}

# ============================================================

# LANGUAGE SYSTEM

# ============================================================

TEXTS = {

    "ru": {

        "choose_language": "🌍 Выбери язык:",

        "language_saved": "🇷🇺 Язык изменён на русский.",

        "main_menu": "📂 Главное меню",

        "catalog": "📚 Каталог",

        "daily_task": "🎯 Задача дня",

        "must_read": "⭐ Must-read",

        "favorites": "❤️ Избранное",

        "search": "🔎 Поиск",

        "rating": "🏆 Рейтинг",

        "challenge": "🎲 Случайный материал",

        "links": "🔗 Полезные ссылки",

        "submit": "📤 Предложить файл",

        "admin": "👑 Админ-панель",

        "language": "🌍 Язык",

        "back": "⬅️ Назад",

        "menu": "⬅️ Меню",

        "solution": "📝 Решение",

        "send_solution": "✍️ Отправить своё решение",

        "previous_tasks": "📅 Прошлые задачи",

        "no_tasks": "📭 Других задач пока нет.",

        "task_not_found": "❌ Задача не найдена.",

        "solution_added": "✅ Решение сохранено.",

        "solution_missing": "Пока решения нет 😔",

        "send_text_or_photo": "Отправь решение текстом или фотографией.",

        "cancel": "❌ Отмена",

        "approved": "✅ Одобрено",

        "rejected": "❌ Отклонено",

        "score": "⭐ Оценка",

        "your_score": "Твои очки",

        "streak": "Твой streak",

    },

    "en": {

        "choose_language": "🌍 Choose your language:",

        "language_saved": "🇬🇧 Language changed to English.",

        "main_menu": "📂 Main menu",

        "catalog": "📚 Catalog",

        "daily_task": "🎯 Daily Problem",

        "must_read": "⭐ Must-read",

        "favorites": "❤️ Favorites",

        "search": "🔎 Search",

        "rating": "🏆 Ranking",

        "challenge": "🎲 Random Material",

        "links": "🔗 Useful Links",

        "submit": "📤 Suggest a File",

        "admin": "👑 Admin Panel",

        "language": "🌍 Language",

        "back": "⬅️ Back",

        "menu": "⬅️ Menu",

        "solution": "📝 Solution",

        "send_solution": "✍️ Submit Your Solution",

        "previous_tasks": "📅 Previous Problems",

        "no_tasks": "📭 There are no other problems yet.",

        "task_not_found": "❌ Problem not found.",

        "solution_added": "✅ Solution saved.",

        "solution_missing": "No solution has been added yet 😔",

        "send_text_or_photo": "Send your solution as text or a photo.",

        "cancel": "❌ Cancel",

        "approved": "✅ Approved",

        "rejected": "❌ Rejected",

        "score": "⭐ Rating",

        "your_score": "Your points",

        "streak": "Your streak",

    }

}

def get_user_language(user_id: int) -> str:
    return "ru"

def t(user_id: int, key: str) -> str:
    return TEXTS["ru"].get(key, key)

def category_title(cat_data: dict, user_id: int) -> str:
    return cat_data.get("title", "")

# ============================================================

# HELPERS

# ============================================================

def get_yerevan_date():

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

                cats.append(cat_key)

                break

    return cats

async def track_user_activity(user_id: int, username: str = ""):

    uid_str = str(user_id)

    today = get_yerevan_date()

    yesterday = (

        datetime.now(YEREVAN_TZ) - timedelta(days=1)

    ).strftime("%Y-%m-%d")

    if uid_str not in DATABASE["users"]:

        user_data = {

            "username": username,

            "streak": 1,

            "last_active": today,

            "score": 0,

            "favorites": [],

            "opened_tasks": [],

            "language": "ru"

        }

        DATABASE["users"][uid_str] = user_data

        await db_collection.update_one(

            {"_id": DB_DOC_ID},

            {"$set": {f"data.users.{uid_str}": user_data}}

        )

        return

    user = DATABASE["users"][uid_str]

    updates = {}

    if username and user.get("username") != username:

        user["username"] = username

        updates[f"data.users.{uid_str}.username"] = username

    if "favorites" not in user:

        user["favorites"] = []

    if "opened_tasks" not in user:

        user["opened_tasks"] = []

    if "language" not in user:

        user["language"] = "ru"

    if user.get("last_active") != today:

        if user.get("last_active") == yesterday:

            user["streak"] = user.get("streak", 0) + 1

        else:

            user["streak"] = 1

        user["last_active"] = today

        updates[f"data.users.{uid_str}.streak"] = user["streak"]

        updates[f"data.users.{uid_str}.last_active"] = today

    if updates:

        await db_collection.update_one(

            {"_id": DB_DOC_ID},

            {"$set": updates}

        )

async def award_points(user_id: int, points: int):

    uid_str = str(user_id)

    if uid_str not in DATABASE["users"]:

        await track_user_activity(user_id)

    DATABASE["users"][uid_str]["score"] = (

        DATABASE["users"][uid_str].get("score", 0) + points

    )

    await db_collection.update_one(

        {"_id": DB_DOC_ID},

        {

            "$set": {

                f"data.users.{uid_str}.score":

                    DATABASE["users"][uid_str]["score"]

            }

        }

    )

# ============================================================

# DATABASE

# ============================================================

async def load_db():

    doc = await db_collection.find_one({"_id": DB_DOC_ID})

    if doc is None:

        logger.info("MongoDB empty - creating DEFAULT_STATE")

        data = copy.deepcopy(DEFAULT_STATE)

        await db_collection.update_one(

            {"_id": DB_DOC_ID},

            {"$set": {"data": data}},

            upsert=True

        )

        return data

    data = doc.get(

        "data",

        copy.deepcopy(DEFAULT_STATE)

    )

    # Missing root fields

    for key, value in DEFAULT_STATE.items():

        if key not in data:

            data[key] = copy.deepcopy(value)

    # Categories migration

    for cat_key, default_cat in DEFAULT_STATE["categories"].items():

        if cat_key not in data["categories"]:

            data["categories"][cat_key] = copy.deepcopy(default_cat)

        cat_data = data["categories"][cat_key]

        if "title" not in cat_data:

            cat_data["title"] = default_cat["title"]

        if "title_en" not in cat_data:

            cat_data["title_en"] = default_cat["title_en"]

        if "files" not in cat_data:

            cat_data["files"] = []

        for f in cat_data["files"]:

            if "file_unique_id" not in f:

                f["file_unique_id"] = (

                    str(uuid.uuid4())

                )

            if "tags" not in f:

                f["tags"] = []

            if "difficulty" not in f:

                f["difficulty"] = None

            if "must_read" not in f:

                f["must_read"] = False

    # Users migration

    for uid, user in data["users"].items():

        user.setdefault("username", "")

        user.setdefault("streak", 1)

        user.setdefault("last_active", get_yerevan_date())

        user.setdefault("score", 0)

        user.setdefault("favorites", [])

        user.setdefault("opened_tasks", [])

        user.setdefault("language", "ru")

    # Daily task migration - group multiple tasks under one date.
    for date_str, group in list(data["daily_tasks"].items()):
        if isinstance(group, dict) and "tasks" not in group:
            group = {"tasks": [copy.deepcopy(group)]}
            data["daily_tasks"][date_str] = group
        elif isinstance(group, list):
            group = {"tasks": group}
            data["daily_tasks"][date_str] = group
        group.setdefault("tasks", [])
        for i, task in enumerate(group["tasks"]):
            task.setdefault("task_id", uuid.uuid4().hex[:10])
            task.setdefault("solution", "")
            task.setdefault("solution_photo_file_id", None)
            task.setdefault("votes", {})
            task.setdefault("user_solutions", {})
            task.setdefault("created_at", get_yerevan_date())
            task["number"] = i + 1
    return data

async def save_db(db_data):

    await db_collection.update_one(

        {"_id": DB_DOC_ID},

        {"$set": {"data": db_data}},

        upsert=True

    )

async def save_submission(sub_id: str, data: dict):

    await submissions_collection.update_one(

        {"_id": sub_id},

        {"$set": data},

        upsert=True

    )

async def get_submission(sub_id: str) -> dict:

    doc = await submissions_collection.find_one({"_id": sub_id})

    return doc if doc else {}

# ============================================================

# FSM STATES

# ============================================================

class FileUpload(StatesGroup):

    selecting_categories = State()

    waiting_for_caption = State()

class UserSubmit(StatesGroup):

    selecting_categories = State()

class AddLink(StatesGroup):

    waiting_for_text = State()

class EditFile(StatesGroup):

    waiting_for_document = State()

    waiting_for_title = State()

    waiting_for_tags = State()

class TaskOfDayAdmin(StatesGroup):

    waiting_for_photo = State()

    waiting_for_solution = State()

    waiting_for_date = State()

class UserTaskSolution(StatesGroup):

    waiting_for_solution = State()

class BroadcastAdmin(StatesGroup):

    waiting_for_message = State()

class LanguageState(StatesGroup):

    choosing = State()

# ============================================================

# DAILY TASK GROUP HELPERS
def get_task_group(date_str: str):
    group = DATABASE.get("daily_tasks", {}).get(date_str)
    if not group:
        return None
    if "tasks" not in group:
        group = {"tasks": [group]}
        DATABASE["daily_tasks"][date_str] = group
    return group

def get_tasks_for_date(date_str: str) -> list:
    group = get_task_group(date_str)
    return group.get("tasks", []) if group else []

def get_task_by_index(date_str: str, index: int = 0):
    tasks = get_tasks_for_date(date_str)
    return tasks[index] if 0 <= index < len(tasks) else None

# KEYBOARDS

# ============================================================

def get_language_keyboard():

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="🇷🇺 Русский",

                    callback_data="lang:ru"

                ),

                InlineKeyboardButton(

                    text="🇬🇧 English",

                    callback_data="lang:en"

                )

            ]

        ]

    )

def get_main_menu_keyboard(user_id: int):

    builder = [

        [

            InlineKeyboardButton(

                text=t(user_id, "catalog"),

                callback_data="menu:catalog"

            ),

            InlineKeyboardButton(

                text=t(user_id, "daily_task"),

                callback_data="task:show"

            )

        ],

        [

            InlineKeyboardButton(

                text=t(user_id, "must_read"),

                callback_data="mustread:main"

            ),

            InlineKeyboardButton(

                text=t(user_id, "favorites"),

                callback_data="favorites:main"

            )

        ],

        [

            InlineKeyboardButton(

                text=t(user_id, "search"),

                switch_inline_query_current_chat=""

            ),

            InlineKeyboardButton(

                text=t(user_id, "rating"),

                callback_data="rating:main"

            )

        ],

        [

            InlineKeyboardButton(

                text=t(user_id, "challenge"),

                callback_data="challenge:main"

            ),

            InlineKeyboardButton(

                text=t(user_id, "links"),

                callback_data="links:main"

            )

        ],

        [

            InlineKeyboardButton(

                text=t(user_id, "submit"),

                callback_data="submit:start"

            )

        ],

    ]

    if is_admin(user_id):

        builder.append([

            InlineKeyboardButton(

                text=t(user_id, "admin"),

                callback_data="admin:main"

            )

        ])

    return InlineKeyboardMarkup(

        inline_keyboard=builder

    )

def get_catalog_keyboard(user_id: int):

    builder = []

    for cat_key, cat_data in DATABASE["categories"].items():

        builder.append([

            InlineKeyboardButton(

                text=category_title(cat_data, user_id),

                callback_data=f"cat:{cat_key}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text=t(user_id, "menu"),

            callback_data="menu:main"

        )

    ])

    return InlineKeyboardMarkup(

        inline_keyboard=builder

    )

def build_admin_categories_kb(selected: set):

    builder = []

    for cat_key, cat_data in DATABASE["categories"].items():

        mark = "☑️" if cat_key in selected else "▫️"

        builder.append([

            InlineKeyboardButton(

                text=f"{mark} {cat_data['title']}",

                callback_data=f"a_toggle:{cat_key}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text=f"✅ Готово ({len(selected)})",

            callback_data="a_done"

        )

    ])

    builder.append([

        InlineKeyboardButton(

            text="❌ Отмена",

            callback_data="a_cancel"

        )

    ])

    return InlineKeyboardMarkup(

        inline_keyboard=builder

    )

def build_user_categories_kb(selected: set):

    builder = []

    for cat_key, cat_data in DATABASE["categories"].items():

        mark = "☑️" if cat_key in selected else "▫️"

        builder.append([

            InlineKeyboardButton(

                text=f"{mark} {cat_data['title']}",

                callback_data=f"usub_toggle:{cat_key}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text=f"✅ Отправить ({len(selected)})",

            callback_data="usub_done"

        )

    ])

    builder.append([

        InlineKeyboardButton(

            text="❌ Отмена",

            callback_data="usub_cancel"

        )

    ])

    return InlineKeyboardMarkup(

        inline_keyboard=builder

    )

def build_submission_action_kb(sub_id: str):

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="✅ Одобрить",

                    callback_data=f"sub_approve:{sub_id}"

                )

            ],

            [

                InlineKeyboardButton(

                    text="✏️ Изменить разделы",

                    callback_data=f"sub_editcat:{sub_id}"

                )

            ],

            [

                InlineKeyboardButton(

                    text="✏️ Изменить название",

                    callback_data=f"sub_edittitle:{sub_id}"

                )

            ],

            [

                InlineKeyboardButton(

                    text="❌ Отклонить",

                    callback_data=f"sub_reject:{sub_id}"

                )

            ]

        ]

    )

def get_file_view_keyboard(uid: str, user_id: int):

    user = DATABASE["users"].get(

        str(user_id),

        {}

    )

    is_fav = uid in user.get(

        "favorites",

        []

    )

    builder = []

    fav_text = (

        "💔 Убрать из избранного"

        if is_fav

        else "❤️ В избранное"

    )

    builder.append([

        InlineKeyboardButton(

            text=fav_text,

            callback_data=f"fav:{uid}"

        )

    ])

    if is_admin(user_id):

        builder.append([

            InlineKeyboardButton(

                text="✏️ Изменить",

                callback_data=f"fe_m:{uid}"

            ),

            InlineKeyboardButton(

                text="🗑 Удалить",

                callback_data=f"fd:{uid}"

            )

        ])

    return InlineKeyboardMarkup(

        inline_keyboard=builder

    )

def get_file_edit_keyboard(uid: str):

    f = get_file_by_uid(uid)

    must_read_text = (

        "⭐ Убрать Must-read"

        if f.get("must_read")

        else "⭐ Сделать Must-read"

    )

    diff = f.get(

        "difficulty",

        "Не указана"

    )

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="📝 Изменить название",

                    callback_data=f"fe_t:{uid}"

                )

            ],

            [

                InlineKeyboardButton(

                    text="📁 Изменить разделы",

                    callback_data=f"fe_c:{uid}"

                )

            ],

            [

                InlineKeyboardButton(

                    text="🏷 Изменить теги",

                    callback_data=f"fe_tg:{uid}"

                )

            ],

            [

                InlineKeyboardButton(

                    text=must_read_text,

                    callback_data=f"fe_mr:{uid}"

                )

            ],

            [

                InlineKeyboardButton(

                    text=f"📚 Уровень: {diff}",

                    callback_data=f"fe_df:{uid}"

                )

            ],

            [

                InlineKeyboardButton(

                    text="🔄 Заменить сам файл",

                    callback_data=f"fe_doc:{uid}"

                )

            ],

            [

                InlineKeyboardButton(

                    text="🔙 Закрыть",

                    callback_data="fe_close"

                )

            ]

        ]

    )

def get_difficulty_keyboard(uid: str):

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="🟢 Easy",

                    callback_data=f"fed_v:{uid}:easy"

                ),

                InlineKeyboardButton(

                    text="🟡 Medium",

                    callback_data=f"fed_v:{uid}:medium"

                )

            ],

            [

                InlineKeyboardButton(

                    text="🔴 Hard",

                    callback_data=f"fed_v:{uid}:hard"

                ),

                InlineKeyboardButton(

                    text="🔥 IMO",

                    callback_data=f"fed_v:{uid}:imo"

                )

            ],

            [

                InlineKeyboardButton(

                    text="❌ Очистить",

                    callback_data=f"fed_v:{uid}:none"

                )

            ],

            [

                InlineKeyboardButton(

                    text="🔙 Назад",

                    callback_data=f"fe_m:{uid}"

                )

            ]

        ]

    )

def get_file_edit_categories_kb(uid: str, selected: set):

    builder = []

    for cat_key, cat_data in DATABASE["categories"].items():

        mark = "☑️" if cat_key in selected else "▫️"

        builder.append([

            InlineKeyboardButton(

                text=f"{mark} {cat_data['title']}",

                callback_data=f"fec_t:{uid}:{cat_key}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text="✅ Сохранить",

            callback_data=f"fec_s:{uid}"

        )

    ])

    builder.append([

        InlineKeyboardButton(

            text="🔙 Назад",

            callback_data=f"fe_m:{uid}"

        )

    ])

    return InlineKeyboardMarkup(

        inline_keyboard=builder

    )

# ============================================================

# DAILY TASK KEYBOARDS

# ============================================================

def get_task_keyboard(

    date_str: str,

    user_id: int,

    admin_view: bool = False,

    task_index: int = 0

):

    builder = [

        [

            InlineKeyboardButton(

                text=t(user_id, "solution"),

                callback_data=f"th:{date_str}:{task_index}"

            )

        ],

        [

            InlineKeyboardButton(

                text=t(user_id, "send_solution"),

                callback_data=f"tsol:{date_str}:{task_index}"

            )

        ],

        [

            InlineKeyboardButton(

                text="⭐ 1",

                callback_data=f"tv:{date_str}:{task_index}:1"

            ),

            InlineKeyboardButton(

                text="⭐ 2",

                callback_data=f"tv:{date_str}:{task_index}:2"

            ),

            InlineKeyboardButton(

                text="⭐ 3",

                callback_data=f"tv:{date_str}:{task_index}:3"

            ),

            InlineKeyboardButton(

                text="⭐ 4",

                callback_data=f"tv:{date_str}:{task_index}:4"

            ),

            InlineKeyboardButton(

                text="⭐ 5",

                callback_data=f"tv:{date_str}:{task_index}:5"

            )

        ]

    ]

    if admin_view:

        builder.append([

            InlineKeyboardButton(

                text="📊 Статистика задачи",

                callback_data=f"ts:{date_str}:{task_index}"

            )

        ])

        builder.append([

            InlineKeyboardButton(

                text="👥 Решения пользователей",

                callback_data=f"tusers:{date_str}:{task_index}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text=t(user_id, "previous_tasks"),

            callback_data="tasks:history"

        )

    ])

    builder.append([

        InlineKeyboardButton(

            text=t(user_id, "menu"),

            callback_data="menu:main"

        )

    ])

    return InlineKeyboardMarkup(

        inline_keyboard=builder

    )

def get_history_keyboard(user_id: int):
    dates = sorted(DATABASE.get("daily_tasks", {}).keys(), reverse=True)
    builder = []
    for date_str in dates[:30]:
        tasks = get_tasks_for_date(date_str)
        if not tasks:
            continue
        title = f"🧩 {date_str} - Сегодня" if date_str == get_yerevan_date() else f"📅 {date_str}"
        builder.append([InlineKeyboardButton(text=title, callback_data="noop")])
        for i, _task in enumerate(tasks):
            builder.append([InlineKeyboardButton(text=f"{i + 1}. Задача", callback_data=f"taskdate:{date_str}:{i}")])
    if not builder:
        builder.append([InlineKeyboardButton(text=t(user_id, "no_tasks"), callback_data="noop")])
    builder.append([InlineKeyboardButton(text=t(user_id, "menu"), callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

# ============================================================

# USER SOLUTION RATING KEYBOARD

# ============================================================

def get_solution_rating_keyboard(

    date_str: str,

    solution_id: str,

    task_index: int = 0

):

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="⭐ 1",

                    callback_data=f"usrate:{date_str}:{task_index}:{solution_id}:1"

                ),

                InlineKeyboardButton(

                    text="⭐ 2",

                    callback_data=f"usrate:{date_str}:{task_index}:{solution_id}:2"

                ),

                InlineKeyboardButton(

                    text="⭐ 3",

                    callback_data=f"usrate:{date_str}:{task_index}:{solution_id}:3"

                ),

                InlineKeyboardButton(

                    text="⭐ 4",

                    callback_data=f"usrate:{date_str}:{task_index}:{solution_id}:4"

                ),

                InlineKeyboardButton(

                    text="⭐ 5",

                    callback_data=f"usrate:{date_str}:{task_index}:{solution_id}:5"

                )

            ]

        ]

    )

# ============================================================

# INLINE SEARCH

# ============================================================

@dp.inline_query()

async def inline_search(inline_query: InlineQuery):

    query = inline_query.query.strip().lower()

    results = []

    if not query:

        results.append(

            InlineQueryResultArticle(

                id="info",

                title="🔎 Поиск по базе matham",

                description="Введите название файла, тему или хештег",

                input_message_content=InputTextMessageContent(

                    message_text=(

                        "Воспользуйтесь встроенным поиском "

                        "для нахождения учебных материалов!"

                    )

                )

            )

        )

        return await inline_query.answer(

            results,

            cache_time=1

        )

    words = [

        w

        for w in query.split()

        if w

    ]

    for cat_data in DATABASE["categories"].values():

        for f in cat_data.get("files", []):

            haystack = (

                f"{cat_data.get('title', '')} "

                f"{cat_data.get('title_en', '')} "

                f"{f.get('caption', '')} "

                + " ".join(f.get("tags", []))

                + f" {f.get('difficulty', '') or ''}"

            ).lower()

            if all(

                word in haystack

                for word in words

            ):

                cap = (

                    f"📄 **{f['caption']}**\n"

                    f"📌 Раздел: {cat_data['title']}"

                )

                if f.get("tags"):

                    cap += (

                        "\n🏷 Теги: "

                        + " ".join(f["tags"])

                    )

                if f.get("difficulty"):

                    cap += (

                        f"\n📚 Уровень: "

                        f"{f['difficulty']}"

                    )

                results.append(

                    InlineQueryResultCachedDocument(

                        id=f["file_unique_id"],

                        title=f["caption"],

                        document_file_id=f["file_id"],

                        caption=cap,

                        parse_mode="Markdown"

                    )

                )

    await inline_query.answer(

        results[:50],

        cache_time=10

    )

# ============================================================

# LANGUAGE

# ============================================================

# COMMANDS

# ============================================================

@dp.message(Command("start"))

async def cmd_start(

    message: types.Message,

    state: FSMContext

):

    await state.clear()


    await message.answer(

        "Здарова! ✌️\n"

        "Я бот библиотеки matham.\n\n"

        "🔎 Поиск - просто напиши слово.\n"

        "🧩 Задача дня - новая олимпиадная задача.\n"

        "⭐ Must-read - важные материалы.",

        reply_markup=get_main_menu_keyboard(

            message.from_user.id

        )

    )

@dp.message(F.text.in_({"⬅️ Назад", "🔙 Назад", "Назад"}))
async def universal_back(message: types.Message, state: FSMContext):
    logger.debug("Back pressed by user=%s; clearing FSM state", message.from_user.id)
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("👑 Админ-панель", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎯 Задачи дня", callback_data="admin:tasks")],[InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]]))
    else:
        await message.answer("📂 Главное меню", reply_markup=get_main_menu_keyboard(message.from_user.id))

@dp.message(F.text.in_({"⬅️ Назад", "🔙 Назад", "Назад"}))
async def universal_back(message: types.Message, state: FSMContext):
    logger.debug("Back pressed user=%s", message.from_user.id)
    await state.clear()
    await message.answer("📂 Главное меню", reply_markup=get_main_menu_keyboard(message.from_user.id))

@dp.message(Command("menu"))

async def cmd_menu(

    message: types.Message,

    state: FSMContext

):

    await state.clear()

    await track_user_activity(

        message.from_user.id,

        message.from_user.username or ""

    )

    await message.answer(

        t(message.from_user.id, "main_menu"),

        reply_markup=get_main_menu_keyboard(

            message.from_user.id

        )

    )

@dp.callback_query(F.data == "menu:main")

async def process_back_to_main(

    callback: types.CallbackQuery

):

    await track_user_activity(

        callback.from_user.id,

        callback.from_user.username or ""

    )

    await callback.message.edit_text(

        t(callback.from_user.id, "main_menu"),

        reply_markup=get_main_menu_keyboard(

            callback.from_user.id

        )

    )

    await callback.answer()

@dp.callback_query(F.data == "menu:catalog")

async def process_catalog(

    callback: types.CallbackQuery

):

    await callback.message.edit_text(

        f"{t(callback.from_user.id, 'catalog')}\n\n"

        "Выбери раздел:",

        reply_markup=get_catalog_keyboard(

            callback.from_user.id

        )

    )

    await callback.answer()

# ============================================================

# DAILY TASK

# ============================================================

async def send_daily_task(target, date_str: str = None, task_index: int = 0):
    if not date_str:
        date_str = get_yerevan_date()
    task = get_task_by_index(date_str, task_index)
    is_message = isinstance(target, types.Message)
    user_id = target.from_user.id
    if not task:
        text = f"🧩 **Задача дня ({date_str})**\n\n{t(user_id, 'task_not_found')}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(user_id, "menu"), callback_data="menu:main")]])
        if is_message: await target.answer(text, reply_markup=kb)
        else: await target.message.edit_text(text, reply_markup=kb)
        return
    if date_str == get_yerevan_date():
        uid_str = str(user_id)
        opened = DATABASE["users"].setdefault(uid_str, {}).setdefault("opened_tasks", [])
        key = f"{date_str}:{task_index}"
        if key not in opened:
            opened.append(key)
            await award_points(user_id, 5)
            await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {f"data.users.{uid_str}.opened_tasks": opened}})
    cap = f"🧩 **Задача {task_index + 1}** ({date_str})"
    votes = task.get("votes", {})
    if votes:
        avg = sum(votes.values()) / len(votes)
        cap += f"\n\n⭐ Оценка: {avg:.1f}/5 (Голосов: {len(votes)})"
    if len(get_tasks_for_date(date_str)) > 1:
        cap += f"\n📚 Задач за эту дату: {len(get_tasks_for_date(date_str))}"
    kb = get_task_keyboard(date_str, user_id, is_admin(user_id), task_index)
    photo_id = task.get("photo_file_id")
    if photo_id:
        if is_message: await target.answer_photo(photo=photo_id, caption=cap, reply_markup=kb)
        else:
            try: await target.message.delete()
            except Exception: pass
            await target.message.answer_photo(photo=photo_id, caption=cap, reply_markup=kb)
    else:
        if is_message: await target.answer(cap, reply_markup=kb)
        else: await target.message.edit_text(cap, reply_markup=kb)

@dp.message(Command("task"))

async def cmd_task(

    message: types.Message

):

    await track_user_activity(

        message.from_user.id,

        message.from_user.username or ""

    )

    await send_daily_task(

        message

    )

@dp.callback_query(F.data == "task:show")

async def callback_task(

    callback: types.CallbackQuery

):

    await track_user_activity(

        callback.from_user.id,

        callback.from_user.username or ""

    )

    await send_daily_task(

        callback

    )

    await callback.answer()

# ============================================================

# PREVIOUS TASKS

# ============================================================

@dp.callback_query(F.data == "tasks:history")

async def tasks_history(

    callback: types.CallbackQuery

):

    await callback.message.edit_text(

        "📅 **Задачи прошлых дней**\n\n"

        "Выбери дату:",

        reply_markup=get_history_keyboard(

            callback.from_user.id

        )

    )

    await callback.answer()

@dp.callback_query(F.data.startswith("taskdate:"))
async def previous_task(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    date_str = parts[1]
    task_index = int(parts[2]) if len(parts) > 2 else 0
    await send_daily_task(callback, date_str, task_index)
    await callback.answer()

# ============================================================

# DAILY TASK VOTING

# ============================================================

@dp.callback_query(F.data.startswith("tv:"))

async def task_vote_handler(

    callback: types.CallbackQuery

):

    _, date_str, score_str = callback.data.split(":")

    score = int(score_str)

    if score < 1 or score > 5:

        return await callback.answer(

            "Invalid rating",

            show_alert=True

        )

    task = get_task_by_index(date_str, task_index)

    if not task:

        return await callback.answer(

            t(callback.from_user.id, "task_not_found"),

            show_alert=True

        )

    uid_str = str(

        callback.from_user.id

    )

    votes = task.setdefault(

        "votes",

        {}

    )

    if uid_str not in votes:

        await award_points(

            callback.from_user.id,

            2

        )

    votes[uid_str] = score

    await save_db(

        DATABASE

    )

    avg = sum(

        votes.values()

    ) / len(votes)

    cap = (

        f"🧩 **Задача {task_index + 1}** ({date_str})\n\n"

        f"⭐ Оценка: {avg:.1f}/5 "

        f"(Голосов: {len(votes)})"

    )

    try:

        await callback.message.edit_caption(

            caption=cap,

            reply_markup=get_task_keyboard(

                date_str,

                callback.from_user.id,

                is_admin(callback.from_user.id),

                task_index

            )

        )

    except Exception:

        pass

    await callback.answer(

        f"Твоя оценка {score}⭐ сохранена!",

        show_alert=True

    )

# ============================================================

# DAILY TASK SOLUTION

# ============================================================

@dp.callback_query(F.data.startswith("th:"))
async def task_solution_handler(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    date_str = parts[1]
    task_index = int(parts[2]) if len(parts) > 2 else 0
    task = get_task_by_index(date_str, task_index)
    if not task:
        return await callback.answer(t(callback.from_user.id, "task_not_found"), show_alert=True)
    text_solution = task.get("solution", "")
    photo_solution = task.get("solution_photo_file_id")
    if not text_solution and not photo_solution:
        return await callback.answer(t(callback.from_user.id, "solution_missing"), show_alert=True)
    title = f"📝 **Решение задачи {task_index + 1} ({date_str})**"
    if photo_solution:
        await callback.message.answer_photo(photo=photo_solution, caption=title + (f"\n\n{text_solution}" if text_solution else ""))
    else:
        await callback.message.answer(title + "\n\n" + text_solution)
    await callback.answer()

# USER SUBMITS DAILY SOLUTION# USER SUBMITS DAILY SOLUTION

# ============================================================

@dp.callback_query(F.data.startswith("tsol:"))
async def user_solution_start(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    date_str = parts[1]
    task_index = int(parts[2]) if len(parts) > 2 else 0
    if not get_task_by_index(date_str, task_index):
        return await callback.answer(t(callback.from_user.id, "task_not_found"), show_alert=True)
    await state.update_data(solution_date=date_str, solution_task_index=task_index)
    await state.set_state(UserTaskSolution.waiting_for_solution)
    await callback.message.answer(t(callback.from_user.id, "send_text_or_photo") + "\n\n❌ Напиши /cancel для отмены.")
    await callback.answer()

@dp.message(

    UserTaskSolution.waiting_for_solution,

    F.text

)

async def user_solution_text(

    message: types.Message,

    state: FSMContext

):

    if message.text.lower() == "/cancel":

        await state.clear()

        return await message.answer(

            t(message.from_user.id, "cancel")

        )

    data = await state.get_data()

    date_str = data.get(

        "solution_date"

    )

    await save_user_daily_solution(

        message,

        state,

        date_str,

        solution_type="text",

        text=message.text

    )

@dp.message(

    UserTaskSolution.waiting_for_solution,

    F.photo

)

async def user_solution_photo(

    message: types.Message,

    state: FSMContext

):

    data = await state.get_data()

    date_str = data.get(

        "solution_date"

    )

    await save_user_daily_solution(

        message,

        state,

        date_str,

        solution_type="photo",

        photo_id=message.photo[-1].file_id

    )

async def save_user_daily_solution(

    message: types.Message,

    state: FSMContext,

    date_str: str,

    solution_type: str,

    text: str = "",

    photo_id: str = None

):

    data = await state.get_data()
    task_index = data.get("solution_task_index", 0)

    if not date_str:

        await state.clear()

        return await message.answer(

            "❌ Ошибка: дата задачи не найдена."

        )

    task = get_task_by_index(date_str, task_index)

    if not task:

        await state.clear()

        return await message.answer(

            t(message.from_user.id, "task_not_found")

        )

    solution_id = uuid.uuid4().hex[:10]

    username = (

        message.from_user.username

        or message.from_user.full_name

    )

    solution = {

        "solution_id": solution_id,

        "user_id": message.from_user.id,

        "username": username,

        "type": solution_type,

        "text": text or "",

        "photo_file_id": photo_id,

        "status": "pending",

        "rating": None,

        "created_at": datetime.now(

            timezone.utc

        ).isoformat()

    }

    task.setdefault(

        "user_solutions",

        {}

    )

    task["user_solutions"][solution_id] = solution

    await save_db(

        DATABASE

    )

    await state.clear()

    await message.answer(

        "✅ Твоё решение отправлено админу!\n"

        "После проверки ты получишь оценку."

    )

    # Send to admins

    for admin_id in ADMIN_IDS:

        try:

            caption = (

                "🧠 **Новое решение задачи**\n\n"

                f"📅 Дата: {date_str}\n"

                f"👤 Автор: @{username}\n"

                f"🆔 Solution ID: `{solution_id}`\n\n"

                "Оцени решение от 1 до 5:"

            )

            kb = get_solution_rating_keyboard(date_str, solution_id, task_index)

            if solution_type == "photo":

                await bot.send_photo(

                    admin_id,

                    photo=photo_id,

                    caption=caption,

                    reply_markup=kb

                )

            else:

                await bot.send_message(

                    admin_id,

                    caption

                    + "\n\n"

                    + text,

                    reply_markup=kb

                )

        except Exception as e:

            logger.error(

                "Failed to send user solution to admin: %s",

                e

            )

# ============================================================

# ADMIN RATES USER SOLUTION

# ============================================================

@dp.callback_query(F.data.startswith("usrate:"))

async def admin_rate_user_solution(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return await callback.answer(

            "⛔",

            show_alert=True

        )

    parts = callback.data.split(":")

    if len(parts) == 5:
        _, date_str, idx_str, solution_id, score_str = parts
        task_index = int(idx_str)
    elif len(parts) == 4:
        _, date_str, solution_id, score_str = parts
        task_index = 0
    else:
        return await callback.answer("Ошибка", show_alert=True)

    score = int(score_str)

    if score < 1 or score > 5:

        return await callback.answer(

            "Ошибка оценки",

            show_alert=True

        )

    task = get_task_by_index(date_str, task_index)

    if not task:

        return await callback.answer(

            "Задача не найдена",

            show_alert=True

        )

    solution = task.get(

        "user_solutions",

        {}

    ).get(solution_id)

    if not solution:

        return await callback.answer(

            "Решение не найдено",

            show_alert=True

        )

    if solution.get("rating") is not None:

        return await callback.answer(

            "Это решение уже оценено.",

            show_alert=True

        )

    solution["rating"] = score

    solution["status"] = "rated"

    solution["rated_by"] = callback.from_user.id

    solution["rated_at"] = datetime.now(

        timezone.utc

    ).isoformat()

    await save_db(

        DATABASE

    )

    # Points

    points = score * 3

    await award_points(

        solution["user_id"],

        points

    )

    # Update admin message

    try:

        await callback.message.edit_reply_markup(

            reply_markup=None

        )

    except Exception:

        pass

    # Notify user

    try:

        await bot.send_message(

            solution["user_id"],

            f"🎉 Твоё решение задачи "

            f"{date_str} проверено!\n\n"

            f"⭐ Оценка: {score}/5\n"

            f"🏆 +{points} очков"

        )

    except Exception as e:

        logger.error(

            "Failed to notify user about rating: %s",

            e

        )

    await callback.answer(

        f"Оценка {score}/5 сохранена!",

        show_alert=True

    )

# ============================================================

# ADMIN: VIEW USER SOLUTIONS

# ============================================================

@dp.callback_query(F.data.startswith("tusers:"))

async def admin_task_user_solutions(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return await callback.answer(

            "⛔",

            show_alert=True

        )

    parts = callback.data.split(":")
    date_str = parts[1]
    task_index = int(parts[2]) if len(parts) > 2 else 0

    task = get_task_by_index(date_str, task_index)

    if not task:

        return await callback.answer(

            "Задача не найдена",

            show_alert=True

        )

    solutions = task.get(

        "user_solutions",

        {}

    )

    if not solutions:

        return await callback.answer(

            "Пользовательских решений пока нет.",

            show_alert=True

        )

    pending = sum(

        1

        for s in solutions.values()

        if s.get("rating") is None

    )

    rated = len(solutions) - pending

    text = (

        f"👥 **Решения пользователей - {date_str}**\n\n"

        f"Всего: {len(solutions)}\n"

        f"⏳ На проверке: {pending}\n"

        f"✅ Проверено: {rated}"

    )

    await callback.message.edit_text(

        text,

        reply_markup=InlineKeyboardMarkup(

            inline_keyboard=[

                [

                    InlineKeyboardButton(

                        text="📨 Показать решения",

                        callback_data=f"tshow:{date_str}:{task_index}"

                    )

                ],

                [

                    InlineKeyboardButton(

                        text="⬅️ Назад",

                        callback_data=f"taskdate:{date_str}:{task_index}"

                    )

                ]

            ]

        )

    )

    await callback.answer()

@dp.callback_query(F.data.startswith("tshow:"))

async def admin_show_user_solutions(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return await callback.answer(

            "⛔",

            show_alert=True

        )

    parts = callback.data.split(":")
    date_str = parts[1]
    task_index = int(parts[2]) if len(parts) > 2 else 0

    task = get_task_by_index(date_str, task_index)

    if not task:

        return await callback.answer(

            "Задача не найдена",

            show_alert=True

        )

    solutions = task.get(

        "user_solutions",

        {}

    )

    await callback.answer()

    for solution in solutions.values():

        username = solution.get(

            "username",

            "Unknown"

        )

        rating = solution.get(

            "rating"

        )

        status = (

            f"⭐ {rating}/5"

            if rating is not None

            else "⏳ Не оценено"

        )

        header = (

            f"🧠 **Решение**\n"

            f"📅 {date_str}\n"

            f"👤 {username}\n"

            f"📊 {status}\n"

            f"🆔 `{solution['solution_id']}`"

        )

        if solution.get("type") == "photo":

            try:

                await callback.message.answer_photo(

                    photo=solution["photo_file_id"],

                    caption=header,

                    reply_markup=(

                        get_solution_rating_keyboard(date_str, solution["solution_id"], task_index)

                        if rating is None

                        else None

                    )

                )

            except Exception:

                pass

        else:

            text = (

                header

                + "\n\n"

                + solution.get("text", "")

            )

            await callback.message.answer(

                text,

                reply_markup=(

                    get_solution_rating_keyboard(

                        date_str,

                        solution["solution_id"]

                    )

                    if rating is None

                    else None

                )

            )

# ============================================================

# TASK ADMIN STATS

# ============================================================

@dp.callback_query(F.data.startswith("ts:"))

async def task_stats_admin(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    parts = callback.data.split(":")
    date_str = parts[1]
    task_index = int(parts[2]) if len(parts) > 2 else 0

    task = get_task_by_index(date_str, task_index)

    if not task:

        return await callback.answer(

            "Нет задачи",

            show_alert=True

        )

    votes = task.get(

        "votes",

        {}

    )

    if not votes:

        return await callback.answer(

            "Оценок пока нет.",

            show_alert=True

        )

    counts = {

        1: 0,

        2: 0,

        3: 0,

        4: 0,

        5: 0

    }

    for v in votes.values():

        if v in counts:

            counts[v] += 1

    avg = sum(

        votes.values()

    ) / len(votes)

    text = (

        f"📊 Статистика за {date_str}\n\n"

        f"Всего голосов: {len(votes)}\n"

        f"Средняя: {avg:.2f}\n\n"

        f"5⭐: {counts[5]}\n"

        f"4⭐: {counts[4]}\n"

        f"3⭐: {counts[3]}\n"

        f"2⭐: {counts[2]}\n"

        f"1⭐: {counts[1]}"

    )

    await callback.answer(

        text,

        show_alert=True

    )

# ============================================================

# MUST READ

# ============================================================

@dp.callback_query(F.data == "mustread:main")

async def mustread_main(

    callback: types.CallbackQuery

):

    files = []

    for cat_data in DATABASE["categories"].values():

        for f in cat_data.get(

            "files",

            []

        ):

            if f.get("must_read"):

                if not any(

                    x["file_unique_id"]

                    == f["file_unique_id"]

                    for x in files

                ):

                    files.append(f)

    if not files:

        return await callback.message.edit_text(

            "⭐ **MUST-READ**\n\n"

            "Пока пусто.",

            reply_markup=InlineKeyboardMarkup(

                inline_keyboard=[

                    [

                        InlineKeyboardButton(

                            text=t(

                                callback.from_user.id,

                                "menu"

                            ),

                            callback_data="menu:main"

                        )

                    ]

                ]

            )

        )

    builder = []

    for f in files[:90]:

        builder.append([

            InlineKeyboardButton(

                text=f"📄 {f['caption'][:35]}",

                callback_data=f"fv:{f['file_unique_id']}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text=t(

                callback.from_user.id,

                "menu"

            ),

            callback_data="menu:main"

        )

    ])

    await callback.message.edit_text(

        "⭐ **MUST-READ**\n\n"

        "Самые полезные материалы:",

        reply_markup=InlineKeyboardMarkup(

            inline_keyboard=builder

        )

    )

    await callback.answer()

# ============================================================

# FAVORITES

# ============================================================

@dp.message(Command("favorites"))

async def cmd_fav(

    message: types.Message

):

    await track_user_activity(

        message.from_user.id,

        message.from_user.username or ""

    )

    await show_favorites(

        message

    )

@dp.callback_query(F.data == "favorites:main")

async def cb_fav(

    callback: types.CallbackQuery

):

    await track_user_activity(

        callback.from_user.id,

        callback.from_user.username or ""

    )

    await show_favorites(

        callback

    )

async def show_favorites(target):

    user_id = target.from_user.id

    user = DATABASE["users"].get(

        str(user_id),

        {}

    )

    favs = user.get(

        "favorites",

        []

    )

    if not favs:

        text = (

            "❤️ **Избранное**\n\n"

            "Тут пока пусто."

        )

        kb = InlineKeyboardMarkup(

            inline_keyboard=[

                [

                    InlineKeyboardButton(

                        text=t(user_id, "menu"),

                        callback_data="menu:main"

                    )

                ]

            ]

        )

        if isinstance(target, types.Message):

            await target.answer(

                text,

                reply_markup=kb

            )

        else:

            await target.message.edit_text(

                text,

                reply_markup=kb

            )

        return

    builder = []

    valid_count = 0

    for uid in favs[:90]:

        f = get_file_by_uid(uid)

        if f:

            valid_count += 1

            builder.append([

                InlineKeyboardButton(

                    text=f"📄 {f['caption'][:35]}",

                    callback_data=f"fv:{uid}"

                )

            ])

    builder.append([

        InlineKeyboardButton(

            text=t(user_id, "menu"),

            callback_data="menu:main"

        )

    ])

    text = (

        f"❤️ **Твое избранное** "

        f"({valid_count} шт.):"

    )

    markup = InlineKeyboardMarkup(

        inline_keyboard=builder

    )

    if isinstance(target, types.Message):

        await target.answer(

            text,

            reply_markup=markup

        )

    else:

        await target.message.edit_text(

            text,

            reply_markup=markup

        )

@dp.callback_query(F.data.startswith("fav:"))

async def toggle_fav(

    callback: types.CallbackQuery

):

    uid = callback.data.split(":")[1]

    user_id_str = str(

        callback.from_user.id

    )

    if user_id_str not in DATABASE["users"]:

        await track_user_activity(

            callback.from_user.id,

            callback.from_user.username or ""

        )

    user = DATABASE["users"][user_id_str]

    favs = user.setdefault(

        "favorites",

        []

    )

    if uid in favs:

        favs.remove(uid)

        await db_collection.update_one(

            {"_id": DB_DOC_ID},

            {

                "$pull": {

                    f"data.users.{user_id_str}.favorites":

                        uid

                }

            }

        )

        await callback.answer(

            "💔 Удалено из избранного"

        )

    else:

        favs.append(uid)

        await db_collection.update_one(

            {"_id": DB_DOC_ID},

            {

                "$addToSet": {

                    f"data.users.{user_id_str}.favorites":

                        uid

                }

            }

        )

        await callback.answer(

            "❤️ Добавлено в избранное"

        )

    try:

        await callback.message.edit_reply_markup(

            reply_markup=get_file_view_keyboard(

                uid,

                callback.from_user.id

            )

        )

    except Exception:

        pass

# ============================================================

# RATING

# ============================================================

@dp.message(Command("rating"))

async def cmd_rating(

    message: types.Message

):

    await show_rating(

        message

    )

@dp.callback_query(F.data == "rating:main")

async def cb_rating(

    callback: types.CallbackQuery

):

    await show_rating(

        callback

    )

async def show_rating(target):

    users = [

        (uid, u)

        for uid, u in DATABASE["users"].items()

        if u.get("score", 0) > 0

    ]

    users.sort(

        key=lambda x: x[1].get(

            "score",

            0

        ),

        reverse=True

    )

    text = "🏆 **Рейтинг активности**\n\n"

    medals = [

        "🥇",

        "🥈",

        "🥉"

    ]

    for i, (uid, u) in enumerate(

        users[:10]

    ):

        medal = (

            medals[i]

            if i < 3

            else "🏅"

        )

        name = (

            u.get("username")

            or f"ID {uid}"

        )

        text += (

            f"{medal} {name} - "

            f"{u.get('score', 0)} очков\n"

        )

    user_id = str(

        target.from_user.id

    )

    my_user = DATABASE["users"].get(

        user_id,

        {}

    )

    my_score = my_user.get(

        "score",

        0

    )

    my_streak = my_user.get(

        "streak",

        0

    )

    text += (

        f"\n🔥 {t(target.from_user.id, 'streak')}: "

        f"{my_streak} дней"

    )

    text += (

        f"\n🎯 {t(target.from_user.id, 'your_score')}: "

        f"{my_score}"

    )

    kb = InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text=t(

                        target.from_user.id,

                        "menu"

                    ),

                    callback_data="menu:main"

                )

            ]

        ]

    )

    if isinstance(target, types.Message):

        await target.answer(

            text,

            reply_markup=kb

        )

    else:

        await target.message.edit_text(

            text,

            reply_markup=kb

        )

# ============================================================

# RANDOM

# ============================================================

@dp.message(Command("surprise"))

async def cmd_surprise(

    message: types.Message

):

    await process_random(

        message,

        diff=None

    )

@dp.message(Command("challenge"))

async def cmd_challenge(

    message: types.Message

):

    kb = InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="🟢 Easy",

                    callback_data="rand:easy"

                ),

                InlineKeyboardButton(

                    text="🟡 Medium",

                    callback_data="rand:medium"

                )

            ],

            [

                InlineKeyboardButton(

                    text="🔴 Hard",

                    callback_data="rand:hard"

                ),

                InlineKeyboardButton(

                    text="🔥 IMO",

                    callback_data="rand:imo"

                )

            ],

            [

                InlineKeyboardButton(

                    text="🎲 Любая",

                    callback_data="rand:any"

                )

            ]

        ]

    )

    await message.answer(

        "Выбери уровень сложности:",

        reply_markup=kb

    )

@dp.callback_query(F.data == "challenge:main")

async def cb_challenge(

    callback: types.CallbackQuery

):

    kb = InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="🟢 Easy",

                    callback_data="rand:easy"

                ),

                InlineKeyboardButton(

                    text="🟡 Medium",

                    callback_data="rand:medium"

                )

            ],

            [

                InlineKeyboardButton(

                    text="🔴 Hard",

                    callback_data="rand:hard"

                ),

                InlineKeyboardButton(

                    text="🔥 IMO",

                    callback_data="rand:imo"

                )

            ],

            [

                InlineKeyboardButton(

                    text="🎲 Любая",

                    callback_data="rand:any"

                )

            ]

        ]

    )

    await callback.message.edit_text(

        "Выбери уровень сложности:",

        reply_markup=kb

    )

    await callback.answer()

@dp.callback_query(F.data.startswith("rand:"))

async def cb_do_random(

    callback: types.CallbackQuery

):

    diff = callback.data.split(":")[1]

    if diff == "any":

        diff = None

    await process_random(

        callback,

        diff

    )

    await callback.answer()

async def process_random(

    target,

    diff: str

):

    all_files = []

    for cat_data in DATABASE["categories"].values():

        for f in cat_data.get(

            "files",

            []

        ):

            if (

                diff is None

                or f.get("difficulty") == diff

            ):

                if not any(

                    x[0]["file_unique_id"]

                    == f["file_unique_id"]

                    for x in all_files

                ):

                    all_files.append(

                        (

                            f,

                            cat_data["title"]

                        )

                    )

    if not all_files:

        msg = (

            "К сожалению, файлов такой "

            "сложности пока нет 😔"

        )

        if isinstance(

            target,

            types.Message

        ):

            await target.answer(

                msg

            )

        else:

            await target.message.edit_text(

                msg

            )

        return

    selected_file, cat_title = random.choice(

        all_files

    )

    await award_points(

        target.from_user.id,

        1

    )

    text = (

        "🎲 Случайный материал!\n"

        f"Раздел: **{cat_title}**"

    )

    if selected_file.get(

        "difficulty"

    ):

        text += (

            f"\nСложность: "

            f"{selected_file['difficulty'].upper()}"

        )

    if isinstance(

        target,

        types.Message

    ):

        await target.answer(

            text

        )

        await target.answer_document(

            document=selected_file["file_id"],

            caption=f"📄 {selected_file['caption']}",

            reply_markup=get_file_view_keyboard(

                selected_file["file_unique_id"],

                target.from_user.id

            )

        )

    else:

        try:

            await target.message.delete()

        except Exception:

            pass

        await target.message.answer(

            text

        )

        await target.message.answer_document(

            document=selected_file["file_id"],

            caption=f"📄 {selected_file['caption']}",

            reply_markup=get_file_view_keyboard(

                selected_file["file_unique_id"],

                target.from_user.id

            )

        )

# ============================================================

# CATEGORIES

# ============================================================

@dp.callback_query(F.data.startswith("cat:"))

async def process_category_click(

    callback: types.CallbackQuery

):

    cat_key = callback.data.split(":")[1]

    cat_data = DATABASE["categories"].get(

        cat_key

    )

    if not cat_data:

        return await callback.answer(

            "Раздел не найден",

            show_alert=True

        )

    if not cat_data.get("files"):

        return await callback.message.edit_text(

            f"**{category_title(cat_data, callback.from_user.id)}**\n\n"

            "📁 Пока нет файлов.",

            reply_markup=InlineKeyboardMarkup(

                inline_keyboard=[

                    [

                        InlineKeyboardButton(

                            text=t(

                                callback.from_user.id,

                                "back"

                            ),

                            callback_data="menu:catalog"

                        )

                    ]

                ]

            )

        )

    builder = []

    for item in cat_data["files"][:90]:

        btn_text = (

            f"📄 {item['caption'][:35]}"

        )

        if len(item["caption"]) > 35:

            btn_text += "..."

        builder.append([

            InlineKeyboardButton(

                text=btn_text,

                callback_data=f"fv:{item['file_unique_id']}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text=t(

                callback.from_user.id,

                "back"

            ),

            callback_data="menu:catalog"

        )

    ])

    await callback.message.edit_text(

        f"**{category_title(cat_data, callback.from_user.id)}**\n\n"

        "⬇️ Выбери файл:",

        reply_markup=InlineKeyboardMarkup(

            inline_keyboard=builder

        )

    )

    await callback.answer()

# ============================================================

# VIEW FILE

# ============================================================

@dp.callback_query(F.data.startswith("fv:"))

async def view_file(

    callback: types.CallbackQuery

):

    uid = callback.data.split(":")[1]

    f = get_file_by_uid(

        uid

    )

    if not f:

        return await callback.answer(

            "❌ Файл больше не доступен.",

            show_alert=True

        )

    await callback.answer(

        "Отправляю... ⏳"

    )

    cap = (

        f"📄 {f['caption']}"

    )

    tags = f.get(

        "tags",

        []

    )

    if tags:

        cap += (

            "\n🏷 Теги: "

            + " ".join(tags)

        )

    if f.get("difficulty"):

        cap += (

            f"\n📚 Уровень: "

            f"{f['difficulty']}"

        )

    if f.get("must_read"):

        cap += "\n⭐ Must-read"

    await callback.message.answer_document(

        document=f["file_id"],

        caption=cap,

        reply_markup=get_file_view_keyboard(

            uid,

            callback.from_user.id

        )

    )

# ============================================================

# IMPORTANT:

# GLOBAL TEXT SEARCH ONLY WHEN NO FSM STATE

# ============================================================

@dp.message(

    StateFilter(None),

    F.text & ~F.text.startswith("/")

)

async def global_search_handler(

    message: types.Message

):

    logger.debug("GLOBAL SEARCH user=%s query=%r state=NONE", message.from_user.id, message.text)

    query = message.text.strip().lower()
    logger.debug("Global search user=%s query=%r", message.from_user.id, query)

    if query in [

        "удиви меня",

        "surprise",

        "рандом",

        "challenge"

    ]:

        return await cmd_challenge(

            message

        )

    words = [

        w

        for w in query.split()

        if w

    ]

    if not words:

        return

    found_files = []

    for cat_data in DATABASE["categories"].values():

        for f in cat_data.get(

            "files",

            []

        ):

            haystack = (

                f"{cat_data.get('title', '')} "

                f"{cat_data.get('title_en', '')} "

                f"{f.get('caption', '')} "

                + " ".join(

                    f.get("tags", [])

                )

                + f" {f.get('difficulty', '')}"

            ).lower()

            if all(

                w in haystack

                for w in words

            ):

                if not any(

                    x[0]["file_unique_id"]

                    == f["file_unique_id"]

                    for x in found_files

                ):

                    found_files.append(

                        (

                            f,

                            cat_data["title"]

                        )

                    )

    found_links = []

    for sec in DATABASE["links"].values():

        for item in sec.get(

            "items",

            []

        ):

            haystack = (

                f"{item.get('title', '')} "

                f"{item.get('description', '')}"

            ).lower()

            if all(

                w in haystack

                for w in words

            ):

                found_links.append(

                    item

                )

    if not found_files and not found_links:

        return await message.answer(

            "🔍 Ничего не найдено.\n"

            "Попробуй другое слово или открой меню:",

            reply_markup=get_main_menu_keyboard(

                message.from_user.id

            )

        )

    if found_files:

        await message.answer(

            f"🔍 Найдено файлов: "

            f"**{len(found_files)}**"

        )

        for f, cat_title in found_files[:10]:

            await message.answer_document(

                document=f["file_id"],

                caption=(

                    f"📄 **{f['caption']}**\n"

                    f"📌 {cat_title}"

                ),

                reply_markup=get_file_view_keyboard(

                    f["file_unique_id"],

                    message.from_user.id

                )

            )

    if found_links:

        builder = [

            [

                InlineKeyboardButton(

                    text=item["title"],

                    url=item["url"]

                )

            ]

            for item in found_links[:10]

        ]

        await message.answer(

            f"🔗 Найдено ссылок: "

            f"**{len(found_links)}**",

            reply_markup=InlineKeyboardMarkup(

                inline_keyboard=builder

            )

        )

# ============================================================

# ADMIN PANEL

# ============================================================

@dp.callback_query(F.data == "admin:main")

async def admin_panel(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return await callback.answer(

            "⛔",

            show_alert=True

        )

    keyboard = InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="📤 Добавить файл",

                    callback_data="admin:upload"

                )

            ],

            [

                InlineKeyboardButton(

                    text="✏️ Управление файлами",

                    callback_data="menu:catalog"

                )

            ],

            [

                InlineKeyboardButton(

                    text="🎯 Задача дня",

                    callback_data="admin:tasks"

                )

            ],

            [

                InlineKeyboardButton(

                    text="⭐ Управление Must-read",

                    callback_data="mustread:main"

                )

            ],

            [

                InlineKeyboardButton(

                    text="📊 Статистика",

                    callback_data="admin:stats"

                )

            ],

            [

                InlineKeyboardButton(

                    text="📢 Рассылка",

                    callback_data="admin:broadcast"

                )

            ],

            [

                InlineKeyboardButton(

                    text="⬅️ Главное меню",

                    callback_data="menu:main"

                )

            ]

        ]

    )

    await callback.message.edit_text(

        "👑 **Админ-панель**\n\n"

        "Выбери действие:",

        reply_markup=keyboard

    )

    await callback.answer()

@dp.callback_query(F.data == "admin:stats")

async def admin_stats(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    unique_files = set()

    for c in DATABASE["categories"].values():

        for f in c.get(

            "files",

            []

        ):

            unique_files.add(

                f["file_unique_id"]

            )

    must_read_files = set()

    for c in DATABASE["categories"].values():

        for f in c.get(

            "files",

            []

        ):

            if f.get("must_read"):

                must_read_files.add(

                    f["file_unique_id"]

                )

    links_count = sum(

        len(

            s.get(

                "items",

                []

            )

        )

        for s in DATABASE["links"].values()

    )

    tasks_count = sum(len(get_tasks_for_date(d)) for d in DATABASE["daily_tasks"])

    users_count = len(

        DATABASE["users"]

    )

    active_users = sum(

        1

        for u in DATABASE["users"].values()

        if u.get("score", 0) > 0

    )

    text = (

        "📊 **Статистика**\n\n"

        f"👥 Пользователей: {users_count}\n"

        f"🔥 Активных: {active_users}\n"

        f"📚 Уникальных файлов: {len(unique_files)}\n"

        f"⭐ Must-read: {len(must_read_files)}\n"

        f"🔗 Ссылок: {links_count}\n"

        f"🎯 Задач дня: {tasks_count}"

    )

    await callback.message.edit_text(

        text,

        reply_markup=InlineKeyboardMarkup(

            inline_keyboard=[

                [

                    InlineKeyboardButton(

                        text="⬅️ Назад",

                        callback_data="admin:main"

                    )

                ]

            ]

        )

    )

    await callback.answer()

# ============================================================

# ADMIN BROADCAST

# ============================================================

@dp.callback_query(F.data == "admin:broadcast")

async def admin_broadcast_start(

    callback: types.CallbackQuery,

    state: FSMContext

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    await state.set_state(

        BroadcastAdmin.waiting_for_message

    )

    await callback.message.answer(

        "📢 Отправь сообщение для рассылки всем пользователям.\n\n"

        "Для отмены напиши 'отмена'."

    )

    await callback.answer()

@dp.message(

    BroadcastAdmin.waiting_for_message

)

async def admin_broadcast_msg(

    message: types.Message,

    state: FSMContext

):

    if not is_admin(

        message.from_user.id

    ):

        return

    if (

        message.text

        and message.text.lower() == "отмена"

    ):

        await state.clear()

        return await message.answer(

            "❌ Рассылка отменена."

        )

    await state.update_data(

        msg_id=message.message_id,

        chat_id=message.chat.id

    )

    kb = InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="✅ Да, отправить всем",

                    callback_data="broadcast:confirm"

                ),

                InlineKeyboardButton(

                    text="❌ Отмена",

                    callback_data="broadcast:cancel"

                )

            ]

        ]

    )

    await message.answer(

        "Отправить это сообщение всем пользователям?",

        reply_markup=kb

    )

@dp.callback_query(F.data == "broadcast:cancel")

async def broadcast_cancel(

    callback: types.CallbackQuery,

    state: FSMContext

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    await state.clear()

    await callback.message.edit_text(

        "❌ Рассылка отменена."

    )

@dp.callback_query(F.data == "broadcast:confirm")

async def broadcast_confirm(

    callback: types.CallbackQuery,

    state: FSMContext

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    data = await state.get_data()

    msg_id = data.get(

        "msg_id"

    )

    chat_id = data.get(

        "chat_id"

    )

    await state.clear()

    if not msg_id:

        return await callback.answer(

            "Ошибка",

            show_alert=True

        )

    await callback.message.edit_text(

        "⏳ Начинаю рассылку..."

    )

    success = 0

    errors = 0

    for uid_str in list(

        DATABASE["users"].keys()

    ):

        try:

            await bot.copy_message(

                chat_id=int(uid_str),

                from_chat_id=chat_id,

                message_id=msg_id

            )

            success += 1

        except TelegramRetryAfter as e:

            await asyncio.sleep(

                e.retry_after

            )

            try:

                await bot.copy_message(

                    chat_id=int(uid_str),

                    from_chat_id=chat_id,

                    message_id=msg_id

                )

                success += 1

            except Exception:

                errors += 1

        except Exception:

            errors += 1

        await asyncio.sleep(

            0.05

        )

    await callback.message.answer(

        f"📢 **Рассылка завершена!**\n"

        f"✅ Успешно: {success}\n"

        f"❌ Ошибок: {errors}"

    )

# ============================================================

# ADMIN DAILY TASK MANAGEMENT

# ============================================================

@dp.callback_query(F.data == "admin:tasks")

async def admin_tasks_menu(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    kb = InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="➕ Добавить задачу",

                    callback_data="adm_t:add"

                )

            ],

            [

                InlineKeyboardButton(

                    text="📅 Просмотреть задачи",

                    callback_data="tasks:history"

                )

            ],

            [

                InlineKeyboardButton(

                    text="⬅️ Назад",

                    callback_data="admin:main"

                )

            ]

        ]

    )

    await callback.message.edit_text(

        "🎯 **Управление задачами дня**",

        reply_markup=kb

    )

    await callback.answer()

@dp.callback_query(F.data == "adm_t:add")

async def adm_task_add(

    callback: types.CallbackQuery,

    state: FSMContext

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    await state.clear()

    await state.set_state(

        TaskOfDayAdmin.waiting_for_photo

    )

    await callback.message.answer(

        "🖼 Отправь ФОТО задачи дня."

    )

    await callback.answer()

# IMPORTANT:

# ADMIN TASK PHOTO HANDLER HAS FSM STATE,

# SO GLOBAL SEARCH CANNOT SEE THIS MESSAGE.

@dp.message(

    TaskOfDayAdmin.waiting_for_photo,

    F.photo

)

async def adm_task_photo(

    message: types.Message,

    state: FSMContext

):

    if not is_admin(

        message.from_user.id

    ):

        return

    logger.debug("Admin task photo received user=%s", message.from_user.id)
    await state.update_data(

        photo_id=message.photo[-1].file_id

    )

    await state.set_state(

        TaskOfDayAdmin.waiting_for_solution

    )
    logger.debug("Admin task state -> waiting_for_solution user=%s", message.from_user.id)

    await message.answer(

        "📝 Теперь отправь решение.\n\n"

        "Можно:\n"

        "• написать решение текстом\n"

        "• отправить фото решения\n"

        "• отправить '-' чтобы оставить без решения."

    )

# TEXT SOLUTION

@dp.message(

    TaskOfDayAdmin.waiting_for_solution,

    F.text

)

async def adm_task_solution_text(

    message: types.Message,

    state: FSMContext

):

    if not is_admin(

        message.from_user.id

    ):

        return

    if message.text.strip() == "-":

        solution = ""

        solution_photo = None

    else:

        solution = message.text

        solution_photo = None

    await state.update_data(

        solution=solution,

        solution_photo_file_id=solution_photo

    )

    await state.set_state(

        TaskOfDayAdmin.waiting_for_date

    )

    today = get_yerevan_date()

    await message.answer(

        "📅 Отправь дату в формате YYYY-MM-DD.\n"

        f"Или напиши 'сегодня' ({today})."

    )

# PHOTO SOLUTION

@dp.message(

    TaskOfDayAdmin.waiting_for_solution,

    F.photo

)

async def adm_task_solution_photo(

    message: types.Message,

    state: FSMContext

):

    if not is_admin(

        message.from_user.id

    ):

        return

    await state.update_data(

        solution="",

        solution_photo_file_id=message.photo[-1].file_id

    )

    await state.set_state(

        TaskOfDayAdmin.waiting_for_date

    )

    today = get_yerevan_date()

    await message.answer(

        "📅 Решение-фото сохранено.\n\n"

        "Теперь отправь дату в формате YYYY-MM-DD.\n"

        f"Или напиши 'сегодня' ({today})."

    )

@dp.message(

    TaskOfDayAdmin.waiting_for_date,

    F.text

)

async def adm_task_date(

    message: types.Message,

    state: FSMContext

):

    if not is_admin(

        message.from_user.id

    ):

        return

    date_str = message.text.strip()

    if date_str.lower() == "сегодня":

        date_str = get_yerevan_date()

    try:

        datetime.strptime(

            date_str,

            "%Y-%m-%d"

        )

    except ValueError:

        return await message.answer(

            "❌ Неверный формат.\n"

            "Используй YYYY-MM-DD или 'сегодня'."

        )

    data = await state.get_data()

    await state.clear()

    group = get_task_group(date_str)
    if not group:
        group = {"tasks": []}
        DATABASE["daily_tasks"][date_str] = group
    group["tasks"].append({
        "task_id": uuid.uuid4().hex[:10],
        "photo_file_id": data["photo_id"],
        "solution": data.get("solution", ""),
        "solution_photo_file_id": data.get("solution_photo_file_id"),
        "votes": {},
        "user_solutions": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    for i, task_item in enumerate(group["tasks"], 1):
        task_item["number"] = i

    await save_db(

        DATABASE

    )

    await message.answer(

        f"✅ Задача на {date_str} успешно сохранена!"

    )

# ============================================================

# ADMIN FILE EDITING

# ============================================================

def update_file_everywhere(

    uid: str,

    key: str,

    value

):

    for cat in DATABASE["categories"].values():

        for f in cat.get(

            "files",

            []

        ):

            if f.get(

                "file_unique_id"

            ) == uid:

                f[key] = value

@dp.callback_query(F.data.startswith("fe_m:"))

async def fe_menu(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(":")[1]

    f = get_file_by_uid(

        uid

    )

    if not f:

        return await callback.answer(

            "Файл не найден",

            show_alert=True

        )

    await callback.message.edit_reply_markup(

        reply_markup=get_file_edit_keyboard(

            uid

        )

    )

    await callback.answer()

@dp.callback_query(F.data == "fe_close")

async def fe_close(

    callback: types.CallbackQuery

):

    try:

        await callback.message.delete()

    except Exception:

        pass

@dp.callback_query(F.data.startswith("fe_mr:"))

async def fe_toggle_mustread(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(":")[1]

    f = get_file_by_uid(

        uid

    )

    if not f:

        return await callback.answer(

            "Ошибка",

            show_alert=True

        )

    new_val = not f.get(

        "must_read",

        False

    )

    update_file_everywhere(

        uid,

        "must_read",

        new_val

    )

    await save_db(

        DATABASE

    )

    await callback.message.edit_reply_markup(

        reply_markup=get_file_edit_keyboard(

            uid

        )

    )

    await callback.answer(

        "Статус Must-read обновлен"

    )

@dp.callback_query(F.data.startswith("fe_df:"))

async def fe_diff_menu(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(":")[1]

    await callback.message.edit_reply_markup(

        reply_markup=get_difficulty_keyboard(

            uid

        )

    )

    await callback.answer()

@dp.callback_query(F.data.startswith("fed_v:"))

async def fe_set_diff(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    _, uid, diff = callback.data.split(":")

    if diff == "none":

        diff = None

    update_file_everywhere(

        uid,

        "difficulty",

        diff

    )

    await save_db(

        DATABASE

    )

    await callback.message.edit_reply_markup(

        reply_markup=get_file_edit_keyboard(

            uid

        )

    )

    await callback.answer(

        "Сложность обновлена"

    )

@dp.callback_query(F.data.startswith("fe_t:"))

async def fe_edit_title(

    callback: types.CallbackQuery,

    state: FSMContext

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(":")[1]

    await state.set_state(

        EditFile.waiting_for_title

    )

    await state.update_data(

        edit_uid=uid

    )

    await callback.message.answer(

        "Отправь новое название файла:"

    )

    await callback.answer()

@dp.message(

    EditFile.waiting_for_title,

    F.text

)

async def fe_save_title(

    message: types.Message,

    state: FSMContext

):

    if not is_admin(

        message.from_user.id

    ):

        return

    data = await state.get_data()

    uid = data["edit_uid"]

    update_file_everywhere(

        uid,

        "caption",

        message.text.strip()

    )

    await save_db(

        DATABASE

    )

    await state.clear()

    await message.answer(

        "✅ Название обновлено!"

    )

@dp.callback_query(F.data.startswith("fe_tg:"))

async def fe_edit_tags(

    callback: types.CallbackQuery,

    state: FSMContext

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(":")[1]

    await state.set_state(

        EditFile.waiting_for_tags

    )

    await state.update_data(

        edit_uid=uid

    )

    await callback.message.answer(

        "Отправь теги через пробел.\n"

        "Например: #geometry #imo"

    )

    await callback.answer()

@dp.message(

    EditFile.waiting_for_tags,

    F.text

)

async def fe_save_tags(

    message: types.Message,

    state: FSMContext

):

    if not is_admin(

        message.from_user.id

    ):

        return

    data = await state.get_data()

    uid = data["edit_uid"]

    tags = [

        w

        for w in message.text.split()

        if w.startswith("#")

    ]

    update_file_everywhere(

        uid,

        "tags",

        tags

    )

    await save_db(

        DATABASE

    )

    await state.clear()

    await message.answer(

        f"✅ Теги обновлены: "

        f"{' '.join(tags)}"

    )

@dp.callback_query(F.data.startswith("fe_c:"))

async def fe_edit_cats(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(":")[1]

    current_cats = set(

        get_file_categories(uid)

    )

    await callback.message.edit_reply_markup(

        reply_markup=get_file_edit_categories_kb(

            uid,

            current_cats

        )

    )

    await callback.answer()

@dp.callback_query(F.data.startswith("fec_t:"))

async def fe_cat_toggle(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    _, uid, cat_key = callback.data.split(":")

    kb = callback.message.reply_markup

    selected = set()

    if kb:

        for row in kb.inline_keyboard:

            for btn in row:

                if (

                    btn.callback_data

                    and btn.callback_data.startswith("fec_t:")

                    and "☑️" in btn.text

                ):

                    selected.add(

                        btn.callback_data.split(":")[2]

                    )

    if cat_key in selected:

        selected.remove(cat_key)

    else:

        selected.add(cat_key)

    await callback.message.edit_reply_markup(

        reply_markup=get_file_edit_categories_kb(

            uid,

            selected

        )

    )

    await callback.answer()

@dp.callback_query(F.data.startswith("fec_s:"))

async def fe_cat_save(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(":")[1]

    kb = callback.message.reply_markup

    new_cats = set()

    if kb:

        for row in kb.inline_keyboard:

            for btn in row:

                if (

                    btn.callback_data

                    and btn.callback_data.startswith("fec_t:")

                    and "☑️" in btn.text

                ):

                    new_cats.add(

                        btn.callback_data.split(":")[2]

                    )

    if not new_cats:

        return await callback.answer(

            "Нужна хотя бы одна категория!",

            show_alert=True

        )

    f_master = get_file_by_uid(

        uid

    )

    if not f_master:

        return await callback.answer(

            "Ошибка",

            show_alert=True

        )

    f_copy = copy.deepcopy(

        f_master

    )

    for cat_data in DATABASE["categories"].values():

        cat_data["files"] = [

            x

            for x in cat_data.get(

                "files",

                []

            )

            if x.get(

                "file_unique_id"

            ) != uid

        ]

    for cat in new_cats:

        DATABASE["categories"][cat]["files"].append(

            f_copy

        )

    await save_db(

        DATABASE

    )

    await callback.message.edit_reply_markup(

        reply_markup=get_file_edit_keyboard(

            uid

        )

    )

    await callback.answer(

        "Категории обновлены!"

    )

@dp.callback_query(F.data.startswith("fe_doc:"))

async def fe_doc_start(

    callback: types.CallbackQuery,

    state: FSMContext

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(":")[1]

    await state.set_state(

        EditFile.waiting_for_document

    )

    await state.update_data(

        edit_uid=uid

    )

    await callback.message.answer(

        "Отправь новый файл-документ:"

    )

    await callback.answer()

@dp.message(

    EditFile.waiting_for_document,

    F.document

)

async def fe_doc_receive(

    message: types.Message,

    state: FSMContext

):

    if not is_admin(

        message.from_user.id

    ):

        return

    data = await state.get_data()

    uid = data["edit_uid"]

    doc = message.document

    old_uid = uid

    update_file_everywhere(

        old_uid,

        "file_id",

        doc.file_id

    )

    update_file_everywhere(

        old_uid,

        "file_unique_id",

        doc.file_unique_id

    )

    for u_id, u in DATABASE["users"].items():

        if old_uid in u.get(

            "favorites",

            []

        ):

            u["favorites"].remove(

                old_uid

            )

            u["favorites"].append(

                doc.file_unique_id

            )

            await db_collection.update_one(

                {"_id": DB_DOC_ID},

                {

                    "$set": {

                        f"data.users.{u_id}.favorites":

                            u["favorites"]

                    }

                }

            )

    await save_db(

        DATABASE

    )

    await state.clear()

    await message.answer(

        "✅ Документ успешно заменен!"

    )

@dp.callback_query(F.data.startswith("fd:"))

async def fe_delete_file(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(":")[1]

    for cat_data in DATABASE["categories"].values():

        cat_data["files"] = [

            x

            for x in cat_data.get(

                "files",

                []

            )

            if x.get(

                "file_unique_id"

            ) != uid

        ]

    # Remove from favorites

    for user in DATABASE["users"].values():

        if uid in user.get(

            "favorites",

            []

        ):

            user["favorites"].remove(

                uid

            )

    await save_db(

        DATABASE

    )

    try:

        await callback.message.delete()

    except Exception:

        pass

    await callback.answer(

        "🗑 Файл полностью удален из базы",

        show_alert=True

    )

# ============================================================

# ADMIN FILE UPLOAD

# ============================================================

@dp.callback_query(F.data == "admin:upload")

async def adm_upload_start(

    callback: types.CallbackQuery,

    state: FSMContext

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    await state.clear()

    await callback.message.answer(

        "📥 Отправь документ (PDF и т.д.), "

        "чтобы добавить его в базу."

    )

    await callback.answer()

@dp.message(

    FileUpload.selecting_categories,

    F.document

)

async def admin_doc_received_state(

    message: types.Message,

    state: FSMContext

):

    if not is_admin(

        message.from_user.id

    ):

        return

    await process_admin_document(

        message,

        state

    )

@dp.message(

    F.document,

    F.from_user.id.in_(ADMIN_IDS),

    StateFilter(None)

)

async def admin_doc_received(

    message: types.Message,

    state: FSMContext

):

    await process_admin_document(

        message,

        state

    )

async def process_admin_document(

    message: types.Message,

    state: FSMContext

):

    doc = message.document

    if get_file_by_uid(

        doc.file_unique_id

    ):

        return await message.answer(

            "⚠️ Этот файл уже есть в базе данных!"

        )

    default_name = (

        message.caption

        if message.caption

        else doc.file_name

    )

    await state.update_data(

        file_id=doc.file_id,

        file_unique_id=doc.file_unique_id,

        default_name=default_name,

        selected=[]

    )

    await state.set_state(

        FileUpload.selecting_categories

    )

    await message.answer(

        f"📥 **Новый файл:** `{default_name}`\n"

        f"Отметь разделы:",

        reply_markup=build_admin_categories_kb(

            set()

        )

    )

@dp.callback_query(

    FileUpload.selecting_categories,

    F.data.startswith("a_toggle:")

)

async def admin_toggle_cat(

    callback: types.CallbackQuery,

    state: FSMContext

):

    cat_key = callback.data.split(":")[1]

    data = await state.get_data()

    selected = set(

        data.get(

            "selected",

            []

        )

    )

    if cat_key in selected:

        selected.remove(cat_key)

    else:

        selected.add(cat_key)

    await state.update_data(

        selected=list(selected)

    )

    await callback.message.edit_reply_markup(

        reply_markup=build_admin_categories_kb(

            selected

        )

    )

    await callback.answer()

@dp.callback_query(

    FileUpload.selecting_categories,

    F.data == "a_cancel"

)

@dp.callback_query(

    FileUpload.waiting_for_caption,

    F.data == "a_cancel"

)

async def admin_cancel_upload(

    callback: types.CallbackQuery,

    state: FSMContext

):

    await state.clear()

    await callback.message.edit_text(

        "❌ Отменено."

    )

@dp.callback_query(

    FileUpload.selecting_categories,

    F.data == "a_done"

)

async def admin_categories_done(

    callback: types.CallbackQuery,

    state: FSMContext

):

    data = await state.get_data()

    selected = set(

        data.get(

            "selected",

            []

        )

    )

    if not selected:

        return await callback.answer(

            "⚠️ Отметь хотя бы один раздел.",

            show_alert=True

        )

    await state.set_state(

        FileUpload.waiting_for_caption

    )

    default_name = data.get(

        "default_name",

        "File"

    )

    builder = [

        [

            InlineKeyboardButton(

                text=f"📝 Оставить: {default_name[:20]}...",

                callback_data="a_skip_caption"

            )

        ],

        [

            InlineKeyboardButton(

                text="❌ Отмена",

                callback_data="a_cancel"

            )

        ]

    ]

    await callback.message.edit_text(

        "✍️ Введи название файла "

        "или нажми оставить:",

        reply_markup=InlineKeyboardMarkup(

            inline_keyboard=builder

        )

    )

async def _admin_save_file(

    state: FSMContext,

    caption: str

):

    data = await state.get_data()

    selected = data.get(

        "selected",

        []

    )

    uid = data.get(

        "file_unique_id"

    )

    for cat_key in selected:

        DATABASE["categories"][cat_key]["files"].append(

            {

                "file_id": data["file_id"],

                "file_unique_id": uid,

                "caption": caption,

                "tags": [],

                "must_read": False,

                "difficulty": None

            }

        )

    await save_db(

        DATABASE

    )

    return selected

@dp.callback_query(

    FileUpload.waiting_for_caption,

    F.data == "a_skip_caption"

)

async def admin_skip_caption(

    callback: types.CallbackQuery,

    state: FSMContext

):

    data = await state.get_data()

    await _admin_save_file(

        state,

        data["default_name"]

    )

    await callback.message.edit_text(

        "✅ Файл сохранён!"

    )

    await state.clear()

@dp.message(

    FileUpload.waiting_for_caption,

    F.text

)

async def admin_save_custom_caption(

    message: types.Message,

    state: FSMContext

):

    await _admin_save_file(

        state,

        message.text.strip()

    )

    await message.answer(

        "✅ Файл сохранён!"

    )

    await state.clear()

# ============================================================

# USER FILE SUBMISSIONS

# ============================================================

@dp.callback_query(F.data == "submit:start")

async def submit_start(

    callback: types.CallbackQuery

):

    await track_user_activity(

        callback.from_user.id,

        callback.from_user.username or ""

    )

    await callback.message.answer(

        "📤 Просто пришли сюда файл "

        "(PDF и т.п.) - я передам его админу."

    )

    await callback.answer()

@dp.message(

    F.document,

    StateFilter(None)

)

async def user_doc_received(

    message: types.Message,

    state: FSMContext

):

    if is_admin(

        message.from_user.id

    ):

        return

    doc = message.document

    if get_file_by_uid(

        doc.file_unique_id

    ):

        return await message.answer(

            "⚠️ Этот файл уже есть в каталоге!"

        )

    default_name = (

        message.caption

        if message.caption

        else doc.file_name

    )

    await state.update_data(

        file_id=doc.file_id,

        file_unique_id=doc.file_unique_id,

        default_name=default_name,

        selected=[]

    )

    await state.set_state(

        UserSubmit.selecting_categories

    )

    await message.answer(

        f"📥 Файл получен: `{default_name}`\n"

        "Подскажи раздел (необязательно):",

        reply_markup=build_user_categories_kb(

            set()

        )

    )

@dp.callback_query(

    UserSubmit.selecting_categories,

    F.data.startswith("usub_toggle:")

)

async def usub_toggle(

    callback: types.CallbackQuery,

    state: FSMContext

):

    cat_key = callback.data.split(":")[1]

    data = await state.get_data()

    selected = set(

        data.get(

            "selected",

            []

        )

    )

    if cat_key in selected:

        selected.remove(cat_key)

    else:

        selected.add(cat_key)

    await state.update_data(

        selected=list(selected)

    )

    await callback.message.edit_reply_markup(

        reply_markup=build_user_categories_kb(

            selected

        )

    )

    await callback.answer()

@dp.callback_query(

    UserSubmit.selecting_categories,

    F.data == "usub_cancel"

)

async def usub_cancel(

    callback: types.CallbackQuery,

    state: FSMContext

):

    await state.clear()

    await callback.message.edit_text(

        "❌ Отправка отменена."

    )

@dp.callback_query(

    UserSubmit.selecting_categories,

    F.data == "usub_done"

)

async def usub_done(

    callback: types.CallbackQuery,

    state: FSMContext

):

    data = await state.get_data()

    sub_id = uuid.uuid4().hex[:8]

    sub_data = {

        "_id": sub_id,

        "user_id": callback.from_user.id,

        "username": (

            callback.from_user.username

            or callback.from_user.full_name

        ),

        "file_id": data["file_id"],

        "file_unique_id": data.get(

            "file_unique_id"

        ),

        "title": data["default_name"],

        "categories": data.get(

            "selected",

            []

        ),

        "status": "pending"

    }

    await save_submission(

        sub_id,

        sub_data

    )

    await state.clear()

    await callback.message.edit_text(

        "📤 Файл отправлен админу. Спасибо! 🙌"

    )

    cats_text = (

        ", ".join(

            DATABASE["categories"][c]["title"]

            for c in sub_data["categories"]

        )

        if sub_data["categories"]

        else "Не указано"

    )

    caption = (

        f"📥 **Новый файл**\n"

        f"👤 От: @{sub_data['username']}\n"

        f"📄 {sub_data['title']}\n"

        f"📁 {cats_text}"

    )

    for admin_id in ADMIN_IDS:

        try:

            await bot.send_document(

                admin_id,

                document=sub_data["file_id"],

                caption=caption,

                reply_markup=build_submission_action_kb(

                    sub_id

                )

            )

        except Exception as e:

            logger.error(

                "Failed to send submission: %s",

                e

            )

# ============================================================

# SUBMISSION APPROVE / REJECT

# ============================================================

@dp.callback_query(F.data.startswith("sub_approve:"))

async def sub_approve(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    sub_id = callback.data.split(":")[1]

    sub = await get_submission(

        sub_id

    )

    if (

        not sub

        or sub.get("status") != "pending"

    ):

        return await callback.answer(

            "Уже обработано.",

            show_alert=True

        )

    if not sub.get(

        "categories"

    ):

        return await callback.answer(

            "Сначала выбери разделы.",

            show_alert=True

        )

    for cat_key in sub["categories"]:

        DATABASE["categories"][cat_key]["files"].append(

            {

                "file_id": sub["file_id"],

                "file_unique_id":

                    sub["file_unique_id"],

                "caption": sub["title"],

                "tags": [],

                "must_read": False,

                "difficulty": None

            }

        )

    await save_db(

        DATABASE

    )

    sub["status"] = "approved"

    await save_submission(

        sub_id,

        sub

    )

    await award_points(

        sub["user_id"],

        15

    )

    try:

        await callback.message.edit_caption(

            caption=(

                callback.message.caption

                or ""

            )

            + "\n\n✅ ОДОБРЕНО",

            reply_markup=None

        )

    except Exception:

        pass

    try:

        await bot.send_message(

            sub["user_id"],

            f"✅ Твой файл "

            f"«{sub['title']}» добавлен!\n"

            f"Спасибо 🙌\n"

            f"+15 очков"

        )

    except Exception:

        pass

    await callback.answer(

        "Одобрено!"

    )

@dp.callback_query(F.data.startswith("sub_reject:"))

async def sub_reject(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    sub_id = callback.data.split(":")[1]

    sub = await get_submission(

        sub_id

    )

    if (

        not sub

        or sub.get("status") != "pending"

    ):

        return

    sub["status"] = "rejected"

    await save_submission(

        sub_id,

        sub

    )

    try:

        await callback.message.edit_caption(

            caption=(

                callback.message.caption

                or ""

            )

            + "\n\n❌ ОТКЛОНЕНО",

            reply_markup=None

        )

    except Exception:

        pass

    try:

        await bot.send_message(

            sub["user_id"],

            "😔 Твой файл не был принят."

        )

    except Exception:

        pass

    await callback.answer(

        "Отклонено"

    )

@dp.callback_query(F.data.startswith("sub_editcat:"))

async def sub_editcat(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    sub_id = callback.data.split(":")[1]

    sub = await get_submission(

        sub_id

    )

    if sub.get("status") != "pending":

        return

    await callback.message.edit_reply_markup(

        reply_markup=build_submission_categories_kb(

            sub_id,

            sub.get(

                "categories",

                []

            )

        )

    )

    await callback.answer()

def build_submission_categories_kb(

    sub_id: str,

    selected_cats: list

):

    selected = set(

        selected_cats

    )

    builder = []

    for cat_key, cat_data in DATABASE["categories"].items():

        mark = (

            "☑️"

            if cat_key in selected

            else "▫️"

        )

        builder.append([

            InlineKeyboardButton(

                text=f"{mark} {cat_data['title']}",

                callback_data=f"subcat_toggle:{sub_id}:{cat_key}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text="✅ Готово",

            callback_data=f"subcat_done:{sub_id}"

        )

    ])

    return InlineKeyboardMarkup(

        inline_keyboard=builder

    )

@dp.callback_query(F.data.startswith("subcat_toggle:"))

async def subcat_toggle(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    _, sub_id, cat_key = callback.data.split(":")

    sub = await get_submission(

        sub_id

    )

    if (

        not sub

        or sub.get("status") != "pending"

    ):

        return

    selected = set(

        sub.get(

            "categories",

            []

        )

    )

    if cat_key in selected:

        selected.remove(cat_key)

    else:

        selected.add(cat_key)

    sub["categories"] = list(

        selected

    )

    await save_submission(

        sub_id,

        sub

    )

    await callback.message.edit_reply_markup(

        reply_markup=build_submission_categories_kb(

            sub_id,

            sub["categories"]

        )

    )

    await callback.answer()

@dp.callback_query(F.data.startswith("subcat_done:"))

async def subcat_done(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    sub_id = callback.data.split(":")[1]

    await callback.message.edit_reply_markup(

        reply_markup=build_submission_action_kb(

            sub_id

        )

    )

    await callback.answer()

# ============================================================

# NOOP

# ============================================================

@dp.callback_query(F.data == "noop")

async def noop(

    callback: types.CallbackQuery

):

    await callback.answer()

# ============================================================

# TELEGRAM COMMANDS MENU

# ============================================================

async def set_main_menu(

    b: Bot

):

    commands = [

        BotCommand(

            command="start",

            description="Главное меню 🚀"

        ),

        BotCommand(

            command="menu",

            description="Меню 📂"

        ),

        BotCommand(

            command="task",

            description="Задача дня 🧩"

        ),

        BotCommand(

            command="challenge",

            description="Случайный материал 🎲"

        ),

        BotCommand(

            command="favorites",

            description="Избранное ❤️"

        ),

        BotCommand(

            command="rating",

            description="Рейтинг 🏆"

        ),

    ]

    await b.set_my_commands(

        commands

    )

# ============================================================

# WEB SERVER

# ============================================================

async def run_web_server():

    app = web.Application()

    async def health(request):

        return web.Response(

            text="Bot is running!"

        )

    app.router.add_get(

        "/",

        health

    )

    runner = web.AppRunner(

        app

    )

    await runner.setup()

    port = int(

        os.environ.get(

            "PORT",

            10000

        )

    )

    site = web.TCPSite(

        runner,

        "0.0.0.0",

        port

    )

    await site.start()

    logger.info(

        "🌐 Web server started on port %s",

        port

    )

# ============================================================

# MAIN

# ============================================================

async def main():

    global DATABASE

    await run_web_server()

    await mongo_client.admin.command(

        "ping"

    )

    logger.info(

        "✅ MongoDB connection established"

    )

    DATABASE = await load_db()

    await set_main_menu(

        bot

    )

    logger.info(

        "🤖 Bot started! DEBUG=%s",

        os.environ.get("DEBUG", "0")

    )

    await dp.start_polling(

        bot

    )

if __name__ == "__main__":

    asyncio.run(main())