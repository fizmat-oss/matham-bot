# ПОЛНЫЙ КОД
import os
import asyncio
import logging
import datetime
import random
import uuid
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand
)
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramAPIError

# ==========================================
# 1. CONFIG & INITIALIZATION
# ==========================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "matham_bot_db")

# Список ID администраторов
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip().isdigit()]

TIMEZONE = ZoneInfo("Asia/Yerevan")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client[DB_NAME]
catalog_collection = db["catalog"]

DEFAULT_STATE = {
    "_id": "catalog_main",
    "categories": {
        "Книги": [],
        "Журналы": [],
        "Статьи": [],
        "Задачи": [],
        "Олимпиады": []
    },
    "links": {},
    "must_read": [],      # [file_id, ...]
    "daily_tasks": {},    # {"YYYY-MM-DD": task_dict}
    "users": {},          # {"user_id": user_dict}
    "settings": {},
    "stats": {
        "file_views": {}, # {"file_id": count}
        "cat_views": {}   # {"cat_name": count}
    }
}

DB_CACHE: Dict[str, Any] = {}

# ==========================================
# 2. DATABASE HELPERS
# ==========================================

async def init_db():
    global DB_CACHE
    data = await catalog_collection.find_one({"_id": "catalog_main"})
    if not data:
        DB_CACHE = DEFAULT_STATE.copy()
        await catalog_collection.insert_one(DB_CACHE)
    else:
        changed = False
        for key in DEFAULT_STATE:
            if key not in data:
                data[key] = DEFAULT_STATE[key]
                changed = True
        
        for cat, files in data.get("categories", {}).items():
            for f in files:
                if "id" not in f:
                    f["id"] = str(uuid.uuid4())
                    changed = True
                if "tags" not in f:
                    f["tags"] = []
                    changed = True
                if "difficulty" not in f:
                    f["difficulty"] = "medium"
                    changed = True
                if "views" not in f:
                    f["views"] = 0
                    changed = True

        DB_CACHE = data
        if changed:
            await save_db()

async def save_db():
    global DB_CACHE
    await catalog_collection.replace_one({"_id": "catalog_main"}, DB_CACHE, upsert=True)

def get_now_date_str() -> str:
    return datetime.datetime.now(TIMEZONE).strftime("%Y-%m-%d")

def register_user_activity(user_id: int, username: str = "", full_name: str = "") -> dict:
    u_str = str(user_id)
    users = DB_CACHE.setdefault("users", {})
    now_str = get_now_date_str()

    if u_str not in users:
        users[u_str] = {
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "favorites": [],
            "points": 0,
            "streak": 0,
            "last_active_date": "",
            "opened_tasks": []
        }
    
    u = users[u_str]
    u["username"] = username or u.get("username", "")
    u["full_name"] = full_name or u.get("full_name", "")

    last_date_str = u.get("last_active_date", "")
    if last_date_str != now_str:
        if last_date_str:
            try:
                last_d = datetime.datetime.strptime(last_date_str, "%Y-%m-%d").date()
                curr_d = datetime.datetime.strptime(now_str, "%Y-%m-%d").date()
                diff = (curr_d - last_d).days
                if diff == 1:
                    u["streak"] = u.get("streak", 0) + 1
                elif diff > 1:
                    u["streak"] = 1
            except Exception:
                u["streak"] = 1
        else:
            u["streak"] = 1
        u["last_active_date"] = now_str

    return u

def find_file_by_id(file_id: str) -> Optional[dict]:
    for cat, files in DB_CACHE.get("categories", {}).items():
        for f in files:
            if f.get("id") == file_id:
                return f
    return None

def get_all_files_unique() -> List[dict]:
    unique_files = {}
    for cat, files in DB_CACHE.get("categories", {}).items():
        for f in files:
            f_id = f.get("id")
            if f_id and f_id not in unique_files:
                unique_files[f_id] = f
    return list(unique_files.values())

# ==========================================
# 3. FSM STATES
# ==========================================

class AddFileStates(StatesGroup):
    waiting_for_file = State()
    waiting_for_title = State()
    waiting_for_category = State()
    waiting_for_tags = State()
    waiting_for_difficulty = State()

class EditFileStates(StatesGroup):
    waiting_for_new_title = State()
    waiting_for_new_categories = State()
    waiting_for_new_tags = State()

class DailyTaskStates(StatesGroup):
    waiting_for_photo = State()
    waiting_for_caption = State()
    waiting_for_date = State()
    confirm_overwrite = State()
    waiting_for_hint1 = State()
    waiting_for_hint2 = State()
    waiting_for_solution = State()

class BroadcastStates(StatesGroup):
    waiting_for_message = State()
    confirm_send = State()

class AddLinkStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_url = State()

# ==========================================
# 4. KEYBOARDS
# ==========================================

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="📚 Каталог"), KeyboardButton(text="🎯 Задача дня")],
        [KeyboardButton(text="⭐ Must-read"), KeyboardButton(text="❤️ Избранное")],
        [KeyboardButton(text="🔎 Поиск"), KeyboardButton(text="🏆 Рейтинг")],
        [KeyboardButton(text="🎲 Случайный материал"), KeyboardButton(text="🔗 Полезные ссылки")]
    ]
    if user_id in ADMIN_IDS:
        kb.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Добавить файл", callback_data="admin_add_file"),
         InlineKeyboardButton(text="✏️ Управление файлами", callback_data="admin_manage_files")],
        [InlineKeyboardButton(text="🎯 Задача дня", callback_data="admin_daily_task"),
         InlineKeyboardButton(text="⭐ Must-read", callback_data="admin_must_read_list")],
        [InlineKeyboardButton(text="🔗 Ссылки", callback_data="admin_manage_links"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")]
    ])

def get_categories_keyboard(prefix: str = "cat_") -> InlineKeyboardMarkup:
    buttons = []
    for cat in DB_CACHE.get("categories", {}).keys():
        buttons.append([InlineKeyboardButton(text=cat, callback_data=f"{prefix}{cat}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu_cb")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_file_actions_keyboard(file_id: str, user_id: int) -> InlineKeyboardMarkup:
    u_str = str(user_id)
    user_favs = DB_CACHE.get("users", {}).get(u_str, {}).get("favorites", [])
    is_fav = file_id in user_favs
    
    fav_text = "💔 Из избранного" if is_fav else "❤️ В избранное"
    fav_cb = f"fav_rem_{file_id}" if is_fav else f"fav_add_{file_id}"

    buttons = [
        [InlineKeyboardButton(text=fav_text, callback_data=fav_cb)]
    ]

    if user_id in ADMIN_IDS:
        f = find_file_by_id(file_id)
        must_list = DB_CACHE.get("must_read", [])
        is_must = file_id in must_list
        must_text = "☆ Убрать Must-read" if is_must else "⭐ В Must-read"
        
        buttons.append([
            InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit_file_{file_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_file_{file_id}")
        ])
        buttons.append([InlineKeyboardButton(text=must_text, callback_data=f"toggle_must_{file_id}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_task_user_keyboard(date_str: str, user_id: int) -> InlineKeyboardMarkup:
    u_str = str(user_id)
    task = DB_CACHE.get("daily_tasks", {}).get(date_str, {})
    ratings = task.get("ratings", {})
    user_rating = ratings.get(u_str, 0)

    stars_row = []
    for i in range(1, 6):
        label = f"★ {i}" if user_rating == i else f"⭐ {i}"
        stars_row.append(InlineKeyboardButton(text=label, callback_data=f"rate_task_{date_str}_{i}"))

    buttons = [stars_row]

    hints_row = []
    if task.get("hint1"):
        hints_row.append(InlineKeyboardButton(text="💡 Подсказка 1", callback_data=f"task_hint_1_{date_str}"))
    if task.get("hint2"):
        hints_row.append(InlineKeyboardButton(text="💡 Подсказка 2", callback_data=f"task_hint_2_{date_str}"))
    if hints_row:
        buttons.append(hints_row)

    if task.get("solution"):
        buttons.append([InlineKeyboardButton(text="✅ Решение", callback_data=f"task_solution_{date_str}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==========================================
# 5. COMMANDS & BASIC HANDLERS
# ==========================================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    register_user_activity(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await save_db()

    text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Добро пожаловать в математическую библиотеку **Matham**.\n"
        "Здесь вы найдете книги, статьи, олимпиадные задачи и ежедневные челленджи!"
    )
    await message.answer(text, reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")

@router.message(F.text == "📚 Каталог")
async def show_catalog(message: Message):
    register_user_activity(message.from_user.id)
    await message.answer("📁 Выберите категорию:", reply_markup=get_categories_keyboard("cat_"))

@router.message(F.text == "🔗 Полезные ссылки")
async def show_links(message: Message):
    links = DB_CACHE.get("links", {})
    if not links:
        await message.answer("🔗 Полезных ссылок пока нет.")
        return
    
    kb = []
    for name, url in links.items():
        kb.append([InlineKeyboardButton(text=name, url=url)])
    await message.answer("🔗 **Полезные ссылки:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@router.callback_query(F.data == "main_menu_cb")
async def cb_main_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard(callback.from_user.id))

# ==========================================
# 6. FILE MANAGEMENT (CATALOG & EDITING)
# ==========================================

@router.callback_query(F.data.startswith("cat_"))
async def open_category(callback: CallbackQuery):
    cat_name = callback.data.replace("cat_", "")
    files = DB_CACHE.get("categories", {}).get(cat_name, [])

    stats = DB_CACHE.setdefault("stats", {}).setdefault("cat_views", {})
    stats[cat_name] = stats.get(cat_name, 0) + 1
    await save_db()

    if not files:
        await callback.answer("В этой категории пока нет файлов.", show_alert=True)
        return

    kb = []
    for f in files:
        diff_badge = {"easy": "🟢", "medium": "🟡", "hard": "🔴", "imo": "🔥"}.get(f.get("difficulty", "medium"), "")
        title = f"{diff_badge} {f.get('title', 'Без названия')}".strip()
        kb.append([InlineKeyboardButton(text=title, callback_data=f"get_file_{f.get('id')}")])
    
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu_cb")])
    await callback.message.edit_text(f"📚 Категория: **{cat_name}**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@router.callback_query(F.data.startswith("get_file_"))
async def send_file(callback: CallbackQuery):
    file_id = callback.data.replace("get_file_", "")
    f = find_file_by_id(file_id)

    if not f:
        await callback.answer("Файл не найден.", show_alert=True)
        return

    u = register_user_activity(callback.from_user.id)
    f["views"] = f.get("views", 0) + 1
    
    stats = DB_CACHE.setdefault("stats", {}).setdefault("file_views", {})
    stats[file_id] = stats.get(file_id, 0) + 1
    await save_db()

    caption = (
        f"📄 **{f.get('title')}**\n"
        f"📊 Сложность: {f.get('difficulty', 'medium').upper()}\n"
        f"🏷 Теги: {', '.join(f.get('tags', [])) or 'нет'}\n"
        f"👁 Просмотров: {f.get('views', 0)}"
    )

    try:
        await callback.message.answer_document(
            document=f.get("file_id"),
            caption=caption,
            reply_markup=get_file_actions_keyboard(file_id, callback.from_user.id),
            parse_mode="Markdown"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error sending file: {e}")
        await callback.answer("Ошибка при отправке файла.", show_alert=True)

# --- РЕДАКТИРОВАНИЕ ФАЙЛОВ (ТОЛЬКО АДМИН) ---

@router.callback_query(F.data.startswith("edit_file_"))
async def edit_file_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен.", show_alert=True)
        return

    file_id = callback.data.replace("edit_file_", "")
    f = find_file_by_id(file_id)
    if not f:
        await callback.answer("Файл не найден.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Изменить название", callback_data=f"ef_name_{file_id}")],
        [InlineKeyboardButton(text="📁 Изменить разделы", callback_data=f"ef_cats_{file_id}")],
        [InlineKeyboardButton(text="🏷 Изменить теги", callback_data=f"ef_tags_{file_id}")],
        [InlineKeyboardButton(text="📊 Изменить сложность", callback_data=f"ef_diff_{file_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu_cb")]
    ])

    await callback.message.answer(f"✏️ Редактирование файла: **{f.get('title')}**", reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data.startswith("ef_name_"))
async def edit_file_name_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    file_id = callback.data.replace("ef_name_", "")
    await state.update_data(edit_file_id=file_id)
    await state.set_state(EditFileStates.waiting_for_new_title)
    await callback.message.answer("Введите новое название для файла:")

@router.message(EditFileStates.waiting_for_new_title)
async def edit_file_name_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("edit_file_id")
    new_title = message.text.strip()

    for cat, files in DB_CACHE.get("categories", {}).items():
        for f in files:
            if f.get("id") == file_id:
                f["title"] = new_title

    await save_db()
    await state.clear()
    await message.answer(f"✅ Название успешно изменено на: **{new_title}**", parse_mode="Markdown")

@router.callback_query(F.data.startswith("ef_tags_"))
async def edit_file_tags_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    file_id = callback.data.replace("ef_tags_", "")
    await state.update_data(edit_file_id=file_id)
    await state.set_state(EditFileStates.waiting_for_new_tags)
    await callback.message.answer("Введите новые теги через пробел или запятую (напр. `#geometry #imo`):")

@router.message(EditFileStates.waiting_for_new_tags)
async def edit_file_tags_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("edit_file_id")
    raw_tags = message.text.replace(",", " ").split()
    tags = [t if t.startswith("#") else f"#{t}" for t in raw_tags]

    for cat, files in DB_CACHE.get("categories", {}).items():
        for f in files:
            if f.get("id") == file_id:
                f["tags"] = tags

    await save_db()
    await state.clear()
    await message.answer(f"✅ Теги обновлены: {', '.join(tags)}")

@router.callback_query(F.data.startswith("ef_diff_"))
async def edit_file_diff_start(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    file_id = callback.data.replace("ef_diff_", "")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Easy", callback_data=f"set_diff_{file_id}_easy"),
         InlineKeyboardButton(text="🟡 Medium", callback_data=f"set_diff_{file_id}_medium")],
        [InlineKeyboardButton(text="🔴 Hard", callback_data=f"set_diff_{file_id}_hard"),
         InlineKeyboardButton(text="🔥 IMO", callback_data=f"set_diff_{file_id}_imo")]
    ])
    await callback.message.answer("Выберите новый уровень сложности:", reply_markup=kb)

@router.callback_query(F.data.startswith("set_diff_"))
async def edit_file_diff_finish(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    parts = callback.data.split("_")
    file_id = parts[2]
    diff = parts[3]

    for cat, files in DB_CACHE.get("categories", {}).items():
        for f in files:
            if f.get("id") == file_id:
                f["difficulty"] = diff

    await save_db()
    await callback.message.answer(f"✅ Сложность файла изменена на **{diff.upper()}**", parse_mode="Markdown")

@router.callback_query(F.data.startswith("delete_file_"))
async def delete_file(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен.", show_alert=True)
        return

    file_id = callback.data.replace("delete_file_", "")

    for cat, files in DB_CACHE.get("categories", {}).items():
        DB_CACHE["categories"][cat] = [f for f in files if f.get("id") != file_id]

    if file_id in DB_CACHE.get("must_read", []):
        DB_CACHE["must_read"].remove(file_id)

    await save_db()
    await callback.answer("Файл успешно удален из всех категорий.", show_alert=True)
    await callback.message.delete()

# ==========================================
# 7. DAILY TASK SYSTEM
# ==========================================

@router.message(Command("task"))
@router.message(F.text == "🎯 Задача дня")
async def show_daily_task(message: Message):
    today = get_now_date_str()
    tasks = DB_CACHE.get("daily_tasks", {})
    task = tasks.get(today)

    if not task:
        await message.answer("🎯 На сегодня задачи еще нет. Загляните позже!")
        return

    u = register_user_activity(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    if today not in u.setdefault("opened_tasks", []):
        u["opened_tasks"].append(today)
        u["points"] = u.get("points", 0) + 5
        await save_db()

    task["views"] = task.get("views", 0) + 1
    await save_db()

    ratings = task.get("ratings", {})
    count = len(ratings)
    avg = round(sum(ratings.values()) / count, 1) if count > 0 else 0.0

    caption = (
        f"🎯 **Задача дня #{today}**\n\n"
        f"{task.get('caption', '')}\n\n"
        f"🔥 Твой streak: **{u.get('streak', 1)} дней**\n"
        f"⭐ Средняя оценка: **{avg}/5** (Всего: {count})"
    )

    await message.answer_photo(
        photo=task.get("photo_file_id"),
        caption=caption,
        reply_markup=get_task_user_keyboard(today, message.from_user.id),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("rate_task_"))
async def rate_daily_task(callback: CallbackQuery):
    parts = callback.data.split("_")
    date_str = parts[2]
    val = int(parts[3])
    u_str = str(callback.from_user.id)

    task = DB_CACHE.get("daily_tasks", {}).get(date_str)
    if not task:
        await callback.answer("Задача не найдена.", show_alert=True)
        return

    ratings = task.setdefault("ratings", {})
    ratings[u_str] = val
    await save_db()

    u = register_user_activity(callback.from_user.id)
    u["points"] = u.get("points", 0) + 2
    await save_db()

    await callback.answer(f"Спасибо! Ваша оценка: {val} ⭐", show_alert=True)
    
    count = len(ratings)
    avg = round(sum(ratings.values()) / count, 1) if count > 0 else 0.0
    
    caption = (
        f"🎯 **Задача дня #{date_str}**\n\n"
        f"{task.get('caption', '')}\n\n"
        f"🔥 Твой streak: **{u.get('streak', 1)} дней**\n"
        f"⭐ Средняя оценка: **{avg}/5** (Всего: {count})"
    )

    try:
        await callback.message.edit_caption(
            caption=caption,
            reply_markup=get_task_user_keyboard(date_str, callback.from_user.id),
            parse_mode="Markdown"
        )
    except Exception:
        pass

@router.callback_query(F.data.startswith("task_hint_"))
async def show_task_hint(callback: CallbackQuery):
    parts = callback.data.split("_")
    hint_num = parts[2]
    date_str = parts[3]

    task = DB_CACHE.get("daily_tasks", {}).get(date_str)
    if not task: return

    hint_text = task.get(f"hint{hint_num}")
    if hint_text:
        await callback.message.answer(f"💡 **Подсказка {hint_num}:**\n{hint_text}", parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data.startswith("task_solution_"))
async def show_task_solution(callback: CallbackQuery):
    date_str = callback.data.replace("task_solution_", "")
    task = DB_CACHE.get("daily_tasks", {}).get(date_str)
    if not task: return

    sol_text = task.get("solution")
    if sol_text:
        await callback.message.answer(f"✅ **Решение:**\n{sol_text}", parse_mode="Markdown")
    await callback.answer()

# --- АДМИН: УПРАВЛЕНИЕ ЗАДАЧАМИ ДНЯ ---

@router.callback_query(F.data == "admin_daily_task")
async def admin_daily_task_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить задачу", callback_data="dt_add")],
        [InlineKeyboardButton(text="📊 Статистика задачи", callback_data="dt_stats")],
        [InlineKeyboardButton(text="🗑 Удалить задачу", callback_data="dt_delete")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu_cb")]
    ])
    await callback.message.answer("🎯 **Управление Задачей Дня**", reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data == "dt_add")
async def dt_add_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.set_state(DailyTaskStates.waiting_for_photo)
    await callback.message.answer("Отправьте ФОТО для задачи дня:")

@router.message(DailyTaskStates.waiting_for_photo, F.photo)
async def dt_process_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_id)
    await state.set_state(DailyTaskStates.waiting_for_caption)
    await message.answer("Отправьте описание/условие задачи:")

@router.message(DailyTaskStates.waiting_for_caption)
async def dt_process_caption(message: Message, state: FSMContext):
    await state.update_data(caption=message.text)
    await state.set_state(DailyTaskStates.waiting_for_hint1)
    await message.answer("Введите **Подсказку 1** (или отправьте `-` если не требуется):")

@router.message(DailyTaskStates.waiting_for_hint1)
async def dt_process_hint1(message: Message, state: FSMContext):
    hint1 = "" if message.text.strip() == "-" else message.text
    await state.update_data(hint1=hint1)
    await state.set_state(DailyTaskStates.waiting_for_hint2)
    await message.answer("Введите **Подсказку 2** (или отправьте `-` если не требуется):")

@router.message(DailyTaskStates.waiting_for_hint2)
async def dt_process_hint2(message: Message, state: FSMContext):
    hint2 = "" if message.text.strip() == "-" else message.text
    await state.update_data(hint2=hint2)
    await state.set_state(DailyTaskStates.waiting_for_solution)
    await message.answer("Введите **Решение задачи** (или отправьте `-` если не требуется):")

@router.message(DailyTaskStates.waiting_for_solution)
async def dt_process_solution(message: Message, state: FSMContext):
    sol = "" if message.text.strip() == "-" else message.text
    await state.update_data(solution=sol)
    await state.set_state(DailyTaskStates.waiting_for_date)
    today = get_now_date_str()
    await message.answer(f"Введите дату задачи в формате YYYY-MM-DD (или отправьте `-` для сегодняшней даты `{today}`):")

@router.message(DailyTaskStates.waiting_for_date)
async def dt_process_date(message: Message, state: FSMContext):
    date_str = message.text.strip()
    if date_str == "-":
        date_str = get_now_date_str()

    data = await state.get_data()
    tasks = DB_CACHE.setdefault("daily_tasks", {})

    if date_str in tasks:
        await state.update_data(target_date=date_str)
        await state.set_state(DailyTaskStates.confirm_overwrite)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Заменить", callback_data="confirm_dt_overwrite"),
             InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_dt_overwrite")]
        ])
        await message.answer(f"⚠️ На дату `{date_str}` уже есть задача. Заменить?", reply_markup=kb, parse_mode="Markdown")
        return

    await save_daily_task_data(date_str, data)
    await state.clear()
    await message.answer(f"✅ Задача успешно сохранена на `{date_str}`!", parse_mode="Markdown")

async def save_daily_task_data(date_str: str, data: dict):
    task_obj = {
        "id": str(uuid.uuid4()),
        "date": date_str,
        "photo_file_id": data.get("photo_file_id"),
        "caption": data.get("caption"),
        "hint1": data.get("hint1"),
        "hint2": data.get("hint2"),
        "solution": data.get("solution"),
        "created_at": datetime.datetime.now(TIMEZONE).isoformat(),
        "ratings": {},
        "views": 0
    }
    DB_CACHE.setdefault("daily_tasks", {})[date_str] = task_obj
    await save_db()

@router.callback_query(F.data == "confirm_dt_overwrite")
async def dt_overwrite_confirm(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    data = await state.get_data()
    date_str = data.get("target_date")
    await save_daily_task_data(date_str, data)
    await state.clear()
    await callback.message.answer(f"✅ Задача перезаписана на `{date_str}`!", parse_mode="Markdown")

@router.callback_query(F.data == "cancel_dt_overwrite")
async def dt_overwrite_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.")

@router.callback_query(F.data == "dt_stats")
async def dt_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    today = get_now_date_str()
    task = DB_CACHE.get("daily_tasks", {}).get(today)

    if not task:
        await callback.answer("На сегодня нет задачи.", show_alert=True)
        return

    ratings = task.get("ratings", {})
    count = len(ratings)
    avg = round(sum(ratings.values()) / count, 2) if count > 0 else 0.0

    dist = {i: 0 for i in range(1, 6)}
    for r in ratings.values():
        dist[r] = dist.get(r, 0) + 1

    text = (
        f"📊 **Статистика задачи дня ({today}):**\n\n"
        f"👁 Просмотров: {task.get('views', 0)}\n"
        f"👥 Всего оценили: {count}\n"
        f"⭐ Средняя оценка: {avg}/5\n\n"
        f"**Распределение:**\n"
        f"⭐ 5: {dist[5]}\n"
        f"⭐ 4: {dist[4]}\n"
        f"⭐ 3: {dist[3]}\n"
        f"⭐ 2: {dist[2]}\n"
        f"⭐ 1: {dist[1]}"
    )
    await callback.message.answer(text, parse_mode="Markdown")

# ==========================================
# 8. MUST-READ & FAVORITES
# ==========================================

@router.message(F.text == "⭐ Must-read")
async def show_must_read(message: Message):
    must_ids = DB_CACHE.get("must_read", [])
    if not must_ids:
        await message.answer("⭐ Раздел Must-read пока пуст.")
        return

    kb = []
    for f_id in must_ids:
        f = find_file_by_id(f_id)
        if f:
            kb.append([InlineKeyboardButton(text=f"📄 {f.get('title')}", callback_data=f"get_file_{f_id}")])

    await message.answer("⭐ **Рекомендуемые материалы (Must-read):**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@router.callback_query(F.data.startswith("toggle_must_"))
async def toggle_must_read(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    file_id = callback.data.replace("toggle_must_", "")

    must_list = DB_CACHE.setdefault("must_read", [])
    if file_id in must_list:
        must_list.remove(file_id)
        msg = "☆ Файл убран из Must-read."
    else:
        must_list.append(file_id)
        msg = "⭐ Файл добавлен в Must-read."

    await save_db()
    await callback.answer(msg, show_alert=True)

@router.message(Command("favorites"))
@router.message(F.text == "❤️ Избранное")
async def show_favorites(message: Message):
    u = register_user_activity(message.from_user.id)
    fav_ids = u.get("favorites", [])

    if not fav_ids:
        await message.answer("❤️ У вас пока нет избранных файлов.")
        return

    kb = []
    for f_id in fav_ids:
        f = find_file_by_id(f_id)
        if f:
            kb.append([InlineKeyboardButton(text=f"📄 {f.get('title')}", callback_data=f"get_file_{f_id}")])

    await message.answer("❤️ **Ваше избранное:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@router.callback_query(F.data.startswith("fav_add_"))
async def fav_add(callback: CallbackQuery):
    file_id = callback.data.replace("fav_add_", "")
    u = register_user_activity(callback.from_user.id)
    favs = u.setdefault("favorites", [])

    if file_id not in favs:
        favs.append(file_id)
        await save_db()

    await callback.answer("❤️ Добавлено в избранное!", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=get_file_actions_keyboard(file_id, callback.from_user.id))

@router.callback_query(F.data.startswith("fav_rem_"))
async def fav_remove(callback: CallbackQuery):
    file_id = callback.data.replace("fav_rem_", "")
    u = register_user_activity(callback.from_user.id)
    favs = u.setdefault("favorites", [])

    if file_id in favs:
        favs.remove(file_id)
        await save_db()

    await callback.answer("💔 Удалено из избранного.", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=get_file_actions_keyboard(file_id, callback.from_user.id))

# ==========================================
# 9. SEARCH, RATING & CHALLENGES
# ==========================================

@router.message(F.text == "🔎 Поиск")
async def search_instruction(message: Message):
    await message.answer("🔎 Введите название, категорию или тег для поиска (например: `geometry` или `#imo`):")

@router.message(Command("rating"))
@router.message(F.text == "🏆 Рейтинг")
async def show_rating(message: Message):
    users = list(DB_CACHE.get("users", {}).values())
    sorted_users = sorted(users, key=lambda x: x.get("points", 0), reverse=True)[:10]

    if not sorted_users:
        await message.answer("🏆 Список лидеров пока пуст.")
        return

    text = "🏆 **Топ участников библиотеки Matham:**\n\n"
    medals = ["🥇", "🥈", "🥉"]

    for idx, u in enumerate(sorted_users):
        badge = medals[idx] if idx < 3 else f"{idx + 1}."
        name = u.get("full_name") or u.get("username") or "Пользователь"
        text += f"{badge} **{name}** — {u.get('points', 0)} очков (🔥 {u.get('streak', 0)}д.)\n"

    u_curr = register_user_activity(message.from_user.id)
    text += f"\nВаш результат: **{u_curr.get('points', 0)} очков** | 🔥 **{u_curr.get('streak', 0)} дней**"

    await message.answer(text, parse_mode="Markdown")

@router.message(Command("surprise"))
async def surprise_file(message: Message):
    all_files = get_all_files_unique()
    if not all_files:
        await message.answer("В библиотеке пока нет файлов.")
        return

    f = random.choice(all_files)
    caption = f"🎲 **Случайный материал:** {f.get('title')}"
    await message.answer_document(
        document=f.get("file_id"),
        caption=caption,
        reply_markup=get_file_actions_keyboard(f.get("id"), message.from_user.id),
        parse_mode="Markdown"
    )

@router.message(Command("challenge"))
@router.message(F.text == "🎲 Случайный материал")
async def challenge_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Easy", callback_data="ch_easy"),
         InlineKeyboardButton(text="🟡 Medium", callback_data="ch_medium")],
        [InlineKeyboardButton(text="🔴 Hard", callback_data="ch_hard"),
         InlineKeyboardButton(text="🔥 IMO", callback_data="ch_imo")],
        [InlineKeyboardButton(text="🎲 Любой уровень", callback_data="ch_any")]
    ])
    await message.answer("🎲 Выберите уровень сложности для случайного материала:", reply_markup=kb)

@router.callback_query(F.data.startswith("ch_"))
async def process_challenge(callback: CallbackQuery):
    diff = callback.data.replace("ch_", "")
    all_files = get_all_files_unique()

    if diff != "any":
        filtered = [f for f in all_files if f.get("difficulty") == diff]
    else:
        filtered = all_files

    if not filtered:
        await callback.answer("Материалов с такой сложностью не найдено.", show_alert=True)
        return

    f = random.choice(filtered)
    await callback.answer()
    caption = f"🎯 **Challenge ({f.get('difficulty', 'medium').upper()}):** {f.get('title')}"
    await callback.message.answer_document(
        document=f.get("file_id"),
        caption=caption,
        reply_markup=get_file_actions_keyboard(f.get("id"), callback.from_user.id),
        parse_mode="Markdown"
    )

@router.message(F.text & ~F.text.startswith("/"))
async def handle_search_query(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        return

    query = message.text.lower().strip()
    if len(query) < 2:
        return

    words = query.split()
    all_files = get_all_files_unique()
    matched = []

    for f in all_files:
        title = f.get("title", "").lower()
        tags = [t.lower() for t in f.get("tags", [])]
        
        score = 0
        for w in words:
            if w in title or any(w in t for t in tags):
                score += 1

        if score > 0:
            matched.append((score, f))

    matched.sort(key=lambda x: x[0], reverse=True)

    if not matched:
        await message.answer("🔍 Ничего не найдено по вашему запросу.")
        return

    kb = []
    for score, f in matched[:10]:
        kb.append([InlineKeyboardButton(text=f"📄 {f.get('title')}", callback_data=f"get_file_{f.get('id')}")])

    await message.answer(f"🔍 **Результаты поиска ({len(matched)}):**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

# ==========================================
# 10. ADMIN PANEL & BROADCAST
# ==========================================

@router.message(Command("admin"))
@router.message(F.text == "👑 Админ-панель")
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return
    await message.answer("👑 **Админ-панель**", reply_markup=get_admin_keyboard(), parse_mode="Markdown")

@router.message(Command("stats"))
@router.callback_query(F.data == "admin_stats")
async def show_stats(event: Message | CallbackQuery):
    user_id = event.from_user.id
    if user_id not in ADMIN_IDS:
        if isinstance(event, CallbackQuery):
            await event.answer("Доступ запрещен.", show_alert=True)
        return

    users = DB_CACHE.get("users", {})
    all_files = get_all_files_unique()
    must_count = len(DB_CACHE.get("must_read", []))
    links_count = len(DB_CACHE.get("links", {}))
    tasks_count = len(DB_CACHE.get("daily_tasks", {}))

    text = (
        f"📊 **Системная статистика:**\n\n"
        f"👥 Всего пользователей: {len(users)}\n"
        f"📚 Всего файлов: {len(all_files)}\n"
        f"⭐ Must-read файлов: {must_count}\n"
        f"🔗 Ссылок: {links_count}\n"
        f"🎯 Задач дня: {tasks_count}\n"
    )

    if isinstance(event, CallbackQuery):
        await event.message.answer(text, parse_mode="Markdown")
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown")

@router.message(Command("broadcast"))
@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast(event: Message | CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    if user_id not in ADMIN_IDS: return

    await state.set_state(BroadcastStates.waiting_for_message)
    msg = "📢 Отправьте сообщение для рассылки всем пользователям:"
    if isinstance(event, CallbackQuery):
        await event.message.answer(msg)
        await event.answer()
    else:
        await event.answer(msg)

@router.message(BroadcastStates.waiting_for_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    await state.update_data(broadcast_msg_id=message.message_id, broadcast_chat_id=message.chat.id)
    await state.set_state(BroadcastStates.confirm_send)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить", callback_data="confirm_bc"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_bc")]
    ])
    await message.answer("Запустить рассылку для всех пользователей?", reply_markup=kb)

@router.callback_query(F.data == "confirm_bc", BroadcastStates.confirm_send)
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return

    data = await state.get_data()
    await state.clear()

    users = DB_CACHE.get("users", {})
    success = 0
    errors = 0

    await callback.message.answer("🚀 Рассылка запущена...")

    for u_id in list(users.keys()):
        try:
            await bot.copy_message(
                chat_id=int(u_id),
                from_chat_id=data.get("broadcast_chat_id"),
                message_id=data.get("broadcast_msg_id")
            )
            success += 1
            await asyncio.sleep(0.05)
        except (TelegramForbiddenError, TelegramBadRequest):
            errors += 1
        except TelegramAPIError:
            errors += 1
        except Exception:
            errors += 1

    await callback.message.answer(f"📢 **Рассылка завершена!**\n\n✅ Успешно: {success}\n❌ Ошибок: {errors}", parse_mode="Markdown")

@router.callback_query(F.data == "cancel_bc")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.")

# --- АДМИН: ДОБАВЛЕНИЕ ФАЙЛОВ ---

@router.callback_query(F.data == "admin_add_file")
async def add_file_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.set_state(AddFileStates.waiting_for_file)
    await callback.message.answer("Отправьте документ (файл) для добавления:")

@router.message(AddFileStates.waiting_for_file, F.document)
async def add_file_doc(message: Message, state: FSMContext):
    await state.update_data(file_id=message.document.file_id, file_name=message.document.file_name)
    await state.set_state(AddFileStates.waiting_for_title)
    await message.answer(f"Введите название для файла (по умолчанию: `{message.document.file_name}`):", parse_mode="Markdown")

@router.message(AddFileStates.waiting_for_title)
async def add_file_title(message: Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(title=title)
    await state.set_state(AddFileStates.waiting_for_category)
    await message.answer("Выберите категорию:", reply_markup=get_categories_keyboard("addcat_"))

@router.callback_query(F.data.startswith("addcat_"))
async def add_file_cat(callback: CallbackQuery, state: FSMContext):
    cat_name = callback.data.replace("addcat_", "")
    await state.update_data(category=cat_name)
    await state.set_state(AddFileStates.waiting_for_tags)
    await callback.message.answer("Введите теги через пробел (напр. `#geometry #imo`) или `-` если без тегов:")

@router.message(AddFileStates.waiting_for_tags)
async def add_file_tags(message: Message, state: FSMContext):
    raw_tags = message.text.strip()
    tags = [] if raw_tags == "-" else [t if t.startswith("#") else f"#{t}" for t in raw_tags.split()]
    await state.update_data(tags=tags)

    await state.set_state(AddFileStates.waiting_for_difficulty)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Easy", callback_data="adddiff_easy"),
         InlineKeyboardButton(text="🟡 Medium", callback_data="adddiff_medium")],
        [InlineKeyboardButton(text="🔴 Hard", callback_data="adddiff_hard"),
         InlineKeyboardButton(text="🔥 IMO", callback_data="adddiff_imo")]
    ])
    await message.answer("Выберите сложность материала:", reply_markup=kb)

@router.callback_query(F.data.startswith("adddiff_"))
async def add_file_finish(callback: CallbackQuery, state: FSMContext):
    diff = callback.data.replace("adddiff_", "")
    data = await state.get_data()

    file_obj = {
        "id": str(uuid.uuid4()),
        "file_id": data.get("file_id"),
        "title": data.get("title"),
        "tags": data.get("tags", []),
        "difficulty": diff,
        "views": 0
    }

    cat = data.get("category")
    DB_CACHE.setdefault("categories", {}).setdefault(cat, []).append(file_obj)
    await save_db()

    await state.clear()
    await callback.message.answer(f"✅ Файл **{file_obj['title']}** успешно добавлен в категорию **{cat}**!", parse_mode="Markdown")

# ==========================================
# 11. WEB SERVER & MAIN
# ==========================================

async def handle_ping(request):
    return web.Response(text="Matham Bot is running smoothly.")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def set_bot_commands():
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="task", description="Задача дня"),
        BotCommand(command="favorites", description="Избранное"),
        BotCommand(command="rating", description="Рейтинг"),
        BotCommand(command="challenge", description="Случайный челлендж"),
        BotCommand(command="surprise", description="Случайный файл"),
        BotCommand(command="admin", description="Админ-панель"),
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="broadcast", description="Рассылка")
    ]
    await bot.set_my_commands(commands)

async def main():
    await init_db()
    await set_bot_commands()
    
    asyncio.create_task(start_web_server())

    logger.info("Bot started successfully!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
