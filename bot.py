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
        "main_menu": "📂 Главное меню библиотеки matham",
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
        "ai_assistant": "🤖 AI Помощник",
        "back": "⬅️ Назад",
        "menu": "⬅️ Меню",
        "solution": "📝 Решение",
        "send_solution": "✍️ Отправить своё решение",
        "previous_tasks": "📅 Архив задач",
        "no_tasks": "📭 Задач пока нет в базе.",
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
        "ai_prompt": "🤖 <b>AI Помощник по математике</b>\n\nЯ проанализировал каждую страницу всех книг в библиотеке!\nНапиши, что ты ищешь, свой класс/уровень и цель.\n\n<i>Например:</i>\n• <i>«Посоветуй книги по планиметрии для подготовки к региону 9 класс»</i>\n• <i>«Базовый задачник по теории чисел для начинающих»</i>\n• <i>«Сложные задачи по комбинаторике уровня IMO»</i>",
        "ai_searching": "🧠 AI анализирует каталог и подбирает лучшие материалы...",
    },
    "en": {
        "choose_language": "🌍 Choose your language:",
        "language_saved": "🇬🇧 Language changed to English.",
        "main_menu": "📂 Matham Main Menu",
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
        "ai_assistant": "🤖 AI Assistant",
        "back": "⬅️ Back",
        "menu": "⬅️ Menu",
        "solution": "📝 Solution",
        "send_solution": "✍️ Submit Your Solution",
        "previous_tasks": "📅 Problem Archive",
        "no_tasks": "📭 No problems available yet.",
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
        "ai_prompt": "🤖 <b>Math AI Assistant</b>\n\nI have read and indexed all materials in this library!\nTell me what topic you need, your level, and your goals.\n\n<i>For example:</i>\n• <i>\"Recommend geometry books for olympiad prep grade 9\"</i>\n• <i>\"Introductory number theory textbook for beginners\"</i>\n• <i>\"Hard IMO-level combinatorics problems\"</i>",
        "ai_searching": "🧠 AI is analyzing the library catalog to find the best materials for you...",
    }
}

def get_user_language(user_id: int) -> str:
    user = DATABASE.get("users", {}).get(str(user_id), {})
    return user.get("language", "ru")

def t(user_id: int, key: str) -> str:
    lang = get_user_language(user_id)
    return TEXTS.get(lang, TEXTS["ru"]).get(key, TEXTS["ru"].get(key, key))

def category_title(cat_data: dict, user_id: int) -> str:
    lang = get_user_language(user_id)
    if lang == "en" and cat_data.get("title_en"):
        return cat_data["title_en"]
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
    yesterday = (datetime.now(YEREVAN_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    DATABASE.setdefault("users", {})
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
    user.setdefault("language", "ru")

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
        cat_data.setdefault("title_en", default_cat["title_en"])
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
        sec_data.setdefault("title_en", default_sec["title_en"])
        sec_data.setdefault("items", [])

    # Users migration
    for uid, user in data["users"].items():
        user.setdefault("username", "")
        user.setdefault("streak", 1)
        user.setdefault("last_active", get_yerevan_date())
        user.setdefault("score", 0)
        user.setdefault("favorites", [])
        user.setdefault("opened_tasks", [])
        user.setdefault("language", "ru")

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
# PDF EXTRACTION & SMART AI INSPECTOR
# ============================================================

def extract_pdf_first_pages_text(file_bytes: bytes, max_pages: int = 6) -> str:
    """Extracts text from the first N pages of a PDF file using pypdf."""
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
        return full_text[:8500]
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

async def call_llm_api(prompt: str) -> str:
    """Calls Gemini or OpenAI LLM API with high reliability."""
    if GEMINI_API_KEY:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 1000}
        }
        timeout = ClientTimeout(total=25)
        async with ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        return candidates[0]["content"]["parts"][0]["text"].strip()
                else:
                    logger.error("Gemini API error status=%s", resp.status)
    elif OPENAI_API_KEY:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Ты профессиональный библиограф математической литературы и тренер олимпиадной сборной."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 1000
        }
        timeout = ClientTimeout(total=25)
        async with ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
    return ""

def clean_filename_title(raw_name: str) -> str:
    """Clean technical filenames to human readable form."""
    name = os.path.splitext(raw_name)[0]
    name = re.sub(r'[_+.-]', ' ', name)
    name = re.sub(r'\b(pdf|djvu|book|scan|final|v\d+|\d{4})\b', '', name, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', name).strip().title()

async def analyze_document_with_ai(file_bytes: bytes, original_name: str) -> dict:
    """
    Analyzes first pages of PDF to return:
    - title (Author — Book Name)
    - summary
    - target_audience
    - categories (list)
    - difficulty (easy, medium, hard, imo)
    - tags (list)
    """
    pdf_text = extract_pdf_first_pages_text(file_bytes, max_pages=6)
    fallback_title = clean_filename_title(original_name)

    prompt = f"""Ты опытный методист и библиограф олимпиадной математики.
Внимательно изучи текст первых страниц книги/статьи (титульный лист, оборот титула, предисловие, оглавление) и выдели точные метаданные.

Оригинальное имя файла: {original_name}

Текст первых страниц:
{pdf_text if pdf_text else 'Текст не извлечен (скан). Ориентируйся строго по имени файла: ' + original_name}

Правила:
1. "title": Найди официальное название книги и автора.
   - Формат: "Автор — Название" (например: "В. В. Прасолов — Задачи по планиметрии" или "Titu Andreescu — 104 Number Theory Problems").
   - Если это сборник олимпиады: "Всероссийская олимпиада — 2022" или "Московская математическая олимпиада — Сборник задач".
   - НЕ оставляй технические символы, расширения .pdf и слова "скачать".
2. "summary": Краткое описание (2 предложения): о чем книга, ключевые темы, какие олимпиадные идеи/методы разбираются.
3. "target_audience": Для кого предназначена (например: "Школьники 7-9 классов, начинающие", "10-11 классы, регион и финал", "Студенты вузов").
4. "categories": Список подходящих категорий из: ["geometry", "number_theory", "algebra", "combinatorics", "higher_math", "titu"].
5. "difficulty": Оценка сложности. Выбери СТРОГО ОДНО:
   - "easy" (базовый уровень, 6-8 класс, кружки)
   - "medium" (региональные олимпиады, 8-11 класс)
   - "hard" (высокий уровень, финал Всероса, продвинутые сборники)
   - "imo" (международный уровень IMO, сборная страны)
6. "tags": 3-5 хештегов (например: ["#geometry", "#planimetry", "#olympiad"]).

Верни ответ ТОЛЬКО в виде JSON:
{{
  "title": "Автор — Название",
  "summary": "...",
  "target_audience": "...",
  "categories": ["geometry"],
  "difficulty": "medium",
  "tags": ["#tag1", "#tag2"]
}}
"""

    ai_raw = await call_llm_api(prompt)

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
                    tags = [f"#{cats[0]}", "#math"]

                return {
                    "title": title,
                    "summary": parsed.get("summary", "Учебный олимпиадный материал."),
                    "target_audience": parsed.get("target_audience", "Школьники и олимпиадники"),
                    "categories": cats,
                    "difficulty": diff,
                    "tags": tags
                }
        except Exception as e:
            logger.error("Failed to parse AI JSON: %s (Raw: %s)", e, ai_raw)

    # Heuristic fallback if AI unavailable
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

    return {
        "title": fallback_title or "Математический сборник",
        "summary": "Материалы и задачи для олимпиадной подготовки.",
        "target_audience": "Школьники и студенты",
        "categories": detected_cats,
        "difficulty": detected_diff,
        "tags": [f"#{detected_cats[0]}", "#olympiad", "#math"]
    }

# ============================================================
# AI RECOMMENDATION ENGINE
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

async def ai_recommend_materials(user_query: str, user_id: int) -> tuple:
    """Main entrypoint for AI recommendations. Returns (text_response, [file_uids])."""
    files = get_catalog_files_list()
    if not files:
        return "В библиотеке пока нет доступных файлов для рекомендации.", []

    catalog_summary = []
    for f in files:
        catalog_summary.append(
            f"ID: {f['uid']}\n"
            f"• Название: {f['caption']}\n"
            f"• Раздел: {f['category']}\n"
            f"• Описание: {f['summary']}\n"
            f"• Аудитория: {f['target_audience']}\n"
            f"• Уровень: {f['difficulty'].upper()} | Теги: {', '.join(f['tags'])}"
        )
    catalog_text = "\n\n".join(catalog_summary)

    lang = get_user_language(user_id)
    lang_instruction = "Ответь на русском языке." if lang == "ru" else "Respond in English."

    prompt = f"""Ты опытный тренер сборной по олимпиадной математике.
Пользователь ищет материалы в нашей математической библиотеке.

Каталог всех имеющихся книг с описаниями и уровнями сложности:
{catalog_text}

Запрос пользователя: "{user_query}"

Инструкция:
1. Выбери от 1 до 3 самых подходящих файлов из каталога под уровень, класс, тему и цель пользователя.
2. {lang_instruction}
3. Кратко и емко объясни, почему каждая выбранная книга подходит под его запрос и как по ней лучше заниматься.
4. В САМОМ КОНЦЕ ответа обязательно напиши строго строку в формате: MATCHED_UIDS:[id1, id2]
Пример конца ответа: MATCHED_UIDS:[12345, 67890]
"""

    ai_response = await call_llm_api(prompt)

    if ai_response:
        uids = []
        uid_match = re.search(r"MATCHED_UIDS:\s*\[(.*?)\]", ai_response)
        if uid_match:
            raw_uids = uid_match.group(1).split(",")
            uids = [u.strip().strip("'\"") for u in raw_uids if u.strip()]
            ai_response = re.sub(r"MATCHED_UIDS:\s*\[(.*?)\]", "", ai_response).strip()

        valid_uids = [u for u in uids if get_file_by_uid(u)]
        if not valid_uids:
            valid_uids = [f["uid"] for f in files[:2]]

        return ai_response, valid_uids

    # Heuristic fallback matching
    q_lower = user_query.lower()
    scored = []
    for f in files:
        score = 0
        haystack = f"{f['caption']} {f['category']} {f['summary']} {f['target_audience']} {' '.join(f['tags'])} {f['difficulty']}".lower()
        for w in q_lower.split():
            if len(w) > 2 and w in haystack:
                score += 3
        if f["must_read"]:
            score += 2
        if score > 0:
            scored.append((score, f))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_matches = [item[1] for item in scored[:3]] or files[:3]

    text = (
        "🤖 <b>Рекомендация по твоему запросу:</b>\n\n"
        f"<i>Запрос:</i> «{html.escape(user_query)}»\n\n"
        "Я проанализировал каталог и подобрал лучшие материалы:\n"
    )
    for i, f in enumerate(top_matches, 1):
        text += (
            f"\n<b>{i}. {html.escape(f['caption'])}</b>\n"
            f"📌 Раздел: {f['category']} | 📚 Уровень: {f['difficulty'].upper()}\n"
            f"📝 <i>{html.escape(f['summary'] or 'Олимпиадный сборник')}</i>\n"
        )
    text += "\nНажми на кнопки ниже, чтобы открыть файлы:"
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
# UI BUILDERS
# ============================================================

DIFF_NAMES = {
    "easy": "🟢 Easy (Базовый)",
    "medium": "🟡 Medium (Регион)",
    "hard": "🔴 Hard (Всерос / Финал)",
    "imo": "🔥 IMO (Международный)"
}

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

def get_language_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")
            ]
        ]
    )

def get_main_menu_keyboard(user_id: int):
    builder = [
        [
            InlineKeyboardButton(text=t(user_id, "ai_assistant"), callback_data="ai:ask"),
            InlineKeyboardButton(text=t(user_id, "catalog"), callback_data="menu:catalog"),
        ],
        [
            InlineKeyboardButton(text=t(user_id, "daily_task"), callback_data="task:show"),
            InlineKeyboardButton(text=t(user_id, "must_read"), callback_data="mustread:main"),
        ],
        [
            InlineKeyboardButton(text=t(user_id, "favorites"), callback_data="favorites:main"),
            InlineKeyboardButton(text=t(user_id, "rating"), callback_data="rating:main"),
        ],
        [
            InlineKeyboardButton(text=t(user_id, "challenge"), callback_data="challenge:main"),
            InlineKeyboardButton(text=t(user_id, "links"), callback_data="links:main"),
        ],
        [
            InlineKeyboardButton(text=t(user_id, "submit"), callback_data="submit:start"),
            InlineKeyboardButton(text=t(user_id, "language"), callback_data="menu:language"),
        ],
    ]
    if is_admin(user_id):
        builder.append([
            InlineKeyboardButton(text=t(user_id, "admin"), callback_data="admin:main")
        ])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_catalog_keyboard(user_id: int):
    builder = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        builder.append([
            InlineKeyboardButton(
                text=category_title(cat_data, user_id),
                callback_data=f"cat:{cat_key}"
            )
        ])
    builder.append([
        InlineKeyboardButton(text=t(user_id, "menu"), callback_data="menu:main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_links_keyboard(user_id: int):
    builder = []
    for sec_key, sec_data in DATABASE.get("links", {}).items():
        title = sec_data.get("title_en") if get_user_language(user_id) == "en" and sec_data.get("title_en") else sec_data.get("title", sec_key)
        builder.append([
            InlineKeyboardButton(
                text=title,
                callback_data=f"links:sec:{sec_key}"
            )
        ])
    builder.append([
        InlineKeyboardButton(text=t(user_id, "menu"), callback_data="menu:main")
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
            text=t(user_id, "back"),
            callback_data="links:main"
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=builder)

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
    return InlineKeyboardMarkup(inline_keyboard=builder)

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
                description="Введите автора, название, олимпиаду или ключевое слово",
                input_message_content=InputTextMessageContent(
                    message_text="Воспользуйтесь поиском для нахождения олимпиадных и учебных материалов!"
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

            # Exact query match
            if query in title_text:
                score += 100
            elif query in haystack:
                score += 50

            # Word by word match
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
# COMMANDS & NAVIGATION
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await track_user_activity(message.from_user.id, message.from_user.username or "")
    await message.answer(
        "👋 <b>Добро пожаловать в библиотеку matham!</b>\n\n"
        "🤖 <b>AI Помощник</b> — прочитал все книги и подберёт материал под твой уровень и задачи\n"
        "📚 <b>Каталог</b> — все материалы по разделам\n"
        "🎯 <b>Задача дня</b> — ежедневная олимпиадная задача\n"
        "⭐ <b>Must-read</b> — проверенная классика",
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
            t(message.from_user.id, "main_menu"),
            reply_markup=get_main_menu_keyboard(message.from_user.id)
        )

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await track_user_activity(message.from_user.id, message.from_user.username or "")
    await message.answer(
        t(message.from_user.id, "main_menu"),
        reply_markup=get_main_menu_keyboard(message.from_user.id)
    )

@dp.message(Command("language"))
async def cmd_language(message: types.Message):
    await message.answer(
        t(message.from_user.id, "choose_language"),
        reply_markup=get_language_keyboard()
    )

@dp.callback_query(F.data == "menu:language")
async def callback_menu_language(callback: types.CallbackQuery):
    await callback.message.edit_text(
        t(callback.from_user.id, "choose_language"),
        reply_markup=get_language_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("lang:"))
async def callback_set_language(callback: types.CallbackQuery):
    lang = callback.data.split(":")[1]
    uid_str = str(callback.from_user.id)
    if uid_str not in DATABASE["users"]:
        await track_user_activity(callback.from_user.id, callback.from_user.username or "")
    DATABASE["users"][uid_str]["language"] = lang
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {f"data.users.{uid_str}.language": lang}}
    )
    await callback.message.edit_text(
        t(callback.from_user.id, "language_saved"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(callback.from_user.id, "menu"), callback_data="menu:main")]
            ]
        )
    )
    await callback.answer()

@dp.callback_query(F.data == "menu:main")
async def process_back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await track_user_activity(callback.from_user.id, callback.from_user.username or "")
    text = t(callback.from_user.id, "main_menu")
    kb = get_main_menu_keyboard(callback.from_user.id)

    if callback.message.photo or callback.message.document:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        try:
            await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    await callback.answer()

@dp.callback_query(F.data == "menu:catalog")
async def process_catalog(callback: types.CallbackQuery):
    await callback.message.edit_text(
        f"{t(callback.from_user.id, 'catalog')}\n\nВыбери раздел:",
        reply_markup=get_catalog_keyboard(callback.from_user.id)
    )
    await callback.answer()

# ============================================================
# AI ASSISTANT
# ============================================================

@dp.message(Command("ai"))
@dp.message(Command("ask"))
@dp.callback_query(F.data == "ai:ask")
async def start_ai_assistant(event: types.Message | types.CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    await track_user_activity(user_id, event.from_user.username or "")
    await state.set_state(AIAssistantState.waiting_for_query)

    text = t(user_id, "ai_prompt")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(user_id, "cancel"), callback_data="ai:cancel")]
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
        t(callback.from_user.id, "main_menu"),
        reply_markup=get_main_menu_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.message(AIAssistantState.waiting_for_query, F.text)
async def process_ai_query(message: types.Message, state: FSMContext):
    if message.text.lower() in ["отмена", "/cancel"]:
        await state.clear()
        return await message.answer(
            t(message.from_user.id, "cancel"),
            reply_markup=get_main_menu_keyboard(message.from_user.id)
        )

    await track_user_activity(message.from_user.id, message.from_user.username or "")
    loading_msg = await message.answer(t(message.from_user.id, "ai_searching"))

    response_text, matched_uids = await ai_recommend_materials(message.text, message.from_user.id)
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
        InlineKeyboardButton(text="🔄 Задать другой вопрос", callback_data="ai:ask"),
        InlineKeyboardButton(text=t(message.from_user.id, "menu"), callback_data="menu:main")
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
# FIXED DAILY TASK SYSTEM (ALWAYS WORKING)
# ============================================================

async def send_daily_task(target, date_str: str = None, task_index: int = 0):
    is_message = isinstance(target, types.Message)
    user_id = target.from_user.id

    # If specific date requested
    if date_str:
        task = get_task_by_index(date_str, task_index)
        current_date = date_str
    else:
        # Check today first
        today = get_yerevan_date()
        task = get_task_by_index(today, task_index)
        if task:
            current_date = today
        else:
            # Fallback to the latest published task
            latest_date, latest_task, _ = get_latest_task_info()
            task = latest_task
            current_date = latest_date or today

    if not task:
        text = (
            f"🧩 <b>Задача дня</b>\n\n"
            "Задач пока нет в базе данных. Администраторы скоро опубликуют первую задачу!"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(user_id, "menu"), callback_data="menu:main")]
            ]
        )
        if is_message:
            await target.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            try:
                await target.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            except Exception:
                await target.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # Activity & reward points
    if current_date == get_yerevan_date():
        uid_str = str(user_id)
        opened = DATABASE["users"].setdefault(uid_str, {}).setdefault("opened_tasks", [])
        key = f"{current_date}:{task_index}"
        if key not in opened:
            opened.append(key)
            await award_points(user_id, 5)
            await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {f"data.users.{uid_str}.opened_tasks": opened}})

    date_title = f"{current_date} (Сегодня)" if current_date == get_yerevan_date() else current_date
    cap = f"🧩 <b>Задача {task_index + 1}</b> ({date_title})"
    
    votes = task.get("votes", {})
    if votes:
        avg = sum(votes.values()) / len(votes)
        cap += f"\n\n⭐ Оценка: {avg:.1f}/5 (Голосов: {len(votes)})"
    if len(get_tasks_for_date(current_date)) > 1:
        cap += f"\n📚 Задач за эту дату: {len(get_tasks_for_date(current_date))}"

    kb = get_task_keyboard(current_date, user_id, is_admin(user_id), task_index)
    photo_id = task.get("photo_file_id")

    if photo_id:
        if is_message:
            await target.answer_photo(photo=photo_id, caption=cap, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            try:
                await target.message.delete()
            except Exception:
                pass
            await target.message.answer_photo(photo=photo_id, caption=cap, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        if is_message:
            await target.answer(cap, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            try:
                if target.message.photo or target.message.document:
                    await target.message.delete()
                    await target.message.answer(cap, parse_mode=ParseMode.HTML, reply_markup=kb)
                else:
                    await target.message.edit_text(cap, parse_mode=ParseMode.HTML, reply_markup=kb)
            except Exception:
                await target.message.answer(cap, parse_mode=ParseMode.HTML, reply_markup=kb)

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
    kb = get_history_keyboard(callback.from_user.id)
    if callback.message.photo or callback.message.document:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        try:
            await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
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
        return await callback.answer("Неверный формат оценки", show_alert=True)

    score = int(score_str)
    if score < 1 or score > 5:
        return await callback.answer("Неверный балл", show_alert=True)

    task = get_task_by_index(date_str, task_index)
    if not task:
        return await callback.answer(t(callback.from_user.id, "task_not_found"), show_alert=True)

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
                reply_markup=get_task_keyboard(
                    date_str,
                    callback.from_user.id,
                    is_admin(callback.from_user.id),
                    task_index
                )
            )
        else:
            await callback.message.edit_text(
                text=cap,
                parse_mode=ParseMode.HTML,
                reply_markup=get_task_keyboard(
                    date_str,
                    callback.from_user.id,
                    is_admin(callback.from_user.id),
                    task_index
                )
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
        return await callback.answer(t(callback.from_user.id, "task_not_found"), show_alert=True)
    text_solution = task.get("solution", "")
    photo_solution = task.get("solution_photo_file_id")
    if not text_solution and not photo_solution:
        return await callback.answer(t(callback.from_user.id, "solution_missing"), show_alert=True)

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
        return await callback.answer(t(callback.from_user.id, "task_not_found"), show_alert=True)
    await state.update_data(solution_date=date_str, solution_task_index=task_index)
    await state.set_state(UserTaskSolution.waiting_for_solution)
    await callback.message.answer(t(callback.from_user.id, "send_text_or_photo") + "\n\n❌ Напиши /cancel для отмены.")
    await callback.answer()

@dp.message(UserTaskSolution.waiting_for_solution, F.text)
async def user_solution_text(message: types.Message, state: FSMContext):
    if message.text.lower() == "/cancel":
        await state.clear()
        return await message.answer(t(message.from_user.id, "cancel"))

    data = await state.get_data()
    date_str = data.get("solution_date")
    await save_user_daily_solution(
        message,
        state,
        date_str,
        solution_type="text",
        text=message.text
    )

@dp.message(UserTaskSolution.waiting_for_solution, F.photo)
async def user_solution_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date_str = data.get("solution_date")
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
        return await message.answer("❌ Ошибка: дата задачи не найдена.")

    task = get_task_by_index(date_str, task_index)
    if not task:
        await state.clear()
        return await message.answer(t(message.from_user.id, "task_not_found"))

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
    elif len(parts) == 4:
        _, date_str, solution_id, score_str = parts
        task_index = 0
    else:
        return await callback.answer("Ошибка", show_alert=True)

    score = int(score_str)
    if score < 1 or score > 5:
        return await callback.answer("Ошибка оценки", show_alert=True)

    task = get_task_by_index(date_str, task_index)
    if not task:
        return await callback.answer("Задача не найдена", show_alert=True)

    solution = task.get("user_solutions", {}).get(solution_id)
    if not solution:
        return await callback.answer("Решение не найдено", show_alert=True)

    if solution.get("rating") is not None:
        return await callback.answer("Это решение уже оценено.", show_alert=True)

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
# GLOBAL SEARCH (GOOGLE-STYLE)
# ============================================================

@dp.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def global_search_handler(message: types.Message, state: FSMContext):
    query = message.text.strip()
    q_lower = query.lower()

    if q_lower in ["удиви меня", "surprise", "рандом", "challenge"]:
        return await cmd_challenge(message)

    # Conversational questions -> Route to AI
    conversational_triggers = ["посоветуй", "порекомендуй", "что почитать", "для олимпиады", "какой задачник", "для начинающих", "для 9 класса", "для 10 класса", "для 11 класса", "помоги найти"]
    if any(trigger in q_lower for trigger in conversational_triggers) or len(query.split()) > 3:
        loading = await message.answer("🤖 Секунду, подключаю AI для подбора книги...")
        response_text, matched_uids = await ai_recommend_materials(query, message.from_user.id)
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
            InlineKeyboardButton(text="🤖 Спросить AI подробнее", callback_data="ai:ask"),
            InlineKeyboardButton(text=t(message.from_user.id, "menu"), callback_data="menu:main")
        ])

        return await message.answer(
            response_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
        )

    # Google-style ranking search
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

            # Substring match (Google style)
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

    found_links = []
    for sec in DATABASE.get("links", {}).values():
        for item in sec.get("items", []):
            haystack = f"{item.get('title', '')} {item.get('description', '')}".lower()
            if any(w in haystack for w in words):
                found_links.append(item)

    if not scored_files and not found_links:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🤖 Спросить у AI", callback_data="ai:ask")],
                [InlineKeyboardButton(text=t(message.from_user.id, "menu"), callback_data="menu:main")]
            ]
        )
        return await message.answer(
            "🔍 По прямому запросу ничего не найдено.\nПопробуй воспользоваться <b>AI Помощником</b> или открой каталог:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )

    if scored_files:
        await message.answer(f"🔍 <b>Найдено файлов: {len(scored_files)}</b>", parse_mode=ParseMode.HTML)
        for f, cat_title, _ in scored_files[:6]:
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

    if found_links:
        builder = [
            [InlineKeyboardButton(text=item["title"], url=item["url"])]
            for item in found_links[:10]
        ]
        await message.answer(
            f"🔗 <b>Найдено ссылок: {len(found_links)}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
        )

# ============================================================
# BATCH AI RE-INDEX OF THE WHOLE CATALOG
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
        return await progress_msg.edit_text("❌ В базе данных пока нет файлов для переиндексации.")

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
                
                # Update file entry everywhere
                for cat in DATABASE.get("categories", {}).values():
                    for f in cat.get("files", []):
                        if f.get("file_unique_id") == uid:
                            f["caption"] = ai_meta["title"]
                            f["summary"] = ai_meta["summary"]
                            f["target_audience"] = ai_meta["target_audience"]
                            f["difficulty"] = ai_meta["difficulty"]
                            f["tags"] = ai_meta["tags"]
            await asyncio.sleep(0.6)  # rate limit safety
        except Exception as e:
            logger.error("Error reindexing file %s: %s", uid, e)
            errors += 1

    await save_db(DATABASE)
    await progress_msg.edit_text(
        f"✅ <b>ИИ-переиндексация каталога завершена!</b>\n\n"
        f"📊 Всего файлов: {total}\n"
        f"✨ Успешно обновлено: {processed - errors}\n"
        f"⚠️ Ошибок: {errors}\n\n"
        "Теперь все книги содержат реальные названия авторов, описания, аудиторию и точные уровни сложности!",
        parse_mode=ParseMode.HTML
    )

# ============================================================
# ADMIN PANEL
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
    await callback.message.edit_text("👑 <b>Админ-панель</b>\n\nВыбери действие:", parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "admin:upload")
async def adm_upload_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.answer("📥 Отправь PDF документ — <b>ИИ прочитает первые страницы</b> и сам определит название, автора, темы, уровень и описание!")
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

# --- EDITING PARAMETERS IN AI PREVIEW ---

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
    await callback.message.answer("📝 Отправь новое название книги (желательно в формате <code>Автор — Название</code>):", parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.message(FileUpload.waiting_for_caption, F.text)
async def admin_ai_save_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    data = await state.get_data()
    await state.set_state(FileUpload.confirming_ai_data)
    await message.answer(
        render_ai_preview_text(data),
        parse_mode=ParseMode.HTML,
        reply_markup=get_ai_preview_keyboard()
    )

@dp.callback_query(FileUpload.confirming_ai_data, F.data == "ai_edit_diff")
async def admin_ai_edit_diff(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(FileUpload.choosing_difficulty)
    await callback.message.edit_text(
        "📚 <b>Выбери уровень сложности для этой книги:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_difficulty_selection_kb("ai_set_diff")
    )
    await callback.answer()

@dp.callback_query(FileUpload.choosing_difficulty, F.data.startswith("ai_set_diff:"))
async def admin_ai_set_diff_value(callback: types.CallbackQuery, state: FSMContext):
    diff = callback.data.split(":")[1]
    if diff != "back":
        await state.update_data(difficulty=diff)
    
    data = await state.get_data()
    await state.set_state(FileUpload.confirming_ai_data)
    await callback.message.edit_text(
        render_ai_preview_text(data),
        parse_mode=ParseMode.HTML,
        reply_markup=get_ai_preview_keyboard()
    )
    await callback.answer("Уровень сложности обновлён!")

@dp.callback_query(FileUpload.confirming_ai_data, F.data == "ai_edit_tags")
async def admin_ai_edit_tags(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(FileUpload.waiting_for_tags)
    await callback.message.answer(
        "🏷 Отправь теги через пробел.\n\n<i>Пример:</i> <code>#geometry #planimetry #olympiad #prasolov</code>",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.message(FileUpload.waiting_for_tags, F.text)
async def admin_ai_save_tags(message: types.Message, state: FSMContext):
    tags = [w if w.startswith("#") else f"#{w}" for w in message.text.split()]
    await state.update_data(tags=tags)
    data = await state.get_data()
    await state.set_state(FileUpload.confirming_ai_data)
    await message.answer(
        render_ai_preview_text(data),
        parse_mode=ParseMode.HTML,
        reply_markup=get_ai_preview_keyboard()
    )

@dp.callback_query(FileUpload.confirming_ai_data, F.data == "ai_edit_summary")
async def admin_ai_edit_summary(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(FileUpload.waiting_for_summary)
    await callback.message.answer("📝 Отправь новое краткое описание книги (суть/темы):")
    await callback.answer()

@dp.message(FileUpload.waiting_for_summary, F.text)
async def admin_ai_save_summary(message: types.Message, state: FSMContext):
    await state.update_data(summary=message.text.strip())
    data = await state.get_data()
    await state.set_state(FileUpload.confirming_ai_data)
    await message.answer(
        render_ai_preview_text(data),
        parse_mode=ParseMode.HTML,
        reply_markup=get_ai_preview_keyboard()
    )

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
    await callback.message.edit_text(
        render_ai_preview_text(data),
        parse_mode=ParseMode.HTML,
        reply_markup=get_ai_preview_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "a_cancel")
async def admin_cancel_upload(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Загрузка отменена.")

# ============================================================
# USER FILE SUBMISSIONS WITH AI SCAN
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
        f"📤 <b>Файл получен и проанализирован ИИ!</b>\n\n"
        f"🏷 <b>Название:</b> {html.escape(ai_meta['title'])}\n"
        f"📝 <b>Описание:</b> {html.escape(ai_meta['summary'])}\n"
        f"📚 <b>Уровень:</b> {ai_meta['difficulty'].upper()}\n\n"
        "Заявка отправлена администраторам на проверку. Спасибо! 🙌",
        parse_mode=ParseMode.HTML
    )

    cats_text = ", ".join(DATABASE["categories"][c]["title"] for c in sub_data["categories"] if c in DATABASE["categories"])
    admin_caption = (
        f"📥 <b>Новая заявка на добавление файла</b>\n"
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

# ============================================================
# SUBMISSION MODERATION
# ============================================================

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
            caption=(callback.message.caption or "") + "\n\n✅ <b>ОДОБРЕНО И ДОБАВЛЕНО В КАТАЛОГ</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=None
        )
    except Exception:
        pass

    try:
        await bot.send_message(
            sub["user_id"],
            f"✅ Твой файл «{sub['title']}» одобрен и добавлен в библиотеку!\nСпасибо 🙌\n+15 очков к рейтингу!"
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

@dp.callback_query(F.data.startswith("sub_editdiff:"))
async def sub_editdiff_start(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    sub_id = callback.data.split(":")[1]
    await callback.message.answer(
        "📚 Выбери уровень сложности для этой заявки:",
        reply_markup=get_difficulty_selection_kb(f"sub_setdiff:{sub_id}")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("sub_setdiff:"))
async def sub_editdiff_save(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    sub_id = parts[1]
    diff = parts[2]
    
    if diff != "back":
        sub = await get_submission(sub_id)
        if sub:
            sub["difficulty"] = diff
            await save_submission(sub_id, sub)
            await callback.message.edit_text(f"✅ Уровень сложности изменён на <b>{diff.upper()}</b>", parse_mode=ParseMode.HTML)
    else:
        try:
            await callback.message.delete()
        except Exception:
            pass
    await callback.answer()

@dp.callback_query(F.data.startswith("sub_edittags:"))
async def sub_edittags_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    sub_id = callback.data.split(":")[1]
    await state.set_state(EditSubmissionState.waiting_for_new_tags)
    await state.update_data(sub_id=sub_id)
    await callback.message.answer("🏷 Отправь новые теги через пробел (например: <code>#geometry #imo</code>):", parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.message(EditSubmissionState.waiting_for_new_tags, F.text)
async def sub_edittags_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    sub_id = data.get("sub_id")
    await state.clear()

    sub = await get_submission(sub_id)
    if not sub:
        return await message.answer("❌ Заявка не найдена.")

    tags = [w if w.startswith("#") else f"#{w}" for w in message.text.split()]
    sub["tags"] = tags
    await save_submission(sub_id, sub)
    await message.answer(f"✅ Теги обновлены: {' '.join(tags)}")

@dp.callback_query(F.data.startswith("sub_edittitle:"))
async def sub_edittitle_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    sub_id = callback.data.split(":")[1]
    await state.set_state(EditSubmissionState.waiting_for_new_title)
    await state.update_data(sub_id=sub_id)
    await callback.message.answer("✏️ Отправь новое название для этого файла:")
    await callback.answer()

@dp.message(EditSubmissionState.waiting_for_new_title, F.text)
async def sub_edittitle_finish(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    sub_id = data.get("sub_id")
    new_title = message.text.strip()
    await state.clear()

    sub = await get_submission(sub_id)
    if not sub:
        return await message.answer("❌ Заявка не найдена.")

    sub["title"] = new_title
    await save_submission(sub_id, sub)
    await message.answer(f"✅ Название изменено на «{new_title}»!")

@dp.callback_query(F.data.startswith("sub_editcat:"))
async def sub_editcat(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    sub_id = callback.data.split(":")[1]
    sub = await get_submission(sub_id)
    if not sub or sub.get("status") != "pending":
        return

    await callback.message.edit_reply_markup(
        reply_markup=build_submission_categories_kb(sub_id, sub.get("categories", []))
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("subcat_toggle:"))
async def subcat_toggle(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    _, sub_id, cat_key = callback.data.split(":")
    sub = await get_submission(sub_id)
    if not sub or sub.get("status") != "pending":
        return

    selected = set(sub.get("categories", []))
    if cat_key in selected:
        selected.remove(cat_key)
    else:
        selected.add(cat_key)

    sub["categories"] = list(selected)
    await save_submission(sub_id, sub)
    await callback.message.edit_reply_markup(
        reply_markup=build_submission_categories_kb(sub_id, sub["categories"])
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("subcat_done:"))
async def subcat_done(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    sub_id = callback.data.split(":")[1]
    await callback.message.edit_reply_markup(reply_markup=build_submission_action_kb(sub_id))
    await callback.answer()

# ============================================================
# ADMIN STATS & BROADCAST & FILE MANAGEMENT
# ============================================================

@dp.callback_query(F.data == "admin:stats")
async def admin_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    unique_files = set()
    for c in DATABASE.get("categories", {}).values():
        for f in c.get("files", []):
            unique_files.add(f["file_unique_id"])

    must_read_files = set()
    for c in DATABASE.get("categories", {}).values():
        for f in c.get("files", []):
            if f.get("must_read"):
                must_read_files.add(f["file_unique_id"])

    links_count = sum(len(s.get("items", [])) for s in DATABASE.get("links", {}).values())
    tasks_count = sum(len(get_tasks_for_date(d)) for d in DATABASE.get("daily_tasks", {}))
    users_count = len(DATABASE.get("users", {}))
    active_users = sum(1 for u in DATABASE.get("users", {}).values() if u.get("score", 0) > 0)

    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей: {users_count}\n"
        f"🔥 Активных: {active_users}\n"
        f"📚 Уникальных файлов: {len(unique_files)}\n"
        f"⭐ Must-read: {len(must_read_files)}\n"
        f"🔗 Ссылок: {links_count}\n"
        f"🎯 Задач дня: {tasks_count}"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main")]
            ]
        )
    )
    await callback.answer()

@dp.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(BroadcastAdmin.waiting_for_message)
    await callback.message.answer("📢 Отправь сообщение для рассылки всем пользователям.\n\nДля отмены напиши 'отмена'.")
    await callback.answer()

@dp.message(BroadcastAdmin.waiting_for_message)
async def admin_broadcast_msg(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if message.text and message.text.lower() == "отмена":
        await state.clear()
        return await message.answer("❌ Рассылка отменена.")

    await state.update_data(msg_id=message.message_id, chat_id=message.chat.id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, отправить всем", callback_data="broadcast:confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")
            ]
        ]
    )
    await message.answer("Отправить это сообщение всем пользователям?", reply_markup=kb)

@dp.callback_query(F.data == "broadcast:cancel")
async def broadcast_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена.")

@dp.callback_query(F.data == "broadcast:confirm")
async def broadcast_confirm(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    data = await state.get_data()
    msg_id = data.get("msg_id")
    chat_id = data.get("chat_id")
    await state.clear()

    if not msg_id:
        return await callback.answer("Ошибка", show_alert=True)

    await callback.message.edit_text("⏳ Начинаю рассылку...")
    success = 0
    errors = 0

    for uid_str in list(DATABASE.get("users", {}).keys()):
        try:
            await bot.copy_message(
                chat_id=int(uid_str),
                from_chat_id=chat_id,
                message_id=msg_id
            )
            success += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
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
        await asyncio.sleep(0.05)

    await callback.message.answer(
        f"📢 <b>Рассылка завершена!</b>\n✅ Успешно: {success}\n❌ Ошибок: {errors}",
        parse_mode=ParseMode.HTML
    )

# ============================================================
# NOOP & BOT MENU
# ============================================================

@dp.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer()

async def set_main_menu(b: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню 🚀"),
        BotCommand(command="ai", description="AI Помощник 🤖"),
        BotCommand(command="menu", description="Меню 📂"),
        BotCommand(command="task", description="Задача дня 🧩"),
        BotCommand(command="links", description="Полезные ссылки 🔗"),
        BotCommand(command="challenge", description="Случайный материал 🎲"),
        BotCommand(command="favorites", description="Избранное ❤️"),
        BotCommand(command="rating", description="Рейтинг 🏆"),
        BotCommand(command="language", description="Язык / Language 🌍"),
    ]
    await b.set_my_commands(commands)

# ============================================================
# WEB SERVER & MAIN
# ============================================================

async def run_web_server():
    app = web.Application()

    async def health(request):
        return web.Response(text="Matham Bot with High-Level AI and Re-indexer is running!")

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
