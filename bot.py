import os
import copy
import uuid
import random
import logging
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramAPIError
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient

# ==========================================
#                  CONFIG
# ==========================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger("MathamBot")

TOKEN = os.environ.get("BOT_TOKEN", "")

ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "matham_bot")
DB_DOC_ID = "catalog_main"

TIMEZONE_YEREVAN = ZoneInfo("Asia/Yerevan")

mongo_client = AsyncIOMotorClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]
db_collection = mongo_db["catalog"]

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Базовая структура по умолчанию
DEFAULT_DATABASE_STRUCTURE = {
    "categories": {
        "geometry": {
            "title": "📐 Геометрия",
            "blocks": {
                "transformations": {
                    "title": "🔄 Преобразования плоскости",
                    "topics": {
                        "inversion": {"title": "Инверсия", "files": []},
                        "homothety": {"title": "Гомотетия и поворот", "files": []},
                        "symmetry": {"title": "Симметрия", "files": []}
                    }
                },
                "analytic": {
                    "title": "📊 Аналитические методы",
                    "topics": {
                        "complex": {"title": "Комплексные числа", "files": []},
                        "barycentric": {"title": "Барицентрические координаты", "files": []},
                        "vectors": {"title": "Векторный метод", "files": []}
                    }
                },
                "books_geo": {
                    "title": "📚 Книги и сборники",
                    "topics": {
                        "classics": {"title": "Классические учебники", "files": []},
                        "problembooks": {"title": "Задачники и сборники", "files": []}
                    }
                }
            }
        },
        "algebra": {
            "title": "🧮 Алгебра",
            "blocks": {
                "polynomials": {
                    "title": "📐 Многочлены",
                    "topics": {
                        "roots": {"title": "Теорема Виета и корни", "files": []},
                        "divisibility": {"title": "Деление и теорема Безу", "files": []}
                    }
                },
                "functional_eq": {
                    "title": "⚙️ Функциональные уравнения",
                    "topics": {
                        "substitution": {"title": "Метод подстановок", "files": []},
                        "cauchy_eq": {"title": "Уравнение Коши", "files": []}
                    }
                },
                "books_alg": {
                    "title": "📚 Книги и сборники",
                    "topics": {
                        "classics": {"title": "Классическая алгебра", "files": []},
                        "problembooks": {"title": "Задачники", "files": []}
                    }
                }
            }
        },
        "number_theory": {
            "title": "🔢 Теория чисел",
            "blocks": {
                "divisibility": {
                    "title": "🔍 Делимость и сравнения",
                    "topics": {
                        "congruences": {"title": "Сравнения по модулю", "files": []},
                        "euler_fermat": {"title": "Теоремы Эйлера и Ферма", "files": []}
                    }
                },
                "advanced_nt": {
                    "title": "🚀 Продвинутые методы",
                    "topics": {
                        "lte": {"title": "LTE (Lifting The Exponent)", "files": []},
                        "diophantine": {"title": "Диофантовы уравнения", "files": []}
                    }
                },
                "books_nt": {
                    "title": "📚 Книги и сборники",
                    "topics": {
                        "classics": {"title": "Учебники по ТЧ", "files": []},
                        "olympiad": {"title": "Олимпиадная теория чисел", "files": []}
                    }
                }
            }
        },
        "inequalities": {
            "title": "⚖️ Неравенства",
            "blocks": {
                "classical": {
                    "title": "📐 Классические",
                    "topics": {
                        "am_gm": {"title": "AM-GM (Коши о средних)", "files": []},
                        "cauchy_schwarz": {"title": "Коши-Буняковский-Шварц", "files": []}
                    }
                },
                "advanced_ineq": {
                    "title": "🔥 Продвинутые",
                    "topics": {
                        "jensen": {"title": "Йенсен и выпуклые функции", "files": []},
                        "uvw": {"title": "Метод uvw", "files": []}
                    }
                },
                "books_ineq": {
                    "title": "📚 Книги и сборники",
                    "topics": {
                        "compilations": {"title": "Сборники неравенств", "files": []}
                    }
                }
            }
        },
        "higher_math": {
            "title": "🎓 Высшая математика / Матанализ",
            "blocks": {
                "calculus": {
                    "title": "📈 Математический анализ",
                    "topics": {
                        "limits": {"title": "Пределы и непрерывность", "files": []},
                        "derivatives": {"title": "Производная и интеграл", "files": []},
                        "series": {"title": "Ряды и последовательности", "files": []}
                    }
                },
                "linear_algebra": {
                    "title": "🔢 Линейная алгебра",
                    "topics": {
                        "matrices": {"title": "Матрицы и определители", "files": []},
                        "vector_spaces": {"title": "Векторные пространства", "files": []}
                    }
                },
                "diff_eq": {
                    "title": "🌀 Дифференциальные уравнения",
                    "topics": {
                        "first_order": {"title": "Уравнения 1-го порядка", "files": []},
                        "systems": {"title": "Системы ДУ", "files": []}
                    }
                },
                "books_hm": {
                    "title": "📚 Книги и фундаментальные труды",
                    "topics": {
                        "textbooks": {"title": "Учебники ВУЗов", "files": []},
                        "problembooks": {"title": "Сборники задач (Демидович и др.)", "files": []}
                    }
                }
            }
        }
    },
    "daily_tasks": {},
    "links": [],
    "users": {},
    "suggestions": []
}

DATABASE = {}

# ==========================================
#         DATABASE & MIGRATION
# ==========================================
def migrate_database_data(raw_data: dict) -> dict:
    """Обеспечивает обратную совместимость со старой структурой MongoDB."""
    data = copy.deepcopy(raw_data) if raw_data else {}

    # Если база хранилась в старом формате, где верхний уровень — это сами категории
    if "categories" not in data:
        old_categories = {}
        for key in ["geometry", "algebra", "number_theory", "inequalities", "higher_math"]:
            if key in data:
                old_categories[key] = data.pop(key)
        for remaining_key, val in list(data.items()):
            if isinstance(val, dict) and "blocks" in val:
                old_categories[remaining_key] = data.pop(remaining_key)

        data = {
            "categories": old_categories if old_categories else copy.deepcopy(DEFAULT_DATABASE_STRUCTURE["categories"]),
            "daily_tasks": data.get("daily_tasks", {}),
            "links": data.get("links", []),
            "users": data.get("users", {}),
            "suggestions": data.get("suggestions", [])
        }

    # Проверка наличия всех ключевых секций
    for section, default_val in DEFAULT_DATABASE_STRUCTURE.items():
        if section not in data:
            data[section] = copy.deepcopy(default_val)

    # Проверка каждого файла на наличие полей: id, tags, difficulty, must_read, views
    for cat_data in data["categories"].values():
        for b_data in cat_data.get("blocks", {}).values():
            for t_data in b_data.get("topics", {}).values():
                for f in t_data.get("files", []):
                    if "id" not in f:
                        f["id"] = uuid.uuid4().hex[:8]
                    if "tags" not in f:
                        f["tags"] = []
                    if "difficulty" not in f:
                        f["difficulty"] = "medium"
                    if "must_read" not in f:
                        f["must_read"] = False
                    if "views" not in f:
                        f["views"] = 0

    return data


async def load_db() -> dict:
    """Загружает базу из MongoDB, при необходимости мигрирует и сохраняет."""
    doc = await db_collection.find_one({"_id": DB_DOC_ID})
    if doc is None:
        logger.info("MongoDB пуста. Инициализирую базу по умолчанию...")
        data = copy.deepcopy(DEFAULT_DATABASE_STRUCTURE)
        await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": data}}, upsert=True)
        return data

    raw_data = doc.get("data", {})
    migrated_data = migrate_database_data(raw_data)
    if migrated_data != raw_data:
        await save_db(migrated_data)
    return migrated_data


async def save_db(db_data: dict):
    """Асинхронно сохраняет базу в MongoDB."""
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {"data": db_data}},
        upsert=True
    )


# ==========================================
#             HELPERS & TIMEZONE
# ==========================================
def get_now_yerevan() -> datetime:
    return datetime.now(TIMEZONE_YEREVAN)


def get_today_str() -> str:
    return get_now_yerevan().strftime("%Y-%m-%d")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def track_user(user: types.User) -> dict:
    """Регистрирует или обновляет данные пользователя в MongoDB."""
    uid = str(user.id)
    today = get_today_str()
    users = DATABASE.setdefault("users", {})

    if uid not in users:
        users[uid] = {
            "id": user.id,
            "username": user.username or "",
            "full_name": user.full_name or "Anonymous",
            "streak": 1,
            "last_active_date": today,
            "points": 5,
            "favorites": [],
            "opened_files": [],
            "rated_tasks": {}
        }
    else:
        u = users[uid]
        u["username"] = user.username or u.get("username", "")
        u["full_name"] = user.full_name or u.get("full_name", "")

        last_date = u.get("last_active_date")
        if last_date != today:
            if last_date:
                try:
                    last_dt = datetime.strptime(last_date, "%Y-%m-%d").date()
                    curr_dt = datetime.strptime(today, "%Y-%m-%d").date()
                    diff = (curr_dt - last_dt).days
                    if diff == 1:
                        u["streak"] = u.get("streak", 0) + 1
                        u["points"] = u.get("points", 0) + 10
                    else:
                        u["streak"] = 1
                        u["points"] = u.get("points", 0) + 5
                except Exception:
                    u["streak"] = 1
            else:
                u["streak"] = 1
            u["last_active_date"] = today

    return users[uid]


def add_user_points(user_id: int, points: int):
    uid = str(user_id)
    if uid in DATABASE.get("users", {}):
        DATABASE["users"][uid]["points"] = DATABASE["users"][uid].get("points", 0) + points


def find_file_by_id(file_uid: str):
    """Ищет файл по уникальному внутреннему ID в каталоге."""
    for cat_k, cat_v in DATABASE.get("categories", {}).items():
        for blk_k, blk_v in cat_v.get("blocks", {}).items():
            for top_k, top_v in blk_v.get("topics", {}).items():
                for f in top_v.get("files", []):
                    if f.get("id") == file_uid:
                        return f, cat_k, blk_k, top_k
    return None, None, None, None


def get_all_files():
    """Возвращает плоский список всех файлов со структурой пути."""
    files = []
    for cat_k, cat_v in DATABASE.get("categories", {}).items():
        for blk_k, blk_v in cat_v.get("blocks", {}).items():
            for top_k, top_v in blk_v.get("topics", {}).items():
                for f in top_v.get("files", []):
                    files.append({
                        "file": f,
                        "cat_k": cat_k,
                        "blk_k": blk_k,
                        "top_k": top_k,
                        "cat_title": cat_v.get("title", ""),
                        "blk_title": blk_v.get("title", ""),
                        "top_title": top_v.get("title", "")
                    })
    return files


def format_difficulty_badge(diff: str) -> str:
    badges = {
        "easy": "🟢 Easy",
        "medium": "🟡 Medium",
        "hard": "🔴 Hard",
        "imo": "🔥 IMO"
    }
    return badges.get(diff.lower(), "🟡 Medium")


# ==========================================
#               KEYBOARDS
# ==========================================
def get_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = [
        [
            InlineKeyboardButton(text="📚 Каталог", callback_data="menu:categories"),
            InlineKeyboardButton(text="🎯 Задача дня", callback_data="menu:task")
        ],
        [
            InlineKeyboardButton(text="⭐ Must-read", callback_data="menu:must_read"),
            InlineKeyboardButton(text="❤️ Избранное", callback_data="menu:favorites")
        ],
        [
            InlineKeyboardButton(text="🎲 Random Challenge", callback_data="menu:challenge"),
            InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating")
        ],
        [
            InlineKeyboardButton(text="🔗 Ссылки", callback_data="menu:links"),
            InlineKeyboardButton(text="📤 Предложить файл", callback_data="menu:suggest")
        ]
    ]
    if is_admin(user_id):
        builder.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin:menu")])

    return InlineKeyboardMarkup(inline_keyboard=builder)


def get_categories_keyboard() -> InlineKeyboardMarkup:
    builder = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        builder.append([InlineKeyboardButton(text=cat_data["title"], callback_data=f"cat:{cat_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def get_admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Добавить файл", callback_data="adm:add_file"),
            InlineKeyboardButton(text="✏️ Управление файлами", callback_data="adm:files_nav")
        ],
        [
            InlineKeyboardButton(text="🎯 Задача дня", callback_data="adm:dt_menu"),
            InlineKeyboardButton(text="⭐ Must-read", callback_data="adm:mr_menu")
        ],
        [
            InlineKeyboardButton(text="🔗 Ссылки", callback_data="adm:links_menu"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")
        ],
        [
            InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast")
        ],
        [
            InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu:main")
        ]
    ])


def get_task_user_keyboard(date_str: str, has_hint1: bool, has_hint2: bool, has_sol: bool) -> InlineKeyboardMarkup:
    hint_row = []
    if has_hint1:
        hint_row.append(InlineKeyboardButton(text="💡 Подсказка 1", callback_data=f"dt_h1:{date_str}"))
    if has_hint2:
        hint_row.append(InlineKeyboardButton(text="💡 Подсказка 2", callback_data=f"dt_h2:{date_str}"))
    if has_sol:
        hint_row.append(InlineKeyboardButton(text="✅ Решение", callback_data=f"dt_sol:{date_str}"))

    stars_row = [
        InlineKeyboardButton(text=f"⭐ {i}", callback_data=f"dt_vote:{date_str}:{i}") for i in range(1, 6)
    ]

    kb = []
    if hint_row:
        kb.append(hint_row)
    kb.append(stars_row)
    kb.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ==========================================
#               FSM STATES
# ==========================================
class FileUpload(StatesGroup):
    selecting_path = State()
    waiting_for_caption = State()
    waiting_for_tags = State()
    waiting_for_difficulty = State()


class FileEditState(StatesGroup):
    waiting_new_caption = State()
    waiting_new_tags = State()


class DailyTaskCreate(StatesGroup):
    waiting_photo = State()
    waiting_caption = State()
    waiting_date = State()
    confirm_overwrite = State()
    waiting_hint1 = State()
    waiting_hint2 = State()
    waiting_solution = State()


class BroadcastState(StatesGroup):
    waiting_message = State()
    confirm = State()


class SuggestionState(StatesGroup):
    waiting_content = State()


class LinkAddState(StatesGroup):
    waiting_title = State()
    waiting_url = State()


# ==========================================
#         DAILY TASK ENGINE & VOTING
# ==========================================
def get_daily_task_for_date(date_str: str) -> dict | None:
    return DATABASE.get("daily_tasks", {}).get(date_str)


def compute_task_rating(task: dict) -> tuple[float, int, dict]:
    ratings = task.get("ratings", {})
    if not ratings:
        return 0.0, 0, {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    total_votes = len(ratings)
    avg = sum(ratings.values()) / total_votes
    distribution = {i: 0 for i in range(1, 6)}
    for score in ratings.values():
        if score in distribution:
            distribution[score] += 1
    return round(avg, 1), total_votes, distribution


async def render_daily_task_view(target, date_str: str, user_id: int):
    """Показывает задачу дня пользователю."""
    task = get_daily_task_for_date(date_str)
    if not task:
        text = f"🎯 **Задача дня на {date_str}**\n\nНа этот день задача пока не опубликована. Загляните позже! ⏳"
        if isinstance(target, types.CallbackQuery):
            await target.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:main")]
            ]))
            await target.answer()
        else:
            await target.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:main")]
            ]))
        return

    # Увеличение просмотров
    task["views"] = task.get("views", 0) + 1
    u = track_user(target.from_user)
    add_user_points(user_id, 2)
    await save_db(DATABASE)

    avg_score, total_votes, _ = compute_task_rating(task)
    user_vote = task.get("ratings", {}).get(str(user_id))

    streak_text = f"🔥 Твой streak: **{u.get('streak', 1)}** дн."
    vote_text = f"\nТвоя оценка: ⭐ **{user_vote}/5**" if user_vote else ""
    caption_text = (
        f"🎯 **Задача дня — {date_str}**\n\n"
        f"{task.get('caption', '')}\n\n"
        f"⭐ Средняя оценка: **{avg_score}/5** (👥 Оценили: {total_votes}){vote_text}\n"
        f"{streak_text}"
    )

    kb = get_task_user_keyboard(
        date_str=date_str,
        has_hint1=bool(task.get("hint_1")),
        has_hint2=bool(task.get("hint_2")),
        has_sol=bool(task.get("solution"))
    )

    if isinstance(target, types.CallbackQuery):
        await target.message.answer_photo(photo=task["photo_file_id"], caption=caption_text, reply_markup=kb)
        await target.answer()
    else:
        await target.answer_photo(photo=task["photo_file_id"], caption=caption_text, reply_markup=kb)


@dp.callback_query(F.data.startswith("dt_vote:"))
async def process_dt_vote(callback: types.CallbackQuery):
    _, date_str, score_str = callback.data.split(":")
    score = int(score_str)
    uid = str(callback.from_user.id)

    task = get_daily_task_for_date(date_str)
    if not task:
        return await callback.answer("❌ Задача не найдена.", show_alert=True)

    if "ratings" not in task:
        task["ratings"] = {}

    first_vote = uid not in task["ratings"]
    task["ratings"][uid] = score

    if first_vote:
        add_user_points(callback.from_user.id, 5)

    await save_db(DATABASE)

    avg_score, total_votes, _ = compute_task_rating(task)
    await callback.answer(f"✅ Твой голос ({score} ⭐) учтён!\nСредний балл: {avg_score}/5", show_alert=True)


@dp.callback_query(F.data.startswith("dt_h1:"))
async def process_dt_hint1(callback: types.CallbackQuery):
    date_str = callback.data.split(":")[1]
    task = get_daily_task_for_date(date_str)
    if not task or not task.get("hint_1"):
        return await callback.answer("Подсказка недоступна.", show_alert=True)
    await callback.message.answer(f"💡 **Подсказка 1 к задаче ({date_str}):**\n\n{task['hint_1']}")
    await callback.answer()


@dp.callback_query(F.data.startswith("dt_h2:"))
async def process_dt_hint2(callback: types.CallbackQuery):
    date_str = callback.data.split(":")[1]
    task = get_daily_task_for_date(date_str)
    if not task or not task.get("hint_2"):
        return await callback.answer("Подсказка недоступна.", show_alert=True)
    await callback.message.answer(f"💡 **Подсказка 2 к задаче ({date_str}):**\n\n{task['hint_2']}")
    await callback.answer()


@dp.callback_query(F.data.startswith("dt_sol:"))
async def process_dt_solution(callback: types.CallbackQuery):
    date_str = callback.data.split(":")[1]
    task = get_daily_task_for_date(date_str)
    if not task or not task.get("solution"):
        return await callback.answer("Решение недоступно.", show_alert=True)
    await callback.message.answer(f"✅ **Решение задачи ({date_str}):**\n\n{task['solution']}")
    await callback.answer()


# ==========================================
#         FILE VIEW & ACTIONS
# ==========================================
def make_file_card_keyboard(file_uid: str, user_id: int) -> InlineKeyboardMarkup:
    uid_str = str(user_id)
    user_favs = DATABASE.get("users", {}).get(uid_str, {}).get("favorites", [])
    is_fav = file_uid in user_favs

    fav_text = "💔 Из избранного" if is_fav else "❤️ В избранное"
    fav_cb = f"fav_rem:{file_uid}" if is_fav else f"fav_add:{file_uid}"

    kb = [
        [InlineKeyboardButton(text="📥 Скачать файл", callback_data=f"fdl:{file_uid}")],
        [InlineKeyboardButton(text=fav_text, callback_data=fav_cb)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:categories")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


@dp.callback_query(F.data.startswith("fdl:"))
async def handle_file_download(callback: types.CallbackQuery):
    file_uid = callback.data.split(":")[1]
    file_item, _, _, _ = find_file_by_id(file_uid)

    if not file_item:
        return await callback.answer("❌ Файл не найден или был удалён.", show_alert=True)

    file_item["views"] = file_item.get("views", 0) + 1
    track_user(callback.from_user)
    add_user_points(callback.from_user.id, 1)
    await save_db(DATABASE)

    await callback.answer("Отправляю файл... ⏳")
    diff_badge = format_difficulty_badge(file_item.get("difficulty", "medium"))
    tags_text = " ".join([f"#{t}" for t in file_item.get("tags", [])])

    cap = f"📄 **{file_item['caption']}**\nСложность: {diff_badge}"
    if tags_text:
        cap += f"\nТеги: {tags_text}"

    await callback.message.answer_document(
        document=file_item["file_id"],
        caption=cap
    )


@dp.callback_query(F.data.startswith("fav_add:"))
async def handle_fav_add(callback: types.CallbackQuery):
    file_uid = callback.data.split(":")[1]
    uid = str(callback.from_user.id)
    u = track_user(callback.from_user)

    if "favorites" not in u:
        u["favorites"] = []

    if file_uid not in u["favorites"]:
        u["favorites"].append(file_uid)
        await save_db(DATABASE)
        await callback.answer("❤️ Файл добавлен в избранное!", show_alert=False)
    else:
        await callback.answer("Файл уже в избранном.", show_alert=False)

    try:
        await callback.message.edit_reply_markup(reply_markup=make_file_card_keyboard(file_uid, callback.from_user.id))
    except Exception:
        pass


@dp.callback_query(F.data.startswith("fav_rem:"))
async def handle_fav_rem(callback: types.CallbackQuery):
    file_uid = callback.data.split(":")[1]
    uid = str(callback.from_user.id)
    u = track_user(callback.from_user)

    if "favorites" in u and file_uid in u["favorites"]:
        u["favorites"].remove(file_uid)
        await save_db(DATABASE)
        await callback.answer("💔 Файл удален из избранного.", show_alert=False)

    try:
        await callback.message.edit_reply_markup(reply_markup=make_file_card_keyboard(file_uid, callback.from_user.id))
    except Exception:
        pass


# ==========================================
#     ПОЛЬЗОВАТЕЛЬ: НАВИГАЦИЯ КАТАЛОГА
# ==========================================
@dp.callback_query(F.data.startswith("cat:"))
async def process_category_click(callback: types.CallbackQuery):
    cat_key = callback.data.split(":")[1]
    cat_data = DATABASE.get("categories", {}).get(cat_key)

    if not cat_data:
        return await callback.answer("Категория не найдена.", show_alert=True)

    builder = [
        [InlineKeyboardButton(text=b_data["title"], callback_data=f"blk:{cat_key}:{b_key}")]
        for b_key, b_data in cat_data.get("blocks", {}).items()
    ]
    builder.append([InlineKeyboardButton(text="⬅️ Все категории", callback_data="menu:categories")])

    await callback.message.edit_text(
        f"📁 Раздел **{cat_data['title']}**\nВыбери блок:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("blk:"))
async def process_block_click(callback: types.CallbackQuery):
    _, cat_key, b_key = callback.data.split(":")
    cat_data = DATABASE.get("categories", {}).get(cat_key, {})
    block_data = cat_data.get("blocks", {}).get(b_key)

    if not block_data:
        return await callback.answer("Блок не найден.", show_alert=True)

    builder = [
        [InlineKeyboardButton(text=f"• {t_data['title']}", callback_data=f"top:{cat_key}:{b_key}:{t_key}")]
        for t_key, t_data in block_data.get("topics", {}).items()
    ]
    builder.append([InlineKeyboardButton(text="⬅️ Назад к разделу", callback_data=f"cat:{cat_key}")])

    await callback.message.edit_text(
        f"📁 **{cat_data.get('title', '')}** ➔ **{block_data['title']}**\nВыбери тему:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("top:"))
async def process_topic_click(callback: types.CallbackQuery):
    _, cat_key, b_key, t_key = callback.data.split(":")
    topic_data = DATABASE.get("categories", {}).get(cat_key, {}).get("blocks", {}).get(b_key, {}).get("topics", {}).get(t_key)

    if not topic_data:
        return await callback.answer("Тема не найдена.", show_alert=True)

    files = topic_data.get("files", [])
    if not files:
        return await callback.answer("📁 В этой теме пока нет файлов.", show_alert=True)

    builder = []
    for f in files:
        f_id = f.get("id")
        mr_icon = "⭐ " if f.get("must_read") else "📄 "
        btn_title = mr_icon + (f['caption'][:28] + ("..." if len(f['caption']) > 28 else ""))
        builder.append([InlineKeyboardButton(text=btn_title, callback_data=f"fview:{f_id}")])

    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"blk:{cat_key}:{b_key}")])

    await callback.message.edit_text(
        f"Тема: **{topic_data['title']}**\nНайдено файлов: {len(files)}\nВыбери файл для просмотра:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("fview:"))
async def process_file_view(callback: types.CallbackQuery):
    file_uid = callback.data.split(":")[1]
    file_item, cat_k, blk_k, top_k = find_file_by_id(file_uid)

    if not file_item:
        return await callback.answer("❌ Файл не найден.", show_alert=True)

    diff_badge = format_difficulty_badge(file_item.get("difficulty", "medium"))
    tags_text = ", ".join([f"#{t}" for t in file_item.get("tags", [])]) or "нет"
    mr_text = "Да ⭐" if file_item.get("must_read") else "Нет"

    info_text = (
        f"📄 **{file_item['caption']}**\n\n"
        f"📊 Сложность: {diff_badge}\n"
        f"🏷 Теги: {tags_text}\n"
        f"⭐ Must-read: {mr_text}\n"
        f"👁 Просмотров: {file_item.get('views', 0)}"
    )

    await callback.message.edit_text(
        info_text,
        reply_markup=make_file_card_keyboard(file_uid, callback.from_user.id)
    )
    await callback.answer()


# ==========================================
#        MUST-READ, FAVORITES, LINKS
# ==========================================
@dp.callback_query(F.data == "menu:must_read")
async def show_must_read(callback: types.CallbackQuery):
    all_f = get_all_files()
    mr_files = [item for item in all_f if item["file"].get("must_read")]

    if not mr_files:
        return await callback.answer("⭐ В списке Must-read пока нет файлов.", show_alert=True)

    builder = []
    for item in mr_files:
        f = item["file"]
        btn_text = f"⭐ {f['caption'][:30]}"
        builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"fview:{f['id']}")])

    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])

    await callback.message.edit_text(
        "⭐ **Must-Read материалы**\nОбязательные и самые полезные книги и статьи:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()


@dp.callback_query(F.data == "menu:favorites")
async def show_user_favorites(callback: types.CallbackQuery):
    uid = str(callback.from_user.id)
    fav_ids = DATABASE.get("users", {}).get(uid, {}).get("favorites", [])

    if not fav_ids:
        return await callback.answer("❤️ У тебя пока нет избранных файлов.", show_alert=True)

    builder = []
    found_any = False
    for fid in fav_ids:
        f_item, _, _, _ = find_file_by_id(fid)
        if f_item:
            found_any = True
            btn_text = f"❤️ {f_item['caption'][:30]}"
            builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"fview:{f_item['id']}")])

    if not found_any:
        return await callback.answer("❤️ Избранные файлы больше недоступны.", show_alert=True)

    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])

    await callback.message.edit_text(
        "❤️ **Твои избранные файлы:**",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()


@dp.callback_query(F.data == "menu:links")
async def show_links(callback: types.CallbackQuery):
    links = DATABASE.get("links", [])
    if not links:
        builder = [[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]]
        await callback.message.edit_text("🔗 Полезных ссылок пока нет.", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
        return await callback.answer()

    builder = []
    for l in links:
        builder.append([InlineKeyboardButton(text=f"🌐 {l['title']}", url=l['url'])])
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])

    await callback.message.edit_text("🔗 **Полезные математические ресурсы и каналы:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


# ==========================================
#            RANDOM & CHALLENGE
# ==========================================
@dp.callback_query(F.data == "menu:challenge")
async def show_challenge_menu(callback: types.CallbackQuery):
    builder = [
        [
            InlineKeyboardButton(text="🟢 Easy", callback_data="chal:easy"),
            InlineKeyboardButton(text="🟡 Medium", callback_data="chal:medium")
        ],
        [
            InlineKeyboardButton(text="🔴 Hard", callback_data="chal:hard"),
            InlineKeyboardButton(text="🔥 IMO", callback_data="chal:imo")
        ],
        [
            InlineKeyboardButton(text="🎲 Любая сложность", callback_data="chal:any")
        ],
        [
            InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")
        ]
    ]
    await callback.message.edit_text("🎯 **Выбери уровень сложности для челленджа:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("chal:"))
async def process_challenge_pick(callback: types.CallbackQuery):
    diff = callback.data.split(":")[1]
    all_f = get_all_files()

    if diff != "any":
        filtered = [item for item in all_f if item["file"].get("difficulty", "medium").lower() == diff]
    else:
        filtered = all_f

    if not filtered:
        return await callback.answer(f"По уровню {diff} материалов пока нет.", show_alert=True)

    selected = random.choice(filtered)
    f = selected["file"]

    diff_badge = format_difficulty_badge(f.get("difficulty", "medium"))
    tags_text = " ".join([f"#{t}" for t in f.get("tags", [])])

    await callback.answer("🎲 Найдено!")
    await callback.message.answer(
        f"🎲 **Твой Challenge:**\n\n"
        f"📁 **Раздел:** {selected['cat_title']} ➔ {selected['top_title']}\n"
        f"📊 **Сложность:** {diff_badge}\n"
        f"📄 **Название:** {f['caption']}\n"
        f"🏷 **Теги:** {tags_text or '—'}"
    )
    await callback.message.answer_document(
        document=f["file_id"],
        caption=f"📄 {f['caption']}"
    )


# ==========================================
#          РЕЙТИНГ И АКТИВНОСТЬ
# ==========================================
@dp.callback_query(F.data == "menu:rating")
async def show_rating_board(callback: types.CallbackQuery):
    users = DATABASE.get("users", {})
    sorted_users = sorted(users.values(), key=lambda x: x.get("points", 0), reverse=True)

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    lines = ["🏆 **Таблица лидеров активности:**\n"]

    for idx, u in enumerate(sorted_users[:10]):
        medal = medals[idx] if idx < len(medals) else f"{idx + 1}."
        name = u.get("full_name") or u.get("username") or f"Пользователь {u.get('id')}"
        pts = u.get("points", 0)
        streak = u.get("streak", 1)
        lines.append(f"{medal} **{name}** — {pts} очков (🔥 {streak} дн.)")

    if not sorted_users:
        lines.append("Пока никто не набрал очков. Будь первым!")

    curr_u = track_user(callback.from_user)
    lines.append(f"\n👤 Твои очки: **{curr_u.get('points', 0)}** | Твой streak: 🔥 **{curr_u.get('streak', 1)} дн.**")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


# ==========================================
#      ПРЕДЛОЖИТЬ ФАЙЛ (ДЛЯ ЮЗЕРОВ)
# ==========================================
@dp.callback_query(F.data == "menu:suggest")
async def start_suggestion(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SuggestionState.waiting_content)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_suggest")]
    ])
    await callback.message.edit_text(
        "📤 **Предложить материал или файл:**\n\n"
        "Отправьте документ, книгу или напишите текст с полезной ссылкой/ресурсом.\n"
        "Администраторы рассмотрят ваше предложение и добавят его в каталог!",
        reply_markup=kb
    )
    await callback.answer()


@dp.callback_query(SuggestionState.waiting_content, F.data == "cancel_suggest")
async def cancel_suggest(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отправка предложения отменена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:main")]
    ]))
    await callback.answer()


@dp.message(SuggestionState.waiting_content)
async def process_suggestion_content(message: types.Message, state: FSMContext):
    user_info = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id} ({message.from_user.full_name})"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"📬 **Новое предложение от {user_info}:**")
            await message.copy_to(admin_id)
        except Exception:
            pass

    await state.clear()
    await message.answer("✅ **Спасибо!** Ваше предложение отправлено администрации.", reply_markup=get_main_menu_keyboard(message.from_user.id))


# ==========================================
#       👑 АДМИН-ПАНЕЛЬ: ГЛАВНОЕ МЕНЮ
# ==========================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("⛔ Доступ запрещён.")
    await message.answer("👑 **Админ-панель библиотеки Matham**", reply_markup=get_admin_menu_keyboard())


@dp.callback_query(F.data == "admin:menu")
async def cb_admin_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    await callback.message.edit_text("👑 **Админ-панель библиотеки Matham**", reply_markup=get_admin_menu_keyboard())
    await callback.answer()


# ==========================================
#      👑 АДМИН: ЗАГРУЗКА ФАЙЛОВ
# ==========================================
@dp.callback_query(F.data == "adm:add_file")
async def admin_start_add_file(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)

    await state.clear()
    await callback.message.edit_text(
        "📥 Отправьте документ (PDF, DJVU и т.д.), который хотите загрузить в библиотеку.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
        ])
    )
    await callback.answer()


@dp.message(F.document)
async def admin_doc_received(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    # Если мы в состоянии предложения от пользователя — обрабатываем там
    if current_state == SuggestionState.waiting_content.state:
        return await process_suggestion_content(message, state)

    if not is_admin(message.from_user.id):
        return await message.answer("ℹ️ Отправка файлов в библиотеку доступна только администраторам. Используйте кнопку «📤 Предложить файл» в меню.")

    doc = message.document
    file_id = doc.file_id
    default_name = message.caption if message.caption else doc.file_name

    await state.update_data(file_id=file_id, default_name=default_name)
    await state.set_state(FileUpload.selecting_path)

    builder = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        builder.append([InlineKeyboardButton(text=cat_data["title"], callback_data=f"a_cat:{cat_key}")])
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")])

    await message.answer(
        f"📥 **Получен файл:** `{default_name}`\n\nВыбери **Категорию** для сохранения:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )


@dp.callback_query(F.data == "a_cancel")
async def admin_cancel_flow(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Операция отменена.", reply_markup=get_admin_menu_keyboard())
    await callback.answer()


@dp.callback_query(FileUpload.selecting_path, F.data.startswith("a_cat:"))
async def admin_select_cat(callback: types.CallbackQuery):
    cat_key = callback.data.split(":")[1]
    cat_data = DATABASE["categories"][cat_key]

    builder = []
    for b_key, b_data in cat_data["blocks"].items():
        builder.append([InlineKeyboardButton(text=b_data["title"], callback_data=f"a_blk:{cat_key}:{b_key}")])
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")])

    await callback.message.edit_text(f"📁 **{cat_data['title']}**\nВыбери **Блок**:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(FileUpload.selecting_path, F.data.startswith("a_blk:"))
async def admin_select_blk(callback: types.CallbackQuery):
    _, cat_key, b_key = callback.data.split(":")
    block_data = DATABASE["categories"][cat_key]["blocks"][b_key]

    builder = []
    for t_key, t_data in block_data["topics"].items():
        builder.append([InlineKeyboardButton(text=f"• {t_data['title']}", callback_data=f"a_top:{cat_key}:{b_key}:{t_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"a_cat:{cat_key}")])

    await callback.message.edit_text(f"📁 **{block_data['title']}**\nВыбери **Тему**:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(FileUpload.selecting_path, F.data.startswith("a_top:"))
async def admin_select_top(callback: types.CallbackQuery, state: FSMContext):
    _, cat_key, b_key, t_key = callback.data.split(":")

    await state.update_data(cat_key=cat_key, b_key=b_key, t_key=t_key)
    await state.set_state(FileUpload.waiting_for_caption)

    data = await state.get_data()
    default_name = data.get("default_name", "Файл")

    builder = [
        [InlineKeyboardButton(text=f"📝 Оставить: {default_name[:20]}...", callback_data="a_skip_cap")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
    ]

    await callback.message.edit_text(
        f"✍️ **Введите название/описание для файла:**\n\n"
        f"Отправьте текстовое сообщение или нажмите кнопку, чтобы оставить текущее имя:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()


@dp.callback_query(FileUpload.waiting_for_caption, F.data == "a_skip_cap")
async def admin_skip_cap(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(caption=data.get("default_name", "Файл"))
    await prompt_for_tags(callback.message, state)
    await callback.answer()


@dp.message(FileUpload.waiting_for_caption, F.text)
async def admin_save_caption(message: types.Message, state: FSMContext):
    await state.update_data(caption=message.text.strip())
    await prompt_for_tags(message, state)


async def prompt_for_tags(target, state: FSMContext):
    await state.set_state(FileUpload.waiting_for_tags)
    builder = [
        [InlineKeyboardButton(text="⏩ Без тегов", callback_data="a_skip_tags")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
    ]
    text = (
        "🏷 **Укажите теги для файла:**\n\n"
        "Отправьте теги через запятую или пробел (например: `geometry, imo, 2024`)\n"
        "Или нажмите «Без тегов»:"
    )
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    else:
        await target.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))


@dp.callback_query(FileUpload.waiting_for_tags, F.data == "a_skip_tags")
async def admin_skip_tags(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(tags=[])
    await prompt_for_difficulty(callback.message, state)
    await callback.answer()


@dp.message(FileUpload.waiting_for_tags, F.text)
async def admin_receive_tags(message: types.Message, state: FSMContext):
    raw = message.text.replace("#", " ").replace(",", " ")
    tags = [t.strip().lower() for t in raw.split() if t.strip()]
    await state.update_data(tags=tags)
    await prompt_for_difficulty(message, state)


async def prompt_for_difficulty(target, state: FSMContext):
    await state.set_state(FileUpload.waiting_for_difficulty)
    builder = [
        [
            InlineKeyboardButton(text="🟢 Easy", callback_data="a_diff_set:easy"),
            InlineKeyboardButton(text="🟡 Medium", callback_data="a_diff_set:medium")
        ],
        [
            InlineKeyboardButton(text="🔴 Hard", callback_data="a_diff_set:hard"),
            InlineKeyboardButton(text="🔥 IMO", callback_data="a_diff_set:imo")
        ]
    ]
    text = "📊 **Выберите уровень сложности для материала:**"
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    else:
        await target.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))


@dp.callback_query(FileUpload.waiting_for_difficulty, F.data.startswith("a_diff_set:"))
async def admin_finalize_file_save(callback: types.CallbackQuery, state: FSMContext):
    diff = callback.data.split(":")[1]
    data = await state.get_data()

    file_id = data.get("file_id")
    caption = data.get("caption", data.get("default_name", "Файл"))
    tags = data.get("tags", [])
    cat_key, b_key, t_key = data.get("cat_key"), data.get("b_key"), data.get("t_key")

    new_file = {
        "id": uuid.uuid4().hex[:8],
        "file_id": file_id,
        "caption": caption,
        "tags": tags,
        "difficulty": diff,
        "must_read": False,
        "views": 0
    }

    DATABASE["categories"][cat_key]["blocks"][b_key]["topics"][t_key]["files"].append(new_file)
    await save_db(DATABASE)

    topic_title = DATABASE["categories"][cat_key]["blocks"][b_key]["topics"][t_key]["title"]
    diff_badge = format_difficulty_badge(diff)
    tags_str = ", ".join([f"#{t}" for t in tags]) or "нет"

    await callback.message.edit_text(
        f"✅ **Файл успешно добавлен в библиотеку!**\n\n"
        f"📁 `{DATABASE['categories'][cat_key]['title']}` ➔ `{DATABASE['categories'][cat_key]['blocks'][b_key]['title']}` ➔ `{topic_title}`\n"
        f"📄 **Название:** `{caption}`\n"
        f"📊 **Сложность:** {diff_badge}\n"
        f"🏷 **Теги:** {tags_str}",
        reply_markup=get_admin_menu_keyboard()
    )
    await state.clear()
    await callback.answer()


# ==========================================
#     👑 АДМИН: РЕДАКТИРОВАНИЕ ФАЙЛОВ
# ==========================================
@dp.callback_query(F.data == "adm:files_nav")
async def admin_files_browse_cats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)

    builder = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        builder.append([InlineKeyboardButton(text=cat_data["title"], callback_data=f"am_cat:{cat_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin:menu")])

    await callback.message.edit_text("✏️ **Управление файлами**\nВыберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("am_cat:"))
async def admin_manage_select_cat(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    cat_key = callback.data.split(":")[1]
    cat_data = DATABASE["categories"][cat_key]

    builder = []
    for b_key, b_data in cat_data["blocks"].items():
        builder.append([InlineKeyboardButton(text=b_data["title"], callback_data=f"am_blk:{cat_key}:{b_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:files_nav")])

    await callback.message.edit_text(f"📁 **{cat_data['title']}**\nВыберите блок:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("am_blk:"))
async def admin_manage_select_blk(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    _, cat_key, b_key = callback.data.split(":")
    block_data = DATABASE["categories"][cat_key]["blocks"][b_key]

    builder = []
    for t_key, t_data in block_data["topics"].items():
        builder.append([InlineKeyboardButton(text=f"• {t_data['title']} ({len(t_data.get('files', []))})", callback_data=f"am_top:{cat_key}:{b_key}:{t_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"am_cat:{cat_key}")])

    await callback.message.edit_text(f"📁 **{block_data['title']}**\nВыберите тему:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("am_top:"))
async def admin_manage_select_top(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    _, cat_key, b_key, t_key = callback.data.split(":")
    topic_data = DATABASE["categories"][cat_key]["blocks"][b_key]["topics"][t_key]
    files = topic_data.get("files", [])

    if not files:
        builder = [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"am_blk:{cat_key}:{b_key}")]]
        await callback.message.edit_text(f"📁 В теме **{topic_data['title']}** пока нет файлов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
        return await callback.answer()

    builder = []
    for f in files:
        f_id = f["id"]
        mr = "⭐ " if f.get("must_read") else ""
        builder.append([
            InlineKeyboardButton(text=f"{mr}{f['caption'][:25]}", callback_data=f"am_fview:{f_id}")
        ])
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"am_blk:{cat_key}:{b_key}")])

    await callback.message.edit_text(f"📁 Тема: **{topic_data['title']}**\nВыберите файл для редактирования:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("am_fview:"))
async def admin_file_card(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    file_uid = callback.data.split(":")[1]
    f, cat_k, blk_k, top_k = find_file_by_id(file_uid)

    if not f:
        return await callback.answer("❌ Файл не найден.", show_alert=True)

    mr_toggle_text = "☆ Убрать из Must-read" if f.get("must_read") else "⭐ Сделать Must-read"
    diff_badge = format_difficulty_badge(f.get("difficulty", "medium"))
    tags_str = ", ".join([f"#{t}" for t in f.get("tags", [])]) or "нет"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Название", callback_data=f"aed_name:{file_uid}"),
            InlineKeyboardButton(text="🏷 Теги", callback_data=f"aed_tags:{file_uid}")
        ],
        [
            InlineKeyboardButton(text=mr_toggle_text, callback_data=f"aed_mr:{file_uid}"),
            InlineKeyboardButton(text=f"📊 {diff_badge}", callback_data=f"aed_diff:{file_uid}")
        ],
        [
            InlineKeyboardButton(text="📥 Открыть файл", callback_data=f"fdl:{file_uid}"),
            InlineKeyboardButton(text="🗑 Удалить файл", callback_data=f"aed_del:{file_uid}")
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад в тему", callback_data=f"am_top:{cat_k}:{blk_k}:{top_k}")
        ]
    ])

    await callback.message.edit_text(
        f"⚙️ **Управление файлом:**\n\n"
        f"📄 **Название:** {f['caption']}\n"
        f"📊 **Сложность:** {diff_badge}\n"
        f"🏷 **Теги:** {tags_str}\n"
        f"⭐ **Must-read:** {'Да' if f.get('must_read') else 'Нет'}\n"
        f"👁 **Просмотров:** {f.get('views', 0)}",
        reply_markup=kb
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("aed_mr:"))
async def admin_toggle_must_read(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    file_uid = callback.data.split(":")[1]
    f, _, _, _ = find_file_by_id(file_uid)
    if not f:
        return await callback.answer("Файл не найден.", show_alert=True)

    f["must_read"] = not f.get("must_read", False)
    await save_db(DATABASE)
    await admin_file_card(callback)


@dp.callback_query(F.data.startswith("aed_diff:"))
async def admin_change_diff_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    file_uid = callback.data.split(":")[1]
    builder = [
        [
            InlineKeyboardButton(text="🟢 Easy", callback_data=f"as_df:{file_uid}:easy"),
            InlineKeyboardButton(text="🟡 Medium", callback_data=f"as_df:{file_uid}:medium")
        ],
        [
            InlineKeyboardButton(text="🔴 Hard", callback_data=f"as_df:{file_uid}:hard"),
            InlineKeyboardButton(text="🔥 IMO", callback_data=f"as_df:{file_uid}:imo")
        ],
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"am_fview:{file_uid}")]
    ]
    await callback.message.edit_text("📊 Выберите новый уровень сложности:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("as_df:"))
async def admin_apply_difficulty(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    _, file_uid, diff = callback.data.split(":")
    f, _, _, _ = find_file_by_id(file_uid)
    if f:
        f["difficulty"] = diff
        await save_db(DATABASE)
    await admin_file_card(callback)


@dp.callback_query(F.data.startswith("aed_name:"))
async def admin_edit_name_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    file_uid = callback.data.split(":")[1]
    await state.set_state(FileEditState.waiting_new_caption)
    await state.update_data(file_uid=file_uid)

    await callback.message.edit_text(
        "📝 **Введите новое название для файла:**",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"am_fview:{file_uid}")]
        ])
    )
    await callback.answer()


@dp.message(FileEditState.waiting_new_caption, F.text)
async def admin_save_new_caption(message: types.Message, state: FSMContext):
    data = await state.get_data()
    file_uid = data.get("file_uid")
    f, _, _, _ = find_file_by_id(file_uid)

    if f:
        f["caption"] = message.text.strip()
        await save_db(DATABASE)
        await message.answer("✅ Название успешно обновлено!")

    await state.clear()
    # Отправка обновленной карточки
    for admin_id in ADMIN_IDS:
        if admin_id == message.from_user.id:
            await message.answer("👑 **Админ-панель:**", reply_markup=get_admin_menu_keyboard())


@dp.callback_query(F.data.startswith("aed_tags:"))
async def admin_edit_tags_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    file_uid = callback.data.split(":")[1]
    await state.set_state(FileEditState.waiting_new_tags)
    await state.update_data(file_uid=file_uid)

    await callback.message.edit_text(
        "🏷 **Введите новые теги через запятую или пробел:**",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"am_fview:{file_uid}")]
        ])
    )
    await callback.answer()


@dp.message(FileEditState.waiting_new_tags, F.text)
async def admin_save_new_tags(message: types.Message, state: FSMContext):
    data = await state.get_data()
    file_uid = data.get("file_uid")
    f, _, _, _ = find_file_by_id(file_uid)

    if f:
        raw = message.text.replace("#", " ").replace(",", " ")
        f["tags"] = [t.strip().lower() for t in raw.split() if t.strip()]
        await save_db(DATABASE)
        await message.answer("✅ Теги успешно обновлены!")

    await state.clear()
    await message.answer("👑 **Админ-панель:**", reply_markup=get_admin_menu_keyboard())


@dp.callback_query(F.data.startswith("aed_del:"))
async def admin_delete_file(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    file_uid = callback.data.split(":")[1]
    f, cat_k, blk_k, top_k = find_file_by_id(file_uid)

    if not f:
        return await callback.answer("Файл уже удален.", show_alert=True)

    topic_files = DATABASE["categories"][cat_k]["blocks"][blk_k]["topics"][top_k]["files"]
    DATABASE["categories"][cat_k]["blocks"][blk_k]["topics"][top_k]["files"] = [x for x in topic_files if x.get("id") != file_uid]
    await save_db(DATABASE)

    await callback.answer("🗑 Файл успешно удален!", show_alert=True)
    await admin_manage_select_top(callback)


# ==========================================
#      👑 АДМИН: ЗАДАЧА ДНЯ (УПРАВЛЕНИЕ)
# ==========================================
@dp.callback_query(F.data == "adm:dt_menu")
async def admin_dt_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)

    today = get_today_str()
    today_task = get_daily_task_for_date(today)
    status = f"✅ На сегодня ({today}) задача есть" if today_task else f"⚠️ На сегодня ({today}) задачи нет"

    builder = [
        [InlineKeyboardButton(text="➕ Добавить задачу дня", callback_data="adm_dt:create")],
        [InlineKeyboardButton(text="📋 Список всех задач", callback_data="adm_dt:list")],
        [InlineKeyboardButton(text="📊 Статистика задач", callback_data="adm_dt:stats_view")],
        [InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin:menu")]
    ]

    await callback.message.edit_text(f"🎯 **Управление Задачей дня**\nСтатус: {status}", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data == "adm_dt:create")
async def admin_dt_start_create(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)

    await state.set_state(DailyTaskCreate.waiting_photo)
    await callback.message.edit_text(
        "📸 **Шаг 1 из 5: Отправьте ФОТО задачи дня.**",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
        ])
    )
    await callback.answer()


@dp.message(DailyTaskCreate.waiting_photo, F.photo)
async def admin_dt_photo_received(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_id)
    await state.set_state(DailyTaskCreate.waiting_caption)

    await message.answer(
        "✍️ **Шаг 2 из 5: Отправьте текст/условие задачи:**",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
        ])
    )


@dp.message(DailyTaskCreate.waiting_caption, F.text)
async def admin_dt_caption_received(message: types.Message, state: FSMContext):
    await state.update_data(caption=message.text.strip())
    await state.set_state(DailyTaskCreate.waiting_date)

    today = get_today_str()
    builder = [
        [InlineKeyboardButton(text=f"📅 Сегодня ({today})", callback_data=f"adm_dt_date:{today}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
    ]
    await message.answer(
        f"📅 **Шаг 3 из 5: Укажите дату задачи**\n\n"
        f"Нажмите кнопку «Сегодня ({today})» или напишите дату в формате `ГГГГ-ММ-ДД` (например `2026-08-25`):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )


@dp.callback_query(DailyTaskCreate.waiting_date, F.data.startswith("adm_dt_date:"))
async def admin_dt_date_button(callback: types.CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":")[1]
    await process_dt_date_choice(date_str, callback.message, state)
    await callback.answer()


@dp.message(DailyTaskCreate.waiting_date, F.text)
async def admin_dt_date_text(message: types.Message, state: FSMContext):
    date_str = message.text.strip()
    await process_dt_date_choice(date_str, message, state)


async def process_dt_date_choice(date_str: str, target, state: FSMContext):
    await state.update_data(date=date_str)
    existing_task = get_daily_task_for_date(date_str)

    if existing_task:
        await state.set_state(DailyTaskCreate.confirm_overwrite)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, заменить", callback_data="dt_ow:yes"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")
            ]
        ])
        text = f"⚠️ **Задача на {date_str} уже существует!** Перезаписать её новой?"
        if isinstance(target, types.CallbackQuery):
            await target.message.edit_text(text, reply_markup=kb)
        else:
            await target.answer(text, reply_markup=kb)
        return

    await prompt_dt_hint1(target, state)


@dp.callback_query(DailyTaskCreate.confirm_overwrite, F.data == "dt_ow:yes")
async def admin_dt_confirm_overwrite(callback: types.CallbackQuery, state: FSMContext):
    await prompt_dt_hint1(callback.message, state)
    await callback.answer()


async def prompt_dt_hint1(target, state: FSMContext):
    await state.set_state(DailyTaskCreate.waiting_hint1)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить", callback_data="dt_skip:h1")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
    ])
    text = "💡 **Шаг 4 из 5: Введите первую подсказку (или нажмите «Пропустить»):**"
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@dp.callback_query(DailyTaskCreate.waiting_hint1, F.data == "dt_skip:h1")
async def admin_dt_skip_hint1(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(hint_1="")
    await prompt_dt_hint2(callback.message, state)
    await callback.answer()


@dp.message(DailyTaskCreate.waiting_hint1, F.text)
async def admin_dt_text_hint1(message: types.Message, state: FSMContext):
    await state.update_data(hint_1=message.text.strip())
    await prompt_dt_hint2(message, state)


async def prompt_dt_hint2(target, state: FSMContext):
    await state.set_state(DailyTaskCreate.waiting_hint2)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить", callback_data="dt_skip:h2")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
    ])
    text = "💡 **Введите вторую подсказку (или нажмите «Пропустить»):**"
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@dp.callback_query(DailyTaskCreate.waiting_hint2, F.data == "dt_skip:h2")
async def admin_dt_skip_hint2(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(hint_2="")
    await prompt_dt_solution(callback.message, state)
    await callback.answer()


@dp.message(DailyTaskCreate.waiting_hint2, F.text)
async def admin_dt_text_hint2(message: types.Message, state: FSMContext):
    await state.update_data(hint_2=message.text.strip())
    await prompt_dt_solution(message, state)


async def prompt_dt_solution(target, state: FSMContext):
    await state.set_state(DailyTaskCreate.waiting_solution)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Без решения", callback_data="dt_skip:sol")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
    ])
    text = "✅ **Шаг 5 из 5: Введите полное решение задачи (или «Без решения»):**"
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@dp.callback_query(DailyTaskCreate.waiting_solution, F.data == "dt_skip:sol")
async def admin_dt_skip_solution(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(solution="")
    await finalize_daily_task_creation(callback.message, state)
    await callback.answer()


@dp.message(DailyTaskCreate.waiting_solution, F.text)
async def admin_dt_text_solution(message: types.Message, state: FSMContext):
    await state.update_data(solution=message.text.strip())
    await finalize_daily_task_creation(message, state)


async def finalize_daily_task_creation(target, state: FSMContext):
    data = await state.get_data()
    date_str = data.get("date", get_today_str())

    new_task = {
        "id": uuid.uuid4().hex[:8],
        "date": date_str,
        "photo_file_id": data.get("photo_file_id"),
        "caption": data.get("caption"),
        "hint_1": data.get("hint_1", ""),
        "hint_2": data.get("hint_2", ""),
        "solution": data.get("solution", ""),
        "created_at": get_now_yerevan().isoformat(),
        "ratings": {},
        "views": 0
    }

    if "daily_tasks" not in DATABASE:
        DATABASE["daily_tasks"] = {}

    DATABASE["daily_tasks"][date_str] = new_task
    await save_db(DATABASE)

    text = f"🎉 **Задача дня на дату `{date_str}` успешно сохранена!**"
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=get_admin_menu_keyboard())
    else:
        await target.answer(text, reply_markup=get_admin_menu_keyboard())

    await state.clear()


@dp.callback_query(F.data == "adm_dt:list")
async def admin_dt_list(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)

    tasks = DATABASE.get("daily_tasks", {})
    if not tasks:
        builder = [[InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:dt_menu")]]
        await callback.message.edit_text("🎯 Задач дня пока нет.", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
        return await callback.answer()

    builder = []
    for d_str in sorted(tasks.keys(), reverse=True)[:15]:
        t = tasks[d_str]
        avg, cnt, _ = compute_task_rating(t)
        builder.append([
            InlineKeyboardButton(text=f"📅 {d_str} (⭐ {avg} | 👥 {cnt})", callback_data=f"adm_dt_v:{d_str}")
        ])
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:dt_menu")])

    await callback.message.edit_text("📋 **Список задач дня (последние 15):**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("adm_dt_v:"))
async def admin_dt_view_single(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    date_str = callback.data.split(":")[1]
    task = get_daily_task_for_date(date_str)
    if not task:
        return await callback.answer("Задача не найдена.", show_alert=True)

    avg, cnt, dist = compute_task_rating(task)
    dist_str = " | ".join([f"{k}⭐: {v}" for k, v in dist.items()])

    text = (
        f"🎯 **Задача на {date_str}**\n\n"
        f"📝 **Условие:** {task.get('caption')}\n"
        f"💡 Подсказка 1: {'Есть' if task.get('hint_1') else 'Нет'}\n"
        f"💡 Подсказка 2: {'Есть' if task.get('hint_2') else 'Нет'}\n"
        f"✅ Решение: {'Есть' if task.get('solution') else 'Нет'}\n\n"
        f"📊 **Статистика:**\n"
        f"⭐ Средний балл: **{avg}/5**\n"
        f"👥 Всего оценок: **{cnt}**\n"
        f"📈 Распределение: `{dist_str}`\n"
        f"👁 Просмотров: **{task.get('views', 0)}**"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить задачу", callback_data=f"adm_dt_del:{date_str}")],
        [InlineKeyboardButton(text="⬅️ К списку задач", callback_data="adm_dt:list")]
    ])

    await callback.message.answer_photo(photo=task["photo_file_id"], caption=text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("adm_dt_del:"))
async def admin_dt_delete(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    date_str = callback.data.split(":")[1]
    if date_str in DATABASE.get("daily_tasks", {}):
        del DATABASE["daily_tasks"][date_str]
        await save_db(DATABASE)
        await callback.answer("🗑 Задача успешно удалена!", show_alert=True)

    await admin_dt_list(callback)


@dp.callback_query(F.data == "adm_dt:stats_view")
async def admin_dt_global_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)

    tasks = DATABASE.get("daily_tasks", {})
    total_tasks = len(tasks)
    total_ratings = sum(len(t.get("ratings", {})) for t in tasks.values())
    all_scores = [score for t in tasks.values() for score in t.get("ratings", {}).values()]
    avg_total = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0

    text = (
        f"📊 **Общая статистика Задач Дня:**\n\n"
        f"🎯 Всего опубликовано задач: **{total_tasks}**\n"
        f"👥 Всего оценок от пользователей: **{total_ratings}**\n"
        f"⭐ Средняя оценка всех задач: **{avg_total}/5**"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:dt_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# ==========================================
#     👑 АДМИН: СТАТИСТИКА & РАССЫЛКА & ССЫЛКИ
# ==========================================
@dp.message(Command("stats"))
@dp.callback_query(F.data == "adm:stats")
async def admin_stats_handler(event: types.Message | types.CallbackQuery):
    user_id = event.from_user.id
    if not is_admin(user_id):
        if isinstance(event, types.CallbackQuery):
            return await event.answer("⛔ Доступ запрещён.", show_alert=True)
        return await event.answer("⛔ Доступ запрещён.")

    all_f = get_all_files()
    total_files = len(all_f)
    mr_count = sum(1 for item in all_f if item["file"].get("must_read"))
    total_users = len(DATABASE.get("users", {}))
    total_tasks = len(DATABASE.get("daily_tasks", {}))
    total_links = len(DATABASE.get("links", []))

    # Сортировка самых просматриваемых файлов
    sorted_files = sorted(all_f, key=lambda x: x["file"].get("views", 0), reverse=True)[:5]
    top_files_str = "\n".join([f"• {item['file']['caption']} — {item['file'].get('views', 0)} просм." for item in sorted_files]) or "Нет данных"

    text = (
        f"📊 **Системная статистика Matham Bot:**\n\n"
        f"👥 Всего пользователей: **{total_users}**\n"
        f"📚 Всего файлов в базе: **{total_files}**\n"
        f"⭐ Must-read файлов: **{mr_count}**\n"
        f"🎯 Задач дня: **{total_tasks}**\n"
        f"🔗 Ссылок: **{total_links}**\n\n"
        f"🔥 **Топ-5 популярных файлов:**\n{top_files_str}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin:menu")]
    ])

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb)


@dp.message(Command("broadcast"))
@dp.callback_query(F.data == "adm:broadcast")
async def admin_broadcast_start(event: types.Message | types.CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    if not is_admin(user_id):
        return

    await state.set_state(BroadcastState.waiting_message)
    text = (
        "📢 **Создание рассылки:**\n\n"
        "Отправьте сообщение (текст, фото, файл), которое вы хотите разослать ВСЕМ пользователям бота."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
    ])

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb)


@dp.message(BroadcastState.waiting_message)
async def admin_broadcast_preview(message: types.Message, state: FSMContext):
    await state.update_data(broadcast_message_id=message.message_id, broadcast_chat_id=message.chat.id)
    await state.set_state(BroadcastState.confirm)

    users_count = len(DATABASE.get("users", {}))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить всем", callback_data="bc_confirm:yes"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")
        ]
    ])
    await message.answer(f"📢 **Подтверждение рассылки**\nПолучателей: **{users_count}** чел.\n\nОтправить?", reply_markup=kb)


@dp.callback_query(BroadcastState.confirm, F.data == "bc_confirm:yes")
async def admin_broadcast_execute(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)

    data = await state.get_data()
    from_chat_id = data.get("broadcast_chat_id")
    msg_id = data.get("broadcast_message_id")

    users = DATABASE.get("users", {})
    await callback.message.edit_text("⏳ Рассылка запущена... Пожалуйста, подождите.")
    await callback.answer()

    success_cnt = 0
    fail_cnt = 0

    for uid_str in list(users.keys()):
        try:
            target_uid = int(uid_str)
            await bot.copy_message(chat_id=target_uid, from_chat_id=from_chat_id, message_id=msg_id)
            success_cnt += 1
            await asyncio.sleep(0.05)  # Защита от лимитов Telegram API
        except (TelegramForbiddenError, TelegramBadRequest):
            fail_cnt += 1
        except TelegramAPIError as e:
            fail_cnt += 1
            logger.warning(f"Ошибка отправки пользователю {uid_str}: {e}")

    await callback.message.answer(
        f"📢 **Рассылка завершена!**\n\n"
        f"✅ Успешно отправлено: **{success_cnt}**\n"
        f"❌ Ошибок (заблокировали бота): **{fail_cnt}**",
        reply_markup=get_admin_menu_keyboard()
    )
    await state.clear()


# Управление ссылками
@dp.callback_query(F.data == "adm:links_menu")
async def admin_links_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)

    links = DATABASE.get("links", [])
    builder = [
        [InlineKeyboardButton(text="➕ Добавить ссылку", callback_data="adm_link:add")]
    ]
    for idx, l in enumerate(links):
        builder.append([
            InlineKeyboardButton(text=f"🌐 {l['title']}", url=l['url']),
            InlineKeyboardButton(text="🗑", callback_data=f"adm_link_del:{idx}")
        ])
    builder.append([InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin:menu")])

    await callback.message.edit_text("🔗 **Управление ссылками:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data == "adm_link:add")
async def admin_link_start_add(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    await state.set_state(LinkAddState.waiting_title)
    await callback.message.edit_text(
        "✍️ Введите название для ссылки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
        ])
    )
    await callback.answer()


@dp.message(LinkAddState.waiting_title, F.text)
async def admin_link_title_received(message: types.Message, state: FSMContext):
    await state.update_data(link_title=message.text.strip())
    await state.set_state(LinkAddState.waiting_url)
    await message.answer("🌐 Введите URL адрес (начиная с `https://`):")


@dp.message(LinkAddState.waiting_url, F.text)
async def admin_link_url_received(message: types.Message, state: FSMContext):
    url = message.text.strip()
    if not url.startswith("http"):
        return await message.answer("⚠️ Неверный формат URL. Ссылка должна начинаться с http:// или https://")

    data = await state.get_data()
    title = data.get("link_title", "Ссылка")

    if "links" not in DATABASE:
        DATABASE["links"] = []

    DATABASE["links"].append({"id": uuid.uuid4().hex[:6], "title": title, "url": url})
    await save_db(DATABASE)

    await state.clear()
    await message.answer(f"✅ Ссылка **{title}** добавлена!", reply_markup=get_admin_menu_keyboard())


@dp.callback_query(F.data.startswith("adm_link_del:"))
async def admin_link_delete(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Доступ запрещён.", show_alert=True)
    idx = int(callback.data.split(":")[1])
    links = DATABASE.get("links", [])
    if 0 <= idx < len(links):
        links.pop(idx)
        await save_db(DATABASE)
        await callback.answer("🗑 Ссылка удалена!", show_alert=True)
    await admin_links_menu(callback)


# ==========================================
#      КОМАНДЫ, МЕНЮ И УМНЫЙ ПОИСК
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    track_user(message.from_user)
    await save_db(DATABASE)

    welcome_text = (
        "Здарова! ✌️ Рад видеть тебя в библиотеке **Matham**.\n\n"
        "📚 **Каталог** — структурированные темы и книги по олимпиадной и высшей математике.\n"
        "🎯 **Задача дня** — свежая олимпиадная задача каждый день с подсказками.\n"
        "🔎 **Поиск** — просто отправь название книги, автора или `#тег` в чат.\n\n"
        "Выбери интересующий раздел:"
    )
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard(message.from_user.id))


@dp.message(Command("task"))
async def cmd_task(message: types.Message):
    today = get_today_str()
    await render_daily_task_view(message, today, message.from_user.id)


@dp.message(Command("favorites"))
async def cmd_favorites(message: types.Message):
    uid = str(message.from_user.id)
    fav_ids = DATABASE.get("users", {}).get(uid, {}).get("favorites", [])

    if not fav_ids:
        return await message.answer("❤️ Твой список избранного пуст. Добавляй файлы кнопкой «❤️ В избранное»!")

    builder = []
    for fid in fav_ids:
        f_item, _, _, _ = find_file_by_id(fid)
        if f_item:
            builder.append([InlineKeyboardButton(text=f"❤️ {f_item['caption'][:30]}", callback_data=f"fview:{f_item['id']}")])

    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    await message.answer("❤️ **Твои избранные файлы:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))


@dp.message(Command("rating"))
async def cmd_rating(message: types.Message):
    users = DATABASE.get("users", {})
    sorted_users = sorted(users.values(), key=lambda x: x.get("points", 0), reverse=True)

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    lines = ["🏆 **Таблица лидеров активности:**\n"]

    for idx, u in enumerate(sorted_users[:10]):
        medal = medals[idx] if idx < len(medals) else f"{idx + 1}."
        name = u.get("full_name") or u.get("username") or f"Пользователь {u.get('id')}"
        pts = u.get("points", 0)
        streak = u.get("streak", 1)
        lines.append(f"{medal} **{name}** — {pts} очков (🔥 {streak} дн.)")

    curr_u = track_user(message.from_user)
    lines.append(f"\n👤 Твои очки: **{curr_u.get('points', 0)}** | Твой streak: 🔥 **{curr_u.get('streak', 1)} дн.**")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]
    ])
    await message.answer("\n".join(lines), reply_markup=kb)


@dp.message(Command("challenge"))
async def cmd_challenge(message: types.Message):
    builder = [
        [
            InlineKeyboardButton(text="🟢 Easy", callback_data="chal:easy"),
            InlineKeyboardButton(text="🟡 Medium", callback_data="chal:medium")
        ],
        [
            InlineKeyboardButton(text="🔴 Hard", callback_data="chal:hard"),
            InlineKeyboardButton(text="🔥 IMO", callback_data="chal:imo")
        ],
        [
            InlineKeyboardButton(text="🎲 Любая сложность", callback_data="chal:any")
        ]
    ]
    await message.answer("🎯 **Выбери уровень сложности для Random Challenge:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))


@dp.message(Command("surprise"))
async def cmd_surprise(message: types.Message):
    all_f = get_all_files()
    if not all_f:
        return await message.answer("📁 В базе пока нет файлов.")

    selected = random.choice(all_f)
    f = selected["file"]

    diff_badge = format_difficulty_badge(f.get("difficulty", "medium"))
    tags_text = " ".join([f"#{t}" for t in f.get("tags", [])])

    await message.answer(
        f"🎲 **Случайный файл из каталога:**\n\n"
        f"📁 **Раздел:** {selected['cat_title']} ➔ {selected['top_title']}\n"
        f"📊 **Сложность:** {diff_badge}\n"
        f"📄 **Название:** {f['caption']}\n"
        f"🏷 **Теги:** {tags_text or '—'}"
    )
    await message.answer_document(
        document=f["file_id"],
        caption=f"📄 {f['caption']}"
    )


@dp.callback_query(F.data == "menu:main")
async def process_back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📂 **Главное меню библиотеки Matham:**",
        reply_markup=get_main_menu_keyboard(callback.from_user.id)
    )
    await callback.answer()


@dp.callback_query(F.data == "menu:categories")
async def process_open_categories(callback: types.CallbackQuery):
    await callback.message.edit_text("📂 **Каталог материалов:**\nВыберите раздел:", reply_markup=get_categories_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "menu:task")
async def process_open_task_cb(callback: types.CallbackQuery):
    today = get_today_str()
    await render_daily_task_view(callback, today, callback.from_user.id)


# Глобальный умный поиск по ключевым словам и тегам
@dp.message(F.text & ~F.text.startswith("/"))
async def global_smart_search(message: types.Message, state: FSMContext):
    # Если бот ожидает текст в рамках FSM — не перехватываем
    current_state = await state.get_state()
    if current_state is not None:
        return

    query_raw = message.text.strip().lower()
    if query_raw in ["удиви меня", "surprise", "рандом", "random"]:
        return await cmd_surprise(message)

    search_tokens = query_raw.replace("#", "").split()
    if not search_tokens:
        return

    all_files = get_all_files()
    matched_files = []

    for item in all_files:
        f = item["file"]
        cap = f.get("caption", "").lower()
        cat_title = item.get("cat_title", "").lower()
        top_title = item.get("top_title", "").lower()
        tags = [t.lower() for t in f.get("tags", [])]
        diff = f.get("difficulty", "").lower()

        # Проверяем вхождение всех поисковых слов
        match = True
        for token in search_tokens:
            token_found = (
                token in cap
                or token in cat_title
                or token in top_title
                or token in diff
                or any(token in t for t in tags)
            )
            if not token_found:
                match = False
                break

        if match:
            matched_files.append(item)

    if not matched_files:
        return await message.answer(
            "🔍 Ничего не найдено. Попробуйте изменить запрос, использовать теги (например, `#geometry`) или перейдите в меню:",
            reply_markup=get_main_menu_keyboard(message.from_user.id)
        )

    await message.answer(f"🔍 Найдено материалов: **{len(matched_files)}**")
    for item in matched_files[:8]:
        f = item["file"]
        diff_badge = format_difficulty_badge(f.get("difficulty", "medium"))
        tags_str = " ".join([f"#{t}" for t in f.get("tags", [])])

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 Скачать", callback_data=f"fdl:{f['id']}")]
        ])

        await message.answer(
            f"📄 **{f['caption']}**\n"
            f"📌 Раздел: _{item['top_title']}_\n"
            f"📊 Сложность: {diff_badge}\n"
            f"🏷 Теги: {tags_str or '—'}",
            reply_markup=kb
        )


# ==========================================
#        ВЕБ-СЕРВЕР И ИНИЦИАЛИЗАЦИЯ
# ==========================================
async def set_main_menu_commands(bot_instance: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню 🚀"),
        BotCommand(command="task", description="🎯 Задача дня"),
        BotCommand(command="favorites", description="❤️ Избранное"),
        BotCommand(command="rating", description="🏆 Рейтинг активности"),
        BotCommand(command="challenge", description="🎲 Random Challenge"),
        BotCommand(command="surprise", description="Случайный файл 🎲")
    ]
    await bot_instance.set_my_commands(commands)


async def run_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Matham Bot is running perfectly! 🚀"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Health-check веб-сервер слушает порт {port}")


async def main():
    global DATABASE

    await run_web_server()

    # Проверка соединения с MongoDB
    await mongo_client.admin.command("ping")
    logger.info("✅ Подключение к MongoDB успешно!")

    DATABASE = await load_db()
    total_files = len(get_all_files())
    logger.info(f"📦 База данных загружена ({len(DATABASE.get('categories', {}))} категорий, {total_files} файлов)")

    await bot.delete_webhook(drop_pending_updates=True)
    await set_main_menu_commands(bot)
    logger.info("🚀 Matham Bot готов к работе!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
