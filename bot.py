import logging
import random
import os
import copy
import asyncio
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

# Чтение списка админов (через запятую)
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

# --- MongoDB ---
MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "matham_bot")
mongo_client = AsyncIOMotorClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]
db_collection = mongo_db["catalog"]
DB_DOC_ID = "catalog_main"  # фиксированный _id — вся база хранится одним документом

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- СТРУКТУРА БАЗЫ ДАННЫХ ПО УМОЛЧАНИЮ (используется только при первом запуске) ---
DEFAULT_DATABASE = {
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
}

# Глобальный кэш в памяти — читаем из Mongo один раз при старте,
# при каждом изменении пишем и в кэш, и в Mongo.
DATABASE = {}


async def load_db():
    """Читает базу из MongoDB. Если документа ещё нет — создаёт его из DEFAULT_DATABASE."""
    doc = await db_collection.find_one({"_id": DB_DOC_ID})
    if doc is None:
        logger.info("В MongoDB нет каталога — создаю из DEFAULT_DATABASE")
        data = copy.deepcopy(DEFAULT_DATABASE)
        await db_collection.update_one(
            {"_id": DB_DOC_ID},
            {"$set": {"data": data}},
            upsert=True
        )
        return data
    return doc["data"]


async def save_db(db_data):
    """Полностью перезаписывает документ каталога в MongoDB."""
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {"data": db_data}},
        upsert=True
    )


# --- FSM ДЛЯ АДМИНОВ ---
class FileUpload(StatesGroup):
    selecting_path = State()
    waiting_for_caption = State()


def get_main_menu_keyboard():
    builder = []
    for cat_key, cat_data in DATABASE.items():
        builder.append([InlineKeyboardButton(text=cat_data["title"], callback_data=f"cat:{cat_key}")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


# ==========================================
#        АДМИН: ИНТЕРАКТИВНОЕ ДОБАВЛЕНИЕ
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
    for cat_key, cat_data in DATABASE.items():
        builder.append([InlineKeyboardButton(text=cat_data["title"], callback_data=f"a_cat:{cat_key}")])
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")])

    await message.answer(
        f"📥 **Получен файл:** `{default_name}`\n\nВыбери **Категорию** для сохранения:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )


@dp.callback_query(FileUpload.selecting_path, F.data == "a_cancel")
@dp.callback_query(FileUpload.waiting_for_caption, F.data == "a_cancel")
async def admin_cancel_upload(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Загрузка файла отменена.")
    await callback.answer()


@dp.callback_query(FileUpload.selecting_path, F.data.startswith("a_cat:"))
async def admin_select_cat(callback: types.CallbackQuery):
    cat_key = callback.data.split(":")[1]
    cat_data = DATABASE[cat_key]

    builder = []
    for b_key, b_data in cat_data["blocks"].items():
        builder.append([InlineKeyboardButton(text=b_data["title"], callback_data=f"a_blk:{cat_key}:{b_key}")])
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")])

    await callback.message.edit_text(f"📁 **{cat_data['title']}**\nВыбери **Блок**:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(FileUpload.selecting_path, F.data.startswith("a_blk:"))
async def admin_select_blk(callback: types.CallbackQuery):
    _, cat_key, b_key = callback.data.split(":")
    block_data = DATABASE[cat_key]["blocks"][b_key]

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
    default_name = data.get("default_name")

    builder = [
        [InlineKeyboardButton(text=f"📝 Оставить: {default_name[:20]}...", callback_data="a_skip_caption")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
    ]

    await callback.message.edit_text(
        f"✍️ **Введите описание для файла:**\n\n"
        f"Отправьте текстовое сообщение с понятным названием или описанием файла.\n"
        f"Или нажмите кнопку ниже, чтобы оставить имя файла по умолчанию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()


@dp.callback_query(FileUpload.waiting_for_caption, F.data == "a_skip_caption")
async def admin_skip_caption(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    file_id, default_name = data.get("file_id"), data.get("default_name")
    cat_key, b_key, t_key = data.get("cat_key"), data.get("b_key"), data.get("t_key")

    new_file = {"file_id": file_id, "caption": default_name}
    DATABASE[cat_key]["blocks"][b_key]["topics"][t_key]["files"].append(new_file)
    await save_db(DATABASE)

    topic_title = DATABASE[cat_key]["blocks"][b_key]["topics"][t_key]["title"]
    await callback.message.edit_text(
        f"✅ **Файл сохранен!**\n\n"
        f"📁 `{DATABASE[cat_key]['title']}` ➔ `{DATABASE[cat_key]['blocks'][b_key]['title']}` ➔ `{topic_title}`\n"
        f"📄 **Описание:** `{default_name}`"
    )
    await state.clear()
    await callback.answer()


@dp.message(FileUpload.waiting_for_caption, F.text)
async def admin_save_custom_caption(message: types.Message, state: FSMContext):
    custom_caption = message.text.strip()
    data = await state.get_data()

    file_id = data.get("file_id")
    cat_key, b_key, t_key = data.get("cat_key"), data.get("b_key"), data.get("t_key")

    new_file = {"file_id": file_id, "caption": custom_caption}
    DATABASE[cat_key]["blocks"][b_key]["topics"][t_key]["files"].append(new_file)
    await save_db(DATABASE)

    topic_title = DATABASE[cat_key]["blocks"][b_key]["topics"][t_key]["title"]
    await message.answer(
        f"✅ **Файл успешно сохранен!**\n\n"
        f"📁 `{DATABASE[cat_key]['title']}` ➔ `{DATABASE[cat_key]['blocks'][b_key]['title']}` ➔ `{topic_title}`\n"
        f"📄 **Описание:** `{custom_caption}`"
    )
    await state.clear()


# ==========================================
#   ПОЛЬЗОВАТЕЛЬ: 4-УРОВНЕВАЯ НАВИГАЦИЯ
# ==========================================

@dp.callback_query(F.data.startswith("cat:"))
async def process_category_click(callback: types.CallbackQuery):
    cat_key = callback.data.split(":")[1]
    cat_data = DATABASE.get(cat_key)

    builder = [[InlineKeyboardButton(text=b_data["title"], callback_data=f"blk:{cat_key}:{b_key}")]
               for b_key, b_data in cat_data["blocks"].items()]
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])

    await callback.message.edit_text(f"Раздел **{cat_data['title']}**.\nВыбери блок:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("blk:"))
async def process_block_click(callback: types.CallbackQuery):
    _, cat_key, b_key = callback.data.split(":")
    block_data = DATABASE[cat_key]["blocks"][b_key]

    builder = [[InlineKeyboardButton(text=f"• {t_data['title']}", callback_data=f"top:{cat_key}:{b_key}:{t_key}")]
               for t_key, t_data in block_data["topics"].items()]
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cat:{cat_key}")])

    await callback.message.edit_text(f"Блок **{block_data['title']}**.\nВыбери тему:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("top:"))
async def process_topic_click(callback: types.CallbackQuery):
    _, cat_key, b_key, t_key = callback.data.split(":")
    topic_data = DATABASE[cat_key]["blocks"][b_key]["topics"][t_key]

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
    _, cat_key, b_key, t_key, file_idx = callback.data.split(":")
    file_idx = int(file_idx)

    topic_data = DATABASE[cat_key]["blocks"][b_key]["topics"][t_key]

    if file_idx >= len(topic_data["files"]):
        return await callback.answer("❌ Файл больше не доступен.", show_alert=True)

    file_item = topic_data["files"][file_idx]

    await callback.answer("Отправляю файл... ⏳")
    await callback.message.answer_document(document=file_item["file_id"], caption=f"📄 {file_item['caption']}")


@dp.callback_query(F.data == "menu:main")
async def process_back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text("📂 **Каталог файлов**\nВыбери раздел:", reply_markup=get_main_menu_keyboard())
    await callback.answer()


# ==========================================
#     КОМАНДЫ И ГЛОБАЛЬНЫЙ ПОИСК
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Здарова! ✌️\nЯ бот канала matham.\n\n"
        "🔎 **Поиск:** Просто напиши название темы или файла.\n"
        "📂 **Каталог:** Выбери раздел из меню ниже:",
        reply_markup=get_main_menu_keyboard()
    )


@dp.message(Command("surprise"))
async def cmd_surprise(message: types.Message):
    all_files = []
    for c_data in DATABASE.values():
        for b_data in c_data["blocks"].values():
            for t_data in b_data["topics"].values():
                for f in t_data["files"]:
                    all_files.append((f, t_data["title"]))

    if not all_files:
        return await message.answer("📁 В базе пока нет файлов.")

    selected_file, topic_name = random.choice(all_files)
    await message.answer(f"🎲 Случайный файл из темы: **{topic_name}**")
    await message.answer_document(document=selected_file["file_id"], caption=f"📄 {selected_file['caption']}")


@dp.message(F.text & ~F.text.startswith("/"))
async def global_search_handler(message: types.Message):
    query = message.text.strip().lower()
    if query in ["удиви меня", "surprise", "рандом"]:
        return await cmd_surprise(message)

    found_files = []
    for cat_data in DATABASE.values():
        for block_data in cat_data["blocks"].values():
            for topic_data in block_data["topics"].values():
                for f in topic_data["files"]:
                    if query in topic_data["title"].lower() or query in f["caption"].lower():
                        found_files.append((f, topic_data["title"]))

    if not found_files:
        return await message.answer("🔍 Ничего не найдено. Попробуй изменить запрос или воспользуйся меню:", reply_markup=get_main_menu_keyboard())

    await message.answer(f"🔍 Найдено файлов: **{len(found_files)}**")
    for file_info, topic_name in found_files[:10]:
        await message.answer_document(
            document=file_info["file_id"],
            caption=f"📄 **{file_info['caption']}**\n📌 Тема: _{topic_name}_"
        )


# ==========================================
#        ЗАПУСК СЕРВЕРА И БОТА
# ==========================================
async def set_main_menu(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню 🚀"),
        BotCommand(command="surprise", description="Случайный файл 🎲")
    ])


async def run_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Веб-сервер запущен на порту {port}")


async def main():
    global DATABASE

    await run_web_server()

    # Проверяем подключение к MongoDB сразу, чтобы упасть с понятной ошибкой,
    # если MONGO_URI неверный, а не тихо использовать пустую базу
    await mongo_client.admin.command("ping")
    logger.info("✅ Подключение к MongoDB установлено")

    DATABASE = await load_db()
    logger.info(f"📦 Каталог загружен из MongoDB ({len(DATABASE)} категорий)")

    await bot.delete_webhook(drop_pending_updates=True)
    await set_main_menu(bot)
    logger.info("🚀 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
