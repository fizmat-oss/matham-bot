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

from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

from aiogram.fsm.context import FSMContext

from aiogram.fsm.state import State, StatesGroup

from aiohttp import web

from motor.motor_asyncio import AsyncIOMotorClient

# =========================================================

# CONFIG

# =========================================================

logging.basicConfig(

    level=logging.INFO,

    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",

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

# =========================================================

# BOT + DATABASE

# =========================================================

mongo_client = AsyncIOMotorClient(MONGO_URI)

mongo_db = mongo_client[MONGO_DB_NAME]

db_collection = mongo_db["catalog"]

submissions_collection = mongo_db["submissions"]

task_solutions_collection = mongo_db["task_solutions"]

DB_DOC_ID = "catalog_main"

bot = Bot(token=TOKEN)

dp = Dispatcher()

DATABASE = {}

# =========================================================

# DEFAULT DATABASE

# =========================================================

DEFAULT_STATE = {

    "categories": {

        "geometry": {

            "title": "📐 Геометрия",

            "files": []

        },

        "number_theory": {

            "title": "🔢 Теория чисел",

            "files": []

        },

        "algebra": {

            "title": "🧮 Алгебра",

            "files": []

        },

        "combinatorics": {

            "title": "🧩 Комбинаторика",

            "files": []

        },

        "higher_math": {

            "title": "🎓 Матанализ и высшая математика",

            "files": []

        },

        "titu": {

            "title": "📘 Titu Andreescu",

            "files": []

        }

    },

    "links": {

        "useful_links": {

            "title": "🔗 Полезные ссылки",

            "items": []

        },

        "useful_videos": {

            "title": "🎥 Полезные видео",

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

# =========================================================

# HELPERS

# =========================================================

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

        }

        DATABASE["users"][uid_str] = user_data

        await db_collection.update_one(

            {"_id": DB_DOC_ID},

            {

                "$set": {

                    f"data.users.{uid_str}": user_data

                }

            },

            upsert=True,

        )

        return

    user = DATABASE["users"][uid_str]

    updates = {}

    if username and user.get("username") != username:

        user["username"] = username

        updates[

            f"data.users.{uid_str}.username"

        ] = username

    if user.get("last_active") != today:

        if user.get("last_active") == yesterday:

            user["streak"] = user.get("streak", 0) + 1

        else:

            user["streak"] = 1

        user["last_active"] = today

        updates[

            f"data.users.{uid_str}.streak"

        ] = user["streak"]

        updates[

            f"data.users.{uid_str}.last_active"

        ] = today

    if "favorites" not in user:

        user["favorites"] = []

        updates[

            f"data.users.{uid_str}.favorites"

        ] = []

    if "opened_tasks" not in user:

        user["opened_tasks"] = []

        updates[

            f"data.users.{uid_str}.opened_tasks"

        ] = []

    if updates:

        await db_collection.update_one(

            {"_id": DB_DOC_ID},

            {"$set": updates},

            upsert=True,

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

            "$inc": {

                f"data.users.{uid_str}.score": points

            }

        },

        upsert=True,

    )

# =========================================================

# DATABASE FUNCTIONS

# =========================================================

async def load_db():

    doc = await db_collection.find_one(

        {"_id": DB_DOC_ID}

    )

    if doc is None:

        logger.info(

            "В MongoDB нет каталога - создаю DEFAULT_STATE"

        )

        data = copy.deepcopy(DEFAULT_STATE)

        await db_collection.update_one(

            {"_id": DB_DOC_ID},

            {"$set": {"data": data}},

            upsert=True,

        )

        return data

    data = doc.get(

        "data",

        copy.deepcopy(DEFAULT_STATE)

    )

    # Missing top-level fields

    if "categories" not in data:

        data["categories"] = copy.deepcopy(

            DEFAULT_STATE["categories"]

        )

    if "links" not in data:

        data["links"] = copy.deepcopy(

            DEFAULT_STATE["links"]

        )

    if "users" not in data:

        data["users"] = {}

    if "daily_tasks" not in data:

        data["daily_tasks"] = {}

    if "settings" not in data:

        data["settings"] = {}

    if "must_read" not in data:

        data["must_read"] = {

            "title": "⭐ Must-read",

            "files": []

        }

    # Missing categories

    for key, default_cat in DEFAULT_STATE["categories"].items():

        if key not in data["categories"]:

            data["categories"][key] = copy.deepcopy(

                default_cat

            )

    # Missing links

    for key, default_link in DEFAULT_STATE["links"].items():

        if key not in data["links"]:

            data["links"][key] = copy.deepcopy(

                default_link

            )

    # Users migration

    for uid, user in data["users"].items():

        if "favorites" not in user:

            user["favorites"] = []

        if "opened_tasks" not in user:

            user["opened_tasks"] = []

        if "score" not in user:

            user["score"] = 0

        if "streak" not in user:

            user["streak"] = 0

    # Files migration

    for cat_data in data["categories"].values():

        for f in cat_data.get("files", []):

            if "file_unique_id" not in f:

                f["file_unique_id"] = (

                    str(f.get("file_id", uuid.uuid4().hex))

                    [-15:]

                    + uuid.uuid4().hex[:5]

                )

            if "tags" not in f:

                f["tags"] = []

            if "difficulty" not in f:

                f["difficulty"] = None

            if "must_read" not in f:

                f["must_read"] = False

    # Old must-read migration

    if "files" in data.get("must_read", {}):

        for mrf in data["must_read"]["files"]:

            uid = mrf.get("file_unique_id")

            for cat_data in data["categories"].values():

                for f in cat_data.get("files", []):

                    if f.get("file_unique_id") == uid:

                        f["must_read"] = True

        data["must_read"]["files"] = []

    return data

async def save_db(db_data):

    await db_collection.update_one(

        {"_id": DB_DOC_ID},

        {"$set": {"data": db_data}},

        upsert=True,

    )

async def save_submission(sub_id: str, data: dict):

    await submissions_collection.update_one(

        {"_id": sub_id},

        {"$set": data},

        upsert=True,

    )

async def get_submission(sub_id: str) -> dict:

    doc = await submissions_collection.find_one(

        {"_id": sub_id}

    )

    return doc if doc else {}

async def save_task_solution(solution_id: str, data: dict):

    await task_solutions_collection.update_one(

        {"_id": solution_id},

        {"$set": data},

        upsert=True,

    )

async def get_task_solution(solution_id: str) -> dict:

    doc = await task_solutions_collection.find_one(

        {"_id": solution_id}

    )

    return doc if doc else {}

# =========================================================

# FSM STATES

# =========================================================

class FileUpload(StatesGroup):

    selecting_categories = State()

    waiting_for_caption = State()

class UserSubmit(StatesGroup):

    selecting_categories = State()

class AddLink(StatesGroup):

    waiting_for_text = State()

class EditFile(StatesGroup):

    waiting_for_document = State()

    selecting_action = State()

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

# =========================================================

# KEYBOARDS

# =========================================================

def get_main_menu_keyboard(user_id: int):

    builder = [

        [

            InlineKeyboardButton(

                text="📚 Каталог",

                callback_data="menu:catalog"

            ),

            InlineKeyboardButton(

                text="🎯 Задача дня",

                callback_data="task:show"

            )

        ],

        [

            InlineKeyboardButton(

                text="⭐ Must-read",

                callback_data="mustread:main"

            ),

            InlineKeyboardButton(

                text="❤️ Избранное",

                callback_data="favorites:main"

            )

        ],

        [

            InlineKeyboardButton(

                text="🔎 Поиск",

                switch_inline_query_current_chat=""

            ),

            InlineKeyboardButton(

                text="🏆 Рейтинг",

                callback_data="rating:main"

            )

        ],

        [

            InlineKeyboardButton(

                text="🎲 Случайный материал",

                callback_data="challenge:main"

            ),

            InlineKeyboardButton(

                text="🔗 Полезные ссылки",

                callback_data="links:main"

            )

        ],

        [

            InlineKeyboardButton(

                text="📤 Предложить файл",

                callback_data="submit:start"

            )

        ]

    ]

    if is_admin(user_id):

        builder.append([

            InlineKeyboardButton(

                text="👑 Админ-панель",

                callback_data="admin:main"

            )

        ])

    return InlineKeyboardMarkup(

        inline_keyboard=builder

    )

def get_catalog_keyboard():

    builder = []

    for cat_key, cat_data in DATABASE["categories"].items():

        builder.append([

            InlineKeyboardButton(

                text=cat_data["title"],

                callback_data=f"cat:{cat_key}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text="⬅️ В главное меню",

            callback_data="menu:main"

        )

    ])

    return InlineKeyboardMarkup(

        inline_keyboard=builder

    )

def build_admin_categories_kb(selected: set):

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

        mark = (

            "☑️"

            if cat_key in selected

            else "▫️"

        )

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

def build_submission_categories_kb(

    sub_id: str,

    selected_cats: list

):

    selected = set(selected_cats)

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

def get_file_edit_categories_kb(

    uid: str,

    selected: set

):

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

# =========================================================

# DAILY TASK KEYBOARDS

# =========================================================

def get_task_keyboard(

    date_str: str,

    admin_view: bool = False

):

    builder = [

        [

            InlineKeyboardButton(

                text="📝 Отправить решение",

                callback_data=f"tsubmit:{date_str}"

            )

        ],

        [

            InlineKeyboardButton(

                text="💡 Решение автора",

                callback_data=f"th:{date_str}:sol"

            )

        ],

        [

            InlineKeyboardButton(

                text="⭐ 1",

                callback_data=f"tv:{date_str}:1"

            ),

            InlineKeyboardButton(

                text="⭐ 2",

                callback_data=f"tv:{date_str}:2"

            ),

            InlineKeyboardButton(

                text="⭐ 3",

                callback_data=f"tv:{date_str}:3"

            ),

            InlineKeyboardButton(

                text="⭐ 4",

                callback_data=f"tv:{date_str}:4"

            ),

            InlineKeyboardButton(

                text="⭐ 5",

                callback_data=f"tv:{date_str}:5"

            )

        ]

    ]

    if admin_view:

        builder.append([

            InlineKeyboardButton(

                text="📊 Статистика задачи",

                callback_data=f"ts:{date_str}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text="⬅️ Меню",

            callback_data="menu:main"

        )

    ])

    return InlineKeyboardMarkup(

        inline_keyboard=builder

    )

def get_solution_rating_keyboard(solution_id: str):

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="⭐ 1",

                    callback_data=f"solrate:{solution_id}:1"

                ),

                InlineKeyboardButton(

                    text="⭐ 2",

                    callback_data=f"solrate:{solution_id}:2"

                ),

                InlineKeyboardButton(

                    text="⭐ 3",

                    callback_data=f"solrate:{solution_id}:3"

                ),

                InlineKeyboardButton(

                    text="⭐ 4",

                    callback_data=f"solrate:{solution_id}:4"

                ),

                InlineKeyboardButton(

                    text="⭐ 5",

                    callback_data=f"solrate:{solution_id}:5"

                )

            ]

        ]

    )

# =========================================================

# INLINE SEARCH

# =========================================================

@dp.inline_query()

async def inline_search(inline_query: InlineQuery):

    query = inline_query.query.strip().lower()

    results = []

    if not query:

        results.append(

            InlineQueryResultArticle(

                id="info",

                title="🔎 Поиск по базе matham",

                description=(

                    "Введите название файла, тему или хештег"

                ),

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

                f"{cat_data['title']} "

                f"{f.get('caption', '')} "

                + " ".join(f.get("tags", []))

                + f" {f.get('difficulty', '') or ''}"

            ).lower()

            if all(

                word in haystack

                for word in words

            ):

                cap = (

                    f"📄 **{f.get('caption', 'Без названия')}**\n"

                    f"📌 Раздел: {cat_data['title']}"

                )

                if f.get("tags"):

                    cap += (

                        f"\n🏷 Теги: "

                        f"{' '.join(f['tags'])}"

                    )

                if f.get("difficulty"):

                    cap += (

                        f"\n📚 Уровень: "

                        f"{f['difficulty']}"

                    )

                results.append(

                    InlineQueryResultCachedDocument(

                        id=f["file_unique_id"],

                        title=f.get(

                            "caption",

                            "Файл"

                        ),

                        document_file_id=f["file_id"],

                        caption=cap,

                        parse_mode="Markdown"

                    )

                )

    await inline_query.answer(

        results[:50],

        cache_time=10

    )

# =========================================================

# COMMANDS

# =========================================================

@dp.message(Command("start"))

async def cmd_start(

    message: types.Message,

    state: FSMContext

):

    await state.clear()

    await track_user_activity(

        message.from_user.id,

        message.from_user.username or ""

    )

    await message.answer(

        "Здарова! ✌️\n"

        "Я бот библиотеки matham.\n\n"

        "🔎 **Поиск:** Просто напиши слово.\n"

        "🧩 **Задача дня:** новая олимпиадная задача.\n"

        "📝 **Решение:** можешь отправить своё решение.\n"

        "⭐ **Must-read:** самые важные материалы.\n",

        reply_markup=get_main_menu_keyboard(

            message.from_user.id

        )

    )

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

        "📂 **Главное меню**",

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

        "📂 **Главное меню**",

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

        "📚 **Каталог файлов**\n"

        "Выбери раздел:",

        reply_markup=get_catalog_keyboard()

    )

    await callback.answer()

# =========================================================

# DAILY TASK

# =========================================================

async def send_daily_task(

    target,

    date_str: str = None

):

    if not date_str:

        date_str = get_yerevan_date()

    task = DATABASE["daily_tasks"].get(

        date_str

    )

    is_msg = isinstance(

        target,

        types.Message

    )

    user_id = target.from_user.id

    if not task:

        text = (

            f"🧩 **Задача дня ({date_str})**\n\n"

            "На эту дату задача еще не добавлена."

        )

        kb = InlineKeyboardMarkup(

            inline_keyboard=[

                [

                    InlineKeyboardButton(

                        text="⬅️ Меню",

                        callback_data="menu:main"

                    )

                ]

            ]

        )

        if is_msg:

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

    if date_str == get_yerevan_date():

        uid_str = str(user_id)

        user = DATABASE["users"].setdefault(

            uid_str,

            {

                "username": "",

                "streak": 1,

                "last_active": date_str,

                "score": 0,

                "favorites": [],

                "opened_tasks": []

            }

        )

        opened_tasks = user.setdefault(

            "opened_tasks",

            []

        )

        if date_str not in opened_tasks:

            opened_tasks.append(date_str)

            await db_collection.update_one(

                {"_id": DB_DOC_ID},

                {

                    "$set": {

                        f"data.users.{uid_str}.opened_tasks":

                            opened_tasks

                    }

                },

                upsert=True,

            )

            await award_points(

                user_id,

                5

            )

    cap = (

        f"🧩 **Задача дня** ({date_str})"

    )

    votes = task.get(

        "votes",

        {}

    )

    if votes:

        avg = (

            sum(votes.values())

            / len(votes)

        )

        cap += (

            f"\n\n⭐ Оценка: "

            f"{avg:.1f}/5 "

            f"(Голосов: {len(votes)})"

        )

    kb = get_task_keyboard(

        date_str,

        is_admin(user_id)

    )

    if is_msg:

        await target.answer_photo(

            photo=task["photo_file_id"],

            caption=cap,

            reply_markup=kb

        )

    else:

        try:

            await target.message.delete()

        except Exception:

            pass

        await target.message.answer_photo(

            photo=task["photo_file_id"],

            caption=cap,

            reply_markup=kb

        )

@dp.message(Command("task"))

async def cmd_task(

    message: types.Message

):

    await track_user_activity(

        message.from_user.id,

        message.from_user.username or ""

    )

    await send_daily_task(message)

@dp.callback_query(F.data == "task:show")

async def callback_task(

    callback: types.CallbackQuery

):

    await track_user_activity(

        callback.from_user.id,

        callback.from_user.username or ""

    )

    await send_daily_task(callback)

    await callback.answer()

# =========================================================

# TASK VOTING

# =========================================================

@dp.callback_query(F.data.startswith("tv:"))

async def task_vote_handler(

    callback: types.CallbackQuery

):

    try:

        _, date_str, score_str = callback.data.split(":")

        score = int(score_str)

    except Exception:

        return await callback.answer(

            "Ошибка.",

            show_alert=True

        )

    if score < 1 or score > 5:

        return await callback.answer(

            "Неверная оценка.",

            show_alert=True

        )

    task = DATABASE["daily_tasks"].get(

        date_str

    )

    if not task:

        return await callback.answer(

            "Задача не найдена.",

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

    await save_db(DATABASE)

    avg = (

        sum(votes.values())

        / len(votes)

    )

    cap = (

        f"🧩 **Задача дня** ({date_str})\n\n"

        f"⭐ Оценка: {avg:.1f}/5 "

        f"(Голосов: {len(votes)})"

    )

    try:

        await callback.message.edit_caption(

            caption=cap,

            reply_markup=get_task_keyboard(

                date_str,

                is_admin(

                    callback.from_user.id

                )

            )

        )

    except Exception:

        pass

    await callback.answer(

        f"Твоя оценка {score}⭐ сохранена!",

        show_alert=True

    )

# =========================================================

# TASK AUTHOR SOLUTION

# =========================================================

@dp.callback_query(F.data.startswith("th:"))

async def task_hint_handler(

    callback: types.CallbackQuery

):

    try:

        _, date_str, action = callback.data.split(":")

    except Exception:

        return await callback.answer(

            "Ошибка.",

            show_alert=True

        )

    task = DATABASE["daily_tasks"].get(

        date_str

    )

    if not task:

        return await callback.answer(

            "Ошибка.",

            show_alert=True

        )

    val = task.get(

        "solution",

        ""

    )

    if not val:

        val = (

            "Админ пока не добавил решение 😔"

        )

    # Telegram callback alert ограничен по длине

    if len(val) > 190:

        val = val[:187] + "..."

    await callback.answer(

        val,

        show_alert=True

    )

# =========================================================

# USER TASK SOLUTION SUBMISSION

# =========================================================

@dp.callback_query(F.data.startswith("tsubmit:"))

async def task_solution_start(

    callback: types.CallbackQuery,

    state: FSMContext

):

    date_str = callback.data.split(":", 1)[1]

    task = DATABASE["daily_tasks"].get(

        date_str

    )

    if not task:

        return await callback.answer(

            "Задача не найдена.",

            show_alert=True

        )

    await state.set_state(

        UserTaskSolution.waiting_for_solution

    )

    await state.update_data(

        task_date=date_str

    )

    await callback.message.answer(

        "📝 **Отправка решения**\n\n"

        "Пришли своё решение текстом "

        "или фотографией.\n\n"

        "Для отмены напиши `/cancel`."

    )

    await callback.answer()

@dp.message(

    UserTaskSolution.waiting_for_solution,

    Command("cancel")

)

async def cancel_task_solution(

    message: types.Message,

    state: FSMContext

):

    await state.clear()

    await message.answer(

        "❌ Отправка решения отменена."

    )

@dp.message(

    UserTaskSolution.waiting_for_solution,

    F.text

)

async def task_solution_text(

    message: types.Message,

    state: FSMContext

):

    text = message.text.strip()

    if not text:

        return await message.answer(

            "❌ Решение не может быть пустым."

        )

    data = await state.get_data()

    date_str = data.get(

        "task_date"

    )

    if not date_str:

        await state.clear()

        return await message.answer(

            "❌ Сессия решения устарела."

        )

    solution_id = uuid.uuid4().hex[:12]

    username = (

        f"@{message.from_user.username}"

        if message.from_user.username

        else message.from_user.full_name

    )

    solution_data = {

        "_id": solution_id,

        "solution_id": solution_id,

        "task_date": date_str,

        "user_id": message.from_user.id,

        "username": username,

        "type": "text",

        "text": text,

        "file_id": None,

        "status": "pending",

        "rating": None,

        "created_at": datetime.now(

            timezone.utc

        ).isoformat(),

    }

    await save_task_solution(

        solution_id,

        solution_data

    )

    await state.clear()

    await award_points(

        message.from_user.id,

        5

    )

    await message.answer(

        "✅ Решение отправлено админу!\n"

        "Ты получил +5 очков за отправку."

    )

    await notify_admins_about_solution(

        solution_data

    )

@dp.message(

    UserTaskSolution.waiting_for_solution,

    F.photo

)

async def task_solution_photo(

    message: types.Message,

    state: FSMContext

):

    data = await state.get_data()

    date_str = data.get(

        "task_date"

    )

    if not date_str:

        await state.clear()

        return await message.answer(

            "❌ Сессия решения устарела."

        )

    solution_id = uuid.uuid4().hex[:12]

    username = (

        f"@{message.from_user.username}"

        if message.from_user.username

        else message.from_user.full_name

    )

    caption = (

        message.caption or ""

    ).strip()

    solution_data = {

        "_id": solution_id,

        "solution_id": solution_id,

        "task_date": date_str,

        "user_id": message.from_user.id,

        "username": username,

        "type": "photo",

        "text": caption,

        "file_id": message.photo[-1].file_id,

        "status": "pending",

        "rating": None,

        "created_at": datetime.now(

            timezone.utc

        ).isoformat(),

    }

    await save_task_solution(

        solution_id,

        solution_data

    )

    await state.clear()

    await award_points(

        message.from_user.id,

        5

    )

    await message.answer(

        "✅ Фото решения отправлено админу!\n"

        "Ты получил +5 очков за отправку."

    )

    await notify_admins_about_solution(

        solution_data

    )

async def notify_admins_about_solution(

    solution_data: dict

):

    solution_id = solution_data["solution_id"]

    date_str = solution_data["task_date"]

    username = solution_data["username"]

    header = (

        "📝 **Новое решение задачи дня**\n\n"

        f"📅 Дата: `{date_str}`\n"

        f"👤 Автор: {username}\n"

        f"🆔 ID: `{solution_id}`"

    )

    keyboard = get_solution_rating_keyboard(

        solution_id

    )

    for admin_id in ADMIN_IDS:

        try:

            if solution_data["type"] == "photo":

                caption = header

                if solution_data.get("text"):

                    caption += (

                        "\n\n💬 Комментарий:\n"

                        + solution_data["text"]

                    )

                await bot.send_photo(

                    admin_id,

                    photo=solution_data["file_id"],

                    caption=caption,

                    reply_markup=keyboard

                )

            else:

                text = (

                    header

                    + "\n\n"

                    + "💬 Решение:\n"

                    + solution_data["text"]

                )

                await bot.send_message(

                    admin_id,

                    text,

                    reply_markup=keyboard

                )

        except Exception as e:

            logger.exception(

                "Не удалось отправить решение админу %s: %s",

                admin_id,

                e

            )

# =========================================================

# ADMIN RATING OF USER SOLUTION

# =========================================================

@dp.callback_query(F.data.startswith("solrate:"))

async def admin_rate_solution(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return await callback.answer(

            "⛔ Нет доступа.",

            show_alert=True

        )

    try:

        _, solution_id, rating_str = (

            callback.data.split(":")

        )

        rating = int(rating_str)

    except Exception:

        return await callback.answer(

            "Ошибка.",

            show_alert=True

        )

    if rating < 1 or rating > 5:

        return await callback.answer(

            "Оценка должна быть от 1 до 5.",

            show_alert=True

        )

    solution = await get_task_solution(

        solution_id

    )

    if not solution:

        return await callback.answer(

            "Решение не найдено.",

            show_alert=True

        )

    if solution.get("rating") is not None:

        return await callback.answer(

            "Это решение уже оценено.",

            show_alert=True

        )

    solution["rating"] = rating

    solution["status"] = "rated"

    solution["rated_by"] = callback.from_user.id

    solution["rated_at"] = datetime.now(

        timezone.utc

    ).isoformat()

    await save_task_solution(

        solution_id,

        solution

    )

    # Очки за оценку решения

    points_by_rating = {

        1: 2,

        2: 4,

        3: 6,

        4: 8,

        5: 10,

    }

    points = points_by_rating[rating]

    await award_points(

        solution["user_id"],

        points

    )

    # Убираем кнопки

    try:

        if callback.message.photo:

            old_caption = (

                callback.message.caption

                or ""

            )

            await callback.message.edit_caption(

                caption=(

                    old_caption

                    + f"\n\n✅ Оценено админом: "

                    f"{rating}/5 ⭐"

                ),

                reply_markup=None

            )

        else:

            old_text = (

                callback.message.text

                or ""

            )

            await callback.message.edit_text(

                old_text

                + f"\n\n✅ Оценено админом: "

                f"{rating}/5 ⭐",

                reply_markup=None

            )

    except Exception:

        pass

    try:

        await bot.send_message(

            solution["user_id"],

            (

                "🎉 **Твоё решение проверено!**\n\n"

                f"📅 Задача: {solution['task_date']}\n"

                f"⭐ Оценка: {rating}/5\n"

                f"🏆 Получено очков: +{points}"

            )

        )

    except Exception:

        pass

    await callback.answer(

        f"Оценка {rating}/5 сохранена.",

        show_alert=True

    )

# =========================================================

# TASK STATISTICS

# =========================================================

@dp.callback_query(F.data.startswith("ts:"))

async def task_stats_admin(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return await callback.answer(

            "⛔",

            show_alert=True

        )

    _, date_str = callback.data.split(":")

    task = DATABASE["daily_tasks"].get(

        date_str

    )

    if not task:

        return await callback.answer(

            "Нет задачи.",

            show_alert=True

        )

    votes = task.get(

        "votes",

        {}

    )

    avg = (

        sum(votes.values()) / len(votes)

        if votes

        else 0

    )

    counts = {

        1: 0,

        2: 0,

        3: 0,

        4: 0,

        5: 0

    }

    for value in votes.values():

        if value in counts:

            counts[value] += 1

    solutions_count = await (

        task_solutions_collection.count_documents(

            {

                "task_date": date_str

            }

        )

    )

    rated_count = await (

        task_solutions_collection.count_documents(

            {

                "task_date": date_str,

                "rating": {

                    "$ne": None

                }

            }

        )

    )

    text = (

        f"📊 **Статистика за {date_str}**\n\n"

        f"👥 Голосов: {len(votes)}\n"

        f"⭐ Средняя: {avg:.2f}/5\n\n"

        f"5⭐: {counts[5]}\n"

        f"4⭐: {counts[4]}\n"

        f"3⭐: {counts[3]}\n"

        f"2⭐: {counts[2]}\n"

        f"1⭐: {counts[1]}\n\n"

        f"📝 Решений пользователей: {solutions_count}\n"

        f"✅ Проверено: {rated_count}"

    )

    await callback.answer(

        text,

        show_alert=True

    )

# =========================================================

# MUST READ

# =========================================================

@dp.callback_query(F.data == "mustread:main")

async def mustread_main(

    callback: types.CallbackQuery

):

    files = []

    for cat_data in DATABASE["categories"].values():

        for f in cat_data.get("files", []):

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

                            text="⬅️ Меню",

                            callback_data="menu:main"

                        )

                    ]

                ]

            )

        )

    builder = []

    for f in files[:90]:

        caption = f.get(

            "caption",

            "Без названия"

        )

        builder.append([

            InlineKeyboardButton(

                text=f"📄 {caption[:35]}",

                callback_data=f"fv:{f['file_unique_id']}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text="⬅️ Меню",

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

# =========================================================

# FAVORITES

# =========================================================

@dp.message(Command("favorites"))

async def cmd_fav(

    message: types.Message

):

    await track_user_activity(

        message.from_user.id,

        message.from_user.username or ""

    )

    await show_favorites(message)

@dp.callback_query(F.data == "favorites:main")

async def cb_fav(

    callback: types.CallbackQuery

):

    await track_user_activity(

        callback.from_user.id,

        callback.from_user.username or ""

    )

    await show_favorites(callback)

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

                        text="⬅️ Меню",

                        callback_data="menu:main"

                    )

                ]

            ]

        )

        if isinstance(

            target,

            types.Message

        ):

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

                    text=f"📄 {f.get('caption', 'Файл')[:35]}",

                    callback_data=f"fv:{uid}"

                )

            ])

    builder.append([

        InlineKeyboardButton(

            text="⬅️ Меню",

            callback_data="menu:main"

        )

    ])

    text = (

        f"❤️ **Твоё избранное** "

        f"({valid_count} шт.):"

    )

    markup = InlineKeyboardMarkup(

        inline_keyboard=builder

    )

    if isinstance(

        target,

        types.Message

    ):

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

    uid = callback.data.split(

        ":",

        1

    )[1]

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

# =========================================================

# RATING

# =========================================================

@dp.message(Command("rating"))

async def cmd_rating(

    message: types.Message

):

    await track_user_activity(

        message.from_user.id,

        message.from_user.username or ""

    )

    await show_rating(message)

@dp.callback_query(F.data == "rating:main")

async def cb_rating(

    callback: types.CallbackQuery

):

    await track_user_activity(

        callback.from_user.id,

        callback.from_user.username or ""

    )

    await show_rating(callback)

async def show_rating(target):

    users = [

        (uid, u)

        for uid, u

        in DATABASE["users"].items()

        if u.get("score", 0) > 0

    ]

    users.sort(

        key=lambda x: x[1].get(

            "score",

            0

        ),

        reverse=True

    )

    text = (

        "🏆 **Рейтинг активности**\n\n"

    )

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

            f"{medal} {name} — "

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

        f"\n🔥 **Твой streak:** "

        f"{my_streak} дней подряд"

    )

    text += (

        f"\n🎯 **Твои очки:** "

        f"{my_score}"

    )

    kb = InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="⬅️ Меню",

                    callback_data="menu:main"

                )

            ]

        ]

    )

    if isinstance(

        target,

        types.Message

    ):

        await target.answer(

            text,

            reply_markup=kb

        )

    else:

        await target.message.edit_text(

            text,

            reply_markup=kb

        )

# =========================================================

# RANDOM / CHALLENGE

# =========================================================

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

        "Выбери уровень сложности для Challenge:",

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

        "Выбери уровень сложности для Challenge:",

        reply_markup=kb

    )

    await callback.answer()

@dp.callback_query(F.data.startswith("rand:"))

async def cb_do_random(

    callback: types.CallbackQuery

):

    diff = callback.data.split(

        ":",

        1

    )[1]

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

        for f in cat_data.get("files", []):

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

            "К сожалению, файлов "

            "такой сложности пока нет 😔"

        )

        if isinstance(

            target,

            types.Message

        ):

            await target.answer(msg)

        else:

            await target.message.edit_text(msg)

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

    if selected_file.get("difficulty"):

        text += (

            f"\nСложность: "

            f"{selected_file['difficulty'].upper()}"

        )

    if isinstance(

        target,

        types.Message

    ):

        await target.answer(text)

        await target.answer_document(

            document=selected_file["file_id"],

            caption=(

                f"📄 "

                f"{selected_file.get('caption', 'Файл')}"

            ),

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

        await target.message.answer_document(

            document=selected_file["file_id"],

            caption=(

                f"📄 "

                f"{selected_file.get('caption', 'Файл')}"

            ),

            reply_markup=get_file_view_keyboard(

                selected_file["file_unique_id"],

                target.from_user.id

            )

        )

# =========================================================

# CATEGORIES & FILES

# =========================================================

@dp.callback_query(F.data.startswith("cat:"))

async def process_category_click(

    callback: types.CallbackQuery

):

    cat_key = callback.data.split(

        ":",

        1

    )[1]

    cat_data = DATABASE["categories"].get(

        cat_key

    )

    if not cat_data:

        return await callback.answer(

            "Раздел не найден.",

            show_alert=True

        )

    if not cat_data.get("files"):

        await callback.message.edit_text(

            f"**{cat_data['title']}**\n\n"

            "📁 Пока нет файлов.",

            reply_markup=InlineKeyboardMarkup(

                inline_keyboard=[

                    [

                        InlineKeyboardButton(

                            text="⬅️ Назад",

                            callback_data="menu:catalog"

                        )

                    ]

                ]

            )

        )

        return await callback.answer()

    builder = []

    for item in cat_data["files"][:90]:

        caption = item.get(

            "caption",

            "Без названия"

        )

        btn_text = (

            f"📄 {caption[:35]}"

            + (

                "..."

                if len(caption) > 35

                else ""

            )

        )

        builder.append([

            InlineKeyboardButton(

                text=btn_text,

                callback_data=f"fv:{item['file_unique_id']}"

            )

        ])

    builder.append([

        InlineKeyboardButton(

            text="⬅️ Назад",

            callback_data="menu:catalog"

        )

    ])

    await callback.message.edit_text(

        f"**{cat_data['title']}**\n\n"

        "⬇️ Выбери файл:",

        reply_markup=InlineKeyboardMarkup(

            inline_keyboard=builder

        )

    )

    await callback.answer()

@dp.callback_query(F.data.startswith("fv:"))

async def view_file(

    callback: types.CallbackQuery

):

    uid = callback.data.split(

        ":",

        1

    )[1]

    f = get_file_by_uid(uid)

    if not f:

        return await callback.answer(

            "❌ Файл больше не доступен "

            "или был удален.",

            show_alert=True

        )

    await callback.answer(

        "Отправляю... ⏳"

    )

    cap = (

        f"📄 {f.get('caption', 'Без названия')}"

    )

    tags = f.get(

        "tags",

        []

    )

    if tags:

        cap += (

            f"\n🏷 Теги: "

            f"{' '.join(tags)}"

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

# =========================================================

# GLOBAL TEXT SEARCH

# =========================================================

#

# ВАЖНО:

# StateFilter(None) означает:

# поиск работает ТОЛЬКО если пользователь

# сейчас не находится ни в одном FSM-состоянии.

#

# Именно это чинит проблему:

# фото -> решение -> поиск.

# =========================================================

@dp.message(

    StateFilter(None),

    F.text,

    ~F.text.startswith("/")

)

async def global_search_handler(

    message: types.Message

):

    query = message.text.strip().lower()

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

        for f in cat_data.get("files", []):

            haystack = (

                f"{cat_data['title']} "

                f"{f.get('caption', '')} "

                + " ".join(

                    f.get("tags", [])

                )

                + f" {f.get('difficulty', '') or ''}"

            ).lower()

            if all(

                word in haystack

                for word in words

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

        for item in sec.get("items", []):

            item_title = item.get(

                "title",

                ""

            ).lower()

            if all(

                word in item_title

                for word in words

            ):

                found_links.append(item)

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

                    f"📄 **{f.get('caption', 'Файл')}**\n"

                    f"📌 {cat_title}"

                ),

                reply_markup=get_file_view_keyboard(

                    f["file_unique_id"],

                    message.from_user.id

                )

            )

    if found_links:

        builder = []

        for item in found_links[:10]:

            builder.append([

                InlineKeyboardButton(

                    text=item.get(

                        "title",

                        "Ссылка"

                    ),

                    url=item.get(

                        "url",

                        ""

                    )

                )

            ])

        await message.answer(

            f"🔗 Найдено ссылок: "

            f"**{len(found_links)}**",

            reply_markup=InlineKeyboardMarkup(

                inline_keyboard=builder

            )

        )

# =========================================================

# ADMIN PANEL

# =========================================================

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

# =========================================================

# ADMIN STATS

# =========================================================

@dp.callback_query(F.data == "admin:stats")

async def admin_stats(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return await callback.answer(

            "⛔",

            show_alert=True

        )

    unique_files = set()

    must_read_files = set()

    for c in DATABASE["categories"].values():

        for f in c.get("files", []):

            uid = f.get(

                "file_unique_id"

            )

            if uid:

                unique_files.add(uid)

                if f.get("must_read"):

                    must_read_files.add(uid)

    links_count = sum(

        len(

            s.get("items", [])

        )

        for s in DATABASE["links"].values()

    )

    tasks_count = len(

        DATABASE["daily_tasks"]

    )

    users_count = len(

        DATABASE["users"]

    )

    active_users = sum(

        1

        for u in DATABASE["users"].values()

        if u.get("score", 0) > 0

    )

    total_solutions = await (

        task_solutions_collection.count_documents({})

    )

    rated_solutions = await (

        task_solutions_collection.count_documents(

            {

                "rating": {

                    "$ne": None

                }

            }

        )

    )

    text = (

        "📊 **Статистика**\n\n"

        f"👥 Пользователей: {users_count}\n"

        f"🔥 Активных: {active_users}\n"

        f"📚 Уникальных файлов: {len(unique_files)}\n"

        f"⭐ Must-read: {len(must_read_files)}\n"

        f"🔗 Ссылок: {links_count}\n"

        f"🎯 Задач дня: {tasks_count}\n"

        f"📝 Решений пользователей: {total_solutions}\n"

        f"✅ Проверено решений: {rated_solutions}"

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

# =========================================================

# ADMIN BROADCAST

# =========================================================

@dp.callback_query(F.data == "admin:broadcast")

async def admin_broadcast_start(

    callback: types.CallbackQuery,

    state: FSMContext

):

    if not is_admin(

        callback.from_user.id

    ):

        return await callback.answer(

            "⛔",

            show_alert=True

        )

    await state.set_state(

        BroadcastAdmin.waiting_for_message

    )

    await callback.message.answer(

        "📢 Отправь сообщение для рассылки "

        "всем пользователям бота.\n\n"

        "Можно отправить текст, фото, видео "

        "или документ.\n\n"

        "Для отмены напиши `/cancel`."

    )

    await callback.answer()

@dp.message(

    BroadcastAdmin.waiting_for_message,

    Command("cancel")

)

async def broadcast_cancel_command(

    message: types.Message,

    state: FSMContext

):

    await state.clear()

    await message.answer(

        "❌ Рассылка отменена."

    )

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

    await callback.answer()

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

            "Ошибка.",

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

        "📢 **Рассылка завершена!**\n\n"

        f"✅ Успешно: {success}\n"

        f"❌ Ошибок: {errors}"

    )

    await callback.answer()

# =========================================================

# ADMIN DAILY TASK MANAGEMENT

# =========================================================

@dp.callback_query(F.data == "admin:tasks")

async def admin_tasks_menu(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return await callback.answer(

            "⛔",

            show_alert=True

        )

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

        return await callback.answer(

            "⛔",

            show_alert=True

        )

    await state.clear()

    await state.set_state(

        TaskOfDayAdmin.waiting_for_photo

    )

    await callback.message.answer(

        "📸 Отправь **ФОТО** для задачи дня."

    )

    await callback.answer()

# ---------------------------------------------------------

# ADMIN TASK PHOTO

# ---------------------------------------------------------

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

    await state.update_data(

        photo_id=message.photo[-1].file_id

    )

    await state.set_state(

        TaskOfDayAdmin.waiting_for_solution

    )

    await message.answer(

        "✅ Фото получено.\n\n"

        "📝 Теперь отправь **решение задачи**.\n\n"

        "Если решения нет - напиши `-`."

    )

# Если вместо фото отправили что-то другое

@dp.message(

    TaskOfDayAdmin.waiting_for_photo

)

async def adm_task_photo_invalid(

    message: types.Message

):

    if not is_admin(

        message.from_user.id

    ):

        return

    await message.answer(

        "⚠️ Сейчас я жду именно **фото** задачи."

    )

# ---------------------------------------------------------

# ADMIN TASK SOLUTION

# ---------------------------------------------------------

@dp.message(

    TaskOfDayAdmin.waiting_for_solution,

    F.text

)

async def adm_task_sol(

    message: types.Message,

    state: FSMContext

):

    if not is_admin(

        message.from_user.id

    ):

        return

    sol = message.text.strip()

    if sol == "-":

        sol = ""

    await state.update_data(

        solution=sol

    )

    await state.set_state(

        TaskOfDayAdmin.waiting_for_date

    )

    today = get_yerevan_date()

    await message.answer(

        "✅ Решение получено.\n\n"

        f"📅 Отправь дату в формате `YYYY-MM-DD`.\n"

        f"Или напиши `сегодня` "

        f"(сохранится на {today})."

    )

# ---------------------------------------------------------

# ADMIN TASK DATE

# ---------------------------------------------------------

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

            "Используй `YYYY-MM-DD` "

            "или `сегодня`."

        )

    data = await state.get_data()

    if not data.get("photo_id"):

        await state.clear()

        return await message.answer(

            "❌ Фото задачи потерялось. "

            "Начни добавление заново."

        )

    DATABASE["daily_tasks"][date_str] = {

        "photo_file_id": data["photo_id"],

        "solution": data.get(

            "solution",

            ""

        ),

        "votes": {},

        "created_at": get_yerevan_date()

    }

    await save_db(DATABASE)

    await state.clear()

    await message.answer(

        f"✅ **Задача на {date_str} сохранена!**\n\n"

        "Теперь пользователи смогут:\n"

        "📝 отправлять свои решения\n"

        "⭐ оценивать задачу\n"

        "👑 а ты сможешь оценивать их решения."

    )

# Invalid input while waiting for solution

@dp.message(

    TaskOfDayAdmin.waiting_for_solution

)

async def adm_task_solution_invalid(

    message: types.Message

):

    if not is_admin(

        message.from_user.id

    ):

        return

    await message.answer(

        "⚠️ Сейчас я жду текст решения.\n"

        "Если решения нет - напиши `-`."

    )

# Invalid input while waiting for date

@dp.message(

    TaskOfDayAdmin.waiting_for_date

)

async def adm_task_date_invalid(

    message: types.Message

):

    if not is_admin(

        message.from_user.id

    ):

        return

    await message.answer(

        "⚠️ Сейчас я жду дату в формате "

        "`YYYY-MM-DD` или `сегодня`."

    )

# =========================================================

# ADMIN FILE EDITING

# =========================================================

def update_file_everywhere(

    uid: str,

    key: str,

    value

):

    for cat in DATABASE["categories"].values():

        for f in cat.get("files", []):

            if f.get("file_unique_id") == uid:

                f[key] = value

@dp.callback_query(F.data.startswith("fe_m:"))

async def fe_menu(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(

        ":",

        1

    )[1]

    f = get_file_by_uid(uid)

    if not f:

        return await callback.answer(

            "Файл не найден.",

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

    await callback.answer()

@dp.callback_query(F.data.startswith("fe_mr:"))

async def fe_toggle_mustread(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(

        ":",

        1

    )[1]

    f = get_file_by_uid(uid)

    if not f:

        return await callback.answer(

            "Ошибка.",

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

    await save_db(DATABASE)

    await callback.message.edit_reply_markup(

        reply_markup=get_file_edit_keyboard(

            uid

        )

    )

    await callback.answer(

        "Статус Must-read обновлен."

    )

@dp.callback_query(F.data.startswith("fe_df:"))

async def fe_diff_menu(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(

        ":",

        1

    )[1]

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

    _, uid, diff = callback.data.split(

        ":"

    )

    if diff == "none":

        diff = None

    update_file_everywhere(

        uid,

        "difficulty",

        diff

    )

    await save_db(DATABASE)

    await callback.message.edit_reply_markup(

        reply_markup=get_file_edit_keyboard(

            uid

        )

    )

    await callback.answer(

        "Сложность обновлена."

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

    uid = callback.data.split(

        ":",

        1

    )[1]

    await state.set_state(

        EditFile.waiting_for_title

    )

    await state.update_data(

        edit_uid=uid

    )

    await callback.message.answer(

        "Отправь новое название для файла."

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

    uid = data.get(

        "edit_uid"

    )

    if not uid:

        await state.clear()

        return await message.answer(

            "❌ Ошибка состояния."

        )

    new_title = message.text.strip()

    if not new_title:

        return await message.answer(

            "Название не может быть пустым."

        )

    update_file_everywhere(

        uid,

        "caption",

        new_title

    )

    await save_db(DATABASE)

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

    uid = callback.data.split(

        ":",

        1

    )[1]

    await state.set_state(

        EditFile.waiting_for_tags

    )

    await state.update_data(

        edit_uid=uid

    )

    await callback.message.answer(

        "🏷 Отправь теги через пробел.\n"

        "Например:\n"

        "`#geometry #imo #inequality`"

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

    uid = data.get(

        "edit_uid"

    )

    if not uid:

        await state.clear()

        return await message.answer(

            "❌ Ошибка состояния."

        )

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

    await save_db(DATABASE)

    await state.clear()

    await message.answer(

        "✅ Теги обновлены:\n"

        + (

            " ".join(tags)

            if tags

            else "нет тегов"

        )

    )

@dp.callback_query(F.data.startswith("fe_c:"))

async def fe_edit_cats(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(

        ":",

        1

    )[1]

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

    _, uid, cat_key = callback.data.split(

        ":"

    )

    current_cats = set(

        get_file_categories(uid)

    )

    if cat_key in current_cats:

        current_cats.remove(cat_key)

    else:

        current_cats.add(cat_key)

    await callback.message.edit_reply_markup(

        reply_markup=get_file_edit_categories_kb(

            uid,

            current_cats

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

    uid = callback.data.split(

        ":",

        1

    )[1]

    # Получаем текущие выбранные категории

    # из markup

    kb = callback.message.reply_markup

    if not kb:

        return await callback.answer(

            "Ошибка.",

            show_alert=True

        )

    new_cats = set()

    for row in kb.inline_keyboard:

        for btn in row:

            if (

                btn.callback_data

                and btn.callback_data.startswith(

                    "fec_t:"

                )

                and "☑️" in btn.text

            ):

                new_cats.add(

                    btn.callback_data.split(

                        ":"

                    )[2]

                )

    if not new_cats:

        return await callback.answer(

            "Нужна хотя бы одна категория!",

            show_alert=True

        )

    f_master = get_file_by_uid(uid)

    if not f_master:

        return await callback.answer(

            "Файл не найден.",

            show_alert=True

        )

    f_copy = copy.deepcopy(

        f_master

    )

    for cat_data in DATABASE["categories"].values():

        cat_data["files"] = [

            x

            for x in cat_data.get("files", [])

            if x.get("file_unique_id") != uid

        ]

    for cat in new_cats:

        if cat in DATABASE["categories"]:

            DATABASE["categories"][cat]["files"].append(

                copy.deepcopy(f_copy)

            )

    await save_db(DATABASE)

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

    uid = callback.data.split(

        ":",

        1

    )[1]

    await state.set_state(

        EditFile.waiting_for_document

    )

    await state.update_data(

        edit_uid=uid

    )

    await callback.message.answer(

        "📄 Отправь новый файл (документ).\n"

        "Он заменит старый."

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

    uid = data.get(

        "edit_uid"

    )

    if not uid:

        await state.clear()

        return await message.answer(

            "❌ Ошибка состояния."

        )

    old_uid = uid

    doc = message.document

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

    new_uid = doc.file_unique_id

    for u_id, u in DATABASE["users"].items():

        favorites = u.get(

            "favorites",

            []

        )

        if old_uid in favorites:

            u["favorites"] = [

                new_uid

                if x == old_uid

                else x

                for x in favorites

            ]

            await db_collection.update_one(

                {"_id": DB_DOC_ID},

                {

                    "$set": {

                        f"data.users.{u_id}.favorites":

                            u["favorites"]

                    }

                }

            )

    await save_db(DATABASE)

    await state.clear()

    await message.answer(

        "✅ Документ успешно заменен!"

    )

@dp.message(

    EditFile.waiting_for_document

)

async def fe_doc_invalid(

    message: types.Message

):

    if not is_admin(

        message.from_user.id

    ):

        return

    await message.answer(

        "⚠️ Отправь именно документ."

    )

@dp.callback_query(F.data.startswith("fd:"))

async def fe_delete_file(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    uid = callback.data.split(

        ":",

        1

    )[1]

    for cat_data in DATABASE["categories"].values():

        cat_data["files"] = [

            x

            for x in cat_data.get("files", [])

            if x.get("file_unique_id") != uid

        ]

    for user in DATABASE["users"].values():

        if uid in user.get(

            "favorites",

            []

        ):

            user["favorites"].remove(uid)

    await save_db(DATABASE)

    try:

        await callback.message.delete()

    except Exception:

        pass

    await callback.answer(

        "🗑 Файл полностью удален из базы.",

        show_alert=True

    )

# =========================================================

# ADMIN FILE UPLOAD

# =========================================================

@dp.callback_query(F.data == "admin:upload")

async def adm_upload_start(

    callback: types.CallbackQuery,

    state: FSMContext

):

    if not is_admin(

        callback.from_user.id

    ):

        return await callback.answer(

            "⛔",

            show_alert=True

        )

    await state.clear()

    await callback.message.answer(

        "📄 Отправь документ (PDF и т.д.), "

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

    # Не надо очищать state здесь,

    # process_admin_document сам установит новый.

    await process_admin_document(

        message,

        state

    )

@dp.message(

    StateFilter(None),

    F.document,

    F.from_user.id.in_(ADMIN_IDS)

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

            "⚠️ Этот файл уже есть "

            "в базе данных!"

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

        f"📥 **Новый файл:**\n"

        f"`{default_name}`\n\n"

        "Отметь разделы:",

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

    cat_key = callback.data.split(

        ":",

        1

    )[1]

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

    await callback.answer()

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

        "Файл"

    )

    short_name = (

        default_name[:25]

        + (

            "..."

            if len(default_name) > 25

            else ""

        )

    )

    builder = [

        [

            InlineKeyboardButton(

                text=f"📝 Оставить: {short_name}",

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

        "или нажми «Оставить».",

        reply_markup=InlineKeyboardMarkup(

            inline_keyboard=builder

        )

    )

    await callback.answer()

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

        if cat_key not in DATABASE["categories"]:

            continue

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

    await save_db(DATABASE)

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

        data.get(

            "default_name",

            "Файл"

        )

    )

    await callback.message.edit_text(

        "✅ Файл сохранён!"

    )

    await state.clear()

    await callback.answer()

@dp.message(

    FileUpload.waiting_for_caption,

    F.text

)

async def admin_save_custom_caption(

    message: types.Message,

    state: FSMContext

):

    title = message.text.strip()

    if not title:

        return await message.answer(

            "Название не может быть пустым."

        )

    await _admin_save_file(

        state,

        title

    )

    await message.answer(

        "✅ Файл сохранён!"

    )

    await state.clear()

# =========================================================

# USER SUBMISSIONS

# =========================================================

@dp.callback_query(F.data == "submit:start")

async def submit_start(

    callback: types.CallbackQuery,

    state: FSMContext

):

    await track_user_activity(

        callback.from_user.id,

        callback.from_user.username or ""

    )

    await state.clear()

    await callback.message.answer(

        "📤 Просто пришли мне сюда файл "

        "(PDF и т.п.) - я передам его админу."

    )

    await callback.answer()

@dp.message(

    StateFilter(None),

    F.document

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

            "⚠️ Этот файл уже есть в каталоге!\n"

            "Спасибо, но второй такой не нужен 😉"

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

        f"📥 Файл получен:\n"

        f"`{default_name}`\n\n"

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

    cat_key = callback.data.split(

        ":",

        1

    )[1]

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

    await callback.answer()

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

        "📤 Файл отправлен админу.\n"

        "Спасибо! 🙌"

    )

    cats_text = (

        ", ".join(

            DATABASE["categories"][c]["title"]

            for c in sub_data["categories"]

            if c in DATABASE["categories"]

        )

        if sub_data["categories"]

        else "Не указано"

    )

    username = sub_data["username"]

    caption = (

        "📥 **Новый файл**\n"

        f"👤 От: @{username}\n"

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

            logger.exception(

                "Ошибка отправки submission админу: %s",

                e

            )

    await callback.answer()

# =========================================================

# SUBMISSION ADMIN ACTIONS

# =========================================================

@dp.callback_query(F.data.startswith("sub_approve:"))

async def sub_approve(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    sub_id = callback.data.split(

        ":",

        1

    )[1]

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

    if not sub.get("categories"):

        return await callback.answer(

            "Сначала выбери разделы.",

            show_alert=True

        )

    for cat_key in sub["categories"]:

        if cat_key not in DATABASE["categories"]:

            continue

        DATABASE["categories"][cat_key]["files"].append(

            {

                "file_id": sub["file_id"],

                "file_unique_id": sub["file_unique_id"],

                "caption": sub["title"],

                "tags": [],

                "must_read": False,

                "difficulty": None

            }

        )

    await save_db(DATABASE)

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

            (

                f"✅ Твой файл "

                f"«{sub['title']}» добавлен!\n\n"

                "Спасибо 🙌\n"

                "🏆 +15 очков"

            )

        )

    except Exception:

        pass

    await callback.answer(

        "Файл одобрен!"

    )

@dp.callback_query(F.data.startswith("sub_reject:"))

async def sub_reject(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    sub_id = callback.data.split(

        ":",

        1

    )[1]

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

        "Файл отклонен."

    )

@dp.callback_query(F.data.startswith("sub_editcat:"))

async def sub_editcat(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    sub_id = callback.data.split(

        ":",

        1

    )[1]

    sub = await get_submission(

        sub_id

    )

    if (

        not sub

        or sub.get("status") != "pending"

    ):

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

@dp.callback_query(F.data.startswith("subcat_toggle:"))

async def subcat_toggle(

    callback: types.CallbackQuery

):

    if not is_admin(

        callback.from_user.id

    ):

        return

    _, sub_id, cat_key = callback.data.split(

        ":"

    )

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

    sub_id = callback.data.split(

        ":",

        1

    )[1]

    await callback.message.edit_reply_markup(

        reply_markup=build_submission_action_kb(

            sub_id

        )

    )

    await callback.answer()

# =========================================================

# TELEGRAM COMMANDS

# =========================================================

async def set_main_menu(b: Bot):

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

        BotCommand(

            command="cancel",

            description="Отменить действие ❌"

        )

    ]

    await b.set_my_commands(

        commands

    )

# =========================================================

# GLOBAL CANCEL

# =========================================================

@dp.message(Command("cancel"))

async def global_cancel(

    message: types.Message,

    state: FSMContext

):

    current_state = await state.get_state()

    if current_state is None:

        return await message.answer(

            "Сейчас нечего отменять."

        )

    await state.clear()

    await message.answer(

        "❌ Текущее действие отменено."

    )

# =========================================================

# WEB SERVER

# =========================================================

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

        "🌐 Веб-сервер запущен на порту %s",

        port

    )

# =========================================================

# MAIN

# =========================================================

async def main():

    global DATABASE

    await run_web_server()

    try:

        await mongo_client.admin.command(

            "ping"

        )

        logger.info(

            "✅ Подключение к MongoDB установлено"

        )

    except Exception as e:

        logger.exception(

            "❌ Не удалось подключиться к MongoDB: %s",

            e

        )

        raise

    DATABASE = await load_db()

    logger.info(

        "📚 База данных загружена"

    )

    await set_main_menu(

        bot

    )

    logger.info(

        "🤖 Бот запущен!"

    )

    try:

        await dp.start_polling(

            bot

        )

    finally:

        await bot.session.close()

        mongo_client.close()

# =========================================================

# ENTRY POINT

# =========================================================

if __name__ == "__main__":

    asyncio.run(main())