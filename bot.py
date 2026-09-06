import asyncio
import copy
import html
import io
import json
import logging
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, StateFilter
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
from aiohttp import ClientSession, ClientTimeout, web
from motor.motor_asyncio import AsyncIOMotorClient

# Safe import for PDF extraction
try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    try:
        from PyPDF2 import PdfReader
        PYPDF_AVAILABLE = True
    except ImportError:
        PYPDF_AVAILABLE = False

# ============================================================
# CONFIG & LOGGING
# ============================================================

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("DEBUG", "0").lower() in ("1", "true", "yes") else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [
    int(x.strip())
    for x in ADMIN_IDS_RAW.split(",")
    if x.strip().isdigit()
]

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "matham_bot")
YEREVAN_TZ = timezone(timedelta(hours=4))

# AI API Keys (Gemini / OpenAI)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

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
# DEFAULT DATABASE STATE
# ============================================================

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
            "title": "🔗 Полезные сайты и базы задач",
            "items": []
        },
        "useful_videos": {
            "title": "🎥 Видеолекции и каналы",
            "items": []
        }
    },
    "must_read": {
        "title": "⭐ Must-read",
        "files": []
    },
    "daily_tasks": {},
    "users": {},
    "settings": {}
}

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

async def safe_send_or_edit(target, text: str, reply_markup=None, photo_id=None, parse_mode=ParseMode.HTML):
    """Safely edits text or deletes and sends a new message to prevent Telegram UI crashes."""
    is_message = isinstance(target, types.Message)
    if is_message:
        if photo_id:
            return await target.answer_photo(photo=photo_id, caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
        return await target.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)

    # If target is CallbackQuery
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

async def track_user_activity(user_id: int, username: str = ""):
    uid_str = str(user_id)
    today = get_yerevan_date()
    yesterday = (datetime.now(YEREVAN_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    DATABASE.setdefault("users", {})
    if uid_str not in DATABASE["users"]:
        user_data = {
            "username": username,
            "streak": 1,
            "last_active": today,
            "score": 0,
            "favorites": [],
            "opened_tasks": []
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

    user.setdefault("favorites", [])
    user.setdefault("opened_tasks", [])

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
    if uid_str not in DATABASE.get("users", {}):
        await track_user_activity(user_id)

    DATABASE["users"][uid_str]["score"] = (
        DATABASE["users"][uid_str].get("score", 0) + points
    )
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {f"data.users.{uid_str}.score": DATABASE["users"][uid_str]["score"]}}
    )

# ============================================================
# DATABASE LOAD & MIGRATIONS
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

    data = doc.get("data", copy.deepcopy(DEFAULT_STATE))

    for key, value in DEFAULT_STATE.items():
        if key not in data:
            data[key] = copy.deepcopy(value)

    # Categories & files migration
    for cat_key, default_cat in DEFAULT_STATE["categories"].items():
        if cat_key not in data["categories"]:
            data["categories"][cat_key] = copy.deepcopy(default_cat)
        cat_data = data["categories"][cat_key]
        cat_data.setdefault("title", default_cat["title"])
        cat_data.setdefault("files", [])
        for f in cat_data["files"]:
            f.setdefault("file_unique_id", str(uuid.uuid4()))
            f.setdefault("tags", [])
            f.setdefault("difficulty", "medium")
            f.setdefault("must_read", False)
            f.setdefault("summary", "")
            f.setdefault("target_audience", "")

    # Links migration
    if "links" not in data:
        data["links"] = copy.deepcopy(DEFAULT_STATE["links"])
    for sec_key, default_sec in DEFAULT_STATE["links"].items():
        if sec_key not in data["links"]:
            data["links"][sec_key] = copy.deepcopy(default_sec)
        sec_data = data["links"][sec_key]
        sec_data.setdefault("title", default_sec["title"])
        sec_data.setdefault("items", [])

    # Users migration
    for uid, user in data["users"].items():
        user.setdefault("username", "")
        user.setdefault("streak", 1)
        user.setdefault("last_active", get_yerevan_date())
        user.setdefault("score", 0)
        user.setdefault("favorites", [])
        user.setdefault("opened_tasks", [])

    # Daily task migration
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
# PDF EXTRACTION & DEEP AI INSPECTOR
# ============================================================

def extract_pdf_first_pages_text(file_bytes: bytes, max_pages: int = 6) -> str:
    """Extracts clean text from the first N pages of a PDF."""
    if not PYPDF_AVAILABLE or not file_bytes:
        return ""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        num_pages = len(reader.pages)
        pages_to_read = min(num_pages, max_pages)

        extracted_text = []
        for i in range(pages_to_read):
            page_text = reader.pages[i].extract_text() or ""
            if page_text.strip():
                cleaned = re.sub(r'\s+', ' ', page_text).strip()
                extracted_text.append(f"--- СТРАНИЦА {i+1} ---\n{cleaned}")

        full_text = "\n\n".join(extracted_text)
        return full_text[:9000]
    except Exception as e:
        logger.error("Failed to extract PDF text: %s", e)
        return ""

async def download_file_bytes(file_id: str) -> bytes:
    """Downloads Telegram file into memory buffer."""
    try:
        tg_file = await bot.get_file(file_id)
        file_stream = io.BytesIO()
        await bot.download_file(tg_file.file_path, destination=file_stream)
        return file_stream.getvalue()
    except Exception as e:
        logger.error("Error downloading file %s: %s", file_id, e)
        return b""

async def call_llm_api(prompt: str, system_prompt: str = "") -> str:
    """Calls Gemini or OpenAI LLM API with high reliability."""
    if GEMINI_API_KEY:
        models = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
        for m in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": (f"{system_prompt}\n\n" if system_prompt else "") + prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500}
            }
            try:
                timeout = ClientTimeout(total=20)
                async with ClientSession(timeout=timeout) as session:
                    async with session.post(url, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            candidates = data.get("candidates", [])
                            if candidates:
                                return candidates[0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                logger.error("Gemini model %s error: %s", m, e)

    if OPENAI_API_KEY:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt or "Ты ведущий профессор и методист олимпиадной математики."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 1500
        }
        try:
            timeout = ClientTimeout(total=20)
            async with ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error("OpenAI API error: %s", e)

    return ""

def clean_filename_title(raw_name: str) -> str:
    """Clean technical filenames to human readable form."""
    name = os.path.splitext(raw_name)[0]
    name = re.sub(r'[_+.-]', ' ', name)
    name = re.sub(r'\b(pdf|djvu|book|scan|final|v\d+|\d{4})\b', '', name, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', name).strip().title()

def generate_smart_individual_summary(title: str, text: str, cat_key: str) -> str:
    """Generates unique, rich fallback descriptions for books when LLM is offline."""
    t_lower = (title + " " + text).lower()
    
    if "прасолов" in t_lower:
        if "планиметр" in t_lower or "геометр" in t_lower:
            return "Легендарный задачник В. В. Прасолова по планиметрии. Содержит подробную теорию, методы геометрических преобразований и свыше 1000 олимпиадных задач с полными решениями."
        if "алгебр" in t_lower or "многочлен" in t_lower:
            return "Фундаментальный труд В. В. Прасолова по алгебре, многочленам и теории чисел для углубленного изучения и подготовки к олимпиадам высшего уровня."
    
    if "шарыгин" in t_lower:
        return "Классическое пособие И. Ф. Шарыгина по геометрии. Учит нестандартному геометрическому мышлению, дополнительным построениям и ключевым конфигурациям."
        
    if "titu" in t_lower or "andreescu" in t_lower:
        if "number theory" in t_lower or "чисел" in t_lower:
            return "Знаменитый олимпиадный задачник Титу Андрееску по теории чисел: диофантовы уравнения, свойства простых чисел, модульная арифметика и задачи уровня IMO."
        return "Олимпиадный сборник Титу Андрееску: передовые методы решения сложных алгебраических и комбинаторных задач международных олимпиад."

    if "гордин" in t_lower:
        return "Качественное олимпиадное пособие Р. К. Гордина по планиметрии для 7-9 классов: пошаговое освоение от базовых теорем до уровня финала Всероса."

    if "мерзляк" in t_lower or "полонский" in t_lower:
        return "Учебное пособие А. Г. Мерзляка: систематизированный курс с большим количеством разноуровневых упражнений и доказательств."

    if "сканави" in t_lower:
        return "Сборник задач под редакцией М. И. Сканави: эталонный задачник для глубокой отработки алгебры, тригонометрии и уравнений."

    # Subject-based dynamic description
    if cat_key == "geometry":
        return f"Сборник по геометрии «{title}»: теоретические основы, свойства фигур, ключевые леммы и олимпиадные задачи на доказательство и построение."
    elif cat_key == "number_theory":
        return f"Задачник по теории чисел «{title}»: свойства делимости, алгоритм Евклида, простые числа, сравнения и диофантовы уравнения."
    elif cat_key == "algebra":
        return f"Пособие по алгебре «{title}»: методы решения систем, многочлены, классические неравенства (Коши, Коши-Буняковского) и функциональные уравнения."
    elif cat_key == "combinatorics":
        return f"Сборник по комбинаторике «{title}»: принцип Дирихле, инварианты, теория графов, комбинаторная геометрия и турниры."
    elif cat_key == "higher_math":
        return f"Курс высшей математики «{title}»: математический анализ, дифференциальное и интегральное исчисление для олимпиадников и студентов."
    
    return f"Учебный материал «{title}»: детальный разбор олимпиадных тем, теоретические справки и задачи для самостоятельного решения."

async def analyze_document_with_ai(file_bytes: bytes, original_name: str) -> dict:
    """
    Analyzes first pages of PDF and returns high-accuracy metadata.
    """
    pdf_text = extract_pdf_first_pages_text(file_bytes, max_pages=6)
    fallback_title = clean_filename_title(original_name)

    prompt = f"""Внимательно изучи текст первых страниц книги/документа (титульный лист, оборот титула, предисловие, оглавление) и выдели точные метаданные.

Оригинальное имя файла: {original_name}

Текст первых страниц:
{pdf_text if pdf_text else 'Текст не извлечен (скан). Ориентируйся строго по названию файла: ' + original_name}

Инструкция:
1. "title": Найди официальное название книги и автора в формате: "Автор — Название" (например: "В. В. Прасолов — Задачи по планиметрии" или "Titu Andreescu — 104 Number Theory Problems").
   - НЕ пиши "Документ", "Книга", "Математический сборник" без автора.
2. "summary": Напиши индивидуальное емкое описание книги (2-3 предложения): конкретные темы, какие разделы охвачены, чем полезна книга.
3. "target_audience": Целевая аудитория (например: "7-9 класс начинающие", "10-11 класс регион и Всерос", "Сборная IMO").
4. "categories": Список ключей категорий из: ["geometry", "number_theory", "algebra", "combinatorics", "higher_math", "titu"].
5. "difficulty": Выбери строго одно: "easy", "medium", "hard", "imo".
6. "tags": 3-5 хештегов (например: ["#geometry", "#planimetry", "#olympiad"]).

Верни ответ ТОЛЬКО валидным JSON:
{{
  "title": "Автор — Название",
  "summary": "...",
  "target_audience": "...",
  "categories": ["geometry"],
  "difficulty": "medium",
  "tags": ["#tag1", "#tag2"]
}}
"""

    ai_raw = await call_llm_api(prompt, "Ты эксперт-библиограф олимпиадной математики.")

    if ai_raw:
        try:
            json_match = re.search(r"\{.*\}", ai_raw, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                cats = [c for c in parsed.get("categories", []) if c in DATABASE.get("categories", {})]
                if not cats:
                    cats = ["algebra"]

                diff = str(parsed.get("difficulty", "medium")).lower().strip()
                if diff not in ["easy", "medium", "hard", "imo"]:
                    diff = "medium"

                title = str(parsed.get("title", "")).strip()
                if not title or len(title) < 3 or title.lower() in ["без названия", "document", "math"]:
                    title = fallback_title

                tags = [t if t.startswith("#") else f"#{t}" for t in parsed.get("tags", [])]
                if not tags:
                    tags = [f"#{cats[0]}", "#olympiad", "#math"]

                return {
                    "title": title,
                    "summary": parsed.get("summary", generate_smart_individual_summary(title, pdf_text, cats[0])),
                    "target_audience": parsed.get("target_audience", "Школьники и олимпиадники"),
                    "categories": cats,
                    "difficulty": diff,
                    "tags": tags
                }
        except Exception as e:
            logger.error("Failed to parse AI JSON: %s (Raw: %s)", e, ai_raw)

    # Heuristic fallback if AI offline
    detected_cats = []
    text_to_check = (fallback_title + " " + pdf_text).lower()
    if any(k in text_to_check for k in ["геометр", "geometr", "треуголь", "планиметр", "стереометр", "шарыгин", "прасолов"]):
        detected_cats.append("geometry")
    if any(k in text_to_check for k in ["чисел", "number theory", "делим", "прост", "диофант"]):
        detected_cats.append("number_theory")
    if any(k in text_to_check for k in ["алгебр", "algebra", "многочлен", "неравенст"]):
        detected_cats.append("algebra")
    if any(k in text_to_check for k in ["комбинат", "combinatorics", "граф", "дирихле"]):
        detected_cats.append("combinatorics")
    if any(k in text_to_check for k in ["матанализ", "интеграл", "дифференц", "calculus"]):
        detected_cats.append("higher_math")
    if any(k in text_to_check for k in ["titu", "andreescu"]):
        detected_cats.append("titu")

    if not detected_cats:
        detected_cats = ["algebra"]

    detected_diff = "medium"
    if any(k in text_to_check for k in ["imo", "всерос", "межнар", "закл"]):
        detected_diff = "imo"
    elif any(k in text_to_check for k in ["сложн", "hard", "продвинут"]):
        detected_diff = "hard"
    elif any(k in text_to_check for k in ["начинающ", "прост", "базов", "easy", "с нуля"]):
        detected_diff = "easy"

    individual_summary = generate_smart_individual_summary(fallback_title, pdf_text, detected_cats[0])

    return {
        "title": fallback_title or "Математический сборник",
        "summary": individual_summary,
        "target_audience": "Школьники и студенты",
        "categories": detected_cats,
        "difficulty": detected_diff,
        "tags": [f"#{detected_cats[0]}", "#olympiad", "#math"]
    }

# ============================================================
# MATH CHATGPT ENGINE
# ============================================================

def get_catalog_files_list() -> list:
    """Returns a unique flat list of all files with full AI metadata."""
    files_dict = {}
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        for f in cat_data.get("files", []):
            uid = f.get("file_unique_id")
            if uid and uid not in files_dict:
                files_dict[uid] = {
                    "uid": uid,
                    "file_id": f.get("file_id"),
                    "caption": f.get("caption", "Без названия"),
                    "category": cat_data.get("title", cat_key),
                    "summary": f.get("summary", ""),
                    "target_audience": f.get("target_audience", ""),
                    "tags": f.get("tags", []),
                    "difficulty": f.get("difficulty") or "medium",
                    "must_read": f.get("must_read", False),
                }
    return list(files_dict.values())

async def answer_math_chatgpt_query(user_query: str, user_id: int) -> tuple:
    """
    Universal Math AI engine (acts like Math ChatGPT + Recommender).
    Returns (response_text, [matched_uids]).
    """
    files = get_catalog_files_list()
    catalog_summary = []
    for f in files[:40]:
        catalog_summary.append(
            f"ID:{f['uid']} | «{f['caption']}» | Раздел:{f['category']} | Уровень:{f['difficulty']} | Теги:{', '.join(f['tags'])}"
        )
    catalog_text = "\n".join(catalog_summary)

    system_prompt = (
        "Ты — выдающийся ИИ-математик и преподаватель олимпиадной математики уровня профессора МГУ и тренера сборной IMO.\n"
        "Твоя задача — давать понятные, математически строгие, красивые и подробные ответы на любые вопросы пользователей (теоремы, формулы, доказательства, разбор задач, понятия высшей и школьной математики).\n"
        "Если в твоей библиотеке есть подходящие книги по теме вопроса, порекомендуй 1-3 книги и в самом конце выведи строку MATCHED_UIDS:[id1, id2].\n"
        "Форматируй ответ красиво с использованием HTML тегов (<b>жирный</b>, <i>курсив</i>, <code>код/формулы</code>)."
    )

    user_prompt = (
        f"Вопрос пользователя: \"{user_query}\"\n\n"
        f"Каталог книг в нашей библиотеке:\n{catalog_text}\n\n"
        "Ответь на вопрос подробно, объясни суть, формулу или доказательство. Если уместно, укажи подходящие книги из каталога. В конце добавь MATCHED_UIDS:[id1, id2] (или MATCHED_UIDS:[] если книг по теме нет)."
    )

    ai_response = await call_llm_api(user_prompt, system_prompt)

    if ai_response:
        uids = []
        uid_match = re.search(r"MATCHED_UIDS:\s*\[(.*?)\]", ai_response)
        if uid_match:
            raw_uids = uid_match.group(1).split(",")
            uids = [u.strip().strip("'\"") for u in raw_uids if u.strip()]
            ai_response = re.sub(r"MATCHED_UIDS:\s*\[(.*?)\]", "", ai_response).strip()

        valid_uids = [u for u in uids if get_file_by_uid(u)]
        return ai_response, valid_uids

    # Fallback built-in answers for common math queries if LLM is offline
    q_lower = user_query.lower()
    
    if "эйлер" in q_lower or "euler" in q_lower:
        ans = (
            "🧠 <b>Формулы Эйлера в математике:</b>\n\n"
            "<b>1. Для комплексных чисел:</b>\n"
            "<code>e^(i*x) = cos(x) + i*sin(x)</code>\n"
            "При x = π получается знаменитое тождество Эйлера:\n"
            "<code>e^(i*π) + 1 = 0</code> (связывает 5 фундаментальных констант).\n\n"
            "<b>2. Для планарных графов и многогранников:</b>\n"
            "<code>V - E + F = 2</code>\n"
            "где V — вершины, E — рёбра, F — грани.\n\n"
            "<b>3. Функция Эйлера φ(n):</b>\n"
            "Количество чисел от 1 до n, взаимно простых с n. Теорема Эйлера: <code>a^φ(m) ≡ 1 (mod m)</code>."
        )
        geom_files = [f["uid"] for f in files if "geometry" in f["category"].lower() or "number" in f["category"].lower()][:2]
        return ans, geom_files

    if "пифагор" in q_lower:
        ans = "📐 <b>Теорема Пифагора:</b>\nВ прямоугольном треугольнике квадрат длины гипотенузы равен сумме квадратов длин катетов:\n<code>a² + b² = c²</code>."
        geom_files = [f["uid"] for f in files if "geometry" in f["category"].lower()][:2]
        return ans, geom_files

    # Fallback catalog search
    scored = []
    for f in files:
        score = 0
        haystack = f"{f['caption']} {f['category']} {f['summary']} {' '.join(f['tags'])}".lower()
        for w in q_lower.split():
            if len(w) > 2 and w in haystack:
                score += 3
        if score > 0:
            scored.append((score, f))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_matches = [item[1] for item in scored[:3]] or files[:3]

    text = (
        f"🤖 <b>Ответ по запросу «{html.escape(user_query)}»:</b>\n\n"
        "Я нашёл подходящие теоретические и практические материалы в нашей библиотеке:\n"
    )
    for i, f in enumerate(top_matches, 1):
        text += f"\n<b>{i}. {html.escape(f['caption'])}</b>\n📝 <i>{html.escape(f['summary'])}</i>\n"
    
    return text, [f["uid"] for f in top_matches]

# ============================================================
# FSM STATES
# ============================================================

class FileUpload(StatesGroup):
    confirming_ai_data = State()
    selecting_categories = State()
    waiting_for_caption = State()
    waiting_for_tags = State()
    waiting_for_summary = State()
    choosing_difficulty = State()

class UserSubmit(StatesGroup):
    confirming_submission = State()

class EditSubmissionState(StatesGroup):
    waiting_for_new_title = State()
    waiting_for_new_tags = State()

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

class AIAssistantState(StatesGroup):
    waiting_for_query = State()

# ============================================================
# KEYBOARDS
# ============================================================

DIFF_NAMES = {
    "easy": "🟢 Easy (Базовый)",
    "medium": "🟡 Medium (Регион)",
    "hard": "🔴 Hard (Всерос / Финал)",
    "imo": "🔥 IMO (Международный)"
}

def get_main_menu_keyboard(user_id: int):
    builder = [
        [
            InlineKeyboardButton(text="🤖 AI Математик (ChatGPT)", callback_data="ai:ask"),
            InlineKeyboardButton(text="📚 Каталог", callback_data="menu:catalog"),
        ],
        [
            InlineKeyboardButton(text="🎯 Задача дня", callback_data="task:show"),
            InlineKeyboardButton(text="⭐ Must-read", callback_data="mustread:main"),
        ],
        [
            InlineKeyboardButton(text="❤️ Избранное", callback_data="favorites:main"),
            InlineKeyboardButton(text="🏆 Рейтинг", callback_data="rating:main"),
        ],
        [
            InlineKeyboardButton(text="🎲 Случайный материал", callback_data="challenge:main"),
            InlineKeyboardButton(text="🔗 Полезные ссылки", callback_data="links:main"),
        ],
        [
            InlineKeyboardButton(text="📤 Предложить файл", callback_data="submit:start"),
        ],
    ]
    if is_admin(user_id):
        builder.append([
            InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin:main")
        ])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_catalog_keyboard():
    builder = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        count = len(cat_data.get("files", []))
        builder.append([
            InlineKeyboardButton(
                text=f"{cat_data['title']} ({count})",
                callback_data=f"cat:{cat_key}"
            )
        ])
    builder.append([
        InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_links_keyboard():
    builder = []
    for sec_key, sec_data in DATABASE.get("links", {}).items():
        title = sec_data.get("title", sec_key)
        builder.append([
            InlineKeyboardButton(
                text=title,
                callback_data=f"links:sec:{sec_key}"
            )
        ])
    builder.append([
        InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_links_section_keyboard(sec_key: str, user_id: int):
    sec = DATABASE.get("links", {}).get(sec_key, {})
    items = sec.get("items", [])
    builder = []
    for item in items[:50]:
        title = item.get("title", "Ссылка")
        url = item.get("url", "https://t.me")
        builder.append([
            InlineKeyboardButton(
                text=f"🌐 {title}",
                url=url
            )
        ])
    if is_admin(user_id):
        builder.append([
            InlineKeyboardButton(
                text="➕ Добавить ссылку",
                callback_data=f"links:add:{sec_key}"
            )
        ])
    builder.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="links:main"
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def render_ai_preview_text(data: dict) -> str:
    cats_names = ", ".join(
        DATABASE["categories"][c]["title"] 
        for c in data.get("selected", []) 
        if c in DATABASE.get("categories", {})
    ) or "Не выбрано"
    
    diff_key = data.get("difficulty", "medium")
    diff_display = DIFF_NAMES.get(diff_key, diff_key.upper())
    tags_display = " ".join(data.get("tags", [])) or "Нет тегов"

    return (
        "🤖 <b>ИИ проанализировал PDF:</b>\n\n"
        f"🏷 <b>Название:</b> {html.escape(data.get('title', 'Без названия'))}\n"
        f"📁 <b>Разделы:</b> {cats_names}\n"
        f"📚 <b>Уровень:</b> {diff_display}\n"
        f"🎯 <b>Аудитория:</b> {html.escape(data.get('target_audience', 'Олимпиадники'))}\n"
        f"📝 <b>Описание:</b> {html.escape(data.get('summary', ''))}\n"
        f"🏷 <b>Теги:</b> {tags_display}\n\n"
        "👇 <i>Нажми на кнопку, чтобы изменить любой параметр, или нажми «Сохранить»:</i>"
    )

def get_ai_preview_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Сохранить в каталог", callback_data="ai_save_confirm")],
            [
                InlineKeyboardButton(text="📝 Название", callback_data="ai_edit_title"),
                InlineKeyboardButton(text="📁 Разделы", callback_data="ai_edit_cats"),
            ],
            [
                InlineKeyboardButton(text="📚 Уровень", callback_data="ai_edit_diff"),
                InlineKeyboardButton(text="🏷 Теги", callback_data="ai_edit_tags"),
            ],
            [InlineKeyboardButton(text="📝 Изменить описание", callback_data="ai_edit_summary")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
        ]
    )

def get_difficulty_selection_kb(prefix: str = "ai_set_diff"):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Easy", callback_data=f"{prefix}:easy"),
                InlineKeyboardButton(text="🟡 Medium", callback_data=f"{prefix}:medium")
            ],
            [
                InlineKeyboardButton(text="🔴 Hard", callback_data=f"{prefix}:hard"),
                InlineKeyboardButton(text="🔥 IMO", callback_data=f"{prefix}:imo")
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"{prefix}:back")]
        ]
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
        InlineKeyboardButton(text=f"✅ Готово ({len(selected)})", callback_data="a_done")
    ])
    builder.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")
    ])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def build_submission_action_kb(sub_id: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Одобрить и опубликовать", callback_data=f"sub_approve:{sub_id}")],
            [
                InlineKeyboardButton(text="📁 Разделы", callback_data=f"sub_editcat:{sub_id}"),
                InlineKeyboardButton(text="📝 Название", callback_data=f"sub_edittitle:{sub_id}")
            ],
            [
                InlineKeyboardButton(text="📚 Уровень", callback_data=f"sub_editdiff:{sub_id}"),
                InlineKeyboardButton(text="🏷 Теги", callback_data=f"sub_edittags:{sub_id}")
            ],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"sub_reject:{sub_id}")]
        ]
    )

def build_submission_categories_kb(sub_id: str, selected_cats: list):
    selected = set(selected_cats)
    builder = []
    for cat_key, cat_data in DATABASE["categories"].items():
        mark = "☑️" if cat_key in selected else "▫️"
        builder.append([
            InlineKeyboardButton(
                text=f"{mark} {cat_data['title']}",
                callback_data=f"subcat_toggle:{sub_id}:{cat_key}"
            )
        ])
    builder.append([
        InlineKeyboardButton(text="✅ Готово", callback_data=f"subcat_done:{sub_id}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_file_view_keyboard(uid: str, user_id: int):
    user = DATABASE.get("users", {}).get(str(user_id), {})
    is_fav = uid in user.get("favorites", [])
    builder = []
    fav_text = "💔 Убрать из избранного" if is_fav else "❤️ В избранное"
    builder.append([InlineKeyboardButton(text=fav_text, callback_data=f"fav:{uid}")])
    if is_admin(user_id):
        builder.append([
            InlineKeyboardButton(text="✏️ Изменить", callback_data=f"fe_m:{uid}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"fd:{uid}")
        ])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_file_edit_keyboard(uid: str):
    f = get_file_by_uid(uid)
    must_read_text = "⭐ Убрать Must-read" if f.get("must_read") else "⭐ Сделать Must-read"
    diff = f.get("difficulty", "Не указана")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Изменить название", callback_data=f"fe_t:{uid}")],
            [InlineKeyboardButton(text="📁 Изменить разделы", callback_data=f"fe_c:{uid}")],
            [InlineKeyboardButton(text="🏷 Изменить теги", callback_data=f"fe_tg:{uid}")],
            [InlineKeyboardButton(text=must_read_text, callback_data=f"fe_mr:{uid}")],
            [InlineKeyboardButton(text=f"📚 Уровень: {diff}", callback_data=f"fe_df:{uid}")],
            [InlineKeyboardButton(text="🔄 Заменить сам файл", callback_data=f"fe_doc:{uid}")],
            [InlineKeyboardButton(text="🔙 Закрыть", callback_data="fe_close")]
        ]
    )

def get_difficulty_keyboard(uid: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Easy", callback_data=f"fed_v:{uid}:easy"),
                InlineKeyboardButton(text="🟡 Medium", callback_data=f"fed_v:{uid}:medium")
            ],
            [
                InlineKeyboardButton(text="🔴 Hard", callback_data=f"fed_v:{uid}:hard"),
                InlineKeyboardButton(text="🔥 IMO", callback_data=f"fed_v:{uid}:imo")
            ],
            [InlineKeyboardButton(text="❌ Очистить", callback_data=f"fed_v:{uid}:none")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"fe_m:{uid}")]
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
    builder.append([InlineKeyboardButton(text="✅ Сохранить", callback_data=f"fec_s:{uid}")])
    builder.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"fe_m:{uid}")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

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

def get_latest_task_info():
    """Returns (date_str, task, task_index) of the most recently published task."""
    dates = sorted(DATABASE.get("daily_tasks", {}).keys(), reverse=True)
    for d in dates:
        tasks = get_tasks_for_date(d)
        if tasks:
            return d, tasks[0], 0
    return None, None, 0

def get_task_keyboard(
    date_str: str,
    user_id: int,
    admin_view: bool = False,
    task_index: int = 0
):
    builder = [
        [
            InlineKeyboardButton(
                text="📝 Решение",
                callback_data=f"th:{date_str}:{task_index}"
            )
        ],
        [
            InlineKeyboardButton(
                text="✍️ Отправить своё решение",
                callback_data=f"tsol:{date_str}:{task_index}"
            )
        ],
        [
            InlineKeyboardButton(text="⭐ 1", callback_data=f"tv:{date_str}:{task_index}:1"),
            InlineKeyboardButton(text="⭐ 2", callback_data=f"tv:{date_str}:{task_index}:2"),
            InlineKeyboardButton(text="⭐ 3", callback_data=f"tv:{date_str}:{task_index}:3"),
            InlineKeyboardButton(text="⭐ 4", callback_data=f"tv:{date_str}:{task_index}:4"),
            InlineKeyboardButton(text="⭐ 5", callback_data=f"tv:{date_str}:{task_index}:5")
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
            text="📅 Архив задач",
            callback_data="tasks:history"
        )
    ])
    builder.append([
        InlineKeyboardButton(
            text="⬅️ Меню",
            callback_data="menu:main"
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_history_keyboard():
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
        builder.append([InlineKeyboardButton(text="📭 Задач пока нет в базе.", callback_data="noop")])
    builder.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_solution_rating_keyboard(date_str: str, solution_id: str, task_index: int = 0):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ 1", callback_data=f"usrate:{date_str}:{task_index}:{solution_id}:1"),
                InlineKeyboardButton(text="⭐ 2", callback_data=f"usrate:{date_str}:{task_index}:{solution_id}:2"),
                InlineKeyboardButton(text="⭐ 3", callback_data=f"usrate:{date_str}:{task_index}:{solution_id}:3"),
                InlineKeyboardButton(text="⭐ 4", callback_data=f"usrate:{date_str}:{task_index}:{solution_id}:4"),
                InlineKeyboardButton(text="⭐ 5", callback_data=f"usrate:{date_str}:{task_index}:{solution_id}:5")
            ]
        ]
    )

# ============================================================
# INLINE SEARCH (GOOGLE-STYLE)
# ============================================================

@dp.inline_query()
async def inline_search(inline_query: InlineQuery):
    query = inline_query.query.strip().lower()
    results = []

    if not query:
        results.append(
            InlineQueryResultArticle(
                id="info",
                title="🔎 Поиск по всей базе matham",
                description="Введите автора, название, тему или теорему",
                input_message_content=InputTextMessageContent(
                    message_text="Воспользуйтесь встроенным поиском для нахождения олимпиадных и учебных материалов!"
                )
            )
        )
        return await inline_query.answer(results, cache_time=1)

    words = [w for w in query.split() if w]
    scored_files = []

    for cat_data in DATABASE.get("categories", {}).values():
        for f in cat_data.get("files", []):
            title_text = f.get("caption", "").lower()
            summary_text = f.get("summary", "").lower()
            tags_text = " ".join(f.get("tags", [])).lower()
            cat_text = cat_data.get("title", "").lower()

            haystack = f"{title_text} {summary_text} {tags_text} {cat_text}"
            score = 0

            if query in title_text:
                score += 100
            elif query in haystack:
                score += 50

            for w in words:
                if w in title_text:
                    score += 30
                elif w in tags_text:
                    score += 20
                elif w in haystack:
                    score += 10

            if score > 0:
                if not any(x[0]["file_unique_id"] == f["file_unique_id"] for x in scored_files):
                    scored_files.append((f, cat_data["title"], score))

    scored_files.sort(key=lambda x: x[2], reverse=True)

    for f, cat_title, _ in scored_files[:50]:
        cap = (
            f"📄 <b>{html.escape(f['caption'])}</b>\n"
            f"📌 Раздел: {html.escape(cat_title)}"
        )
        if f.get("summary"):
            cap += f"\n📝 {html.escape(f['summary'])}"
        if f.get("difficulty"):
            cap += f"\n📚 Уровень: {f['difficulty'].upper()}"

        results.append(
            InlineQueryResultCachedDocument(
                id=f["file_unique_id"],
                title=f["caption"],
                description=f.get("summary", f"Раздел: {cat_title}"),
                document_file_id=f["file_id"],
                caption=cap,
                parse_mode=ParseMode.HTML
            )
        )

    await inline_query.answer(results[:50], cache_time=3)

# ============================================================
# COMMANDS & MAIN NAVIGATION
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await track_user_activity(message.from_user.id, message.from_user.username or "")
    await message.answer(
        "👋 <b>Добро пожаловать в библиотеку matham!</b>\n\n"
        "🤖 <b>AI Математик (ChatGPT)</b> — ответит на любой математический вопрос, объяснит формулы и подберёт книги\n"
        "📚 <b>Каталог</b> — учебники и сборники по разделам\n"
        "🎯 <b>Задача дня</b> — ежедневная олимпиадная задача\n"
        "⭐ <b>Must-read</b> — обязательная классика",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_menu_keyboard(message.from_user.id)
    )

@dp.message(F.text.in_({"⬅️ Назад", "🔙 Назад", "Назад"}))
async def universal_back(message: types.Message, state: FSMContext):
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer(
            "👑 <b>Админ-панель</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🎯 Задачи дня", callback_data="admin:tasks")],
                    [InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]
                ]
            )
        )
    else:
        await message.answer(
            "📂 Главное меню",
            reply_markup=get_main_menu_keyboard(message.from_user.id)
        )

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await track_user_activity(message.from_user.id, message.from_user.username or "")
    await message.answer(
        "📂 Главное меню библиотеки",
        reply_markup=get_main_menu_keyboard(message.from_user.id)
    )

@dp.callback_query(F.data == "menu:main")
async def process_back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await track_user_activity(callback.from_user.id, callback.from_user.username or "")
    await safe_send_or_edit(
        callback,
        "📂 <b>Главное меню библиотеки matham</b>",
        reply_markup=get_main_menu_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == "menu:catalog")
async def process_catalog(callback: types.CallbackQuery):
    await safe_send_or_edit(
        callback,
        "📚 <b>Каталог материалов</b>\n\nВыбери интересующий раздел математики:",
        reply_markup=get_catalog_keyboard()
    )
    await callback.answer()

# ============================================================
# AI ASSISTANT (MATH CHATGPT)
# ============================================================

@dp.message(Command("ai"))
@dp.message(Command("ask"))
@dp.callback_query(F.data == "ai:ask")
async def start_ai_assistant(event: types.Message | types.CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    await track_user_activity(user_id, event.from_user.username or "")
    await state.set_state(AIAssistantState.waiting_for_query)

    text = (
        "🤖 <b>AI Математик (ChatGPT + Библиотека)</b>\n\n"
        "Задай мне <b>любой вопрос</b> по математике или попроси подобрать книги!\n\n"
        "<i>Примеры запросов:</i>\n"
        "• <i>«Какая формула Эйлера и где она применяется?»</i>\n"
        "• <i>«Докажи теорему Чевы простыми словами»</i>\n"
        "• <i>«Посоветуй книги по планиметрии для 9 класса для региона»</i>\n"
        "• <i>«Как решать диофантовы уравнения в целых числах?»</i>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="ai:cancel")]
        ]
    )

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

@dp.callback_query(AIAssistantState.waiting_for_query, F.data == "ai:cancel")
async def cancel_ai_assistant(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📂 Главное меню",
        reply_markup=get_main_menu_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.message(AIAssistantState.waiting_for_query, F.text)
async def process_ai_query(message: types.Message, state: FSMContext):
    if message.text.lower() in ["отмена", "/cancel"]:
        await state.clear()
        return await message.answer(
            "❌ Отменено.",
            reply_markup=get_main_menu_keyboard(message.from_user.id)
        )

    await track_user_activity(message.from_user.id, message.from_user.username or "")
    loading_msg = await message.answer("🧠 <i>AI думает над ответом...</i>", parse_mode=ParseMode.HTML)

    response_text, matched_uids = await answer_math_chatgpt_query(message.text, message.from_user.id)
    await state.clear()

    builder = []
    for uid in matched_uids:
        f = get_file_by_uid(uid)
        if f:
            builder.append([
                InlineKeyboardButton(
                    text=f"📥 Скачать: {f['caption'][:30]}",
                    callback_data=f"fv:{uid}"
                )
            ])
    builder.append([
        InlineKeyboardButton(text="🔄 Задать ещё вопрос", callback_data="ai:ask"),
        InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")
    ])

    try:
        await loading_msg.delete()
    except Exception:
        pass

    await message.answer(
        response_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )

# ============================================================
# FIXED DAILY TASK SYSTEM
# ============================================================

async def send_daily_task(target, date_str: str = None, task_index: int = 0):
    user_id = target.from_user.id

    if date_str:
        task = get_task_by_index(date_str, task_index)
        current_date = date_str
    else:
        today = get_yerevan_date()
        task = get_task_by_index(today, task_index)
        if task:
            current_date = today
        else:
            latest_date, latest_task, _ = get_latest_task_info()
            task = latest_task
            current_date = latest_date or today

    if not task:
        text = (
            "🎯 <b>Задача дня</b>\n\n"
            "Задач пока нет в базе. Администраторы скоро добавят первую задачу!"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]
            ]
        )
        return await safe_send_or_edit(target, text, reply_markup=kb)

    if current_date == get_yerevan_date():
        uid_str = str(user_id)
        opened = DATABASE["users"].setdefault(uid_str, {}).setdefault("opened_tasks", [])
        key = f"{current_date}:{task_index}"
        if key not in opened:
            opened.append(key)
            await award_points(user_id, 5)
            await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {f"data.users.{uid_str}.opened_tasks": opened}})

    date_title = f"{current_date} (Сегодня)" if current_date == get_yerevan_date() else f"{current_date} (Архив)"
    cap = f"🧩 <b>Задача {task_index + 1}</b> ({date_title})"
    
    votes = task.get("votes", {})
    if votes:
        avg = sum(votes.values()) / len(votes)
        cap += f"\n\n⭐ Оценка: {avg:.1f}/5 (Голосов: {len(votes)})"
    if len(get_tasks_for_date(current_date)) > 1:
        cap += f"\n📚 Задач за эту дату: {len(get_tasks_for_date(current_date))}"

    kb = get_task_keyboard(current_date, user_id, is_admin(user_id), task_index)
    photo_id = task.get("photo_file_id")

    await safe_send_or_edit(target, cap, reply_markup=kb, photo_id=photo_id)

@dp.message(Command("task"))
async def cmd_task(message: types.Message):
    await track_user_activity(message.from_user.id, message.from_user.username or "")
    await send_daily_task(message)

@dp.callback_query(F.data == "task:show")
async def callback_task(callback: types.CallbackQuery):
    await track_user_activity(callback.from_user.id, callback.from_user.username or "")
    await send_daily_task(callback)
    try:
        await callback.answer()
    except Exception:
        pass

@dp.callback_query(F.data == "tasks:history")
async def tasks_history(callback: types.CallbackQuery):
    text = "📅 <b>Архив задач прошлых дней</b>\n\nВыбери дату:"
    kb = get_history_keyboard()
    await safe_send_or_edit(callback, text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("taskdate:"))
async def previous_task(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    date_str = parts[1]
    task_index = int(parts[2]) if len(parts) > 2 else 0
    await send_daily_task(callback, date_str, task_index)
    await callback.answer()

# ============================================================
# DAILY TASK VOTING & SOLUTION
# ============================================================

@dp.callback_query(F.data.startswith("tv:"))
async def task_vote_handler(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) == 4:
        _, date_str, idx_str, score_str = parts
        task_index = int(idx_str)
    elif len(parts) == 3:
        _, date_str, score_str = parts
        task_index = 0
    else:
        return await callback.answer("Неверный формат", show_alert=True)

    score = int(score_str)
    task = get_task_by_index(date_str, task_index)
    if not task:
        return await callback.answer("Задача не найдена", show_alert=True)

    uid_str = str(callback.from_user.id)
    votes = task.setdefault("votes", {})
    if uid_str not in votes:
        await award_points(callback.from_user.id, 2)
    votes[uid_str] = score
    await save_db(DATABASE)

    avg = sum(votes.values()) / len(votes)
    cap = (
        f"🧩 <b>Задача {task_index + 1}</b> ({date_str})\n\n"
        f"⭐ Оценка: {avg:.1f}/5 (Голосов: {len(votes)})"
    )
    if len(get_tasks_for_date(date_str)) > 1:
        cap += f"\n📚 Задач за эту дату: {len(get_tasks_for_date(date_str))}"

    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=cap,
                parse_mode=ParseMode.HTML,
                reply_markup=get_task_keyboard(date_str, callback.from_user.id, is_admin(callback.from_user.id), task_index)
            )
        else:
            await callback.message.edit_text(
                text=cap,
                parse_mode=ParseMode.HTML,
                reply_markup=get_task_keyboard(date_str, callback.from_user.id, is_admin(callback.from_user.id), task_index)
            )
    except Exception:
        pass

    await callback.answer(f"Твоя оценка {score}⭐ сохранена!", show_alert=True)

@dp.callback_query(F.data.startswith("th:"))
async def task_solution_handler(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    date_str = parts[1]
    task_index = int(parts[2]) if len(parts) > 2 else 0
    task = get_task_by_index(date_str, task_index)
    if not task:
        return await callback.answer("Задача не найдена", show_alert=True)
    text_solution = task.get("solution", "")
    photo_solution = task.get("solution_photo_file_id")
    if not text_solution and not photo_solution:
        return await callback.answer("Пока решения нет 😔", show_alert=True)

    title = f"📝 <b>Решение задачи {task_index + 1} ({date_str})</b>"
    if photo_solution:
        await callback.message.answer_photo(
            photo=photo_solution,
            caption=title + (f"\n\n{text_solution}" if text_solution else ""),
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.answer(f"{title}\n\n{text_solution}", parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data.startswith("tsol:"))
async def user_solution_start(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    date_str = parts[1]
    task_index = int(parts[2]) if len(parts) > 2 else 0
    if not get_task_by_index(date_str, task_index):
        return await callback.answer("Задача не найдена", show_alert=True)
    await state.update_data(solution_date=date_str, solution_task_index=task_index)
    await state.set_state(UserTaskSolution.waiting_for_solution)
    await callback.message.answer("Отправь решение текстом или фотографией.\n\n❌ Напиши /cancel для отмены.")
    await callback.answer()

@dp.message(UserTaskSolution.waiting_for_solution, F.text)
async def user_solution_text(message: types.Message, state: FSMContext):
    if message.text.lower() == "/cancel":
        await state.clear()
        return await message.answer("❌ Отмена.")

    data = await state.get_data()
    date_str = data.get("solution_date")
    await save_user_daily_solution(message, state, date_str, solution_type="text", text=message.text)

@dp.message(UserTaskSolution.waiting_for_solution, F.photo)
async def user_solution_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date_str = data.get("solution_date")
    await save_user_daily_solution(message, state, date_str, solution_type="photo", photo_id=message.photo[-1].file_id)

async def save_user_daily_solution(message: types.Message, state: FSMContext, date_str: str, solution_type: str, text: str = "", photo_id: str = None):
    data = await state.get_data()
    task_index = data.get("solution_task_index", 0)

    task = get_task_by_index(date_str, task_index)
    if not task:
        await state.clear()
        return await message.answer("❌ Задача не найдена.")

    solution_id = uuid.uuid4().hex[:10]
    username = message.from_user.username or message.from_user.full_name

    solution = {
        "solution_id": solution_id,
        "user_id": message.from_user.id,
        "username": username,
        "type": solution_type,
        "text": text or "",
        "photo_file_id": photo_id,
        "status": "pending",
        "rating": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    task.setdefault("user_solutions", {})
    task["user_solutions"][solution_id] = solution
    await save_db(DATABASE)
    await state.clear()

    await message.answer("✅ Твоё решение отправлено админу!\nПосле проверки ты получишь оценку.")

    for admin_id in ADMIN_IDS:
        try:
            caption = (
                "🧠 <b>Новое решение задачи</b>\n\n"
                f"📅 Дата: {date_str} (Задача #{task_index + 1})\n"
                f"👤 Автор: @{username}\n"
                f"🆔 Solution ID: <code>{solution_id}</code>\n\n"
                "Оцени решение от 1 до 5:"
            )
            kb = get_solution_rating_keyboard(date_str, solution_id, task_index)
            if solution_type == "photo":
                await bot.send_photo(admin_id, photo=photo_id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await bot.send_message(admin_id, caption + "\n\n" + text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            logger.error("Failed to send user solution to admin: %s", e)

@dp.callback_query(F.data.startswith("usrate:"))
async def admin_rate_user_solution(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)

    parts = callback.data.split(":")
    if len(parts) == 5:
        _, date_str, idx_str, solution_id, score_str = parts
        task_index = int(idx_str)
    else:
        return await callback.answer("Ошибка", show_alert=True)

    score = int(score_str)
    task = get_task_by_index(date_str, task_index)
    if not task:
        return await callback.answer("Задача не найдена", show_alert=True)

    solution = task.get("user_solutions", {}).get(solution_id)
    if not solution:
        return await callback.answer("Решение не найдено", show_alert=True)

    solution["rating"] = score
    solution["status"] = "rated"
    solution["rated_by"] = callback.from_user.id
    solution["rated_at"] = datetime.now(timezone.utc).isoformat()
    await save_db(DATABASE)

    points = score * 3
    await award_points(solution["user_id"], points)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    try:
        await bot.send_message(
            solution["user_id"],
            f"🎉 Твоё решение задачи {date_str} проверено!\n\n⭐ Оценка: {score}/5\n🏆 +{points} очков"
        )
    except Exception as e:
        logger.error("Failed to notify user about rating: %s", e)

    await callback.answer(f"Оценка {score}/5 сохранена!", show_alert=True)

# ============================================================
# RANDOM MATERIAL & CHALLENGE
# ============================================================

@dp.message(Command("surprise"))
@dp.message(Command("challenge"))
@dp.callback_query(F.data == "challenge:main")
async def cb_challenge(event: types.Message | types.CallbackQuery):
    user_id = event.from_user.id
    await track_user_activity(user_id, event.from_user.username or "")
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Любая сложность (Случайно)", callback_data="rand:any")],
            [
                InlineKeyboardButton(text="🟢 Easy (Базовый)", callback_data="rand:easy"),
                InlineKeyboardButton(text="🟡 Medium (Регион)", callback_data="rand:medium")
            ],
            [
                InlineKeyboardButton(text="🔴 Hard (Всерос)", callback_data="rand:hard"),
                InlineKeyboardButton(text="🔥 IMO (Межнар)", callback_data="rand:imo")
            ],
            [InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]
        ]
    )
    text = "🎲 <b>Выбери уровень сложности для случайной книги:</b>"
    await safe_send_or_edit(event, text, reply_markup=kb)
    if isinstance(event, types.CallbackQuery):
        await event.answer()

@dp.callback_query(F.data.startswith("rand:"))
async def cb_do_random(callback: types.CallbackQuery):
    diff = callback.data.split(":")[1]
    if diff == "any":
        diff = None
    await process_random_material(callback, diff)
    await callback.answer()

async def process_random_material(target, diff: str = None):
    all_files = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        for f in cat_data.get("files", []):
            if diff is None or (f.get("difficulty") and f.get("difficulty").lower() == diff.lower()):
                if not any(x[0]["file_unique_id"] == f["file_unique_id"] for x in all_files):
                    all_files.append((f, cat_data["title"]))

    if not all_files:
        # Fallback to any file if specific difficulty empty
        for cat_key, cat_data in DATABASE.get("categories", {}).items():
            for f in cat_data.get("files", []):
                if not any(x[0]["file_unique_id"] == f["file_unique_id"] for x in all_files):
                    all_files.append((f, cat_data["title"]))

    if not all_files:
        return await safe_send_or_edit(target, "📭 В библиотеке пока нет доступных файлов.", reply_markup=get_main_menu_keyboard(target.from_user.id))

    selected_file, cat_title = random.choice(all_files)
    await award_points(target.from_user.id, 1)

    diff_str = f" | 📚 Уровень: {selected_file.get('difficulty', 'medium').upper()}"
    cap = (
        f"🎲 <b>Случайная книга:</b>\n\n"
        f"📄 <b>{html.escape(selected_file['caption'])}</b>\n"
        f"📌 Раздел: {html.escape(cat_title)}{diff_str}\n"
    )
    if selected_file.get("summary"):
        cap += f"\n📝 <b>Описание:</b> {html.escape(selected_file['summary'])}"

    if isinstance(target, types.CallbackQuery):
        try:
            await target.message.delete()
        except Exception:
            pass
        await target.message.answer_document(
            document=selected_file["file_id"],
            caption=cap,
            parse_mode=ParseMode.HTML,
            reply_markup=get_file_view_keyboard(selected_file["file_unique_id"], target.from_user.id)
        )
    else:
        await target.answer_document(
            document=selected_file["file_id"],
            caption=cap,
            parse_mode=ParseMode.HTML,
            reply_markup=get_file_view_keyboard(selected_file["file_unique_id"], target.from_user.id)
        )

# ============================================================
# CATEGORY VIEW & FILE VIEW
# ============================================================

@dp.callback_query(F.data.startswith("cat:"))
async def process_category_click(callback: types.CallbackQuery):
    cat_key = callback.data.split(":")[1]
    cat_data = DATABASE.get("categories", {}).get(cat_key)
    if not cat_data:
        return await callback.answer("Раздел не найден", show_alert=True)

    files = cat_data.get("files", [])
    if not files:
        return await safe_send_or_edit(
            callback,
            f"<b>{html.escape(cat_data['title'])}</b>\n\n📁 В этом разделе пока нет файлов.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в каталог", callback_data="menu:catalog")]]
            )
        )

    builder = []
    for item in files[:60]:
        btn_text = f"📄 {item['caption'][:35]}"
        if len(item["caption"]) > 35:
            btn_text += "..."
        builder.append([
            InlineKeyboardButton(text=btn_text, callback_data=f"fv:{item['file_unique_id']}")
        ])
    builder.append([
        InlineKeyboardButton(text="⬅️ Назад в каталог", callback_data="menu:catalog")
    ])

    await safe_send_or_edit(
        callback,
        f"<b>{html.escape(cat_data['title'])}</b> (всего: {len(files)})\n\n⬇️ Выбери интересующий материал:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("fv:"))
async def view_file(callback: types.CallbackQuery):
    uid = callback.data.split(":")[1]
    f = get_file_by_uid(uid)
    if not f:
        return await callback.answer("❌ Файл больше не доступен.", show_alert=True)

    await callback.answer("Отправляю файл... ⏳")
    cap = f"📄 <b>{html.escape(f['caption'])}</b>"
    if f.get("summary"):
        cap += f"\n\n📝 <b>Описание:</b> {html.escape(f['summary'])}"
    if f.get("target_audience"):
        cap += f"\n🎯 <b>Аудитория:</b> {html.escape(f['target_audience'])}"
    if f.get("difficulty"):
        cap += f"\n📚 <b>Уровень:</b> {f['difficulty'].upper()}"
    tags = f.get("tags", [])
    if tags:
        cap += "\n🏷 " + " ".join(tags)

    await callback.message.answer_document(
        document=f["file_id"],
        caption=cap,
        parse_mode=ParseMode.HTML,
        reply_markup=get_file_view_keyboard(uid, callback.from_user.id)
    )

# ============================================================
# MUST READ & FAVORITES & RATING & USEFUL LINKS
# ============================================================

@dp.callback_query(F.data == "mustread:main")
async def mustread_main(callback: types.CallbackQuery):
    files = []
    for cat_data in DATABASE.get("categories", {}).values():
        for f in cat_data.get("files", []):
            if f.get("must_read"):
                if not any(x["file_unique_id"] == f["file_unique_id"] for x in files):
                    files.append(f)

    if not files:
        return await safe_send_or_edit(
            callback,
            "⭐ <b>MUST-READ</b>\n\nПока нет отмеченных файлов.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]]
            )
        )

    builder = []
    for f in files[:80]:
        builder.append([
            InlineKeyboardButton(text=f"📄 {f['caption'][:35]}", callback_data=f"fv:{f['file_unique_id']}")
        ])
    builder.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")])

    await safe_send_or_edit(
        callback,
        "⭐ <b>MUST-READ: Золотой фонд математики</b>\n\nГлавные книги и сборники:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()

@dp.message(Command("favorites"))
@dp.callback_query(F.data == "favorites:main")
async def cb_fav(event: types.Message | types.CallbackQuery):
    user_id = event.from_user.id
    await track_user_activity(user_id, event.from_user.username or "")
    
    user = DATABASE.get("users", {}).get(str(user_id), {})
    favs = user.get("favorites", [])

    if not favs:
        text = "❤️ <b>Избранное</b>\n\nУ тебя пока нет сохранённых материалов."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]])
        return await safe_send_or_edit(event, text, reply_markup=kb)

    builder = []
    valid_count = 0
    for uid in favs[:80]:
        f = get_file_by_uid(uid)
        if f:
            valid_count += 1
            builder.append([InlineKeyboardButton(text=f"📄 {f['caption'][:35]}", callback_data=f"fv:{uid}")])
    builder.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")])

    text = f"❤️ <b>Твоё избранное ({valid_count} шт.):</b>"
    await safe_send_or_edit(event, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    if isinstance(event, types.CallbackQuery):
        await event.answer()

@dp.callback_query(F.data.startswith("fav:"))
async def toggle_fav(callback: types.CallbackQuery):
    uid = callback.data.split(":")[1]
    user_id_str = str(callback.from_user.id)
    if user_id_str not in DATABASE.get("users", {}):
        await track_user_activity(callback.from_user.id, callback.from_user.username or "")

    user = DATABASE["users"][user_id_str]
    favs = user.setdefault("favorites", [])

    if uid in favs:
        favs.remove(uid)
        await db_collection.update_one({"_id": DB_DOC_ID}, {"$pull": {f"data.users.{user_id_str}.favorites": uid}})
        await callback.answer("💔 Удалено из избранного")
    else:
        favs.append(uid)
        await db_collection.update_one({"_id": DB_DOC_ID}, {"$addToSet": {f"data.users.{user_id_str}.favorites": uid}})
        await callback.answer("❤️ Добавлено в избранное")

    try:
        await callback.message.edit_reply_markup(reply_markup=get_file_view_keyboard(uid, callback.from_user.id))
    except Exception:
        pass

@dp.message(Command("rating"))
@dp.callback_query(F.data == "rating:main")
async def cb_rating(event: types.Message | types.CallbackQuery):
    user_id = event.from_user.id
    await track_user_activity(user_id, event.from_user.username or "")
    
    users = [(uid, u) for uid, u in DATABASE.get("users", {}).items() if u.get("score", 0) > 0]
    users.sort(key=lambda x: x[1].get("score", 0), reverse=True)

    text = "🏆 <b>Рейтинг активности участников:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]

    for i, (uid, u) in enumerate(users[:10]):
        medal = medals[i] if i < 3 else "🏅"
        name = u.get("username") or f"ID {uid}"
        text += f"{medal} @{html.escape(name)} — <b>{u.get('score', 0)}</b> очков\n"

    my_user = DATABASE.get("users", {}).get(str(user_id), {})
    text += f"\n🔥 Твой streak: <b>{my_user.get('streak', 0)}</b> дней"
    text += f"\n🎯 Твои очки: <b>{my_user.get('score', 0)}</b>"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]])
    await safe_send_or_edit(event, text, reply_markup=kb)
    if isinstance(event, types.CallbackQuery):
        await event.answer()

@dp.message(Command("links"))
@dp.callback_query(F.data == "links:main")
async def cb_links_main(event: types.Message | types.CallbackQuery):
    user_id = event.from_user.id
    await track_user_activity(user_id, event.from_user.username or "")
    text = "🔗 <b>Полезные математические ссылки:</b>\n\nВыбери раздел:"
    await safe_send_or_edit(event, text, reply_markup=get_links_keyboard())
    if isinstance(event, types.CallbackQuery):
        await event.answer()

@dp.callback_query(F.data.startswith("links:sec:"))
async def cb_links_section(callback: types.CallbackQuery):
    sec_key = callback.data.split(":")[2]
    sec = DATABASE.get("links", {}).get(sec_key, {})
    title = sec.get("title", sec_key)
    items = sec.get("items", [])

    text = f"<b>{title}</b>\n\n" + ("Список ресурсов:" if items else "В этом разделе пока нет ссылок.")
    await safe_send_or_edit(callback, text, reply_markup=get_links_section_keyboard(sec_key, callback.from_user.id))
    await callback.answer()

# ============================================================
# GLOBAL SEARCH & CHATGPT NATURAL QUERIES
# ============================================================

@dp.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def global_search_and_chat_handler(message: types.Message, state: FSMContext):
    query = message.text.strip()
    q_lower = query.lower()

    if q_lower in ["удиви меня", "surprise", "рандом", "challenge", "случайная книга"]:
        return await cb_challenge(message)

    # Conversational math questions -> Route to Math ChatGPT
    math_chat_triggers = [
        "что такое", "какая формула", "как решить", "объясни", "докажи", "теорема", "формула",
        "посоветуй", "порекомендуй", "что почитать", "для олимпиады", "для 9 класса", "для 10 класса", "для 11 класса"
    ]
    if any(trigger in q_lower for trigger in math_chat_triggers) or len(query.split()) > 3:
        loading = await message.answer("🧠 <i>AI анализирует математический запрос...</i>", parse_mode=ParseMode.HTML)
        response_text, matched_uids = await answer_math_chatgpt_query(query, message.from_user.id)
        try:
            await loading.delete()
        except Exception:
            pass

        builder = []
        for uid in matched_uids:
            f = get_file_by_uid(uid)
            if f:
                builder.append([
                    InlineKeyboardButton(
                        text=f"📥 Скачать: {f['caption'][:30]}",
                        callback_data=f"fv:{uid}"
                    )
                ])
        builder.append([
            InlineKeyboardButton(text="🤖 Задать ещё вопрос", callback_data="ai:ask"),
            InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")
        ])

        return await message.answer(
            response_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
        )

    # Google-style keywords search
    words = [w for w in q_lower.split() if w]
    scored_files = []

    for cat_data in DATABASE.get("categories", {}).values():
        for f in cat_data.get("files", []):
            title_text = f.get("caption", "").lower()
            summary_text = f.get("summary", "").lower()
            tags_text = " ".join(f.get("tags", [])).lower()
            cat_text = cat_data.get("title", "").lower()

            haystack = f"{title_text} {summary_text} {tags_text} {cat_text}"
            score = 0

            if q_lower in title_text:
                score += 100
            elif q_lower in haystack:
                score += 50

            for w in words:
                if w in title_text:
                    score += 30
                elif w in tags_text:
                    score += 20
                elif w in haystack:
                    score += 10

            if score > 0:
                if not any(x[0]["file_unique_id"] == f["file_unique_id"] for x in scored_files):
                    scored_files.append((f, cat_data["title"], score))

    scored_files.sort(key=lambda x: x[2], reverse=True)

    if not scored_files:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🤖 Спросить у AI Математика", callback_data="ai:ask")],
                [InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]
            ]
        )
        return await message.answer(
            "🔍 По прямому поиску ничего не найдено.\nПопробуй спросить у <b>AI Математика</b> или открой каталог:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )

    await message.answer(f"🔍 <b>Найдено материалов: {len(scored_files)}</b>", parse_mode=ParseMode.HTML)
    for f, cat_title, _ in scored_files[:5]:
        cap = f"📄 <b>{html.escape(f['caption'])}</b>\n📌 {html.escape(cat_title)}"
        if f.get("summary"):
            cap += f"\n📝 {html.escape(f['summary'])}"
        if f.get("difficulty"):
            cap += f"\n📚 Уровень: {f['difficulty'].upper()}"

        await message.answer_document(
            document=f["file_id"],
            caption=cap,
            parse_mode=ParseMode.HTML,
            reply_markup=get_file_view_keyboard(f["file_unique_id"], message.from_user.id)
        )

# ============================================================
# BATCH AI RE-INDEX OF ALL FILES (/reindex)
# ============================================================

@dp.message(Command("reindex"))
@dp.callback_query(F.data == "admin:reindex")
async def admin_reindex_catalog(event: types.Message | types.CallbackQuery):
    user_id = event.from_user.id
    if not is_admin(user_id):
        if isinstance(event, types.CallbackQuery):
            await event.answer("⛔ Только для администраторов", show_alert=True)
        return

    progress_msg = (
        await event.message.answer("⚡ <b>Запуск полной ИИ-переиндексации базы...</b>", parse_mode=ParseMode.HTML)
        if isinstance(event, types.CallbackQuery)
        else await event.answer("⚡ <b>Запуск полной ИИ-переиндексации базы...</b>", parse_mode=ParseMode.HTML)
    )

    all_unique_files = {}
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        for f in cat_data.get("files", []):
            uid = f.get("file_unique_id")
            if uid and uid not in all_unique_files:
                all_unique_files[uid] = (f, cat_key)

    total = len(all_unique_files)
    if total == 0:
        return await progress_msg.edit_text("❌ В базе данных пока нет файлов.")

    processed = 0
    errors = 0

    for uid, (f_entry, current_cat) in all_unique_files.items():
        processed += 1
        old_title = f_entry.get("caption", "Файл")
        
        try:
            await progress_msg.edit_text(
                f"⚡ <b>ИИ анализирует каталог [{processed}/{total}]...</b>\n\n"
                f"Обработка: <code>{html.escape(old_title[:40])}</code>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

        try:
            file_bytes = await download_file_bytes(f_entry["file_id"])
            if file_bytes:
                ai_meta = await analyze_document_with_ai(file_bytes, old_title)
                
                for cat in DATABASE.get("categories", {}).values():
                    for f in cat.get("files", []):
                        if f.get("file_unique_id") == uid:
                            f["caption"] = ai_meta["title"]
                            f["summary"] = ai_meta["summary"]
                            f["target_audience"] = ai_meta["target_audience"]
                            f["difficulty"] = ai_meta["difficulty"]
                            f["tags"] = ai_meta["tags"]
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error("Error reindexing file %s: %s", uid, e)
            errors += 1

    await save_db(DATABASE)
    await progress_msg.edit_text(
        f"✅ <b>ИИ-переиндексация каталога завершена!</b>\n\n"
        f"📊 Всего файлов: {total}\n"
        f"✨ Успешно обновлено: {processed - errors}\n"
        f"⚠️ Ошибок: {errors}\n\n"
        "Теперь все книги имеют индивидуальные описания, авторов, теги и точные уровни сложности!",
        parse_mode=ParseMode.HTML
    )

# ============================================================
# ADMIN PANEL & INTERACTIVE FILE UPLOAD
# ============================================================

@dp.callback_query(F.data == "admin:main")
async def admin_panel(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Добавить файл (AI авто-анализ)", callback_data="admin:upload")],
            [InlineKeyboardButton(text="⚡ ИИ переиндексация всей базы", callback_data="admin:reindex")],
            [InlineKeyboardButton(text="🎯 Управление задачами дня", callback_data="admin:tasks")],
            [InlineKeyboardButton(text="⭐ Must-read", callback_data="mustread:main")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]
        ]
    )
    await safe_send_or_edit(callback, "👑 <b>Админ-панель</b>\n\nВыбери действие:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "admin:upload")
async def adm_upload_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.answer("📥 Отправь PDF документ — <b>ИИ прочитает первые страницы</b> и сам определит автора, название, сложность и описание!")
    await callback.answer()

@dp.message(F.document, StateFilter(None))
async def global_doc_received(message: types.Message, state: FSMContext):
    if is_admin(message.from_user.id):
        await process_admin_document(message, state)
    else:
        await process_user_submission_doc(message, state)

async def process_admin_document(message: types.Message, state: FSMContext):
    doc = message.document
    if get_file_by_uid(doc.file_unique_id):
        return await message.answer("⚠️ Этот файл уже есть в базе данных!")

    status_msg = await message.answer("⏳ <i>Скачиваю и читаю страницы PDF с помощью ИИ...</i>", parse_mode=ParseMode.HTML)

    file_bytes = await download_file_bytes(doc.file_id)
    original_name = message.caption or doc.file_name or "Документ"
    ai_meta = await analyze_document_with_ai(file_bytes, original_name)

    data_payload = {
        "file_id": doc.file_id,
        "file_unique_id": doc.file_unique_id,
        "title": ai_meta["title"],
        "summary": ai_meta["summary"],
        "target_audience": ai_meta["target_audience"],
        "difficulty": ai_meta["difficulty"],
        "tags": ai_meta["tags"],
        "selected": ai_meta["categories"]
    }
    await state.update_data(**data_payload)
    await state.set_state(FileUpload.confirming_ai_data)

    try:
        await status_msg.delete()
    except Exception:
        pass

    await message.answer(
        render_ai_preview_text(data_payload),
        parse_mode=ParseMode.HTML,
        reply_markup=get_ai_preview_keyboard()
    )

@dp.callback_query(FileUpload.confirming_ai_data, F.data == "ai_save_confirm")
async def admin_confirm_ai_save(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_cats = data.get("selected", ["algebra"])
    uid = data.get("file_unique_id")

    file_entry = {
        "file_id": data["file_id"],
        "file_unique_id": uid,
        "caption": data.get("title", "Без названия"),
        "summary": data.get("summary", ""),
        "target_audience": data.get("target_audience", ""),
        "tags": data.get("tags", []),
        "must_read": False,
        "difficulty": data.get("difficulty", "medium")
    }

    for cat_key in selected_cats:
        if cat_key in DATABASE["categories"]:
            DATABASE["categories"][cat_key]["files"].append(copy.deepcopy(file_entry))

    await save_db(DATABASE)
    await state.clear()
    await callback.message.edit_text(
        f"✅ <b>Файл успешно добавлен в каталог!</b>\n\n"
        f"📄 <b>{html.escape(file_entry['caption'])}</b>\n"
        f"📚 Уровень: {file_entry['difficulty'].upper()}\n"
        f"🏷 Теги: {' '.join(file_entry['tags'])}",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.callback_query(FileUpload.confirming_ai_data, F.data == "ai_edit_title")
async def admin_ai_edit_title(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(FileUpload.waiting_for_caption)
    await callback.message.answer("📝 Отправь новое название книги (<code>Автор — Название</code>):", parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.message(FileUpload.waiting_for_caption, F.text)
async def admin_ai_save_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    data = await state.get_data()
    await state.set_state(FileUpload.confirming_ai_data)
    await message.answer(render_ai_preview_text(data), parse_mode=ParseMode.HTML, reply_markup=get_ai_preview_keyboard())

@dp.callback_query(FileUpload.confirming_ai_data, F.data == "ai_edit_diff")
async def admin_ai_edit_diff(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(FileUpload.choosing_difficulty)
    await callback.message.edit_text("📚 <b>Выбери уровень сложности:</b>", parse_mode=ParseMode.HTML, reply_markup=get_difficulty_selection_kb("ai_set_diff"))
    await callback.answer()

@dp.callback_query(FileUpload.choosing_difficulty, F.data.startswith("ai_set_diff:"))
async def admin_ai_set_diff_value(callback: types.CallbackQuery, state: FSMContext):
    diff = callback.data.split(":")[1]
    if diff != "back":
        await state.update_data(difficulty=diff)
    
    data = await state.get_data()
    await state.set_state(FileUpload.confirming_ai_data)
    await callback.message.edit_text(render_ai_preview_text(data), parse_mode=ParseMode.HTML, reply_markup=get_ai_preview_keyboard())
    await callback.answer()

@dp.callback_query(FileUpload.confirming_ai_data, F.data == "ai_edit_tags")
async def admin_ai_edit_tags(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(FileUpload.waiting_for_tags)
    await callback.message.answer("🏷 Отправь теги через пробел (<code>#geometry #imo</code>):", parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.message(FileUpload.waiting_for_tags, F.text)
async def admin_ai_save_tags(message: types.Message, state: FSMContext):
    tags = [w if w.startswith("#") else f"#{w}" for w in message.text.split()]
    await state.update_data(tags=tags)
    data = await state.get_data()
    await state.set_state(FileUpload.confirming_ai_data)
    await message.answer(render_ai_preview_text(data), parse_mode=ParseMode.HTML, reply_markup=get_ai_preview_keyboard())

@dp.callback_query(FileUpload.confirming_ai_data, F.data == "ai_edit_summary")
async def admin_ai_edit_summary(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(FileUpload.waiting_for_summary)
    await callback.message.answer("📝 Отправь новое описание книги:")
    await callback.answer()

@dp.message(FileUpload.waiting_for_summary, F.text)
async def admin_ai_save_summary(message: types.Message, state: FSMContext):
    await state.update_data(summary=message.text.strip())
    data = await state.get_data()
    await state.set_state(FileUpload.confirming_ai_data)
    await message.answer(render_ai_preview_text(data), parse_mode=ParseMode.HTML, reply_markup=get_ai_preview_keyboard())

@dp.callback_query(FileUpload.confirming_ai_data, F.data == "ai_edit_cats")
async def admin_ai_edit_cats(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = set(data.get("selected", []))
    await state.set_state(FileUpload.selecting_categories)
    await callback.message.edit_reply_markup(reply_markup=build_admin_categories_kb(selected))
    await callback.answer()

@dp.callback_query(FileUpload.selecting_categories, F.data.startswith("a_toggle:"))
async def admin_toggle_cat(callback: types.CallbackQuery, state: FSMContext):
    cat_key = callback.data.split(":")[1]
    data = await state.get_data()
    selected = set(data.get("selected", []))

    if cat_key in selected:
        selected.remove(cat_key)
    else:
        selected.add(cat_key)

    await state.update_data(selected=list(selected))
    await callback.message.edit_reply_markup(reply_markup=build_admin_categories_kb(selected))
    await callback.answer()

@dp.callback_query(FileUpload.selecting_categories, F.data == "a_done")
async def admin_cat_done_save(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(FileUpload.confirming_ai_data)
    await callback.message.edit_text(render_ai_preview_text(data), parse_mode=ParseMode.HTML, reply_markup=get_ai_preview_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "a_cancel")
async def admin_cancel_upload(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Загрузка отменена.")

# ============================================================
# USER SUBMISSIONS WITH AI SCAN
# ============================================================

@dp.callback_query(F.data == "submit:start")
async def submit_start(callback: types.CallbackQuery):
    await track_user_activity(callback.from_user.id, callback.from_user.username or "")
    await callback.message.answer("📤 Просто пришли сюда PDF-файл — ИИ сам прочитает его и подготовит заявку для админа.")
    await callback.answer()

async def process_user_submission_doc(message: types.Message, state: FSMContext):
    doc = message.document
    if get_file_by_uid(doc.file_unique_id):
        return await message.answer("⚠️ Этот файл уже есть в каталоге!")

    status_msg = await message.answer("⏳ <i>ИИ анализирует файл...</i>", parse_mode=ParseMode.HTML)

    file_bytes = await download_file_bytes(doc.file_id)
    original_name = message.caption or doc.file_name or "Документ"
    ai_meta = await analyze_document_with_ai(file_bytes, original_name)

    sub_id = uuid.uuid4().hex[:8]
    sub_data = {
        "_id": sub_id,
        "user_id": message.from_user.id,
        "username": message.from_user.username or message.from_user.full_name,
        "file_id": doc.file_id,
        "file_unique_id": doc.file_unique_id,
        "title": ai_meta["title"],
        "summary": ai_meta["summary"],
        "target_audience": ai_meta["target_audience"],
        "difficulty": ai_meta["difficulty"],
        "tags": ai_meta["tags"],
        "categories": ai_meta["categories"],
        "status": "pending"
    }
    await save_submission(sub_id, sub_data)

    try:
        await status_msg.delete()
    except Exception:
        pass

    await message.answer(
        f"📤 <b>Файл получен и обработан ИИ!</b>\n\n"
        f"🏷 <b>Название:</b> {html.escape(ai_meta['title'])}\n"
        f"📝 <b>Описание:</b> {html.escape(ai_meta['summary'])}\n"
        f"📚 <b>Уровень:</b> {ai_meta['difficulty'].upper()}\n\n"
        "Заявка передана на проверку. Спасибо за вклад в библиотеку! 🙌",
        parse_mode=ParseMode.HTML
    )

    cats_text = ", ".join(DATABASE["categories"][c]["title"] for c in sub_data["categories"] if c in DATABASE["categories"])
    admin_caption = (
        f"📥 <b>Новая заявка на файл</b>\n"
        f"👤 От: @{html.escape(sub_data['username'])}\n"
        f"📄 <b>{html.escape(sub_data['title'])}</b>\n"
        f"📁 Разделы: {cats_text}\n"
        f"📚 Уровень: {sub_data['difficulty'].upper()}\n"
        f"🎯 Аудитория: {html.escape(sub_data['target_audience'])}\n"
        f"🏷 Теги: {' '.join(sub_data['tags'])}\n"
        f"📝 Описание: {html.escape(sub_data['summary'])}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_document(
                admin_id,
                document=sub_data["file_id"],
                caption=admin_caption,
                parse_mode=ParseMode.HTML,
                reply_markup=build_submission_action_kb(sub_id)
            )
        except Exception as e:
            logger.error("Failed to send submission: %s", e)

@dp.callback_query(F.data.startswith("sub_approve:"))
async def sub_approve(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    sub_id = callback.data.split(":")[1]
    sub = await get_submission(sub_id)
    if not sub or sub.get("status") != "pending":
        return await callback.answer("Уже обработано.", show_alert=True)

    for cat_key in sub.get("categories", ["algebra"]):
        if cat_key in DATABASE["categories"]:
            DATABASE["categories"][cat_key]["files"].append({
                "file_id": sub["file_id"],
                "file_unique_id": sub["file_unique_id"],
                "caption": sub["title"],
                "summary": sub.get("summary", ""),
                "target_audience": sub.get("target_audience", ""),
                "tags": sub.get("tags", []),
                "must_read": False,
                "difficulty": sub.get("difficulty", "medium")
            })

    await save_db(DATABASE)
    sub["status"] = "approved"
    await save_submission(sub_id, sub)
    await award_points(sub["user_id"], 15)

    try:
        await callback.message.edit_caption(
            caption=(callback.message.caption or "") + "\n\n✅ <b>ОДОБРЕНО И ДОБАВЛЕНО</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=None
        )
    except Exception:
        pass

    try:
        await bot.send_message(
            sub["user_id"],
            f"✅ Твой файл «{sub['title']}» добавлен в библиотеку!\nСпасибо 🙌 (+15 очков)"
        )
    except Exception:
        pass

    await callback.answer("Одобрено!")

@dp.callback_query(F.data.startswith("sub_reject:"))
async def sub_reject(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    sub_id = callback.data.split(":")[1]
    sub = await get_submission(sub_id)
    if not sub or sub.get("status") != "pending":
        return

    sub["status"] = "rejected"
    await save_submission(sub_id, sub)

    try:
        await callback.message.edit_caption(
            caption=(callback.message.caption or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=None
        )
    except Exception:
        pass

    try:
        await bot.send_message(sub["user_id"], "😔 Твой файл не был принят администратором.")
    except Exception:
        pass

    await callback.answer("Отклонено")

# ============================================================
# NOOP & BOT MENU
# ============================================================

@dp.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer()

async def set_main_menu(b: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню 🚀"),
        BotCommand(command="ai", description="AI Математик (ChatGPT) 🤖"),
        BotCommand(command="menu", description="Меню 📂"),
        BotCommand(command="task", description="Задача дня 🧩"),
        BotCommand(command="challenge", description="Случайный материал 🎲"),
        BotCommand(command="favorites", description="Избранное ❤️"),
        BotCommand(command="rating", description="Рейтинг 🏆"),
        BotCommand(command="links", description="Полезные ссылки 🔗"),
    ]
    await b.set_my_commands(commands)

# ============================================================
# WEB SERVER & MAIN
# ============================================================

async def run_web_server():
    app = web.Application()

    async def health(request):
        return web.Response(text="Matham Bot with Math ChatGPT is fully active!")

    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("🌐 Web server started on port %s", port)

async def main():
    global DATABASE
    if not TOKEN:
        logger.error("BOT_TOKEN is missing! Set BOT_TOKEN environment variable.")
        return

    await run_web_server()
    try:
        await mongo_client.admin.command("ping")
        logger.info("✅ MongoDB connection established")
    except Exception as e:
        logger.error("❌ MongoDB connection error: %s", e)

    DATABASE = await load_db()
    await set_main_menu(bot)
    logger.info("🤖 Bot started! Admin IDs: %s | pypdf available: %s", ADMIN_IDS, PYPDF_AVAILABLE)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
