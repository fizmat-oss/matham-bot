import logging
import random
import os
import copy
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "matham_bot")
mongo_client = AsyncIOMotorClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]
db_collection = mongo_db["catalog"]
DB_DOC_ID = "catalog_main"

TIMEZONE = ZoneInfo("Asia/Yerevan")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==========================================
#              DEFAULT DATABASE
# ==========================================
DEFAULT_DATABASE = {
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
    "must_read": [],
    "daily_tasks": {},
    "links": {},
    "users": {},
    "settings": {}
}

DATABASE = {}

# ==========================================
#              FSM STATES
# ==========================================
class FileUpload(StatesGroup):
    selecting_path = State()
    waiting_for_caption = State()
    choosing_difficulty = State()
    choosing_tags = State()

class FileEdit(StatesGroup):
    selecting_file = State()
    edit_menu = State()
    editing_caption = State()
    editing_category = State()
    choosing_new_category = State()
    choosing_new_block = State()
    choosing_new_topic = State()
    editing_difficulty = State()
    editing_tags = State()

class DailyTaskState(StatesGroup):
    waiting_photo = State()
    waiting_caption = State()
    waiting_date = State()
    edit_menu = State()
    choosing_task_to_edit = State()
    editing_caption = State()
    editing_date = State()
    adding_hint = State()
    hint_menu = State()

class BroadcastState(StatesGroup):
    waiting_message = State()
    confirm = State()

class SearchState(StatesGroup):
    searching = State()

# ==========================================
#              DATABASE FUNCTIONS
# ==========================================
async def load_db():
    """Load database from MongoDB with auto-migration."""
    doc = await db_collection.find_one({"_id": DB_DOC_ID})
    if doc is None:
        logger.info("Creating new database from DEFAULT_DATABASE")
        data = copy.deepcopy(DEFAULT_DATABASE)
        await db_collection.update_one(
            {"_id": DB_DOC_ID},
            {"$set": {"data": data}},
            upsert=True
        )
        return data
    
    data = doc.get("data", {})
    
    # Auto-migration for new fields
    if "categories" not in data:
        # Old format migration
        old_data = copy.deepcopy(data)
        data = copy.deepcopy(DEFAULT_DATABASE)
        # Migrate old categories if needed
        for old_key in old_data.keys():
            if old_key in data["categories"]:
                data["categories"][old_key] = old_data[old_key]
    
    if "must_read" not in data:
        data["must_read"] = []
    if "daily_tasks" not in data:
        data["daily_tasks"] = {}
    if "links" not in data:
        data["links"] = {}
    if "users" not in data:
        data["users"] = {}
    if "settings" not in data:
        data["settings"] = {}
    
    await save_db(data)
    return data

async def save_db(db_data):
    """Save database to MongoDB."""
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {"data": db_data}},
        upsert=True
    )

def get_today_yerevan():
    """Get today's date in Yerevan timezone."""
    return datetime.now(TIMEZONE).date()

# ==========================================
#              HELPER FUNCTIONS
# ==========================================
def add_file_to_catalog(cat_key, b_key, t_key, file_data):
    """Add file to catalog with proper indexing."""
    if cat_key not in DATABASE["categories"]:
        return False
    if b_key not in DATABASE["categories"][cat_key]["blocks"]:
        return False
    if t_key not in DATABASE["categories"][cat_key]["blocks"][b_key]["topics"]:
        return False
    
    DATABASE["categories"][cat_key]["blocks"][b_key]["topics"][t_key]["files"].append(file_data)
    return True

def find_file_by_id(file_id):
    """Find file location in catalog by file_id."""
    for cat_key, cat_data in DATABASE["categories"].items():
        for b_key, b_data in cat_data["blocks"].items():
            for t_key, t_data in b_data["topics"].items():
                for idx, f in enumerate(t_data["files"]):
                    if f["file_id"] == file_id:
                        return (cat_key, b_key, t_key, idx)
    return None

def get_main_menu_keyboard(is_admin=False):
    """Generate main menu keyboard."""
    builder = [
        [InlineKeyboardButton(text="📚 Каталог", callback_data="menu:catalog")],
        [InlineKeyboardButton(text="🎯 Задача дня", callback_data="menu:task")],
        [InlineKeyboardButton(text="⭐ Must-read", callback_data="menu:mustread")],
        [InlineKeyboardButton(text="❤️ Избранное", callback_data="menu:favorites")],
        [InlineKeyboardButton(text="🔎 Поиск", callback_data="menu:search")],
        [InlineKeyboardButton(text="🏆 Рейтинг", callback_data="menu:rating")],
        [InlineKeyboardButton(text="🎲 Случайный материал", callback_data="menu:challenge")]
    ]
    
    if is_admin:
        builder.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin:menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_categories_keyboard():
    """Generate categories keyboard."""
    builder = []
    for cat_key, cat_data in DATABASE["categories"].items():
        builder.append([InlineKeyboardButton(text=cat_data["title"], callback_data=f"cat:{cat_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

# ==========================================
#              USER TRACKING
# ==========================================
async def track_user(user_id: int):
    """Track user in database."""
    if str(user_id) not in DATABASE["users"]:
        DATABASE["users"][str(user_id)] = {
            "id": user_id,
            "first_seen": datetime.now(TIMEZONE).isoformat(),
            "last_seen": datetime.now(TIMEZONE).isoformat(),
            "favorites": [],
            "ratings": {},
            "views": 0,
            "streak": 0,
            "last_task_date": None,
            "points": 0
        }
    else:
        DATABASE["users"][str(user_id)]["last_seen"] = datetime.now(TIMEZONE).isoformat()
        
        # Check streak
        today = get_today_yerevan()
        user = DATABASE["users"][str(user_id)]
        if user.get("last_task_date"):
            last_date = datetime.fromisoformat(user["last_task_date"]).date() if isinstance(user["last_task_date"], str) else user["last_task_date"]
            if (today - last_date).days == 1:
                user["streak"] = user.get("streak", 0) + 1
            elif (today - last_date).days > 1:
                user["streak"] = 1
        else:
            user["streak"] = 1
        
        user["last_task_date"] = today.isoformat()
    
    await save_db(DATABASE)

# ==========================================
#              FILE UPLOAD (EXISTING)
# ==========================================
@dp.message(F.document)
async def admin_doc_received(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("ℹ️ Отправка файлов доступна только администраторам.")
    
    doc = message.document
    file_id = doc.file_id
    default_name = message.caption if message.caption else doc.file_name
    
    await state.update_data(file_id=file_id, default_name=default_name)
    await state.set_state(FileUpload.selecting_path)
    
    builder = []
    for cat_key, cat_data in DATABASE["categories"].items():
        builder.append([InlineKeyboardButton(text=cat_data["title"], callback_data=f"a_cat:{cat_key}")])
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")])
    
    await message.answer(
        f"📥 **Получен файл:** `{default_name}`\n\nВыбери **Категорию** для сохранения:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )

@dp.callback_query(F.data == "a_cancel")
async def admin_cancel_upload(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Операция отменена.")
    await callback.answer()

@dp.callback_query(FileUpload.selecting_path, F.data.startswith("a_cat:"))
async def admin_select_cat(callback: types.CallbackQuery):
    cat_key = callback.data.split(":")[1]
    cat_data = DATABASE["categories"].get(cat_key)
    
    if not cat_data:
        return await callback.answer("❌ Категория не найдена.", show_alert=True)
    
    builder = []
    for b_key, b_data in cat_data["blocks"].items():
        builder.append([InlineKeyboardButton(text=b_data["title"], callback_data=f"a_blk:{cat_key}:{b_key}")])
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")])
    
    await callback.message.edit_text(f"📁 **{cat_data['title']}**\nВыбери **Блок**:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(FileUpload.selecting_path, F.data.startswith("a_blk:"))
async def admin_select_blk(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) < 3:
        return await callback.answer("❌ Ошибка данных.", show_alert=True)
    
    cat_key, b_key = parts[1], parts[2]
    block_data = DATABASE["categories"][cat_key]["blocks"].get(b_key)
    
    if not block_data:
        return await callback.answer("❌ Блок не найден.", show_alert=True)
    
    builder = []
    for t_key, t_data in block_data["topics"].items():
        builder.append([InlineKeyboardButton(text=f"• {t_data['title']}", callback_data=f"a_top:{cat_key}:{b_key}:{t_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"a_cat:{cat_key}")])
    
    await callback.message.edit_text(f"📁 **{block_data['title']}**\nВыбери **Тему**:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(FileUpload.selecting_path, F.data.startswith("a_top:"))
async def admin_select_top(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) < 4:
        return await callback.answer("❌ Ошибка данных.", show_alert=True)
    
    cat_key, b_key, t_key = parts[1], parts[2], parts[3]
    
    await state.update_data(cat_key=cat_key, b_key=b_key, t_key=t_key)
    await state.set_state(FileUpload.choosing_difficulty)
    
    data = await state.get_data()
    default_name = data.get("default_name")
    
    builder = [
        [InlineKeyboardButton(text="🟢 Easy", callback_data="diff:easy")],
        [InlineKeyboardButton(text="🟡 Medium", callback_data="diff:medium")],
        [InlineKeyboardButton(text="🔴 Hard", callback_data="diff:hard")],
        [InlineKeyboardButton(text="🔥 IMO", callback_data="diff:imo")],
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="diff:none")]
    ]
    
    await callback.message.edit_text(
        f"Выбери уровень сложности для файла **{default_name[:30]}**:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(FileUpload.choosing_difficulty, F.data.startswith("diff:"))
async def admin_select_difficulty(callback: types.CallbackQuery, state: FSMContext):
    difficulty = callback.data.split(":")[1]
    if difficulty == "none":
        difficulty = None
    
    await state.update_data(difficulty=difficulty)
    await state.set_state(FileUpload.choosing_tags)
    
    builder = [
        [InlineKeyboardButton(text="➕ Добавить теги", callback_data="tags:add")],
        [InlineKeyboardButton(text="⏭️ Далее", callback_data="tags:skip")]
    ]
    
    await callback.message.edit_text(
        "Хочешь добавить теги? (например: #geometry, #imo)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(FileUpload.choosing_tags, F.data == "tags:skip")
async def admin_skip_tags(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(tags=[])
    await state.set_state(FileUpload.waiting_for_caption)
    
    data = await state.get_data()
    default_name = data.get("default_name")
    
    builder = [
        [InlineKeyboardButton(text=f"📝 Оставить: {default_name[:20]}...", callback_data="a_skip_caption")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
    ]
    
    await callback.message.edit_text(
        "✍️ **Введите описание для файла:**\n\nОтправьте текстовое сообщение или нажмите кнопку:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(FileUpload.choosing_tags, F.data == "tags:add")
async def admin_add_tags(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(FileUpload.waiting_for_caption)
    await callback.message.edit_text("Введи теги через запятую (например: geometry, imo, algebra)")
    await callback.answer()

@dp.message(FileUpload.waiting_for_caption, F.text)
async def admin_process_caption_or_tags(message: types.Message, state: FSMContext):
    data = await state.get_data()
    state_name = (await state.get_state())
    
    if state_name == FileUpload.waiting_for_caption:
        custom_caption = message.text.strip()
        await state.update_data(caption=custom_caption)
        await admin_save_file(message, state)
    else:
        tags = [t.strip().lower().replace("#", "") for t in message.text.split(",")]
        await state.update_data(tags=tags)
        await state.set_state(FileUpload.waiting_for_caption)
        
        data = await state.get_data()
        default_name = data.get("default_name")
        
        builder = [
            [InlineKeyboardButton(text=f"📝 Оставить: {default_name[:20]}...", callback_data="a_skip_caption")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
        ]
        
        await message.answer(
            "✍️ **Введите описание для файла:**\n\nОтправьте текстовое сообщение или нажмите кнопку:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
        )

@dp.callback_query(FileUpload.waiting_for_caption, F.data == "a_skip_caption")
async def admin_skip_caption(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    default_name = data.get("default_name")
    
    await state.update_data(caption=default_name)
    await admin_save_file_from_callback(callback, state)

async def admin_save_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("file_id")
    caption = data.get("caption", data.get("default_name"))
    cat_key = data.get("cat_key")
    b_key = data.get("b_key")
    t_key = data.get("t_key")
    difficulty = data.get("difficulty")
    tags = data.get("tags", [])
    
    new_file = {
        "file_id": file_id,
        "caption": caption,
        "difficulty": difficulty,
        "tags": tags,
        "is_must_read": False,
        "uploaded_at": datetime.now(TIMEZONE).isoformat()
    }
    
    add_file_to_catalog(cat_key, b_key, t_key, new_file)
    await save_db(DATABASE)
    
    topic_title = DATABASE["categories"][cat_key]["blocks"][b_key]["topics"][t_key]["title"]
    await message.answer(
        f"✅ **Файл успешно сохранен!**\n\n"
        f"📁 `{DATABASE['categories'][cat_key]['title']}` ➔ "
        f"`{DATABASE['categories'][cat_key]['blocks'][b_key]['title']}` ➔ `{topic_title}`\n"
        f"📄 **Описание:** `{caption}`"
    )
    await state.clear()

async def admin_save_file_from_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("file_id")
    caption = data.get("caption", data.get("default_name"))
    cat_key = data.get("cat_key")
    b_key = data.get("b_key")
    t_key = data.get("t_key")
    difficulty = data.get("difficulty")
    tags = data.get("tags", [])
    
    new_file = {
        "file_id": file_id,
        "caption": caption,
        "difficulty": difficulty,
        "tags": tags,
        "is_must_read": False,
        "uploaded_at": datetime.now(TIMEZONE).isoformat()
    }
    
    add_file_to_catalog(cat_key, b_key, t_key, new_file)
    await save_db(DATABASE)
    
    topic_title = DATABASE["categories"][cat_key]["blocks"][b_key]["topics"][t_key]["title"]
    await callback.message.edit_text(
        f"✅ **Файл успешно сохранен!**\n\n"
        f"📁 `{DATABASE['categories'][cat_key]['title']}` ➔ "
        f"`{DATABASE['categories'][cat_key]['blocks'][b_key]['title']}` ➔ `{topic_title}`\n"
        f"📄 **Описание:** `{caption}`"
    )
    await state.clear()
    await callback.answer()

# ==========================================
#          CATALOG NAVIGATION (EXISTING)
# ==========================================
@dp.callback_query(F.data == "menu:main")
async def process_main_menu(callback: types.CallbackQuery):
    is_admin = callback.from_user.id in ADMIN_IDS
    await callback.message.edit_text(
        "📂 **Главное меню**",
        reply_markup=get_main_menu_keyboard(is_admin)
    )
    await callback.answer()

@dp.callback_query(F.data == "menu:catalog")
async def process_catalog_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📚 **Каталог файлов**\nВыбери раздел:",
        reply_markup=get_categories_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("cat:"))
async def process_category_click(callback: types.CallbackQuery):
    cat_key = callback.data.split(":")[1]
    cat_data = DATABASE["categories"].get(cat_key)
    
    if not cat_data:
        return await callback.answer("❌ Категория не найдена.", show_alert=True)
    
    builder = [[InlineKeyboardButton(text=b_data["title"], callback_data=f"blk:{cat_key}:{b_key}")]
               for b_key, b_data in cat_data["blocks"].items()]
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    
    await callback.message.edit_text(
        f"Раздел **{cat_data['title']}**.\nВыбери блок:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("blk:"))
async def process_block_click(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) < 3:
        return await callback.answer("❌ Ошибка.", show_alert=True)
    
    cat_key, b_key = parts[1], parts[2]
    block_data = DATABASE["categories"][cat_key]["blocks"].get(b_key)
    
    if not block_data:
        return await callback.answer("❌ Блок не найден.", show_alert=True)
    
    builder = [[InlineKeyboardButton(text=f"• {t_data['title']}", callback_data=f"top:{cat_key}:{b_key}:{t_key}")]
               for t_key, t_data in block_data["topics"].items()]
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cat:{cat_key}")])
    
    await callback.message.edit_text(
        f"Блок **{block_data['title']}**.\nВыбери тему:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("top:"))
async def process_topic_click(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) < 4:
        return await callback.answer("❌ Ошибка.", show_alert=True)
    
    cat_key, b_key, t_key = parts[1], parts[2], parts[3]
    topic_data = DATABASE["categories"][cat_key]["blocks"][b_key]["topics"].get(t_key)
    
    if not topic_data:
        return await callback.answer("❌ Тема не найдена.", show_alert=True)
    
    if not topic_data["files"]:
        return await callback.answer("📁 В этой теме пока нет файлов.", show_alert=True)
    
    builder = []
    for idx, item in enumerate(topic_data["files"]):
        btn_text = f"📄 {item['caption'][:30]}" + ("..." if len(item['caption']) > 30 else "")
        builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"file:{cat_key}:{b_key}:{t_key}:{idx}")])
    
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"blk:{cat_key}:{b_key}")])
    
    await callback.message.edit_text(
        f"Тема: **{topic_data['title']}**\n⬇️ Выбери файл для скачивания:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("file:"))
async def process_file_click(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) < 5:
        return await callback.answer("❌ Ошибка.", show_alert=True)
    
    cat_key, b_key, t_key = parts[1], parts[2], parts[3]
    try:
        file_idx = int(parts[4])
    except:
        return await callback.answer("❌ Ошибка индекса.", show_alert=True)
    
    topic_data = DATABASE["categories"][cat_key]["blocks"][b_key]["topics"].get(t_key)
    
    if not topic_data or file_idx >= len(topic_data["files"]):
        return await callback.answer("❌ Файл больше не доступен.", show_alert=True)
    
    file_item = topic_data["files"][file_idx]
    
    await track_user(callback.from_user.id)
    
    builder = [
        [InlineKeyboardButton(text="❤️ В избранное", callback_data=f"fav:add:{file_item['file_id']}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"top:{cat_key}:{b_key}:{t_key}")]
    ]
    
    await callback.answer("Отправляю файл... ⏳")
    await callback.message.answer_document(
        document=file_item["file_id"],
        caption=f"📄 {file_item['caption']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )

# ==========================================
#              DAILY TASK
# ==========================================
@dp.message(Command("task"))
async def cmd_task(message: types.Message):
    await track_user(message.from_user.id)
    
    today = get_today_yerevan().isoformat()
    task = DATABASE["daily_tasks"].get(today)
    
    if not task:
        return await message.answer("📁 На сегодня нет задачи.")
    
    DATABASE["users"][str(message.from_user.id)]["views"] = DATABASE["users"][str(message.from_user.id)].get("views", 0) + 1
    await save_db(DATABASE)
    
    builder = [
        [InlineKeyboardButton(text="⭐ 1", callback_data=f"rate:1:{today}"),
         InlineKeyboardButton(text="⭐ 2", callback_data=f"rate:2:{today}"),
         InlineKeyboardButton(text="⭐ 3", callback_data=f"rate:3:{today}"),
         InlineKeyboardButton(text="⭐ 4", callback_data=f"rate:4:{today}"),
         InlineKeyboardButton(text="⭐ 5", callback_data=f"rate:5:{today}")]
    ]
    
    if task.get("hints"):
        builder.append([InlineKeyboardButton(text="💡 Подсказки", callback_data=f"hint:{today}:0")])
    
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    
    ratings = task.get("ratings", {})
    if ratings:
        avg_rating = sum(ratings.values()) / len(ratings)
        await message.answer_photo(
            photo=task["photo_file_id"],
            caption=f"🎯 Задача дня #{today}\n\n{task['caption']}\n\n⭐ Средняя оценка: {avg_rating:.1f}/5\n👥 Оценили: {len(ratings)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
        )
    else:
        await message.answer_photo(
            photo=task["photo_file_id"],
            caption=f"🎯 Задача дня #{today}\n\n{task['caption']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
        )

@dp.callback_query(F.data == "menu:task")
async def menu_task(callback: types.CallbackQuery):
    await callback.message.delete()
    await cmd_task(callback.message)

@dp.callback_query(F.data.startswith("rate:"))
async def rate_task(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    rating = int(parts[1])
    date = parts[2]
    
    task = DATABASE["daily_tasks"].get(date)
    if not task:
        return await callback.answer("❌ Задача не найдена.", show_alert=True)
    
    user_id = str(callback.from_user.id)
    ratings = task.get("ratings", {})
    
    if user_id in ratings:
        old_rating = ratings[user_id]
        ratings[user_id] = rating
        await callback.answer(f"✅ Оценка обновлена: {old_rating} → {rating}")
    else:
        ratings[user_id] = rating
        await callback.answer(f"✅ Спасибо за оценку: {rating}!")
    
    task["ratings"] = ratings
    DATABASE["daily_tasks"][date] = task
    await save_db(DATABASE)
    
    avg_rating = sum(ratings.values()) / len(ratings)
    await callback.message.edit_caption(
        caption=f"🎯 Задача дня #{date}\n\n{task['caption']}\n\n⭐ Средняя оценка: {avg_rating:.1f}/5\n👥 Оценили: {len(ratings)}"
    )

@dp.callback_query(F.data.startswith("hint:"))
async def show_hint(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    date = parts[1]
    hint_idx = int(parts[2])
    
    task = DATABASE["daily_tasks"].get(date)
    if not task:
        return await callback.answer("❌ Задача не найдена.", show_alert=True)
    
    hints = task.get("hints", [])
    if hint_idx >= len(hints):
        return await callback.answer("❌ Подсказка не найдена.", show_alert=True)
    
    builder = []
    if hint_idx > 0:
        builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"hint:{date}:{hint_idx - 1}")])
    
    if hint_idx < len(hints) - 1:
        builder.append([InlineKeyboardButton(text="➡️ Далее", callback_data=f"hint:{date}:{hint_idx + 1}")])
    elif "solution" in task:
        builder.append([InlineKeyboardButton(text="✅ Решение", callback_data=f"sol:{date}")])
    
    await callback.message.edit_text(
        f"💡 **Подсказка {hint_idx + 1}:**\n\n{hints[hint_idx]}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("sol:"))
async def show_solution(callback: types.CallbackQuery):
    date = callback.data.split(":")[1]
    task = DATABASE["daily_tasks"].get(date)
    
    if not task or "solution" not in task:
        return await callback.answer("❌ Решение не найдено.", show_alert=True)
    
    await callback.message.edit_text(
        f"✅ **Решение:**\n\n{task['solution']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")]])
    )
    await callback.answer()

# ==========================================
#              MUST-READ
# ==========================================
@dp.callback_query(F.data == "menu:mustread")
async def show_mustread(callback: types.CallbackQuery):
    must_read_ids = DATABASE.get("must_read", [])
    
    if not must_read_ids:
        await callback.message.edit_text(
            "⭐ **Must-read пусто**",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
        )
        return await callback.answer()
    
    builder = []
    for file_id in must_read_ids:
        for cat_key, cat_data in DATABASE["categories"].items():
            for b_key, b_data in cat_data["blocks"].items():
                for t_key, t_data in b_data["topics"].items():
                    for idx, f in enumerate(t_data["files"]):
                        if f["file_id"] == file_id:
                            btn_text = f"📄 {f['caption'][:30]}"
                            builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"mr:{file_id}:{cat_key}:{b_key}:{t_key}:{idx}")])
    
    if not builder:
        await callback.message.edit_text(
            "⭐ **Must-read пусто**",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
        )
        return await callback.answer()
    
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    
    await callback.message.edit_text(
        "⭐ **Must-read файлы**",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("mr:"))
async def open_mustread_file(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    file_id, cat_key, b_key, t_key = parts[1], parts[2], parts[3], parts[4]
    try:
        file_idx = int(parts[5])
    except:
        return await callback.answer("❌ Ошибка.", show_alert=True)
    
    topic_data = DATABASE["categories"][cat_key]["blocks"][b_key]["topics"].get(t_key)
    
    if not topic_data or file_idx >= len(topic_data["files"]):
        return await callback.answer("❌ Файл не найден.", show_alert=True)
    
    file_item = topic_data["files"][file_idx]
    
    await track_user(callback.from_user.id)
    
    await callback.answer("Отправляю файл...")
    await callback.message.answer_document(
        document=file_item["file_id"],
        caption=f"📄 {file_item['caption']}⭐"
    )

# ==========================================
#              FAVORITES
# ==========================================
@dp.callback_query(F.data.startswith("fav:"))
async def manage_favorites(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    action = parts[1]
    file_id = parts[2]
    
    user_id = str(callback.from_user.id)
    if user_id not in DATABASE["users"]:
        DATABASE["users"][user_id] = {
            "id": int(user_id),
            "favorites": [],
            "ratings": {},
            "views": 0,
            "streak": 0,
            "points": 0
        }
    
    favorites = DATABASE["users"][user_id].get("favorites", [])
    
    if action == "add":
        if file_id not in favorites:
            favorites.append(file_id)
            await callback.answer("❤️ Добавлено в избранное!")
        else:
            await callback.answer("⚠️ Уже в избранном.")
    elif action == "remove":
        if file_id in favorites:
            favorites.remove(file_id)
            await callback.answer("💔 Удалено из избранного.")
        else:
            await callback.answer("⚠️ Не в избранном.")
    
    DATABASE["users"][user_id]["favorites"] = favorites
    await save_db(DATABASE)

@dp.callback_query(F.data == "menu:favorites")
async def show_favorites(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    user_data = DATABASE["users"].get(user_id, {})
    favorites = user_data.get("favorites", [])
    
    if not favorites:
        await callback.message.edit_text(
            "❤️ **Избранное пусто**",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
        )
        return await callback.answer()
    
    builder = []
    for file_id in favorites:
        for cat_key, cat_data in DATABASE["categories"].items():
            for b_key, b_data in cat_data["blocks"].items():
                for t_key, t_data in b_data["topics"].items():
                    for idx, f in enumerate(t_data["files"]):
                        if f["file_id"] == file_id:
                            btn_text = f"📄 {f['caption'][:30]}"
                            builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"fv:{file_id}:{cat_key}:{b_key}:{t_key}:{idx}")])
    
    if not builder:
        await callback.message.edit_text(
            "❤️ **Избранное пусто**",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
        )
        return await callback.answer()
    
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    
    await callback.message.edit_text(
        f"❤️ **Избранное** ({len(favorites)} файлов)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("fv:"))
async def open_favorite_file(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    file_id, cat_key, b_key, t_key = parts[1], parts[2], parts[3], parts[4]
    try:
        file_idx = int(parts[5])
    except:
        return await callback.answer("❌ Ошибка.", show_alert=True)
    
    topic_data = DATABASE["categories"][cat_key]["blocks"][b_key]["topics"].get(t_key)
    
    if not topic_data or file_idx >= len(topic_data["files"]):
        return await callback.answer("❌ Файл не найден.", show_alert=True)
    
    file_item = topic_data["files"][file_idx]
    
    await track_user(callback.from_user.id)
    
    user_id = str(callback.from_user.id)
    is_favorited = file_id in DATABASE["users"].get(user_id, {}).get("favorites", [])
    
    if is_favorited:
        btn_text = "💔 Убрать из избранного"
        btn_data = f"fav:remove:{file_id}"
    else:
        btn_text = "❤️ Добавить в избранное"
        btn_data = f"fav:add:{file_id}"
    
    builder = [
        [InlineKeyboardButton(text=btn_text, callback_data=btn_data)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:favorites")]
    ]
    
    await callback.answer("Отправляю файл...")
    await callback.message.answer_document(
        document=file_item["file_id"],
        caption=f"📄 {file_item['caption']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )

# ==========================================
#              RATING / LEADERBOARD
# ==========================================
@dp.message(Command("rating"))
@dp.callback_query(F.data == "menu:rating")
async def show_rating(update):
    # Handle both message and callback query
    if isinstance(update, types.Message):
        message = update
        is_message = True
    else:
        message = update.message
        is_message = False
    
    users = DATABASE.get("users", {})
    if not users:
        text = "🏆 **Рейтинг пуст**"
        if is_message:
            await message.answer(text, reply_markup=get_main_menu_keyboard(update.from_user.id in ADMIN_IDS))
        else:
            await update.message.edit_text(text, reply_markup=get_main_menu_keyboard(update.from_user.id in ADMIN_IDS))
            await update.answer()
        return
    
    sorted_users = sorted(
        users.items(),
        key=lambda x: x[1].get("points", 0),
        reverse=True
    )[:10]
    
    medals = ["🥇", "🥈", "🥉"]
    text = "🏆 **Топ рейтинга**\n\n"
    
    for idx, (user_id, user_data) in enumerate(sorted_users):
        medal = medals[idx] if idx < 3 else f"{idx + 1}."
        points = user_data.get("points", 0)
        text += f"{medal} ID {user_id}: {points} очков\n"
    
    if is_message:
        await message.answer(text, reply_markup=get_main_menu_keyboard(update.from_user.id in ADMIN_IDS))
    else:
        await update.message.edit_text(text, reply_markup=get_main_menu_keyboard(update.from_user.id in ADMIN_IDS))
        await update.answer()

# ==========================================
#              SEARCH
# ==========================================
@dp.callback_query(F.data == "menu:search")
async def start_search(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchState.searching)
    await callback.message.edit_text("🔎 Введи запрос для поиска (название, тег или категория):")
    await callback.answer()

@dp.message(SearchState.searching, F.text)
async def perform_search(message: types.Message, state: FSMContext):
    query = message.text.strip().lower()
    await state.clear()
    
    found_files = []
    for cat_data in DATABASE["categories"].values():
        for block_data in cat_data["blocks"].values():
            for topic_data in block_data["topics"].values():
                for f in topic_data["files"]:
                    if (query in topic_data["title"].lower() or
                        query in f["caption"].lower() or
                        any(query in tag for tag in f.get("tags", []))):
                        found_files.append((f, topic_data["title"]))
    
    if not found_files:
        await message.answer(
            "🔍 Ничего не найдено. Попробуй изменить запрос.",
            reply_markup=get_main_menu_keyboard(message.from_user.id in ADMIN_IDS)
        )
        return
    
    await message.answer(f"🔍 Найдено файлов: **{len(found_files)}**")
    
    for file_info, topic_name in found_files[:10]:
        await message.answer_document(
            document=file_info["file_id"],
            caption=f"📄 **{file_info['caption']}**\n📌 Тема: _{topic_name}_"
        )

# ==========================================
#              CHALLENGE / RANDOM
# ==========================================
@dp.message(Command("surprise"))
async def cmd_surprise(message: types.Message):
    await track_user(message.from_user.id)
    
    all_files = []
    for c_data in DATABASE["categories"].values():
        for b_data in c_data["blocks"].values():
            for t_data in b_data["topics"].values():
                for f in t_data["files"]:
                    all_files.append((f, t_data["title"]))
    
    if not all_files:
        return await message.answer("📁 В базе пока нет файлов.")
    
    selected_file, topic_name = random.choice(all_files)
    await message.answer(f"🎲 Случайный файл из темы: **{topic_name}**")
    await message.answer_document(
        document=selected_file["file_id"],
        caption=f"📄 {selected_file['caption']}"
    )

@dp.message(Command("challenge"))
async def cmd_challenge(message: types.Message):
    await track_user(message.from_user.id)
    
    builder = [
        [InlineKeyboardButton(text="🟢 Easy", callback_data="chal:easy")],
        [InlineKeyboardButton(text="🟡 Medium", callback_data="chal:medium")],
        [InlineKeyboardButton(text="🔴 Hard", callback_data="chal:hard")],
        [InlineKeyboardButton(text="🔥 IMO", callback_data="chal:imo")],
        [InlineKeyboardButton(text="🎲 Любой", callback_data="chal:any")]
    ]
    
    await message.answer("🎯 Выбери уровень сложности:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))

@dp.callback_query(F.data.startswith("chal:"))
async def select_challenge(callback: types.CallbackQuery):
    difficulty = callback.data.split(":")[1]
    
    all_files = []
    for c_data in DATABASE["categories"].values():
        for b_data in c_data["blocks"].values():
            for t_data in b_data["topics"].values():
                for f in t_data["files"]:
                    if difficulty == "any" or f.get("difficulty") == difficulty:
                        all_files.append((f, t_data["title"]))
    
    if not all_files:
        return await callback.answer(f"📁 Файлов с уровнем '{difficulty}' не найдено.", show_alert=True)
    
    selected_file, topic_name = random.choice(all_files)
    await callback.answer("Отправляю задачу...")
    await callback.message.answer_document(
        document=selected_file["file_id"],
        caption=f"🎯 Вызов: **{selected_file['caption']}**\n📌 Тема: _{topic_name}_"
    )

# ==========================================
#              ADMIN PANEL
# ==========================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("🔒 Доступ запрещен.")
    
    builder = [
        [InlineKeyboardButton(text="📤 Добавить файл", callback_data="admin:upload")],
        [InlineKeyboardButton(text="✏️ Управление файлами", callback_data="admin:manage_files")],
        [InlineKeyboardButton(text="🎯 Задача дня", callback_data="admin:task_menu")],
        [InlineKeyboardButton(text="⭐ Must-read", callback_data="admin:mustread_menu")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]
    ]
    
    await message.answer("👑 **Админ-панель**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))

@dp.callback_query(F.data == "admin:menu")
async def admin_menu(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    builder = [
        [InlineKeyboardButton(text="📤 Добавить файл", callback_data="admin:upload")],
        [InlineKeyboardButton(text="✏️ Управление файлами", callback_data="admin:manage_files")],
        [InlineKeyboardButton(text="🎯 Задача дня", callback_data="admin:task_menu")],
        [InlineKeyboardButton(text="⭐ Must-read", callback_data="admin:mustread_menu")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]
    ]
    
    await callback.message.edit_text("👑 **Админ-панель**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(F.data == "admin:upload")
async def admin_upload_menu(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    await callback.message.edit_text(
        "📤 **Загрузить файл**\n\nПожалуйста, отправь файл с подписью (опционально).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]])
    )
    await callback.answer()

# ==========================================
#              MANAGE FILES (EDIT/DELETE)
# ==========================================
@dp.callback_query(F.data == "admin:manage_files")
async def admin_manage_files(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    all_files = []
    for cat_key, cat_data in DATABASE["categories"].items():
        for b_key, b_data in cat_data["blocks"].items():
            for t_key, t_data in b_data["topics"].items():
                for idx, f in enumerate(t_data["files"]):
                    all_files.append({
                        "file_id": f["file_id"],
                        "caption": f["caption"],
                        "cat_key": cat_key,
                        "b_key": b_key,
                        "t_key": t_key,
                        "idx": idx
                    })
    
    if not all_files:
        await callback.message.edit_text(
            "✏️ **Управление файлами**\n\n📁 Нет файлов в базе.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]])
        )
        return await callback.answer()
    
    builder = []
    for f in all_files[:10]:
        btn_text = f"📄 {f['caption'][:25]}"
        builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"edit_file:{f['file_id']}")])
    
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")])
    
    await callback.message.edit_text(
        f"✏️ **Управление файлами** ({len(all_files)} файлов)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_file:"))
async def edit_file_menu(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    file_id = callback.data.split(":")[1]
    
    file_info = find_file_by_id(file_id)
    if not file_info:
        return await callback.answer("❌ Файл не найден.", show_alert=True)
    
    cat_key, b_key, t_key, idx = file_info
    file_data = DATABASE["categories"][cat_key]["blocks"][b_key]["topics"][t_key]["files"][idx]
    
    await state.update_data(
        file_id=file_id,
        cat_key=cat_key,
        b_key=b_key,
        t_key=t_key,
        idx=idx
    )
    
    builder = [
        [InlineKeyboardButton(text="📝 Изменить название", callback_data="edit:caption")],
        [InlineKeyboardButton(text="📁 Изменить разделы", callback_data="edit:category")],
        [InlineKeyboardButton(text="🏷 Изменить теги", callback_data="edit:tags")],
        [InlineKeyboardButton(text="🔧 Уровень сложности", callback_data="edit:difficulty")],
        [InlineKeyboardButton(text="⭐ Must-read", callback_data="edit:mustread")],
        [InlineKeyboardButton(text="🗑 Удалить файл", callback_data="edit:delete")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:manage_files")]
    ]
    
    await callback.message.edit_text(
        f"📄 **{file_data['caption']}**\n\nВыбери действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(F.data == "edit:caption")
async def edit_caption(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    await state.set_state(FileEdit.editing_caption)
    await callback.message.edit_text("✍️ Введи новое название для файла:")
    await callback.answer()

@dp.message(FileEdit.editing_caption, F.text)
async def save_new_caption(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cat_key, b_key, t_key, idx = data["cat_key"], data["b_key"], data["t_key"], data["idx"]
    
    new_caption = message.text.strip()
    DATABASE["categories"][cat_key]["blocks"][b_key]["topics"][t_key]["files"][idx]["caption"] = new_caption
    await save_db(DATABASE)
    
    await message.answer("✅ Название обновлено!")
    await state.clear()

@dp.callback_query(F.data == "edit:category")
async def edit_category(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    await state.set_state(FileEdit.choosing_new_category)
    
    builder = []
    for cat_key, cat_data in DATABASE["categories"].items():
        builder.append([InlineKeyboardButton(text=cat_data["title"], callback_data=f"newcat:{cat_key}")])
    
    await callback.message.edit_text(
        "📁 Выбери новую категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(FileEdit.choosing_new_category, F.data.startswith("newcat:"))
async def select_new_block(callback: types.CallbackQuery, state: FSMContext):
    cat_key = callback.data.split(":")[1]
    cat_data = DATABASE["categories"].get(cat_key)
    
    await state.update_data(new_cat_key=cat_key)
    await state.set_state(FileEdit.choosing_new_block)
    
    builder = []
    for b_key, b_data in cat_data["blocks"].items():
        builder.append([InlineKeyboardButton(text=b_data["title"], callback_data=f"newblk:{b_key}")])
    
    await callback.message.edit_text(
        "📁 Выбери новый блок:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(FileEdit.choosing_new_block, F.data.startswith("newblk:"))
async def select_new_topic(callback: types.CallbackQuery, state: FSMContext):
    b_key = callback.data.split(":")[1]
    data = await state.get_data()
    new_cat_key = data["new_cat_key"]
    
    block_data = DATABASE["categories"][new_cat_key]["blocks"].get(b_key)
    
    await state.update_data(new_b_key=b_key)
    await state.set_state(FileEdit.choosing_new_topic)
    
    builder = []
    for t_key, t_data in block_data["topics"].items():
        builder.append([InlineKeyboardButton(text=t_data["title"], callback_data=f"newtopic:{t_key}")])
    
    await callback.message.edit_text(
        "📌 Выбери новую тему:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(FileEdit.choosing_new_topic, F.data.startswith("newtopic:"))
async def confirm_move_file(callback: types.CallbackQuery, state: FSMContext):
    t_key = callback.data.split(":")[1]
    data = await state.get_data()
    
    old_cat_key, old_b_key, old_t_key = data["cat_key"], data["b_key"], data["t_key"]
    new_cat_key, new_b_key = data["new_cat_key"], data["new_b_key"]
    idx = data["idx"]
    
    file_item = DATABASE["categories"][old_cat_key]["blocks"][old_b_key]["topics"][old_t_key]["files"][idx]
    
    # Remove from old location
    DATABASE["categories"][old_cat_key]["blocks"][old_b_key]["topics"][old_t_key]["files"].pop(idx)
    
    # Add to new location
    DATABASE["categories"][new_cat_key]["blocks"][new_b_key]["topics"][t_key]["files"].append(file_item)
    
    await save_db(DATABASE)
    
    await callback.message.edit_text("✅ Файл перемещен в новую категорию!")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "edit:tags")
async def edit_tags(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    await state.set_state(FileEdit.editing_tags)
    await callback.message.edit_text("🏷 Введи теги через запятую (или оставь пусто для удаления):")
    await callback.answer()

@dp.message(FileEdit.editing_tags, F.text)
async def save_tags(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cat_key, b_key, t_key, idx = data["cat_key"], data["b_key"], data["t_key"], data["idx"]
    
    tags = [t.strip().lower().replace("#", "") for t in message.text.split(",") if t.strip()]
    DATABASE["categories"][cat_key]["blocks"][b_key]["topics"][t_key]["files"][idx]["tags"] = tags
    await save_db(DATABASE)
    
    await message.answer(f"✅ Теги обновлены: {', '.join(tags) if tags else '(удалены)'}")
    await state.clear()

@dp.callback_query(F.data == "edit:difficulty")
async def edit_difficulty(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    await state.set_state(FileEdit.editing_difficulty)
    
    builder = [
        [InlineKeyboardButton(text="🟢 Easy", callback_data="newdiff:easy")],
        [InlineKeyboardButton(text="🟡 Medium", callback_data="newdiff:medium")],
        [InlineKeyboardButton(text="🔴 Hard", callback_data="newdiff:hard")],
        [InlineKeyboardButton(text="🔥 IMO", callback_data="newdiff:imo")],
        [InlineKeyboardButton(text="⏸ Без уровня", callback_data="newdiff:none")]
    ]
    
    await callback.message.edit_text(
        "🔧 Выбери уровень сложности:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(FileEdit.editing_difficulty, F.data.startswith("newdiff:"))
async def save_difficulty(callback: types.CallbackQuery, state: FSMContext):
    difficulty = callback.data.split(":")[1]
    if difficulty == "none":
        difficulty = None
    
    data = await state.get_data()
    cat_key, b_key, t_key, idx = data["cat_key"], data["b_key"], data["t_key"], data["idx"]
    
    DATABASE["categories"][cat_key]["blocks"][b_key]["topics"][t_key]["files"][idx]["difficulty"] = difficulty
    await save_db(DATABASE)
    
    await callback.message.edit_text(f"✅ Уровень сложности обновлен!")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "edit:mustread")
async def toggle_mustread(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    data = await state.get_data()
    file_id = data.get("file_id")
    
    must_read_list = DATABASE.get("must_read", [])
    
    if file_id in must_read_list:
        must_read_list.remove(file_id)
        status = "☆ Обычный файл"
    else:
        must_read_list.append(file_id)
        status = "⭐ Must-read"
    
    DATABASE["must_read"] = must_read_list
    await save_db(DATABASE)
    
    await callback.message.edit_text(f"✅ Статус изменен: {status}")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "edit:delete")
async def delete_file(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    data = await state.get_data()
    cat_key, b_key, t_key, idx = data["cat_key"], data["b_key"], data["t_key"], data["idx"]
    file_id = data.get("file_id")
    
    # Remove from must_read if present
    if file_id in DATABASE.get("must_read", []):
        DATABASE["must_read"].remove(file_id)
    
    # Remove from catalog
    DATABASE["categories"][cat_key]["blocks"][b_key]["topics"][t_key]["files"].pop(idx)
    
    await save_db(DATABASE)
    
    await callback.message.edit_text("🗑 ✅ Файл удален!")
    await state.clear()
    await callback.answer()

# ==========================================
#              DAILY TASK ADMIN
# ==========================================
@dp.callback_query(F.data == "admin:task_menu")
async def admin_task_menu(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    builder = [
        [InlineKeyboardButton(text="➕ Добавить задачу", callback_data="task:add")],
        [InlineKeyboardButton(text="✏️ Изменить задачу", callback_data="task:edit")],
        [InlineKeyboardButton(text="🗑 Удалить задачу", callback_data="task:delete")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="task:stats")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]
    ]
    
    await callback.message.edit_text("🎯 **Управление задачами дня**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(F.data == "task:add")
async def task_add_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    await state.set_state(DailyTaskState.waiting_photo)
    await callback.message.edit_text("📷 Отправь фото для задачи:")
    await callback.answer()

@dp.message(DailyTaskState.waiting_photo, F.photo)
async def task_photo_received(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(DailyTaskState.waiting_caption)
    
    await message.answer("✍️ Введи условие/описание задачи:")

@dp.message(DailyTaskState.waiting_caption, F.text)
async def task_caption_received(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    caption = message.text.strip()
    await state.update_data(caption=caption)
    await state.set_state(DailyTaskState.waiting_date)
    
    await message.answer("📅 Введи дату (YYYY-MM-DD) или оставь пусто для сегодня:")

@dp.message(DailyTaskState.waiting_date, F.text)
async def task_date_received(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    date_str = message.text.strip()
    
    if not date_str:
        date_str = get_today_yerevan().isoformat()
    else:
        try:
            datetime.fromisoformat(date_str)
        except:
            return await message.answer("❌ Неверный формат даты. Используй YYYY-MM-DD")
    
    existing_task = DATABASE["daily_tasks"].get(date_str)
    
    if existing_task:
        await state.update_data(date=date_str)
        await state.set_state(DailyTaskState.waiting_photo)
        
        builder = [
            [InlineKeyboardButton(text="✅ Заменить", callback_data="task:confirm_replace")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="task:cancel")]
        ]
        await message.answer(
            f"⚠️ На дату {date_str} уже есть задача.\n\nХочешь её заменить?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
        )
    else:
        data = await state.get_data()
        photo_file_id = data["photo_file_id"]
        caption = data["caption"]
        
        task_id = f"task_{date_str}_{random.randint(1000, 9999)}"
        
        new_task = {
            "id": task_id,
            "date": date_str,
            "photo_file_id": photo_file_id,
            "caption": caption,
            "created_at": datetime.now(TIMEZONE).isoformat(),
            "ratings": {},
            "views": 0,
            "hints": [],
            "solution": None
        }
        
        DATABASE["daily_tasks"][date_str] = new_task
        await save_db(DATABASE)
        
        await message.answer(f"✅ Задача добавлена на {date_str}")
        await state.clear()

@dp.callback_query(F.data == "task:confirm_replace")
async def confirm_task_replace(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    data = await state.get_data()
    date_str = data["date"]
    photo_file_id = data["photo_file_id"]
    caption = data["caption"]
    
    task_id = f"task_{date_str}_{random.randint(1000, 9999)}"
    
    new_task = {
        "id": task_id,
        "date": date_str,
        "photo_file_id": photo_file_id,
        "caption": caption,
        "created_at": datetime.now(TIMEZONE).isoformat(),
        "ratings": {},
        "views": 0,
        "hints": [],
        "solution": None
    }
    
    DATABASE["daily_tasks"][date_str] = new_task
    await save_db(DATABASE)
    
    await callback.message.edit_text(f"✅ Задача на {date_str} обновлена")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "task:cancel")
async def cancel_task(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Операция отменена.")
    await callback.answer()

@dp.callback_query(F.data == "task:delete")
async def task_delete(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    tasks = DATABASE.get("daily_tasks", {})
    
    if not tasks:
        await callback.message.edit_text(
            "🎯 **Задач нет**",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:task_menu")]])
        )
        return await callback.answer()
    
    builder = []
    for date_str, task in list(tasks.items())[:10]:
        btn_text = f"📅 {date_str}"
        builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"taskdel:{date_str}")])
    
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:task_menu")])
    
    await callback.message.edit_text(
        "🗑 Выбери задачу для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("taskdel:"))
async def confirm_task_delete(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    date_str = callback.data.split(":")[1]
    
    if date_str in DATABASE["daily_tasks"]:
        DATABASE["daily_tasks"].pop(date_str)
        await save_db(DATABASE)
        await callback.message.edit_text(f"🗑 ✅ Задача от {date_str} удалена")
    else:
        await callback.message.edit_text("❌ Задача не найдена")
    
    await callback.answer()

@dp.callback_query(F.data == "task:stats")
async def task_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    tasks = DATABASE.get("daily_tasks", {})
    
    if not tasks:
        await callback.message.edit_text(
            "📊 **Статистика**\n\nЗадач нет",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:task_menu")]])
        )
        return await callback.answer()
    
    total_ratings = sum(len(task.get("ratings", {})) for task in tasks.values())
    avg_rating = 0
    if total_ratings > 0:
        all_ratings = []
        for task in tasks.values():
            all_ratings.extend(task.get("ratings", {}).values())
        avg_rating = sum(all_ratings) / len(all_ratings)
    
    text = f"""📊 **Статистика задач дня**

📅 Всего задач: {len(tasks)}
⭐ Всего оценок: {total_ratings}
⭐ Средняя оценка: {avg_rating:.2f}/5
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:task_menu")]])
    )
    await callback.answer()

# ==========================================
#              MUST-READ ADMIN
# ==========================================
@dp.callback_query(F.data == "admin:mustread_menu")
async def admin_mustread_menu(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    must_read_list = DATABASE.get("must_read", [])
    
    if not must_read_list:
        await callback.message.edit_text(
            "⭐ **Must-read пусто**",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]])
        )
        return await callback.answer()
    
    builder = []
    for file_id in must_read_list:
        for cat_key, cat_data in DATABASE["categories"].items():
            for b_key, b_data in cat_data["blocks"].items():
                for t_key, t_data in b_data["topics"].items():
                    for idx, f in enumerate(t_data["files"]):
                        if f["file_id"] == file_id:
                            btn_text = f"⭐ {f['caption'][:25]}"
                            builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_mr:{file_id}")])
    
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")])
    
    await callback.message.edit_text(
        f"⭐ **Must-read** ({len(must_read_list)} файлов)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_mr:"))
async def admin_mr_toggle(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    file_id = callback.data.split(":")[1]
    must_read_list = DATABASE.get("must_read", [])
    
    if file_id in must_read_list:
        must_read_list.remove(file_id)
        await callback.answer("☆ Удалено из Must-read")
    else:
        must_read_list.append(file_id)
        await callback.answer("⭐ Добавлено в Must-read")
    
    DATABASE["must_read"] = must_read_list
    await save_db(DATABASE)

# ==========================================
#              STATS
# ==========================================
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("🔒 Доступ запрещен.")
    
    await show_stats(message)

@dp.callback_query(F.data == "admin:stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    class MessageWrapper:
        def __init__(self, msg):
            self.message = msg
        
        async def answer(self, text, **kwargs):
            await self.message.edit_text(text, **kwargs)
    
    wrapper = MessageWrapper(callback.message)
    await show_stats(wrapper)
    await callback.answer()

async def show_stats(message_obj):
    users = DATABASE.get("users", {})
    must_read_list = DATABASE.get("must_read", [])
    tasks = DATABASE.get("daily_tasks", {})
    
    all_files = []
    for cat_data in DATABASE["categories"].values():
        for b_data in cat_data["blocks"].values():
            for t_data in b_data["topics"].values():
                all_files.extend(t_data["files"])
    
    total_ratings = sum(len(task.get("ratings", {})) for task in tasks.values())
    avg_rating = 0
    if total_ratings > 0:
        all_ratings = []
        for task in tasks.values():
            all_ratings.extend(task.get("ratings", {}).values())
        avg_rating = sum(all_ratings) / len(all_ratings)
    
    active_users = sum(1 for u in users.values() if u.get("views", 0) > 0)
    
    text = f"""📊 **Статистика**

👥 Пользователи: {len(users)}
📚 Всего файлов: {len(all_files)}
⭐ Must-read: {len(must_read_list)}
🎯 Задач дня: {len(tasks)}
⭐ Средняя оценка: {avg_rating:.2f}/5
🏆 Активных пользователей: {active_users}
"""
    
    await message_obj.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]])
    )

# ==========================================
#              BROADCAST
# ==========================================
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("🔒 Доступ запрещен.")
    
    await state.set_state(BroadcastState.waiting_message)
    await message.answer("📢 Введи сообщение для рассылки:")

@dp.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    await state.set_state(BroadcastState.waiting_message)
    await callback.message.edit_text("📢 Введи сообщение для рассылки:")
    await callback.answer()

@dp.message(BroadcastState.waiting_message, F.text)
async def broadcast_confirm(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    text = message.text.strip()
    await state.update_data(broadcast_text=text)
    await state.set_state(BroadcastState.confirm)
    
    builder = [
        [InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast:send")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")]
    ]
    
    await message.answer(
        f"Отправить это сообщение всем пользователям?\n\n{text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )

@dp.callback_query(BroadcastState.confirm, F.data == "broadcast:send")
async def broadcast_send(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("🔒 Доступ запрещен.", show_alert=True)
    
    data = await state.get_data()
    text = data["broadcast_text"]
    
    users = DATABASE.get("users", {})
    
    success = 0
    errors = 0
    
    for user_id_str in users.keys():
        try:
            user_id = int(user_id_str)
            await bot.send_message(user_id, text)
            success += 1
        except:
            errors += 1
    
    await callback.message.edit_text(
        f"✅ **Рассылка завершена**\n\n✅ Отправлено: {success}\n❌ Ошибок: {errors}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]])
    )
    
    await state.clear()
    await callback.answer()

@dp.callback_query(BroadcastState.confirm, F.data == "broadcast:cancel")
async def broadcast_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена.")
    await callback.answer()

# ==========================================
#              COMMANDS
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await track_user(message.from_user.id)
    
    is_admin = message.from_user.id in ADMIN_IDS
    
    await message.answer(
        "Здарова! ✌️\nЯ бот канала matham.\n\n"
        "🔎 **Поиск:** Просто напиши название темы или файла.\n"
        "📂 **Каталог:** Выбери раздел из меню ниже:",
        reply_markup=get_main_menu_keyboard(is_admin)
    )

@dp.message(F.text & ~F.text.startswith("/"))
async def global_search_handler(message: types.Message, state: FSMContext):
    if message.text.strip() in ["удиви меня", "surprise", "рандом"]:
        return await cmd_surprise(message)
    
    await state.set_state(SearchState.searching)
    await perform_search(message, state)

# ==========================================
#              WEB SERVER
# ==========================================
async def run_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Веб-сервер запущен на порту {port}")

# ==========================================
#              MAIN
# ==========================================
async def set_main_menu(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню 🚀"),
        BotCommand(command="task", description="Задача дня 🎯"),
        BotCommand(command="favorites", description="Избранное ❤️"),
        BotCommand(command="rating", description="Рейтинг 🏆"),
        BotCommand(command="challenge", description="Случайный материал 🎲"),
        BotCommand(command="surprise", description="Случайный файл 🎲"),
    ]
    
    if ADMIN_IDS:
        commands.extend([
            BotCommand(command="admin", description="Админ-панель 👑"),
            BotCommand(command="stats", description="Статистика 📊"),
            BotCommand(command="broadcast", description="Рассылка 📢"),
        ])
    
    await bot.set_my_commands(commands)

async def main():
    global DATABASE
    
    await run_web_server()
    
    # Check MongoDB
    try:
        await mongo_client.admin.command("ping")
        logger.info("✅ MongoDB connected")
    except Exception as e:
        logger.error(f"❌ MongoDB error: {e}")
        raise
    
    DATABASE = await load_db()
    logger.info(f"📦 Database loaded ({len(DATABASE.get('categories', {}))} categories)")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await set_main_menu(bot)
    logger.info("🚀 Bot started!")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
