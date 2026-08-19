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

ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

# --- MongoDB ---
MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "matham_bot")
mongo_client = AsyncIOMotorClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]
db_collection = mongo_db["catalog"]
DB_DOC_ID = "catalog_main"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==========================================
#        НОВАЯ СТРУКТУРА КАТАЛОГА
# ==========================================
DEFAULT_DATABASE = {
    "geometry": {
        "title": "📐 Геометрия",
        "blocks": {
            "planimetry_basic": {
                "title": "Планиметрия: Базовая конфигурация",
                "topics": {
                    "notable_points": {"title": "Замечательные точки треугольника", "files": []},
                    "euler_line": {"title": "Прямая Эйлера и окружность 9 точек", "files": []},
                    "ceva_menelaus": {"title": "Теоремы Чевы и Менелая", "files": []},
                    "ptolemy": {"title": "Вписанные/описанные четырёхугольники, теорема Птолемея", "files": []}
                }
            },
            "planimetry_circles": {
                "title": "Планиметрия: Окружности и степени точек",
                "topics": {
                    "power_of_point": {"title": "Степень точки относительно окружности", "files": []},
                    "radical_axis": {"title": "Радикальная ось и радикальный центр", "files": []},
                    "excircles": {"title": "Внеписанные окружности, лемма о трезубце", "files": []},
                    "apollonius": {"title": "Окружности Аполлония и теорема Монжа", "files": []}
                }
            },
            "geo_methods": {
                "title": "Геометрические методы и преобразования",
                "topics": {
                    "inversion": {"title": "Инверсия относительно окружности", "files": []},
                    "spiral_homothety": {"title": "Поворотная гомотетия и центральная симметрия", "files": []},
                    "auxiliary_circle": {"title": "Метод вспомогательной окружности", "files": []},
                    "mass_points": {"title": "Метод масс (барицентрические координаты) и векторы", "files": []}
                }
            },
            "projective": {
                "title": "Проективная геометрия",
                "topics": {
                    "harmonic": {"title": "Гармонические четвёрки и двойное отношение", "files": []},
                    "pole_polar": {"title": "Полюс и поляра", "files": []},
                    "pascal_desargues": {"title": "Теоремы Паскаля, Дезарга и Брианшона", "files": []}
                }
            },
            "stereometry": {
                "title": "Стереометрия",
                "topics": {
                    "cross_sections": {"title": "Построение сечений многогранников", "files": []},
                    "distances_angles": {"title": "Расстояния и углы в пространстве", "files": []},
                    "spheres": {"title": "Сферы, вписанные и описанные в пирамиды/призмы", "files": []}
                }
            }
        }
    },
    "number_theory": {
        "title": "🔢 Теория чисел",
        "blocks": {
            "divisibility": {
                "title": "Делимость и остатки",
                "topics": {
                    "euclid": {"title": "Алгоритм Евклида и свойства НОД/НОК", "files": []},
                    "fermat_euler": {"title": "Малая теорема Ферма и теорема Эйлера", "files": []},
                    "wilson": {"title": "Теорема Вильсона и функция Эйлера φ(n)", "files": []}
                }
            },
            "congruences": {
                "title": "Сравнения и диофантовы уравнения",
                "topics": {
                    "linear_congruences": {"title": "Линейные сравнения и Китайская теорема об остатках", "files": []},
                    "diophantine": {"title": "Линейные диофантовы уравнения (ax+by=c)", "files": []},
                    "pell": {"title": "Уравнение Пелля и цепные дроби", "files": []},
                    "primitive_roots": {"title": "Первообразные корни и показатели", "files": []}
                }
            },
            "quadratic": {
                "title": "Квадратичные сравнения",
                "topics": {
                    "legendre_jacobi": {"title": "Символ Лежандра и символ Якоби", "files": []},
                    "reciprocity": {"title": "Квадратичный закон взаимности Гаусса", "files": []}
                }
            },
            "special_nt": {
                "title": "Специальные методы",
                "topics": {
                    "p_adic": {"title": "p-адическая оценка (лемма v_p)", "files": []},
                    "dirichlet_convolution": {"title": "Мультипликативные функции и свёртка Дирихле", "files": []}
                }
            }
        }
    },
    "algebra": {
        "title": "🧮 Алгебра (классическая и олимпиадная)",
        "blocks": {
            "polynomials": {
                "title": "Многочлены",
                "topics": {
                    "horner_bezout": {"title": "Схема Горнера и теорема Безу", "files": []},
                    "vieta_higher": {"title": "Теорема Виета для высших степеней", "files": []},
                    "symmetric_poly": {"title": "Симметрические многочлены", "files": []},
                    "eisenstein": {"title": "Критерий Эйзенштейна (неприводимость)", "files": []},
                    "complex_roots": {"title": "Комплексные числа и корни из единицы", "files": []}
                }
            },
            "inequalities": {
                "title": "Неравенства",
                "topics": {
                    "am_gm": {"title": "AM-GM (среднее арифметическое и геометрическое)", "files": []},
                    "cauchy_schwarz": {"title": "Коши-Буняковский-Шварц (CBS)", "files": []},
                    "jensen": {"title": "Неравенство Йенсена и выпуклость", "files": []},
                    "holder_muirhead": {"title": "Неравенства Гёльдера и Мюрхеда", "files": []},
                    "sos_abel": {"title": "Методы SOS и подстановка Абеля", "files": []}
                }
            },
            "functional_seq": {
                "title": "Функциональные уравнения и последовательности",
                "topics": {
                    "linear_recurrence": {"title": "Линейные рекуррентные соотношения", "files": []},
                    "substitution_cauchy": {"title": "Метод подстановки и подстановки Коши", "files": []},
                    "injective_monotone": {"title": "Инъективность, сюръективность и монотонность", "files": []}
                }
            }
        }
    },
    "combinatorics": {
        "title": "🧩 Комбинаторика",
        "blocks": {
            "enumerative": {
                "title": "Перечислительная комбинаторика",
                "topics": {
                    "binomial": {"title": "Биномиальные коэффициенты и треугольник Паскаля", "files": []},
                    "inclusion_exclusion": {"title": "Принцип включений-исключений (PIE)", "files": []},
                    "catalan": {"title": "Числа Каталана", "files": []},
                    "stirling_bell": {"title": "Числа Стирлинга и Белла", "files": []}
                }
            },
            "graph_theory": {
                "title": "Теория графов",
                "topics": {
                    "handshake_euler_ham": {"title": "Лемма о рукопожатиях, эйлеровы и гамильтоновы циклы", "files": []},
                    "trees_cayley": {"title": "Деревья и формула Кэли", "files": []},
                    "bipartite_hall": {"title": "Двудольные графы и теорема Холла", "files": []},
                    "coloring_euler_formula": {"title": "Раскраска графов и формула Эйлера (V-E+F=2)", "files": []}
                }
            },
            "extremal": {
                "title": "Экстремальная комбинаторика",
                "topics": {
                    "pigeonhole": {"title": "Принцип Дирихле и его обобщения", "files": []},
                    "invariants": {"title": "Инварианты и полуинварианты", "files": []},
                    "ramsey": {"title": "Теорема Рамсея", "files": []},
                    "turan_sperner": {"title": "Теоремы Турана и Шпернера", "files": []}
                }
            },
            "generating_functions": {
                "title": "Производящие функции",
                "topics": {
                    "ogf_egf": {"title": "Обыкновенные и экспоненциальные производящие функции", "files": []},
                    "recurrence_via_gf": {"title": "Решение рекуррент через производящие функции", "files": []}
                }
            }
        }
    },
    "higher_math": {
        "title": "🎓 Матанализ и высшая математика",
        "blocks": {
            "calculus": {
                "title": "Математический анализ",
                "topics": {
                    "limits_series": {"title": "Пределы, производные, ряды Тейлора и Фурье", "files": []},
                    "integrals": {"title": "Неопределённые, определённые и кратные интегралы", "files": []},
                    "ode": {"title": "Обыкновенные дифференциальные уравнения (ОДУ)", "files": []}
                }
            },
            "linear_abstract_algebra": {
                "title": "Линейная и абстрактная алгебра",
                "topics": {
                    "matrices_slau": {"title": "Матрицы, определители, СЛАУ, векторные пространства", "files": []},
                    "groups_rings_fields": {"title": "Теория групп, колец и полей", "files": []},
                    "tensors": {"title": "Тензоры и полилинейная алгебра", "files": []}
                }
            },
            "higher_geo_topology": {
                "title": "Высшая геометрия и топология",
                "topics": {
                    "diff_geometry": {"title": "Дифференциальная геометрия и кривизна", "files": []},
                    "topology": {"title": "Общая и алгебраическая топология", "files": []}
                }
            },
            "complex_functional": {
                "title": "Комплексный и функциональный анализ",
                "topics": {
                    "tfkp": {"title": "ТФКП (голоморфные функции, интеграл Коши, вычеты)", "files": []},
                    "banach_hilbert": {"title": "Банаховы и Гильбертовы пространства", "files": []}
                }
            }
        }
    }
}

DATABASE = {}


async def load_db():
    doc = await db_collection.find_one({"_id": DB_DOC_ID})
    if doc is None:
        logger.info("В MongoDB нет каталога — создаю из DEFAULT_DATABASE")
        data = copy.deepcopy(DEFAULT_DATABASE)
        await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": data}}, upsert=True)
        return data
    return doc["data"]


async def save_db(db_data):
    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": db_data}}, upsert=True)


# --- FSM ДЛЯ АДМИНОВ (множественный выбор тем) ---
class FileUpload(StatesGroup):
    selecting_topics = State()
    waiting_for_caption = State()


def get_main_menu_keyboard():
    builder = [[InlineKeyboardButton(text=cat_data["title"], callback_data=f"cat:{cat_key}")]
               for cat_key, cat_data in DATABASE.items()]
    return InlineKeyboardMarkup(inline_keyboard=builder)


def _selected_set(data: dict) -> set:
    return set(data.get("selected", []))


def build_admin_categories_kb(selected: set):
    builder = []
    for cat_key, cat_data in DATABASE.items():
        builder.append([InlineKeyboardButton(text=cat_data["title"], callback_data=f"a_cat:{cat_key}")])
    n = len(selected)
    builder.append([InlineKeyboardButton(text=f"✅ Готово ({n} выбрано)", callback_data="a_done")])
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def build_admin_blocks_kb(cat_key: str, selected: set):
    cat_data = DATABASE[cat_key]
    builder = []
    for b_key, b_data in cat_data["blocks"].items():
        marked = sum(1 for t_key in b_data["topics"] if f"{cat_key}|{b_key}|{t_key}" in selected)
        prefix = f"({marked}) " if marked else ""
        builder.append([InlineKeyboardButton(text=f"{prefix}{b_data['title']}", callback_data=f"a_blk:{cat_key}:{b_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ К категориям", callback_data="a_backcats")])
    n = len(selected)
    builder.append([InlineKeyboardButton(text=f"✅ Готово ({n} выбрано)", callback_data="a_done")])
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def build_admin_topics_kb(cat_key: str, b_key: str, selected: set):
    block_data = DATABASE[cat_key]["blocks"][b_key]
    builder = []
    for t_key, t_data in block_data["topics"].items():
        code = f"{cat_key}|{b_key}|{t_key}"
        mark = "☑️" if code in selected else "▫️"
        builder.append([InlineKeyboardButton(text=f"{mark} {t_data['title']}", callback_data=f"a_toggle:{cat_key}:{b_key}:{t_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ К блокам", callback_data=f"a_cat:{cat_key}")])
    n = len(selected)
    builder.append([InlineKeyboardButton(text=f"✅ Готово ({n} выбрано)", callback_data="a_done")])
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


# ==========================================
#        АДМИН: ЗАГРУЗКА С МУЛЬТИВЫБОРОМ
# ==========================================
@dp.message(F.document)
async def admin_doc_received(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("ℹ️ Отправка файлов доступна только администраторам.")

    doc = message.document
    file_id = doc.file_id
    default_name = message.caption if message.caption else doc.file_name

    await state.update_data(file_id=file_id, default_name=default_name, selected=[])
    await state.set_state(FileUpload.selecting_topics)

    await message.answer(
        f"📥 **Получен файл:** `{default_name}`\n\n"
        f"Отметь **все разделы**, куда нужно добавить этот файл (можно несколько), "
        f"потом жми **✅ Готово**:",
        reply_markup=build_admin_categories_kb(set())
    )


@dp.callback_query(FileUpload.selecting_topics, F.data == "a_cancel")
@dp.callback_query(FileUpload.waiting_for_caption, F.data == "a_cancel")
async def admin_cancel_upload(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Загрузка файла отменена.")
    await callback.answer()


@dp.callback_query(FileUpload.selecting_topics, F.data == "a_backcats")
async def admin_back_to_categories(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = _selected_set(data)
    await callback.message.edit_text("Выбери **Категорию**:", reply_markup=build_admin_categories_kb(selected))
    await callback.answer()


@dp.callback_query(FileUpload.selecting_topics, F.data.startswith("a_cat:"))
async def admin_select_cat(callback: types.CallbackQuery, state: FSMContext):
    cat_key = callback.data.split(":")[1]
    data = await state.get_data()
    selected = _selected_set(data)
    cat_data = DATABASE[cat_key]
    await callback.message.edit_text(f"📁 **{cat_data['title']}**\nВыбери **Блок**:", reply_markup=build_admin_blocks_kb(cat_key, selected))
    await callback.answer()


@dp.callback_query(FileUpload.selecting_topics, F.data.startswith("a_blk:"))
async def admin_select_blk(callback: types.CallbackQuery, state: FSMContext):
    _, cat_key, b_key = callback.data.split(":")
    data = await state.get_data()
    selected = _selected_set(data)
    block_data = DATABASE[cat_key]["blocks"][b_key]
    await callback.message.edit_text(
        f"📁 **{block_data['title']}**\nОтметь темы (можно несколько):",
        reply_markup=build_admin_topics_kb(cat_key, b_key, selected)
    )
    await callback.answer()


@dp.callback_query(FileUpload.selecting_topics, F.data.startswith("a_toggle:"))
async def admin_toggle_topic(callback: types.CallbackQuery, state: FSMContext):
    _, cat_key, b_key, t_key = callback.data.split(":")
    code = f"{cat_key}|{b_key}|{t_key}"

    data = await state.get_data()
    selected = _selected_set(data)
    if code in selected:
        selected.discard(code)
    else:
        selected.add(code)
    await state.update_data(selected=list(selected))

    await callback.message.edit_reply_markup(reply_markup=build_admin_topics_kb(cat_key, b_key, selected))
    await callback.answer()


@dp.callback_query(FileUpload.selecting_topics, F.data == "a_done")
async def admin_selection_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = _selected_set(data)

    if not selected:
        return await callback.answer("⚠️ Сначала отметь хотя бы одну тему.", show_alert=True)

    await state.set_state(FileUpload.waiting_for_caption)
    default_name = data.get("default_name")

    lines = []
    for code in sorted(selected):
        cat_key, b_key, t_key = code.split("|")
        t_title = DATABASE[cat_key]["blocks"][b_key]["topics"][t_key]["title"]
        lines.append(f"• {t_title}")
    summary = "\n".join(lines)

    builder = [
        [InlineKeyboardButton(text=f"📝 Оставить: {default_name[:20]}...", callback_data="a_skip_caption")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
    ]

    await callback.message.edit_text(
        f"✅ Выбрано разделов: **{len(selected)}**\n{summary}\n\n"
        f"✍️ Отправь описание файла текстом, или оставь имя по умолчанию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()


async def _save_file_to_selected(state: FSMContext, caption: str):
    data = await state.get_data()
    file_id = data.get("file_id")
    selected = _selected_set(data)

    for code in selected:
        cat_key, b_key, t_key = code.split("|")
        DATABASE[cat_key]["blocks"][b_key]["topics"][t_key]["files"].append({"file_id": file_id, "caption": caption})

    await save_db(DATABASE)
    return selected


@dp.callback_query(FileUpload.waiting_for_caption, F.data == "a_skip_caption")
async def admin_skip_caption(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    default_name = data.get("default_name")
    selected = await _save_file_to_selected(state, default_name)

    lines = []
    for code in sorted(selected):
        cat_key, b_key, t_key = code.split("|")
        lines.append(f"• {DATABASE[cat_key]['title']} ➔ {DATABASE[cat_key]['blocks'][b_key]['title']} ➔ {DATABASE[cat_key]['blocks'][b_key]['topics'][t_key]['title']}")
    summary = "\n".join(lines)

    await callback.message.edit_text(f"✅ **Файл сохранён в {len(selected)} раздел(ов)!**\n\n{summary}\n\n📄 **Описание:** `{default_name}`")
    await state.clear()
    await callback.answer()


@dp.message(FileUpload.waiting_for_caption, F.text)
async def admin_save_custom_caption(message: types.Message, state: FSMContext):
    custom_caption = message.text.strip()
    selected = await _save_file_to_selected(state, custom_caption)

    lines = []
    for code in sorted(selected):
        cat_key, b_key, t_key = code.split("|")
        lines.append(f"• {DATABASE[cat_key]['title']} ➔ {DATABASE[cat_key]['blocks'][b_key]['title']} ➔ {DATABASE[cat_key]['blocks'][b_key]['topics'][t_key]['title']}")
    summary = "\n".join(lines)

    await message.answer(f"✅ **Файл сохранён в {len(selected)} раздел(ов)!**\n\n{summary}\n\n📄 **Описание:** `{custom_caption}`")
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
