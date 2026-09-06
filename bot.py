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

# AI API Keys
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
# PDF EXTRACTION & LLM API WITH RETRY LOGIC
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
    """Calls Gemini or OpenAI LLM API with automatic retry on rate limits (429)."""
    if GEMINI_API_KEY:
        models = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
        for m in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": (f"{system_prompt}\n\n" if system_prompt else "") + prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1500}
            }
            # Retry up to 3 times on 429
            for attempt in range(3):
                try:
                    timeout = ClientTimeout(total=25)
                    async with ClientSession(timeout=timeout) as session:
                        async with session.post(url, json=payload) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                candidates = data.get("candidates", [])
                                if candidates:
                                    return candidates[0]["content"]["parts"][0]["text"].strip()
                            elif resp.status == 429:
                                logger.warning("Gemini 429 Rate limit hit, sleeping %s s (attempt %s)", 3 * (attempt + 1), attempt + 1)
                                await asyncio.sleep(3 * (attempt + 1))
                                continue
                            else:
                                logger.error("Gemini API error %s on model %s", resp.status, m)
                                break
                except Exception as e:
                    logger.error("Gemini model %s error: %s", m, e)
                    await asyncio.sleep(2)

    if OPENAI_API_KEY:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt or "Ты профессор и библиограф математической литературы."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 1500
        }
        try:
            timeout = ClientTimeout(total=25)
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

def generate_smart_fallback_description(title: str, text: str, cat_key: str) -> str:
    """Accurate fallback descriptions per specific author/subject without generic repeats."""
    t_lower = (title + " " + text).lower()
    
    if "прасолов" in t_lower:
        if any(k in t_lower for k in ["планиметр", "геометр", "треуголь"]):
            return "Задачник В. В. Прасолова по планиметрии: классические теоремы, геометрические преобразования и задачи с полными решениями."
        if any(k in t_lower for k in ["алгебр", "многочлен", "чисел"]):
            return "Труд В. В. Прасолова по многочленам, алгебре и теории чисел для олимпиадников старших классов."
    
    if "шарыгин" in t_lower:
        return "Пособие И. Ф. Шарыгина по геометрии: развитие наглядного мышления, ключевые олимпиадные леммы и конструкции."
        
    if "titu" in t_lower or "andreescu" in t_lower:
        return "Сборник задач Титу Андрееску: методы решения олимпиадных задач международного уровня (IMO)."

    if "гордин" in t_lower:
        return "Пособие Р. К. Гордина по планиметрии: систематический курс от базовых теорем до уровня финала Всероса."

    if "сканави" in t_lower:
        return "Сборник под редакцией М. И. Сканави: фундаментальная отработка алгебры, тригонометрии и уравнений."

    if cat_key == "geometry":
        return f"Книга по геометрии «{title}»: теоремы планиметрии, свойства фигур и методы доказательств."
    elif cat_key == "number_theory":
        return f"Книга по теории чисел «{title}»: делимость, простые числа, модульная арифметика и диофантовы уравнения."
    elif cat_key == "algebra":
        return f"Книга по алгебре «{title}»: неравенства Коши-Буняковского, многочлены и функциональные уравнения."
    elif cat_key == "combinatorics":
        return f"Книга по комбинаторике «{title}»: принцип Дирихле, графы, инварианты и комбинаторные задачи."
    elif cat_key == "higher_math":
        return f"Курс высшей математики «{title}»: математический анализ, дифференциальное и интегральное исчисление."
    
    return f"Учебный материал «{title}»: разбор олимпиадных тем и подборка задач с решениями."

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
1. "title": Найди официальное название книги и автора в формате: "Автор — Название" (например: "В. В. Прасолов — Задачи по планиметрии").
   - НЕ пиши "Документ", "Книга", "Математический сборник" если есть реальное название.
2. "summary": Напиши индивидуальное емкое описание книги (2-3 предложения): конкретные темы, какие разделы охвачены, чем полезна книга.
3. "target_audience": Для кого предназначена (например: "7-9 класс начинающие", "10-11 класс регион и Всерос", "Студенты").
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
                    "summary": parsed.get("summary", generate_smart_fallback_description(title, pdf_text, cats[0])),
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

    individual_summary = generate_smart_fallback_description(fallback_title, pdf_text, detected_cats[0])

    return {
        "title": fallback_title or "Математический сборник",
        "summary": individual_summary,
        "target_audience": "Школьники и студенты",
        "categories": detected_cats,
        "difficulty": detected_diff,
        "tags": [f"#{detected_cats[0]}", "#olympiad", "#math"]
    }

# ============================================================
# MATH CHATGPT & BOOK RECOMMENDER
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

async def answer_pure_math_question(question: str) -> str:
    """Pure Math ChatGPT: answers any math question, proves theorems, solves problems."""
    system_prompt = (
        "Ты — выдающийся профессор математики и тренер олимпиадной сборной IMO (как ChatGPT).\n"
        "Отвечай на любые вопросы пользователей по математике: объясняй формулы, давай строгие и понятные доказательства, разбирай задачи шаг за шагом.\n"
        "Пиши красиво и понятно на русском языке, используя HTML теги (<b>жирный</b>, <i>курсив</i>, <code>формулы/код</code>)."
    )
    user_prompt = f"Вопрос пользователя: {question}\n\nДай полный, понятный и математически грамотный ответ:"
    
    response = await call_llm_api(user_prompt, system_prompt)
    if response:
        return response

    # Fallback built-in answers
    q_lower = question.lower()
    if "эйлер" in q_lower or "euler" in q_lower:
        return (
            "🧠 <b>Формулы Эйлера в математике:</b>\n\n"
            "<b>1. В комплексном анализе:</b>\n"
            "<code>e^(i*x) = cos(x) + i*sin(x)</code>\n"
            "При x = π получается прекрасное тождество: <code>e^(i*π) + 1 = 0</code>.\n\n"
            "<b>2. В геометрии и теории графов (для многогранников):</b>\n"
            "<code>V - E + F = 2</code> (вершины − рёбра + грани = 2).\n\n"
            "<b>3. В теории чисел (теорема Эйлера):</b>\n"
            "Если НОД(a, m) = 1, то <code>a^φ(m) ≡ 1 (mod m)</code>, где φ(m) — функция Эйлера."
        )
    if "пифагор" in q_lower:
        return "📐 <b>Теорема Пифагора:</b>\nВ прямоугольном треугольнике: <code>a² + b² = c²</code> (квадрат гипотенузы равен сумме квадратов катетов)."

    return f"🧠 <b>Математический ответ на тему «{html.escape(question)}»:</b>\n\nДля детального разбора этой темы воспользуйтесь литературой из каталога или уточните вопрос."

async def recommend_books_by_criteria(user_query: str) -> tuple:
    """Recommends matching books from catalog based on topic, grade and goals."""
    files = get_catalog_files_list()
    if not files:
        return "В библиотеке пока нет доступных книг.", []

    catalog_summary = []
    for f in files[:45]:
        catalog_summary.append(
            f"ID:{f['uid']} | «{f['caption']}» | Раздел:{f['category']} | Описание:{f['summary']} | Уровень:{f['difficulty']} | Теги:{', '.join(f['tags'])}"
        )
    catalog_text = "\n".join(catalog_summary)

    system_prompt = (
        "Ты эксперт-библиограф олимпиадной математики.\n"
        "Подбери от 1 до 3 самых лучших книг из каталога под запрос пользователя (класс, тема, уровень сложности).\n"
        "Объясни для каждой книги, почему она подходит и как по ней заниматься.\n"
        "В САМОМ КОНЦЕ ответа строго добавь строку: MATCHED_UIDS:[id1, id2]"
    )
    user_prompt = f"Запрос пользователя: \"{user_query}\"\n\nКаталог книг:\n{catalog_text}\n\nДай рекомендации с MATCHED_UIDS в конце:"

    response = await call_llm_api(user_prompt, system_prompt)
    if response:
        uids = []
        uid_match = re.search(r"MATCHED_UIDS:\s*\[(.*?)\]", response)
        if uid_match:
            raw_uids = uid_match.group(1).split(",")
            uids = [u.strip().strip("'\"") for u in raw_uids if u.strip()]
            response = re.sub(r"MATCHED_UIDS:\s*\[(.*?)\]", "", response).strip()

        valid_uids = [u for u in uids if get_file_by_uid(u)]
        return response, valid_uids

    # Fallback keyword match
    q_lower = user_query.lower()
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

    text = f"📚 <b>Рекомендованные книги по запросу «{html.escape(user_query)}»:</b>\n"
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
    waiting_for_math_question = State()
    waiting_for_book_recommendation = State()

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
            InlineKeyboardButton(text="🤖 AI Математик", callback_data="ai:menu"),
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

def get_ai_choice_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❓ Задать вопрос по математике (ChatGPT)", callback_data="ai:ask_question")],
            [InlineKeyboardButton(text="📚 Подобрать книгу / задачник", callback_data="ai:find_books")],
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]
        ]
    )

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

    for idx, item in enumerate(items):
        builder.append([
            InlineKeyboardButton(text=item.get("title", f"Ссылка #{idx+1}"), url=item.get("url", ""))
        ])
        if is_admin(user_id):
            builder.append([
                InlineKeyboardButton(text=f"🗑 Удалить #{idx+1}", callback_data=f"links:del:{sec_key}:{idx}")
            ])

    if is_admin(user_id):
        builder.append([
            InlineKeyboardButton(text="➕ Добавить ссылку", callback_data=f"links:add:{sec_key}")
        ])

    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="links:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_file_view_keyboard(uid: str, user_id: int):
    uid_str = str(user_id)
    user_favs = DATABASE.get("users", {}).get(uid_str, {}).get("favorites", [])
    is_fav = uid in user_favs
    fav_text = "💔 Из Избранного" if is_fav else "❤️ В Избранное"

    builder = [
        [InlineKeyboardButton(text=fav_text, callback_data=f"fav:toggle:{uid}")],
    ]
    if is_admin(user_id):
        builder.extend([
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"admin:edit_file:{uid}")],
            [InlineKeyboardButton(text="🗑 Удалить файл", callback_data=f"admin:del_file:{uid}")],
        ])
    builder.append([InlineKeyboardButton(text="⬅️ Каталог", callback_data="menu:catalog")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_daily_task_keyboard(date_str: str, task_idx: int, user_id: int):
    uid_str = str(user_id)
    group = DATABASE.get("daily_tasks", {}).get(date_str, {})
    tasks = group.get("tasks", [])

    if not tasks or task_idx >= len(tasks):
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]])

    task = tasks[task_idx]
    has_submitted = uid_str in task.get("user_solutions", {})

    builder = []
    if not has_submitted:
        builder.append([InlineKeyboardButton(text="📝 Отправить решение", callback_data=f"task:solve:{date_str}:{task_idx}")])
    else:
        builder.append([InlineKeyboardButton(text="✅ Решение отправлено", callback_data="noop")])

    if task.get("solution") or task.get("solution_photo_file_id"):
        builder.append([InlineKeyboardButton(text="💡 Посмотреть решение автора", callback_data=f"task:show_sol:{date_str}:{task_idx}")])

    nav_row = []
    if task_idx > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"task:view:{date_str}:{task_idx - 1}"))
    if task_idx < len(tasks) - 1:
        nav_row.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"task:view:{date_str}:{task_idx + 1}"))
    if nav_row:
        builder.append(nav_row)

    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_admin_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Загрузить материал (AI)", callback_data="admin:upload")],
            [InlineKeyboardButton(text="🎯 Добавить задачу дня", callback_data="admin:add_task")],
            [InlineKeyboardButton(text="📥 Заявки пользователей", callback_data="admin:submissions")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]
        ]
    )

# ============================================================
# ROUTE HANDLERS: START & COMMANDS
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await track_user_activity(message.from_user.id, message.from_user.username or "")
    welcome_text = (
        f"👋 <b>Привет, {html.escape(message.from_user.first_name)}!</b>\n\n"
        f"Добро пожаловать в бота <b>MathAm</b> — твою олимпиадную математическую библиотеку и AI-помощник.\n\n"
        f"📚 Выбирай раздел в меню ниже или задавай любые вопросы по математике через <b>AI Математик</b>."
    )
    await safe_send_or_edit(message, welcome_text, reply_markup=get_main_menu_keyboard(message.from_user.id))

@dp.message(Command("ai"))
async def cmd_ai(message: types.Message):
    await track_user_activity(message.from_user.id, message.from_user.username or "")
    text = (
        "🤖 <b>AI Математический Ассистент</b>\n\n"
        "• <b>Задать вопрос:</b> Извлечение решений, доказательства теорем, помощь с задачами.\n"
        "• <b>Подобрать книгу:</b> ИИ проанализирует библиотеку под ваш класс и цели."
    )
    await safe_send_or_edit(message, text, reply_markup=get_ai_choice_keyboard())

@dp.message(Command("catalog"))
async def cmd_catalog(message: types.Message):
    await track_user_activity(message.from_user.id, message.from_user.username or "")
    await safe_send_or_edit(message, "📚 <b>Каталог материалов по разделам:</b>", reply_markup=get_catalog_keyboard())

@dp.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await track_user_activity(callback.from_user.id, callback.from_user.username or "")
    await safe_send_or_edit(
        callback, 
        "🏠 <b>Главное меню</b>\nВыберите интересующий вас раздел:", 
        reply_markup=get_main_menu_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()

# ============================================================
# ROUTE HANDLERS: AI ASSISTANT
# ============================================================

@dp.callback_query(F.data == "ai:menu")
async def cb_ai_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "🤖 <b>AI Математический Ассистент</b>\n\n"
        "• <b>Задать вопрос:</b> Извлечение решений, доказательства теорем, помощь с задачами.\n"
        "• <b>Подобрать книгу:</b> ИИ проанализирует библиотеку под ваш класс и цели."
    )
    await safe_send_or_edit(callback, text, reply_markup=get_ai_choice_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "ai:ask_question")
async def cb_ai_ask_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AIAssistantState.waiting_for_math_question)
    text = "❓ <b>Напишите ваш математический вопрос или задачу:</b>\n\n(Пример: <i>Докажи теорему Чевы</i> или <i>Как решать однородные диофантовы уравнения?</i>)"
    await safe_send_or_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="ai:menu")]]))
    await callback.answer()

@dp.message(AIAssistantState.waiting_for_math_question)
async def process_ai_question(message: types.Message, state: FSMContext):
    await state.clear()
    wait_msg = await message.answer("🧠 <i>Размышляю над решением...</i>", parse_mode=ParseMode.HTML)
    answer = await answer_pure_math_question(message.text)
    try:
        await wait_msg.delete()
    except Exception:
        pass
    await message.answer(answer, reply_markup=get_ai_choice_keyboard(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "ai:find_books")
async def cb_ai_books_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AIAssistantState.waiting_for_book_recommendation)
    text = "📚 <b>Опишите ваши цели, класс и интересующую тему:</b>\n\n(Пример: <i>Я в 9 классе, хочу подтянуть геометрию для регионального этапа Всероса</i>)"
    await safe_send_or_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="ai:menu")]]))
    await callback.answer()

@dp.message(AIAssistantState.waiting_for_book_recommendation)
async def process_ai_books(message: types.Message, state: FSMContext):
    await state.clear()
    wait_msg = await message.answer("🔍 <i>Анализирую библиотеку и подбираю книги...</i>", parse_mode=ParseMode.HTML)
    recommendation, matched_uids = await recommend_books_by_criteria(message.text)
    try:
        await wait_msg.delete()
    except Exception:
        pass

    builder = []
    for uid in matched_uids:
        f = get_file_by_uid(uid)
        if f:
            builder.append([InlineKeyboardButton(text=f"📖 Открыть «{f.get('caption', 'Книга')}»", callback_data=f"file:view:{uid}")])
    builder.append([InlineKeyboardButton(text="🤖 Вернуться в AI меню", callback_data="ai:menu")])

    await message.answer(recommendation, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode=ParseMode.HTML)

# ============================================================
# ROUTE HANDLERS: CATALOG & FILE BROWSING
# ============================================================

@dp.callback_query(F.data == "menu:catalog")
async def cb_catalog(callback: types.CallbackQuery):
    await safe_send_or_edit(callback, "📚 <b>Каталог материалов по разделам:</b>", reply_markup=get_catalog_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("cat:"))
async def cb_view_category(callback: types.CallbackQuery):
    cat_key = callback.data.split(":")[1]
    cat_data = DATABASE.get("categories", {}).get(cat_key, {})
    files = cat_data.get("files", [])

    if not files:
        await callback.answer("В этом разделе пока нет файлов.", show_alert=True)
        return

    builder = []
    for f in files:
        builder.append([
            InlineKeyboardButton(text=f"📄 {f.get('caption', 'Документ')}", callback_data=f"file:view:{f['file_unique_id']}")
        ])
    builder.append([InlineKeyboardButton(text="⬅️ Каталог", callback_data="menu:catalog")])

    text = f"📂 Раздел: <b>{html.escape(cat_data.get('title', cat_key))}</b>\nВсего материалов: {len(files)}"
    await safe_send_or_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(F.data.startswith("file:view:"))
async def cb_view_file(callback: types.CallbackQuery):
    uid = callback.data.split(":")[2]
    f = get_file_by_uid(uid)
    if not f:
        await callback.answer("Файл не найден.", show_alert=True)
        return

    diff_str = DIFF_NAMES.get(f.get("difficulty", "medium"), "🟡 Medium")
    tags_str = " ".join(f.get("tags", []))

    caption_text = (
        f"📖 <b>{html.escape(f.get('caption', 'Без названия'))}</b>\n\n"
        f"📝 <b>Описание:</b> {html.escape(f.get('summary', '—'))}\n"
        f"🎯 <b>Целевая аудитория:</b> {html.escape(f.get('target_audience', '—'))}\n"
        f"📊 <b>Сложность:</b> {diff_str}\n"
        f"🏷 <b>Теги:</b> {html.escape(tags_str)}"
    )

    try:
        await callback.message.answer_document(
            document=f["file_id"],
            caption=caption_text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_file_view_keyboard(uid, callback.from_user.id)
        )
    except Exception as e:
        logger.error("Failed to send document: %s", e)
        await callback.answer("Ошибка при отправке файла.", show_alert=True)
    await callback.answer()

@dp.callback_query(F.data.startswith("fav:toggle:"))
async def cb_toggle_fav(callback: types.CallbackQuery):
    uid = callback.data.split(":")[2]
    uid_str = str(callback.from_user.id)

    await track_user_activity(callback.from_user.id, callback.from_user.username or "")
    user_favs = DATABASE["users"][uid_str].setdefault("favorites", [])

    if uid in user_favs:
        user_favs.remove(uid)
        msg = "Удалено из избранного"
    else:
        user_favs.append(uid)
        msg = "Добавлено в избранное ❤️"

    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {f"data.users.{uid_str}.favorites": user_favs}}
    )

    await callback.answer(msg)
    try:
        await callback.message.edit_reply_markup(reply_markup=get_file_view_keyboard(uid, callback.from_user.id))
    except Exception:
        pass

@dp.callback_query(F.data == "favorites:main")
async def cb_favorites_main(callback: types.CallbackQuery):
    uid_str = str(callback.from_user.id)
    await track_user_activity(callback.from_user.id, callback.from_user.username or "")
    fav_uids = DATABASE.get("users", {}).get(uid_str, {}).get("favorites", [])

    if not fav_uids:
        await safe_send_or_edit(
            callback,
            "❤️ <b>Ваше Избранное пусто.</b>\n\nСохраняйте полезные книги и задачники, нажимая кнопку «❤️ В Избранное».",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
        )
        await callback.answer()
        return

    builder = []
    for uid in fav_uids:
        f = get_file_by_uid(uid)
        if f:
            builder.append([InlineKeyboardButton(text=f"📖 {f.get('caption', 'Книга')}", callback_data=f"file:view:{uid}")])

    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    await safe_send_or_edit(callback, f"❤️ <b>Избранные материалы ({len(builder)-1}):</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(F.data == "mustread:main")
async def cb_mustread_main(callback: types.CallbackQuery):
    files = get_catalog_files_list()
    must_read_files = [f for f in files if f.get("must_read")]

    if not must_read_files:
        must_read_files = files[:5]

    builder = []
    for f in must_read_files:
        builder.append([InlineKeyboardButton(text=f"⭐ {f['caption']}", callback_data=f"file:view:{f['uid']}")])

    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    await safe_send_or_edit(callback, "⭐ <b>Золотой фонд и Must-Read литература:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()

@dp.callback_query(F.data == "challenge:main")
async def cb_challenge_main(callback: types.CallbackQuery):
    files = get_catalog_files_list()
    if not files:
        await callback.answer("Каталог пуст.", show_alert=True)
        return

    random_file = random.choice(files)
    uid = random_file["uid"]
    await cb_view_file(types.CallbackQuery(id=callback.id, from_user=callback.from_user, message=callback.message, data=f"file:view:{uid}"))

# ============================================================
# ROUTE HANDLERS: LINKS & RATING
# ============================================================

@dp.callback_query(F.data == "links:main")
async def cb_links_main(callback: types.CallbackQuery):
    await safe_send_or_edit(callback, "🔗 <b>Полезные математические ресурсы:</b>", reply_markup=get_links_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("links:sec:"))
async def cb_links_section(callback: types.CallbackQuery):
    sec_key = callback.data.split(":")[2]
    sec_data = DATABASE.get("links", {}).get(sec_key, {})
    await safe_send_or_edit(
        callback,
        f"🔗 <b>{html.escape(sec_data.get('title', sec_key))}</b>",
        reply_markup=get_links_section_keyboard(sec_key, callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == "rating:main")
async def cb_rating_main(callback: types.CallbackQuery):
    users = DATABASE.get("users", {})
    sorted_users = sorted(users.items(), key=lambda x: x[1].get("score", 0), reverse=True)[:10]

    text = "🏆 <b>Топ олимпиадников MathAm:</b>\n\n"
    for idx, (uid, udata) in enumerate(sorted_users, 1):
        uname = udata.get("username") or f"ID: {uid[:5]}..."
        score = udata.get("score", 0)
        streak = udata.get("streak", 1)
        text += f"<b>{idx}. @{html.escape(uname)}</b> — {score} очков (🔥 {streak} дней подряд)\n"

    uid_str = str(callback.from_user.id)
    user_score = users.get(uid_str, {}).get("score", 0)
    text += f"\nВаш текущий счет: <b>{user_score} очков</b>"

    await safe_send_or_edit(
        callback,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
    )
    await callback.answer()

# ============================================================
# ROUTE HANDLERS: DAILY TASK OF THE DAY
# ============================================================

@dp.callback_query(F.data == "task:show")
async def cb_task_show(callback: types.CallbackQuery):
    today = get_yerevan_date()
    group = DATABASE.get("daily_tasks", {}).get(today, {})
    tasks = group.get("tasks", [])

    if not tasks:
        # Check last available task
        all_dates = sorted(DATABASE.get("daily_tasks", {}).keys(), reverse=True)
        if all_dates:
            today = all_dates[0]
            tasks = DATABASE["daily_tasks"][today].get("tasks", [])

    if not tasks:
        await safe_send_or_edit(
            callback,
            "🎯 <b>На сегодня задач пока нет. Загляните позже!</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]])
        )
        await callback.answer()
        return

    await show_daily_task(callback, today, 0)

async def show_daily_task(target, date_str: str, task_idx: int):
    group = DATABASE.get("daily_tasks", {}).get(date_str, {})
    tasks = group.get("tasks", [])
    if not tasks or task_idx >= len(tasks):
        return

    task = tasks[task_idx]
    text = (
        f"🎯 <b>Задача дня ({date_str}) — №{task_idx + 1}/{len(tasks)}</b>\n\n"
        f"{html.escape(task.get('text', 'Текст задачи отсутствует'))}"
    )
    photo_id = task.get("photo_file_id")
    user_id = target.from_user.id if isinstance(target, types.CallbackQuery) else target.from_user.id

    await safe_send_or_edit(
        target,
        text,
        reply_markup=get_daily_task_keyboard(date_str, task_idx, user_id),
        photo_id=photo_id
    )

@dp.callback_query(F.data.startswith("task:view:"))
async def cb_task_view(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    date_str = parts[2]
    task_idx = int(parts[3])
    await show_daily_task(callback, date_str, task_idx)
    await callback.answer()

@dp.callback_query(F.data.startswith("task:solve:"))
async def cb_task_solve(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    date_str = parts[2]
    task_idx = int(parts[3])

    await state.set_state(UserTaskSolution.waiting_for_solution)
    await state.update_data(date_str=date_str, task_idx=task_idx)

    await safe_send_or_edit(
        callback,
        "📝 <b>Пришлите ваше решение или ответ сообщением:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"task:view:{date_str}:{task_idx}")]])
    )
    await callback.answer()

@dp.message(UserTaskSolution.waiting_for_solution)
async def process_user_task_solution(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    date_str = data["date_str"]
    task_idx = data["task_idx"]
    uid_str = str(message.from_user.id)

    task = DATABASE["daily_tasks"][date_str]["tasks"][task_idx]
    task["user_solutions"][uid_str] = {
        "text": message.text or message.caption or "Решение в виде фото/файла",
        "submitted_at": get_yerevan_date()
    }

    await award_points(message.from_user.id, 10)
    await save_db(DATABASE)

    await message.answer(
        "✅ <b>Ваше решение принято! Вам начислено +10 очков!</b>",
        reply_markup=get_daily_task_keyboard(date_str, task_idx, message.from_user.id),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("task:show_sol:"))
async def cb_task_show_solution(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    date_str = parts[2]
    task_idx = int(parts[3])

    task = DATABASE["daily_tasks"][date_str]["tasks"][task_idx]
    sol_text = task.get("solution", "Авторское решение пока не заполнено.")
    sol_photo = task.get("solution_photo_file_id")

    text = f"💡 <b>Авторское решение задачи №{task_idx + 1}:</b>\n\n{html.escape(sol_text)}"
    await safe_send_or_edit(
        callback,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад к задаче", callback_data=f"task:view:{date_str}:{task_idx}")]]),
        photo_id=sol_photo
    )
    await callback.answer()

# ============================================================
# ROUTE HANDLERS: USER SUBMISSIONS (ПРЕДЛОЖИТЬ ФАЙЛ)
# ============================================================

@dp.callback_query(F.data == "submit:start")
async def cb_submit_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserSubmit.confirming_submission)
    await safe_send_or_edit(
        callback,
        "📤 <b>Отправьте PDF документ или книгу, которую хотите предложить в каталог:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="menu:main")]])
    )
    await callback.answer()

@dp.message(UserSubmit.confirming_submission, F.document)
async def process_user_submission_doc(message: types.Message, state: FSMContext):
    await state.clear()
    doc = message.document
    sub_id = uuid.uuid4().hex[:8]

    sub_data = {
        "sub_id": sub_id,
        "user_id": message.from_user.id,
        "username": message.from_user.username or "",
        "file_id": doc.file_id,
        "file_name": doc.file_name or "документ.pdf",
        "created_at": get_yerevan_date(),
        "status": "pending"
    }
    await save_submission(sub_id, sub_data)

    # Notify admins
    for admin_id in ADMIN_IDS:
        try:
            builder = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Принять", callback_data=f"admin:sub_approve:{sub_id}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin:sub_reject:{sub_id}")
                ]
            ])
            await bot.send_document(
                admin_id,
                document=doc.file_id,
                caption=f"📥 <b>Новая заявка #{sub_id} от @{html.escape(message.from_user.username or str(message.from_user.id))}</b>\nФайл: {html.escape(doc.file_name or '')}",
                parse_mode=ParseMode.HTML,
                reply_markup=builder
            )
        except Exception as e:
            logger.error("Failed to notify admin %s: %s", admin_id, e)

    await message.answer("✅ <b>Ваш файл успешно отправлен на модерацию! Спасибо за вклад в библиотеку.</b>", parse_mode=ParseMode.HTML)

# ============================================================
# ROUTE HANDLERS: ADMIN PANEL
# ============================================================

@dp.callback_query(F.data == "admin:main")
async def cb_admin_main(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return
    await safe_send_or_edit(callback, "👑 <b>Панель администратора MathAm:</b>", reply_markup=get_admin_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin:upload")
async def cb_admin_upload_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(FileUpload.confirming_ai_data)
    await safe_send_or_edit(
        callback,
        "➕ <b>Отправьте PDF файл книги. AI автоматически распознает авторство, название, теги и категорию!</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin:main")]])
    )
    await callback.answer()

@dp.message(FileUpload.confirming_ai_data, F.document)
async def process_admin_upload_doc(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    wait_msg = await message.answer("⏳ <i>Скачиваю и анализирую умные метаданные через AI...</i>", parse_mode=ParseMode.HTML)
    doc = message.document
    file_bytes = await download_file_bytes(doc.file_id)

    ai_meta = await analyze_document_with_ai(file_bytes, doc.file_name or "книга.pdf")
    try:
        await wait_msg.delete()
    except Exception:
        pass

    await state.update_data(
        file_id=doc.file_id,
        file_name=doc.file_name,
        ai_meta=ai_meta
    )

    diff_str = DIFF_NAMES.get(ai_meta.get("difficulty", "medium"), "🟡 Medium")
    text = (
        f"🤖 <b>AI Результат распознавания:</b>\n\n"
        f"📖 <b>Название:</b> {html.escape(ai_meta['title'])}\n"
        f"📝 <b>Описание:</b> {html.escape(ai_meta['summary'])}\n"
        f"🎯 <b>Аудитория:</b> {html.escape(ai_meta['target_audience'])}\n"
        f"📊 <b>Сложность:</b> {diff_str}\n"
        f"🏷 <b>Теги:</b> {' '.join(ai_meta['tags'])}\n"
        f"📂 <b>Предложенный раздел:</b> {ai_meta['categories'][0]}\n\n"
        f"Публикуем или изменим данные?"
    )

    builder = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать как есть", callback_data="admin:upload_confirm")],
        [InlineKeyboardButton(text="✏️ Изменить название", callback_data="admin:upload_edit_title")],
        [InlineKeyboardButton(text="📂 Выбрать категории", callback_data="admin:upload_edit_cats")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:main")]
    ])

    await message.answer(text, reply_markup=builder, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin:upload_confirm")
async def cb_admin_upload_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    ai_meta = data["ai_meta"]
    file_id = data["file_id"]
    file_uid = uuid.uuid4().hex[:10]

    file_obj = {
        "file_id": file_id,
        "file_unique_id": file_uid,
        "caption": ai_meta["title"],
        "summary": ai_meta["summary"],
        "target_audience": ai_meta["target_audience"],
        "difficulty": ai_meta["difficulty"],
        "tags": ai_meta["tags"],
        "must_read": False
    }

    for cat_key in ai_meta["categories"]:
        if cat_key in DATABASE["categories"]:
            DATABASE["categories"][cat_key]["files"].append(file_obj)

    await save_db(DATABASE)
    await safe_send_or_edit(callback, f"🎉 <b>Материал «{html.escape(ai_meta['title'])}» успешно сохранен в библиотеку!</b>", reply_markup=get_admin_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("admin:sub_approve:"))
async def cb_admin_sub_approve(callback: types.CallbackQuery):
    sub_id = callback.data.split(":")[2]
    sub = await get_submission(sub_id)
    if not sub:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return

    file_bytes = await download_file_bytes(sub["file_id"])
    ai_meta = await analyze_document_with_ai(file_bytes, sub.get("file_name", "книга.pdf"))

    file_uid = uuid.uuid4().hex[:10]
    file_obj = {
        "file_id": sub["file_id"],
        "file_unique_id": file_uid,
        "caption": ai_meta["title"],
        "summary": ai_meta["summary"],
        "target_audience": ai_meta["target_audience"],
        "difficulty": ai_meta["difficulty"],
        "tags": ai_meta["tags"],
        "must_read": False
    }

    cat_key = ai_meta["categories"][0]
    DATABASE["categories"][cat_key]["files"].append(file_obj)
    await save_db(DATABASE)

    sub["status"] = "approved"
    await save_submission(sub_id, sub)

    # Notify user & award points
    await award_points(sub["user_id"], 50)
    try:
        await bot.send_message(sub["user_id"], f"🎉 <b>Ваша предлагаемая книга «{html.escape(ai_meta['title'])}» была одобрена и добавлена в каталог! Вам начислено +50 очков!</b>", parse_mode=ParseMode.HTML)
    except Exception:
        pass

    await callback.message.edit_caption(caption=f"✅ <b>Заявка #{sub_id} одобрена и опубликована!</b>", parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin:sub_reject:"))
async def cb_admin_sub_reject(callback: types.CallbackQuery):
    sub_id = callback.data.split(":")[2]
    sub = await get_submission(sub_id)
    if sub:
        sub["status"] = "rejected"
        await save_submission(sub_id, sub)
        try:
            await bot.send_message(sub["user_id"], "❌ К сожалению, ваша предложенная книга не прошла модерацию.", parse_mode=ParseMode.HTML)
        except Exception:
            pass

    await callback.message.edit_caption(caption=f"❌ <b>Заявка #{sub_id} отклонена.</b>", parse_mode=ParseMode.HTML)
    await callback.answer()

# ============================================================
# ROUTE HANDLERS: ADMIN TASK OF THE DAY
# ============================================================

@dp.callback_query(F.data == "admin:add_task")
async def cb_admin_add_task_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(TaskOfDayAdmin.waiting_for_photo)
    await safe_send_or_edit(
        callback,
        "🎯 <b>Пришлите фото задачи дня или отправьте /skip если задачи без картинки:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin:main")]])
    )
    await callback.answer()

@dp.message(TaskOfDayAdmin.waiting_for_photo)
async def process_admin_task_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(photo_file_id=photo_id)
    await state.set_state(TaskOfDayAdmin.waiting_for_solution)
    await message.answer("📝 <b>Теперь введите текст задачи и авторское решение:</b>", parse_mode=ParseMode.HTML)

@dp.message(TaskOfDayAdmin.waiting_for_solution)
async def process_admin_task_solution(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    today = get_yerevan_date()
    group = DATABASE["daily_tasks"].setdefault(today, {"tasks": []})

    new_task = {
        "task_id": uuid.uuid4().hex[:10],
        "text": message.text or "Задача дня",
        "photo_file_id": data.get("photo_file_id"),
        "solution": message.text,
        "solution_photo_file_id": None,
        "user_solutions": {},
        "created_at": today
    }
    group["tasks"].append(new_task)
    await save_db(DATABASE)

    await message.answer("✅ <b>Задача дня успешно добавлена и опубликована!</b>", reply_markup=get_admin_menu_keyboard(), parse_mode=ParseMode.HTML)

# ============================================================
# ROUTE HANDLERS: BROADCAST & LINKS MANAGEMENT
# ============================================================

@dp.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(BroadcastAdmin.waiting_for_message)
    await safe_send_or_edit(
        callback,
        "📢 <b>Пришлите сообщение для рассылки всем пользователям бота:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin:main")]])
    )
    await callback.answer()

@dp.message(BroadcastAdmin.waiting_for_message)
async def process_admin_broadcast(message: types.Message, state: FSMContext):
    await state.clear()
    users = DATABASE.get("users", {})
    count = 0

    for uid_str in users.keys():
        try:
            await message.copy_to(int(uid_str))
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await message.answer(f"✅ <b>Рассылка завершена! Успешно доставлено {count} пользователям.</b>", reply_markup=get_admin_menu_keyboard(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("links:del:"))
async def cb_links_delete(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    sec_key = parts[2]
    idx = int(parts[3])

    items = DATABASE["links"][sec_key]["items"]
    if 0 <= idx < len(items):
        items.pop(idx)
        await save_db(DATABASE)
        await callback.answer("Ссылка удалена.")

    await cb_links_section(callback)

@dp.callback_query(F.data.startswith("links:add:"))
async def cb_links_add_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    sec_key = callback.data.split(":")[2]
    await state.set_state(AddLink.waiting_for_text)
    await state.update_data(sec_key=sec_key)

    await safe_send_or_edit(
        callback,
        "🔗 <b>Пришлите ссылку в формате:</b>\n<code>Название сайта - https://example.com</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"links:sec:{sec_key}")]])
    )
    await callback.answer()

@dp.message(AddLink.waiting_for_text)
async def process_add_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    sec_key = data["sec_key"]

    if "-" in message.text:
        parts = message.text.split("-", 1)
        title = parts[0].strip()
        url = parts[1].strip()
    else:
        title = "Ресурс"
        url = message.text.strip()

    DATABASE["links"][sec_key]["items"].append({"title": title, "url": url})
    await save_db(DATABASE)

    await message.answer("✅ <b>Ссылка добавлена!</b>", reply_markup=get_links_section_keyboard(sec_key, message.from_user.id), parse_mode=ParseMode.HTML)

# ============================================================
# INLINE QUERY SEARCH ENGINE
# ============================================================

@dp.inline_query()
async def inline_search(query: InlineQuery):
    q = query.query.strip().lower()
    results = []
    files = get_catalog_files_list()

    for f in files:
        if not q or q in f["caption"].lower() or any(q in t.lower() for t in f["tags"]):
            results.append(
                InlineQueryResultCachedDocument(
                    id=f["uid"],
                    title=f["caption"],
                    document_file_id=f["file_id"],
                    description=f["summary"][:100],
                    caption=f"📖 <b>{html.escape(f['caption'])}</b>\n{html.escape(f['summary'])}"
                )
            )
            if len(results) >= 20:
                break

    await query.answer(results, cache_time=10, is_personal=True)

# ============================================================
# STARTUP & MAIN RUNNER
# ============================================================

async def on_startup():
    global DATABASE
    DATABASE = await load_db()
    logger.info("Database loaded successfully. Registered %d categories.", len(DATABASE.get("categories", {})))

    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="ai", description="🤖 AI Математик"),
        BotCommand(command="catalog", description="📚 Каталог литературы"),
    ]
    await bot.set_my_commands(commands)

async def main():
    dp.startup.register(on_startup)
    logger.info("Starting Telegram Bot listener...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
