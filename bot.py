import logging
import random
import os
import copy
import uuid

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient


# ==========================================
# CONFIG
# ==========================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")

ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [
    int(x.strip())
    for x in ADMIN_IDS_RAW.split(",")
    if x.strip().isdigit()
]

MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "matham_bot")


# ==========================================
# BOT + DATABASE
# ==========================================

mongo_client = AsyncIOMotorClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]

db_collection = mongo_db["catalog"]
DB_DOC_ID = "catalog_main"

bot = Bot(token=TOKEN)
dp = Dispatcher()

DATABASE = {}

PENDING_SUBMISSIONS = {}


# ==========================================
# DEFAULT DATABASE
# ==========================================

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
            "title": "🎥 Полезные видео и YouTube-каналы",
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
    }
}


# ==========================================
# DATABASE FUNCTIONS
# ==========================================

async def load_db():
    doc = await db_collection.find_one({"_id": DB_DOC_ID})

    if doc is None:
        logger.info(
            "В MongoDB нет каталога — создаю DEFAULT_STATE"
        )

        data = copy.deepcopy(DEFAULT_STATE)

        await db_collection.update_one(
            {"_id": DB_DOC_ID},
            {"$set": {"data": data}},
            upsert=True
        )

        return data

    data = doc["data"]

    # --------------------------------------
    # Миграция старой базы
    # --------------------------------------

    if "must_read" not in data:
        data["must_read"] = {
            "title": "⭐ Must-read",
            "files": []
        }

    if "task_of_day" not in data:
        data["task_of_day"] = {
            "file_id": None,
            "caption": "",
            "votes": {}
        }

    return data


async def save_db(db_data):
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {"data": db_data}},
        upsert=True
    )


# ==========================================
# ADMIN CHECK
# ==========================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ==========================================
# DUPLICATE FILE CHECK
# ==========================================

def is_file_exists(file_unique_id: str) -> bool:

    for cat_data in DATABASE["categories"].values():

        for f in cat_data["files"]:

            if f.get("file_unique_id") == file_unique_id:
                return True

    # Must-read тоже проверяем

    for f in DATABASE["must_read"]["files"]:

        if f.get("file_unique_id") == file_unique_id:
            return True

    return False


# ==========================================
# FSM STATES
# ==========================================

class FileUpload(StatesGroup):

    selecting_categories = State()
    waiting_for_caption = State()


class UserSubmit(StatesGroup):

    selecting_categories = State()


class AdminReview(StatesGroup):

    editing_title = State()


class AddLink(StatesGroup):

    waiting_for_text = State()


class EditFile(StatesGroup):

    waiting_for_document = State()


class TaskOfDay(StatesGroup):

    waiting_for_photo = State()


class MustReadUpload(StatesGroup):

    waiting_for_document = State()


# ==========================================
# MAIN MENU
# ==========================================

def get_main_menu_keyboard(user_id=None):

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
            text="🧩 Задача дня",
            callback_data="task:show"
        )
    ])

    builder.append([
        InlineKeyboardButton(
            text="⭐ Must-read",
            callback_data="mustread:main"
        )
    ])

    builder.append([
        InlineKeyboardButton(
            text="🔗 Полезные материалы",
            callback_data="links:main"
        )
    ])

    builder.append([
        InlineKeyboardButton(
            text="📤 Предложить файл",
            callback_data="submit:start"
        )
    ])

    if user_id in ADMIN_IDS:
        builder.append([
            InlineKeyboardButton(
                text="👑 Админ-панель",
                callback_data="admin:main"
            )
        ])

    return InlineKeyboardMarkup(
        inline_keyboard=builder
    )


# ==========================================
# ADMIN CATEGORY KEYBOARD
# ==========================================

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


# ==========================================
# USER CATEGORY KEYBOARD
# ==========================================

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
            text=f"✅ Отправить на проверку ({len(selected)})",
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


# ==========================================
# SUBMISSION CATEGORY KEYBOARD
# ==========================================

def build_submission_categories_kb(sub_id: str):

    sub = PENDING_SUBMISSIONS[sub_id]

    selected = set(sub["categories"])

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


# ==========================================
# SUBMISSION ACTION KEYBOARD
# ==========================================

def build_submission_action_kb(sub_id: str):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить как есть",
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


# ==========================================
# TASK OF THE DAY KEYBOARD
# ==========================================

def task_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👍 Полезная",
                    callback_data="task_vote:up"
                ),
                InlineKeyboardButton(
                    text="👎 Не очень",
                    callback_data="task_vote:down"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Результаты",
                    callback_data="task:stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Меню",
                    callback_data="menu:main"
                )
            ]
        ]
    )


# ==========================================
# SEND TASK OF DAY
# ==========================================

async def send_task_of_day(target):

    task = DATABASE.get(
        "task_of_day",
        {}
    )

    if not task.get("file_id"):

        text = (
            "🧩 **Задача дня**\n\n"
            "Пока задача дня не добавлена."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Меню",
                        callback_data="menu:main"
                    )
                ]
            ]
        )

        if isinstance(target, types.Message):

            await target.answer(
                text,
                reply_markup=keyboard
            )

        else:

            await target.message.edit_text(
                text,
                reply_markup=keyboard
            )

        return

    caption = task.get("caption") or ""

    full_caption = "🧩 **Задача дня**"

    if caption:
        full_caption += f"\n\n{caption}"

    if isinstance(target, types.Message):

        await target.answer_photo(
            photo=task["file_id"],
            caption=full_caption,
            reply_markup=task_keyboard()
        )

    else:

        await target.message.answer_photo(
            photo=task["file_id"],
            caption=full_caption,
            reply_markup=task_keyboard()
        )


# ==========================================
# /START
# ==========================================

@dp.message(Command("start"))
async def cmd_start(
    message: types.Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "Здарова! ✌️\n"
        "Я бот канала matham.\n\n"
        "🔎 **Поиск:** Просто напиши слово или несколько слов.\n"
        "🧩 **Задача дня:** новая олимпиадная задача каждый день.\n"
        "⭐ **Must-read:** самые полезные материалы.\n"
        "📂 **Каталог:** выбери раздел ниже.",
        reply_markup=get_main_menu_keyboard(
            message.from_user.id
        )
    )


# ==========================================
# /MENU
# ==========================================

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):

    await message.answer(
        "📂 **Главное меню**\n"
        "Выбери раздел:",
        reply_markup=get_main_menu_keyboard(
            message.from_user.id
        )
    )


# ==========================================
# /SURPRISE
# ==========================================

@dp.message(Command("surprise"))
async def cmd_surprise(message: types.Message):

    all_files = []

    for cat_key, cat_data in DATABASE["categories"].items():

        for f in cat_data["files"]:

            all_files.append(
                (
                    f,
                    cat_data["title"]
                )
            )

    if not all_files:

        return await message.answer(
            "📁 В базе пока нет файлов."
        )

    selected_file, cat_title = random.choice(
        all_files
    )

    await message.answer(
        f"🎲 Случайный файл из раздела: **{cat_title}**"
    )

    await message.answer_document(
        document=selected_file["file_id"],
        caption=f"📄 {selected_file['caption']}"
    )


# ==========================================
# /TASK
# ==========================================

@dp.message(Command("task"))
async def cmd_task(message: types.Message):

    await send_task_of_day(message)


# ==========================================
# TASK CALLBACK
# ==========================================

@dp.callback_query(F.data == "task:show")
async def callback_task(
    callback: types.CallbackQuery
):

    await callback.answer()

    await send_task_of_day(callback)


# ==========================================
# TASK VOTE
# ==========================================

@dp.callback_query(F.data.startswith("task_vote:"))
async def task_vote(
    callback: types.CallbackQuery
):

    vote = callback.data.split(
        ":",
        1
    )[1]

    task = DATABASE.get(
        "task_of_day",
        {}
    )

    if not task.get("file_id"):

        return await callback.answer(
            "Задачи дня пока нет.",
            show_alert=True
        )

    votes = task.setdefault(
        "votes",
        {}
    )

    user_id = str(
        callback.from_user.id
    )

    if user_id in votes:

        return await callback.answer(
            "Ты уже оценил эту задачу 😭",
            show_alert=True
        )

    votes[user_id] = vote

    await save_db(DATABASE)

    await callback.answer(
        "Голос засчитан! 🔥"
    )


# ==========================================
# TASK STATISTICS
# ==========================================

@dp.callback_query(F.data == "task:stats")
async def task_stats(
    callback: types.CallbackQuery
):

    task = DATABASE.get(
        "task_of_day",
        {}
    )

    votes = task.get(
        "votes",
        {}
    )

    up = sum(
        1
        for v in votes.values()
        if v == "up"
    )

    down = sum(
        1
        for v in votes.values()
        if v == "down"
    )

    total = up + down

    if total == 0:

        text = (
            "📊 Пока никто не проголосовал."
        )

    else:

        text = (
            f"📊 **Результаты**\n\n"
            f"👍 Полезная: {up}\n"
            f"👎 Не очень: {down}\n"
            f"👥 Всего голосов: {total}"
        )

    await callback.answer(
        text,
        show_alert=True
    )


# ==========================================
# ADMIN: SET TASK
# ==========================================

@dp.message(Command("settask"))
async def admin_set_task(
    message: types.Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):

        return await message.answer(
            "⛔ Только для админов."
        )

    await state.set_state(
        TaskOfDay.waiting_for_photo
    )

    await message.answer(
        "🧩 **Новая задача дня**\n\n"
        "Отправь фотографию задачи.\n\n"
        "💡 Подпись к фото станет описанием."
    )


# ==========================================
# ADMIN: RECEIVE TASK PHOTO
# ==========================================

@dp.message(
    TaskOfDay.waiting_for_photo,
    F.photo
)
async def admin_task_photo(
    message: types.Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        return

    photo = message.photo[-1]

    DATABASE["task_of_day"] = {
        "file_id": photo.file_id,
        "caption": message.caption or "",
        "votes": {}
    }

    await save_db(DATABASE)

    await state.clear()

    await message.answer(
        "✅ **Задача дня установлена!**\n\n"
        "Голоса предыдущей задачи сброшены.\n"
        "Пользователи увидят новую задачу через /task."
    )


# ==========================================
# MUST-READ KEYBOARD
# ==========================================

def must_read_keyboard(user_id=None):

    files = DATABASE["must_read"]["files"]

    builder = []

    for idx, item in enumerate(files):

        row = [
            InlineKeyboardButton(
                text=f"📄 {item['caption'][:35]}",
                callback_data=f"mustread:file:{idx}"
            )
        ]

        if is_admin(user_id):

            row.append(
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"mustread:delete:{idx}"
                )
            )

        builder.append(row)

    if is_admin(user_id):

        builder.append([
            InlineKeyboardButton(
                text="➕ Добавить файл",
                callback_data="mustread:add"
            )
        ])

    builder.append([
        InlineKeyboardButton(
            text="⬅️ Главное меню",
            callback_data="menu:main"
        )
    ])

    return InlineKeyboardMarkup(
        inline_keyboard=builder
    )


# ==========================================
# MUST-READ MAIN
# ==========================================

@dp.callback_query(F.data == "mustread:main")
async def mustread_main(
    callback: types.CallbackQuery
):

    files = DATABASE["must_read"]["files"]

    text = (
        "⭐ **MUST-READ**\n\n"
        "Материалы, которые стоит прочитать "
        "каждому участнику."
    )

    if not files:

        text += "\n\n📁 Пока пусто."

    await callback.message.edit_text(
        text,
        reply_markup=must_read_keyboard(
            callback.from_user.id
        )
    )

    await callback.answer()


# ==========================================
# MUST-READ OPEN FILE
# ==========================================

@dp.callback_query(
    F.data.startswith("mustread:file:")
)
async def mustread_file(
    callback: types.CallbackQuery
):

    idx = int(
        callback.data.split(":")[2]
    )

    files = DATABASE["must_read"]["files"]

    if idx >= len(files):

        return await callback.answer(
            "Файл больше недоступен.",
            show_alert=True
        )

    item = files[idx]

    await callback.answer(
        "Отправляю... ⏳"
    )

    await callback.message.answer_document(
        document=item["file_id"],
        caption=(
            f"⭐ **Must-read**\n"
            f"📄 {item['caption']}"
        )
    )


# ==========================================
# MUST-READ ADD
# ==========================================

@dp.callback_query(
    F.data == "mustread:add"
)
async def mustread_add(
    callback: types.CallbackQuery,
    state: FSMContext
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    await state.set_state(
        MustReadUpload.waiting_for_document
    )

    await callback.message.answer(
        "📚 **Добавление Must-read**\n\n"
        "Отправь PDF или другой файл.\n"
        "Caption станет названием файла."
    )

    await callback.answer()


# ==========================================
# MUST-READ RECEIVE FILE
# ==========================================

@dp.message(
    MustReadUpload.waiting_for_document,
    F.document
)
async def mustread_save(
    message: types.Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        return

    doc = message.document

    if is_file_exists(doc.file_unique_id):

        await state.clear()

        return await message.answer(
            "⚠️ Такой файл уже есть в базе."
        )

    caption = (
        message.caption
        or doc.file_name
        or "Без названия"
    )

    DATABASE["must_read"]["files"].append({
        "file_id": doc.file_id,
        "file_unique_id": doc.file_unique_id,
        "caption": caption
    })

    await save_db(DATABASE)

    await state.clear()

    await message.answer(
        f"✅ Добавлено в Must-read:\n\n"
        f"📄 {caption}"
    )


# ==========================================
# MUST-READ DELETE
# ==========================================

@dp.callback_query(
    F.data.startswith("mustread:delete:")
)
async def mustread_delete(
    callback: types.CallbackQuery
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    idx = int(
        callback.data.split(":")[2]
    )

    files = DATABASE["must_read"]["files"]

    if idx >= len(files):

        return await callback.answer(
            "Файл не найден.",
            show_alert=True
        )

    deleted = files.pop(idx)

    await save_db(DATABASE)

    await callback.answer(
        "Файл удалён."
    )

    await callback.message.edit_reply_markup(
        reply_markup=must_read_keyboard(
            callback.from_user.id
        )
    )


# ==========================================
# ADMIN PANEL
# ==========================================

@dp.callback_query(F.data == "admin:main")
async def admin_panel(
    callback: types.CallbackQuery
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    files_count = sum(
        len(cat["files"])
        for cat in DATABASE["categories"].values()
    )

    must_read_count = len(
        DATABASE["must_read"]["files"]
    )

    task_exists = bool(
        DATABASE["task_of_day"].get("file_id")
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧩 Установить задачу дня",
                    callback_data="admin:settask"
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
                    text="⬅️ Главное меню",
                    callback_data="menu:main"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        "👑 **Админ-панель**\n\n"
        f"📚 Файлов: {files_count}\n"
        f"⭐ Must-read: {must_read_count}\n"
        f"🧩 Задача дня: "
        f"{'установлена ✅' if task_exists else 'нет ❌'}",
        reply_markup=keyboard
    )

    await callback.answer()


# ==========================================
# ADMIN SET TASK BUTTON
# ==========================================

@dp.callback_query(
    F.data == "admin:settask"
)
async def admin_settask_button(
    callback: types.CallbackQuery,
    state: FSMContext
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    await state.set_state(
        TaskOfDay.waiting_for_photo
    )

    await callback.message.answer(
        "🧩 Отправь фотографию новой задачи дня."
    )

    await callback.answer()


# ==========================================
# ADMIN STATS
# ==========================================

@dp.callback_query(
    F.data == "admin:stats"
)
async def admin_stats(
    callback: types.CallbackQuery
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    task = DATABASE["task_of_day"]

    votes = task.get(
        "votes",
        {}
    )

    up = sum(
        1 for v in votes.values()
        if v == "up"
    )

    down = sum(
        1 for v in votes.values()
        if v == "down"
    )

    files_count = sum(
        len(c["files"])
        for c in DATABASE["categories"].values()
    )

    links_count = sum(
        len(s["items"])
        for s in DATABASE["links"].values()
    )

    await callback.message.edit_text(
        "📊 **Статистика бота**\n\n"
        f"📚 Файлов: {files_count}\n"
        f"🔗 Ссылок: {links_count}\n"
        f"⭐ Must-read: {len(DATABASE['must_read']['files'])}\n\n"
        f"🧩 Задача дня:\n"
        f"👍 {up}\n"
        f"👎 {down}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Админ-панель",
                        callback_data="admin:main"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# ==========================================
# ADMIN: DIRECT FILE UPLOAD
# ==========================================

@dp.message(
    FileUpload.selecting_categories,
    F.document
)
async def admin_doc_received_state(
    message: types.Message,
    state: FSMContext
):

    # На всякий случай
    await state.clear()

    await process_admin_document(
        message,
        state
    )


@dp.message(
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

    if is_file_exists(
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
        f"📥 **Получен файл:** `{default_name}`\n\n"
        "Отметь разделы (можно несколько):",
        reply_markup=build_admin_categories_kb(set())
    )


# ==========================================
# ADMIN CATEGORY TOGGLE
# ==========================================

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
        data.get("selected", [])
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


# ==========================================
# ADMIN CANCEL UPLOAD
# ==========================================

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
        "❌ Загрузка файла отменена."
    )

    await callback.answer()


# ==========================================
# ADMIN CATEGORY DONE
# ==========================================

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
        data.get("selected", [])
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
        "default_name"
    )

    cats_text = ", ".join(
        DATABASE["categories"][c]["title"]
        for c in selected
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
        f"✅ Разделы: {cats_text}\n\n"
        "✍️ Введи название файла или "
        "оставь имя по умолчанию:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=builder
        )
    )

    await callback.answer()


# ==========================================
# SAVE ADMIN FILE
# ==========================================

async def _admin_save_file(
    state: FSMContext,
    caption: str
):

    data = await state.get_data()

    selected = data.get(
        "selected",
        []
    )

    for cat_key in selected:

        DATABASE["categories"][cat_key]["files"].append({
            "file_id": data["file_id"],
            "file_unique_id": data.get("file_unique_id"),
            "caption": caption
        })

    await save_db(DATABASE)

    return selected


# ==========================================
# ADMIN DEFAULT CAPTION
# ==========================================

@dp.callback_query(
    FileUpload.waiting_for_caption,
    F.data == "a_skip_caption"
)
async def admin_skip_caption(
    callback: types.CallbackQuery,
    state: FSMContext
):

    data = await state.get_data()

    default_name = data["default_name"]

    selected = await _admin_save_file(
        state,
        default_name
    )

    cats_text = ", ".join(
        DATABASE["categories"][c]["title"]
        for c in selected
    )

    await callback.message.edit_text(
        f"✅ Файл сохранён в:\n"
        f"{cats_text}\n\n"
        f"📄 {default_name}"
    )

    await state.clear()

    await callback.answer()


# ==========================================
# ADMIN CUSTOM CAPTION
# ==========================================

@dp.message(
    FileUpload.waiting_for_caption,
    F.text
)
async def admin_save_custom_caption(
    message: types.Message,
    state: FSMContext
):

    caption = message.text.strip()

    selected = await _admin_save_file(
        state,
        caption
    )

    cats_text = ", ".join(
        DATABASE["categories"][c]["title"]
        for c in selected
    )

    await message.answer(
        f"✅ Файл сохранён в:\n"
        f"{cats_text}\n\n"
        f"📄 {caption}"
    )

    await state.clear()


# ==========================================
# EDIT EXISTING FILE
# ==========================================

@dp.callback_query(
    F.data.startswith("edit_file:")
)
async def edit_file_start(
    callback: types.CallbackQuery,
    state: FSMContext
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    _, cat_key, idx = callback.data.split(
        ":"
    )

    idx = int(idx)

    files = DATABASE["categories"][cat_key]["files"]

    if idx >= len(files):

        return await callback.answer(
            "Файл не найден.",
            show_alert=True
        )

    old_file = files[idx]

    await state.set_state(
        EditFile.waiting_for_document
    )

    await state.update_data(
        old_file_unique_id=old_file.get(
            "file_unique_id"
        ),
        old_caption=old_file.get(
            "caption"
        )
    )

    await callback.message.answer(
        "✏️ **Изменение файла**\n\n"
        f"Текущий файл:\n"
        f"📄 {old_file.get('caption', 'Без названия')}\n\n"
        "Отправь новый файл.\n"
        "Он заменит старый файл во всех "
        "разделах, где он находится."
    )

    await callback.answer()


# ==========================================
# RECEIVE NEW FILE
# ==========================================

@dp.message(
    EditFile.waiting_for_document,
    F.document
)
async def edit_file_receive(
    message: types.Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()

    old_unique_id = data.get(
        "old_file_unique_id"
    )

    old_caption = data.get(
        "old_caption"
    )

    new_doc = message.document

    new_caption = (
        message.caption
        or old_caption
        or new_doc.file_name
    )

    replaced = 0

    for cat_data in DATABASE["categories"].values():

        for item in cat_data["files"]:

            if item.get(
                "file_unique_id"
            ) == old_unique_id:

                item["file_id"] = new_doc.file_id

                item["file_unique_id"] = (
                    new_doc.file_unique_id
                )

                item["caption"] = new_caption

                replaced += 1

    await save_db(DATABASE)

    await state.clear()

    await message.answer(
        "✅ **Файл успешно изменён!**\n\n"
        f"📄 {new_caption}\n"
        f"📁 Обновлено записей: {replaced}"
    )


# ==========================================
# USER SUBMIT FILE
# ==========================================

@dp.callback_query(
    F.data == "submit:start"
)
async def submit_start(
    callback: types.CallbackQuery
):

    await callback.message.answer(
        "📤 Просто пришли мне сюда файл "
        "(PDF и т.п.), который хочешь предложить "
        "для базы — я передам его админу на проверку."
    )

    await callback.answer()


# ==========================================
# USER DOCUMENT
# ==========================================

@dp.message(F.document)
async def user_doc_received(
    message: types.Message,
    state: FSMContext
):

    # Если это админ — его обработает админский handler
    # Этот handler нужен обычным пользователям.

    if is_admin(message.from_user.id):
        return

    doc = message.document

    if is_file_exists(
        doc.file_unique_id
    ):

        return await message.answer(
            "⚠️ Этот файл уже есть в каталоге! "
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
        f"📥 Файл получен: `{default_name}`\n\n"
        "Можешь подсказать раздел "
        "(необязательно — админ сам решит):",
        reply_markup=build_user_categories_kb(set())
    )


# ==========================================
# USER SUBMIT CATEGORY TOGGLE
# ==========================================

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
        data.get("selected", [])
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


# ==========================================
# USER SUBMIT CANCEL
# ==========================================

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
        "❌ Отправка файла отменена."
    )

    await callback.answer()


# ==========================================
# USER SUBMIT DONE
# ==========================================

@dp.callback_query(
    UserSubmit.selecting_categories,
    F.data == "usub_done"
)
async def usub_done(
    callback: types.CallbackQuery,
    state: FSMContext
):

    data = await state.get_data()

    selected = list(
        set(
            data.get("selected", [])
        )
    )

    sub_id = uuid.uuid4().hex[:8]

    username = (
        f"@{callback.from_user.username}"
        if callback.from_user.username
        else callback.from_user.full_name
    )

    PENDING_SUBMISSIONS[sub_id] = {
        "user_id": callback.from_user.id,
        "username": username,
        "file_id": data["file_id"],
        "file_unique_id": data.get(
            "file_unique_id"
        ),
        "title": data["default_name"],
        "categories": selected,
        "status": "pending"
    }

    await state.clear()

    await callback.message.edit_text(
        "📤 Файл отправлен на проверку админу.\n"
        "Спасибо за помощь! 🙌"
    )

    await callback.answer()

    await send_submission_for_review(
        sub_id
    )


# ==========================================
# SEND SUBMISSION TO ADMINS
# ==========================================

async def send_submission_for_review(
    sub_id: str
):

    sub = PENDING_SUBMISSIONS[sub_id]

    cats_text = (
        ", ".join(
            DATABASE["categories"][c]["title"]
            for c in sub["categories"]
        )
        if sub["categories"]
        else "не указано"
    )

    caption = (
        "📥 **Новый файл на проверку**\n"
        f"👤 От: {sub['username']}\n"
        f"📄 Название: {sub['title']}\n"
        f"📁 Разделы: {cats_text}"
    )

    for admin_id in ADMIN_IDS:

        try:

            await bot.send_document(
                admin_id,
                document=sub["file_id"],
                caption=caption,
                reply_markup=build_submission_action_kb(
                    sub_id
                )
            )

        except Exception as e:

            logger.error(
                f"Не удалось отправить админу "
                f"{admin_id}: {e}"
            )


# ==========================================
# APPROVE SUBMISSION
# ==========================================

@dp.callback_query(
    F.data.startswith("sub_approve:")
)
async def sub_approve(
    callback: types.CallbackQuery
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    sub_id = callback.data.split(
        ":",
        1
    )[1]

    sub = PENDING_SUBMISSIONS.get(
        sub_id
    )

    if not sub or sub["status"] != "pending":

        return await callback.answer(
            "Уже обработано.",
            show_alert=True
        )

    if not sub["categories"]:

        return await callback.answer(
            "Сначала выбери разделы.",
            show_alert=True
        )

    for cat_key in sub["categories"]:

        DATABASE["categories"][cat_key]["files"].append({
            "file_id": sub["file_id"],
            "file_unique_id": sub.get(
                "file_unique_id"
            ),
            "caption": sub["title"]
        })

    await save_db(DATABASE)

    sub["status"] = "approved"

    try:

        await callback.message.edit_caption(
            caption=(
                callback.message.caption or ""
            ) + "\n\n✅ ОДОБРЕНО",
            reply_markup=None
        )

    except Exception:
        pass

    await callback.answer(
        "Добавлено ✅"
    )

    try:

        await bot.send_message(
            sub["user_id"],
            f"✅ Твой файл «{sub['title']}» "
            "добавлен в каталог! Спасибо 🙌"
        )

    except Exception:
        pass


# ==========================================
# REJECT SUBMISSION
# ==========================================

@dp.callback_query(
    F.data.startswith("sub_reject:")
)
async def sub_reject(
    callback: types.CallbackQuery
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    sub_id = callback.data.split(
        ":",
        1
    )[1]

    sub = PENDING_SUBMISSIONS.get(
        sub_id
    )

    if not sub or sub["status"] != "pending":

        return await callback.answer(
            "Уже обработано.",
            show_alert=True
        )

    sub["status"] = "rejected"

    try:

        await callback.message.edit_caption(
            caption=(
                callback.message.caption or ""
            ) + "\n\n❌ ОТКЛОНЕНО",
            reply_markup=None
        )

    except Exception:
        pass

    await callback.answer(
        "Отклонено"
    )

    try:

        await bot.send_message(
            sub["user_id"],
            "😔 Твой файл не был принят в каталог."
        )

    except Exception:
        pass


# ==========================================
# EDIT SUBMISSION CATEGORIES
# ==========================================

@dp.callback_query(
    F.data.startswith("sub_editcat:")
)
async def sub_editcat(
    callback: types.CallbackQuery
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    sub_id = callback.data.split(
        ":",
        1
    )[1]

    if PENDING_SUBMISSIONS.get(
        sub_id,
        {}
    ).get("status") != "pending":

        return await callback.answer(
            "Уже обработано.",
            show_alert=True
        )

    await callback.message.edit_reply_markup(
        reply_markup=build_submission_categories_kb(
            sub_id
        )
    )

    await callback.answer()


# ==========================================
# TOGGLE SUBMISSION CATEGORY
# ==========================================

@dp.callback_query(
    F.data.startswith("subcat_toggle:")
)
async def subcat_toggle(
    callback: types.CallbackQuery
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    _, sub_id, cat_key = callback.data.split(
        ":"
    )

    sub = PENDING_SUBMISSIONS.get(
        sub_id
    )

    if not sub or sub["status"] != "pending":

        return await callback.answer(
            "Уже обработано.",
            show_alert=True
        )

    selected = set(
        sub["categories"]
    )

    if cat_key in selected:
        selected.remove(cat_key)
    else:
        selected.add(cat_key)

    sub["categories"] = list(
        selected
    )

    await callback.message.edit_reply_markup(
        reply_markup=build_submission_categories_kb(
            sub_id
        )
    )

    await callback.answer()


# ==========================================
# SUBMISSION CATEGORY DONE
# ==========================================

@dp.callback_query(
    F.data.startswith("subcat_done:")
)
async def subcat_done(
    callback: types.CallbackQuery
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    sub_id = callback.data.split(
        ":",
        1
    )[1]

    if PENDING_SUBMISSIONS.get(
        sub_id,
        {}
    ).get("status") != "pending":

        return await callback.answer(
            "Уже обработано.",
            show_alert=True
        )

    await callback.message.edit_reply_markup(
        reply_markup=build_submission_action_kb(
            sub_id
        )
    )

    await callback.answer()


# ==========================================
# EDIT SUBMISSION TITLE
# ==========================================

@dp.callback_query(
    F.data.startswith("sub_edittitle:")
)
async def sub_edittitle(
    callback: types.CallbackQuery,
    state: FSMContext
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    sub_id = callback.data.split(
        ":",
        1
    )[1]

    if PENDING_SUBMISSIONS.get(
        sub_id,
        {}
    ).get("status") != "pending":

        return await callback.answer(
            "Уже обработано.",
            show_alert=True
        )

    await state.set_state(
        AdminReview.editing_title
    )

    await state.update_data(
        sub_id=sub_id
    )

    await callback.message.answer(
        "✍️ Введи новое название файла:"
    )

    await callback.answer()


# ==========================================
# SAVE NEW SUBMISSION TITLE
# ==========================================

@dp.message(
    AdminReview.editing_title,
    F.text
)
async def admin_retitle_submission(
    message: types.Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()

    sub_id = data.get(
        "sub_id"
    )

    sub = PENDING_SUBMISSIONS.get(
        sub_id
    )

    await state.clear()

    if not sub or sub["status"] != "pending":

        return await message.answer(
            "⚠️ Эта заявка уже обработана."
        )

    sub["title"] = message.text.strip()

    await message.answer(
        f"✅ Название обновлено:\n"
        f"{sub['title']}"
    )


# ==========================================
# LINKS MAIN
# ==========================================

@dp.callback_query(
    F.data == "links:main"
)
async def links_main(
    callback: types.CallbackQuery
):

    builder = []

    for key, sec in DATABASE["links"].items():

        builder.append([
            InlineKeyboardButton(
                text=sec["title"],
                callback_data=f"links:sec:{key}"
            )
        ])

    builder.append([
        InlineKeyboardButton(
            text="⬅️ Главное меню",
            callback_data="menu:main"
        )
    ])

    await callback.message.edit_text(
        "🔗 **Полезные материалы**\n"
        "Выбери раздел:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=builder
        )
    )

    await callback.answer()


# ==========================================
# LINKS SECTION
# ==========================================

@dp.callback_query(
    F.data.startswith("links:sec:")
)
async def links_section(
    callback: types.CallbackQuery
):

    key = callback.data.split(
        ":",
        2
    )[2]

    sec = DATABASE["links"][key]

    builder = []

    for idx, item in enumerate(
        sec["items"]
    ):

        row = [
            InlineKeyboardButton(
                text=item["title"],
                url=item["url"]
            )
        ]

        if is_admin(
            callback.from_user.id
        ):

            row.append(
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"del_link:{key}:{idx}"
                )
            )

        builder.append(row)

    if is_admin(
        callback.from_user.id
    ):

        builder.append([
            InlineKeyboardButton(
                text="➕ Добавить ссылку",
                callback_data=f"links:add:{key}"
            )
        ])

    builder.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="links:main"
        )
    ])

    text = f"**{sec['title']}**"

    if not sec["items"]:
        text += "\n\nПока пусто."

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=builder
        )
    )

    await callback.answer()


# ==========================================
# ADD LINK
# ==========================================

@dp.callback_query(
    F.data.startswith("links:add:")
)
async def links_add_start(
    callback: types.CallbackQuery,
    state: FSMContext
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    key = callback.data.split(
        ":",
        2
    )[2]

    await state.set_state(
        AddLink.waiting_for_text
    )

    await state.update_data(
        link_key=key
    )

    await callback.message.answer(
        "Отправь в формате:\n\n"
        "Название - URL\n\n"
        "Например:\n"
        "Официальный канал - https://t.me/matham"
    )

    await callback.answer()


# ==========================================
# SAVE LINK
# ==========================================

@dp.message(
    AddLink.waiting_for_text,
    F.text
)
async def links_add_save(
    message: types.Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()

    key = data["link_key"]

    text = message.text.strip()

    if " - " in text:

        title, url = text.split(
            " - ",
            1
        )

    elif "|" in text:

        title, url = text.split(
            "|",
            1
        )

    else:

        return await message.answer(
            "⚠️ Не понял формат.\n\n"
            "Используй:\n"
            "Название - URL"
        )

    title = title.strip()
    url = url.strip()

    DATABASE["links"][key]["items"].append({
        "title": title,
        "url": url
    })

    await save_db(DATABASE)

    await state.clear()

    await message.answer(
        f"✅ Ссылка добавлена:\n"
        f"{title}"
    )


# ==========================================
# DELETE LINK
# ==========================================

@dp.callback_query(
    F.data.startswith("del_link:")
)
async def admin_delete_link(
    callback: types.CallbackQuery
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    _, key, idx = callback.data.split(
        ":"
    )

    idx = int(idx)

    sec = DATABASE["links"][key]

    if idx >= len(sec["items"]):

        return await callback.answer(
            "Ошибка: ссылка не найдена.",
            show_alert=True
        )

    sec["items"].pop(idx)

    await save_db(DATABASE)

    await callback.answer(
        "Ссылка удалена."
    )

    builder = []

    for i, item in enumerate(
        sec["items"]
    ):

        row = [
            InlineKeyboardButton(
                text=item["title"],
                url=item["url"]
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"del_link:{key}:{i}"
            )
        ]

        builder.append(row)

    builder.append([
        InlineKeyboardButton(
            text="➕ Добавить ссылку",
            callback_data=f"links:add:{key}"
        )
    ])

    builder.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="links:main"
        )
    ])

    text = f"**{sec['title']}**"

    if not sec["items"]:
        text += "\n\nПока пусто."

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=builder
        )
    )


# ==========================================
# CATEGORY
# ==========================================

@dp.callback_query(
    F.data.startswith("cat:")
)
async def process_category_click(
    callback: types.CallbackQuery
):

    cat_key = callback.data.split(
        ":",
        1
    )[1]

    cat_data = DATABASE["categories"][cat_key]

    if not cat_data["files"]:

        builder = [
            [
                InlineKeyboardButton(
                    text="⬅️ Главное меню",
                    callback_data="menu:main"
                )
            ]
        ]

        return await callback.message.edit_text(
            f"**{cat_data['title']}**\n\n"
            "📁 Пока нет файлов.\n"
            "Попробуй поиск.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=builder
            )
        )

    builder = []

    for idx, item in enumerate(
        cat_data["files"]
    ):

        btn_text = (
            f"📄 {item['caption'][:35]}"
        )

        if len(item["caption"]) > 35:
            btn_text += "..."

        row = [
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"file:{cat_key}:{idx}"
            )
        ]

        if is_admin(
            callback.from_user.id
        ):

            row.append(
                InlineKeyboardButton(
                    text="✏️",
                    callback_data=f"edit_file:{cat_key}:{idx}"
                )
            )

            row.append(
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"del_file:{cat_key}:{idx}"
                )
            )

        builder.append(row)

    builder.append([
        InlineKeyboardButton(
            text="⬅️ Главное меню",
            callback_data="menu:main"
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


# ==========================================
# DELETE FILE
# ==========================================

@dp.callback_query(
    F.data.startswith("del_file:")
)
async def admin_delete_file(
    callback: types.CallbackQuery
):

    if not is_admin(callback.from_user.id):

        return await callback.answer(
            "⛔ Только для админов.",
            show_alert=True
        )

    _, cat_key, idx = callback.data.split(
        ":"
    )

    idx = int(idx)

    cat_data = DATABASE["categories"][cat_key]

    files = cat_data["files"]

    if idx >= len(files):

        return await callback.answer(
            "Файл не найден.",
            show_alert=True
        )

    deleted = files.pop(idx)

    await save_db(DATABASE)

    await callback.answer(
        f"Удалено: {deleted['caption']}"
    )

    if not files:

        return await callback.message.edit_text(
            f"**{cat_data['title']}**\n\n"
            "📁 Пока нет файлов.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Главное меню",
                            callback_data="menu:main"
                        )
                    ]
                ]
            )
        )

    builder = []

    for i, item in enumerate(files):

        btn_text = (
            f"📄 {item['caption'][:35]}"
        )

        if len(item["caption"]) > 35:
            btn_text += "..."

        builder.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"file:{cat_key}:{i}"
            ),
            InlineKeyboardButton(
                text="✏️",
                callback_data=f"edit_file:{cat_key}:{i}"
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"del_file:{cat_key}:{i}"
            )
        ])

    builder.append([
        InlineKeyboardButton(
            text="⬅️ Главное меню",
            callback_data="menu:main"
        )
    ])

    await callback.message.edit_text(
        f"**{cat_data['title']}**\n\n"
        "⬇️ Выбери файл:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=builder
        )
    )


# ==========================================
# OPEN FILE
# ==========================================

@dp.callback_query(
    F.data.startswith("file:")
)
async def process_file_click(
    callback: types.CallbackQuery
):

    _, cat_key, idx = callback.data.split(
        ":"
    )

    idx = int(idx)

    files = DATABASE["categories"][cat_key]["files"]

    if idx >= len(files):

        return await callback.answer(
            "❌ Файл больше не доступен.",
            show_alert=True
        )

    item = files[idx]

    await callback.answer(
        "Отправляю... ⏳"
    )

    await callback.message.answer_document(
        document=item["file_id"],
        caption=f"📄 {item['caption']}"
    )


# ==========================================
# BACK TO MAIN MENU
# ==========================================

@dp.callback_query(
    F.data == "menu:main"
)
async def process_back_to_main(
    callback: types.CallbackQuery
):

    await callback.message.edit_text(
        "📂 **Каталог файлов**\n"
        "Выбери раздел:",
        reply_markup=get_main_menu_keyboard(
            callback.from_user.id
        )
    )

    await callback.answer()


# ==========================================
# GLOBAL SEARCH
# ==========================================

@dp.message(
    F.text & ~F.text.startswith("/")
)
async def global_search_handler(
    message: types.Message
):

    query = message.text.strip().lower()

    if query in [
        "удиви меня",
        "surprise",
        "рандом"
    ]:

        return await cmd_surprise(message)

    words = [
        w
        for w in query.split()
        if w
    ]

    if not words:
        return

    found_files = []

    for cat_data in DATABASE["categories"].values():

        haystack_cat = cat_data["title"].lower()

        for f in cat_data["files"]:

            haystack = (
                f"{haystack_cat} "
                f"{f['caption'].lower()}"
            )

            if all(
                w in haystack
                for w in words
            ):

                found_files.append(
                    (
                        f,
                        cat_data["title"]
                    )
                )

    found_links = []

    for sec in DATABASE["links"].values():

        for item in sec["items"]:

            if all(
                w in item["title"].lower()
                for w in words
            ):

                found_links.append(item)

    # Search Must-read

    found_must_read = []

    for item in DATABASE["must_read"]["files"]:

        if all(
            w in item["caption"].lower()
            for w in words
        ):

            found_must_read.append(item)

    if (
        not found_files
        and not found_links
        and not found_must_read
    ):

        return await message.answer(
            "🔍 Ничего не найдено.\n\n"
            "Попробуй другое слово или открой меню:",
            reply_markup=get_main_menu_keyboard(
                message.from_user.id
            )
        )

    # Files

    if found_files:

        await message.answer(
            f"🔍 Найдено файлов: "
            f"**{len(found_files)}**"
        )

        for file_info, cat_title in found_files[:10]:

            await message.answer_document(
                document=file_info["file_id"],
                caption=(
                    f"📄 **{file_info['caption']}**\n"
                    f"📌 {cat_title}"
                )
            )

    # Links

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

    # Must-read

    if found_must_read:

        await message.answer(
            f"⭐ Найдено в Must-read: "
            f"**{len(found_must_read)}**"
        )

        for item in found_must_read[:10]:

            await message.answer_document(
                document=item["file_id"],
                caption=(
                    f"⭐ **Must-read**\n"
                    f"📄 {item['caption']}"
                )
            )


# ==========================================
# TELEGRAM COMMANDS
# ==========================================

async def set_main_menu(bot: Bot):

    commands = [
        BotCommand(
            command="start",
            description="Главное меню 🚀"
        ),
        BotCommand(
            command="menu",
            description="Открыть меню 📂"
        ),
        BotCommand(
            command="task",
            description="Задача дня 🧩"
        ),
        BotCommand(
            command="surprise",
            description="Случайный файл 🎲"
        )
    ]

    await bot.set_my_commands(
        commands
    )


# ==========================================
# WEB SERVER
# ==========================================

async def run_web_server():

    app = web.Application()

    app.router.add_get(
        "/",
        lambda r: web.Response(
            text="Bot is running!"
        )
    )

    runner = web.AppRunner(app)

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
        f"🌐 Веб-сервер запущен "
        f"на порту {port}"
    )


# ==========================================
# MAIN
# ==========================================

async def main():

    global DATABASE

    await run_web_server()

    # MongoDB connection

    await mongo_client.admin.command(
        "ping"
    )

    logger.info(
        "✅ Подключение к MongoDB установлено"
    )

    DATABASE = await load_db()

    # --------------------------------------
    # Migration
    # --------------------------------------

    if "must_read" not in DATABASE:

        DATABASE["must_read"] = {
            "title": "⭐ Must-read",
            "files": []
        }

    if "task_of_day" not in DATABASE:

        DATABASE["task_of_day"] = {
            "file_id": None,
            "caption": "",
            "votes": {}
        }

    await save_db(DATABASE)

    # --------------------------------------
    # Statistics
    # --------------------------------------

    n_files = sum(
        len(c["files"])
        for c in DATABASE["categories"].values()
    )

    n_links = sum(
        len(s["items"])
        for s in DATABASE["links"].values()
    )

    n_must_read = len(
        DATABASE["must_read"]["files"]
    )

    logger.info(
        f"📦 Каталог загружен: "
        f"{len(DATABASE['categories'])} категорий, "
        f"{n_files} файлов, "
        f"{n_links} ссылок, "
        f"{n_must_read} Must-read"
    )

    await set_main_menu(bot)

    logger.info(
        "🤖 Бот запущен!"
    )

    await dp.start_polling(bot)


# ==========================================
# START
# ==========================================

if __name__ == "__main__":

    import asyncio

    try:
        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        logger.info(
            "🛑 Бот остановлен."
        )