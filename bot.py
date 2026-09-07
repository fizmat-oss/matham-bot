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
from aiogram import BaseMiddleware
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
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
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not configured")

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
# USER ACTIVITY MIDDLEWARE
# ============================================================

class UserActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user:
            try:
                await track_user_activity(user.id, user.username or "")
            except Exception:
                logger.exception("Failed to track user activity")
        return await handler(event, data)


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
            "created_at": datetime.now(YEREVAN_TZ).isoformat(),
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
            f.setdefault("topics", [])
            f.setdefault("authors", [])
            f.setdefault("publisher", "")
            f.setdefault("year", "")
            f.setdefault("has_solutions", None)
            f.setdefault("ai_confidence", 0)
            f.setdefault("ai_evidence", "")

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
        user.setdefault("created_at", datetime.now(YEREVAN_TZ).isoformat())
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
            task.setdefault("solution_document_file_id", None)
            task.setdefault("votes", {})
            task.setdefault("difficulty", "medium")
            task.setdefault("tags", [])
            task.setdefault("source", "admin")
            task.setdefault("user_solutions", {})
            task.setdefault("created_at", get_yerevan_date())
            task["number"] = i + 1

    # Persist migrations/defaults immediately so generated IDs and missing fields survive restart.
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {"data": data}},
        upsert=True
    )
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

def extract_pdf_all_text(file_bytes: bytes, max_chars: int = 120000) -> str:
    """Extract text from the whole PDF, not just the first pages."""
    if not PYPDF_AVAILABLE or not file_bytes:
        return ""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        chunks, total = [], 0
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            block = f"--- СТРАНИЦА {i + 1} ---\n{text}"
            if total + len(block) > max_chars:
                remaining = max_chars - total
                if remaining > 500:
                    chunks.append(block[:remaining])
                break
            chunks.append(block)
            total += len(block)
        return "\n\n".join(chunks)
    except Exception as e:
        logger.exception("Failed to extract full PDF text: %s", e)
        return ""

def extract_pdf_metadata_pages(file_bytes: bytes) -> str:
    if not PYPDF_AVAILABLE or not file_bytes:
        return ""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        indexes = list(range(min(8, len(reader.pages)))
        )
        if len(reader.pages) > 8:
            indexes += [len(reader.pages)//4, len(reader.pages)//2]
        out = []
        for i in sorted(set(indexes)):
            text = (reader.pages[i].extract_text() or "").strip()
            if text:
                out.append(f"--- СТРАНИЦА {i+1} ---\n{re.sub(r'\s+', ' ', text)}")
        return "\n\n".join(out)[:30000]
    except Exception:
        return ""

async def download_file_bytes(file_id: str) -> bytes:
    try:
        tg_file = await bot.get_file(file_id)
        stream = io.BytesIO()
        await bot.download_file(tg_file.file_path, destination=stream)
        return stream.getvalue()
    except Exception as e:
        logger.exception("Error downloading file %s: %s", file_id, e)
        return b""

async def call_llm_api(prompt: str, system_prompt: str = "", max_tokens: int = 1800, temperature: float = 0.05) -> str:
    if GEMINI_API_KEY:
        models = [os.environ.get("GEMINI_MODEL", "gemini-3.7-flash"), "gemini-3.6-flash", "gemini-3.5-flash"]
        seen = set()
        for model in models:
            if not model or model in seen:
                continue
            seen.add(model)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            payload = {"contents": [{"parts": [{"text": (f"{system_prompt}\n\n" if system_prompt else "") + prompt}]}],
                       "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
            for attempt in range(3):
                try:
                    async with ClientSession(timeout=ClientTimeout(total=120)) as session:
                        async with session.post(url, headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}, json=payload) as resp:
                            body = await resp.text()
                            if resp.status == 200:
                                data = json.loads(body)
                                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                                return "".join(x.get("text", "") for x in parts).strip()
                            if resp.status == 429:
                                await asyncio.sleep(min(15, 2 ** attempt * 2))
                                continue
                            logger.warning("Gemini %s: %s", resp.status, body[:500])
                            break
                except Exception as e:
                    logger.warning("Gemini %s attempt %s: %s", model, attempt + 1, e)
                    await asyncio.sleep(2 * (attempt + 1))
    if OPENAI_API_KEY:
        try:
            payload = {"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                       "messages": [{"role": "system", "content": system_prompt or "Ты эксперт по математической библиографии."}, {"role": "user", "content": prompt}],
                       "temperature": temperature, "max_tokens": max_tokens}
            async with ClientSession(timeout=ClientTimeout(total=120)) as session:
                async with session.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning("OpenAI API error: %s", e)
    return ""

def clean_filename_title(raw_name: str) -> str:
    name = os.path.splitext(raw_name)[0]
    name = re.sub(r"[_+.-]+", " ", name)
    name = re.sub(r"\b(pdf|djvu|book|scan|final|copy|v\d+|\d{4})\b", "", name, flags=re.I)
    return re.sub(r"\s+", " ", name).strip()

def normalize_tags(tags, categories):
    clean=[]
    for tag in tags if isinstance(tags,list) else []:
        tag=re.sub(r"[^#\wа-яА-ЯёЁ-]","",str(tag).strip().replace(" ","-"))
        if tag and not tag.startswith("#"): tag="#"+tag
        if tag and len(tag)<=40 and tag.lower() not in {x.lower() for x in clean}: clean.append(tag)
    aliases={"geometry":"#геометрия","number_theory":"#теориячисел","algebra":"#алгебра","combinatorics":"#комбинаторика","higher_math":"#матанализ","titu":"#олимпиаднаяматематика"}
    for cat in categories:
        if len(clean)>=8: break
        if cat in aliases and aliases[cat].lower() not in {x.lower() for x in clean}: clean.append(aliases[cat])
    return clean[:8]

def generate_smart_fallback_description(title: str, text: str, cat_key: str) -> str:
    subject={"geometry":"геометрии","number_theory":"теории чисел","algebra":"алгебре","combinatorics":"комбинаторике","higher_math":"высшей математике","titu":"олимпиадной математике"}.get(cat_key,"математике")
    return f"Материал по {subject}. В автоматическом описании используются только данные, найденные в самом файле."

async def analyze_document_with_ai(file_bytes: bytes, original_name: str) -> dict:
    'Deep, slow-first analysis: every extracted page is considered before metadata is published.'
    full_text = extract_pdf_all_text(file_bytes, max_chars=600000)
    meta_text = extract_pdf_metadata_pages(file_bytes)
    fallback_title = clean_filename_title(original_name)
    categories = list(DATABASE.get("categories", {}).keys()) or ["algebra"]

    # Pass 1: inspect the entire document in chunks. This prevents a long book's
    # contents from being decided from only the cover/first six pages.
    chunks = [full_text[i:i+18000] for i in range(0, len(full_text), 18000)] if full_text else []
    if not chunks:
        chunks = [f"ИЗВЛЕЧЕННОГО ТЕКСТА НЕТ. Имя файла: {original_name}"]

    chunk_facts = []
    for idx, chunk in enumerate(chunks, 1):
        prompt = f'''JSON_ONLY
Документ: {original_name}
Часть {idx}/{len(chunks)}.

{chunk}

Извлеки только факты, реально подтверждаемые этой частью: авторы, название, издатель/год, темы и главы, целевая аудитория/класс, уровень, тип материала, наличие решений, конкурсы/олимпиады. Не угадывай. Если факта нет — оставь пустым. Верни JSON:
{{"authors":[],"titles":[],"publisher":"","year":"","topics":[],"audience":[],"difficulty_evidence":[],"has_solutions":null,"important_facts":[],"page_evidence":""}}'''
        raw = await call_llm_api(prompt, "Ты библиограф-исследователь. Извлекай факты строго из данного фрагмента. JSON_ONLY", 1400, 0.0)
        try:
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                chunk_facts.append(json.loads(m.group(0)))
        except Exception:
            logger.warning("Failed to parse document chunk %s/%s", idx, len(chunks))

    evidence_blob = json.dumps(chunk_facts, ensure_ascii=False)[:120000]
    final_prompt = f'''JSON_ONLY
Сформируй окончательную карточку математического материала.

Имя файла: {original_name}
Титульные страницы/оглавление:
{meta_text[:30000]}

Факты, извлеченные из ВСЕХ частей документа:
{evidence_blob}

Правила качества:
1. Название и автор должны быть взяты из подтвержденных данных. Не угадывай по имени файла, если внутри есть более надежные данные.
2. Если автор не подтвержден, не приписывай автора.
3. summary — 3-5 конкретных предложений: реальные темы/главы, структура, уровень и наличие решений. Не рекламный шаблон.
4. target_audience — только если подтверждено; иначе "Не указано в файле".
5. categories — 1-3 из {categories}.
6. difficulty — easy/medium/hard/imo; если данных недостаточно — medium.
7. tags — 5-8 конкретных русских/английских тегов по реальному содержанию, без #math/#book/#pdf.
8. confidence — 0..1. Снижай его, если данные противоречивы или плохо извлечены.
9. evidence — укажи, на каких страницах/фрагментах подтверждены название и автор.
10. Никогда не выдумывай год, издателя, автора, уровень или наличие решений.

Верни только JSON:
{{"title":"","summary":"","target_audience":"","categories":[],"difficulty":"medium","tags":[],"confidence":0,"evidence":""}}'''
    raw = await call_llm_api(final_prompt, "Ты старший редактор библиотеки олимпиадной математики. Точность важнее скорости. JSON_ONLY", 2600, 0.0)
    try:
        m = re.search(r"\{.*\}", raw, re.S)
        parsed = json.loads(m.group(0)) if m else {}
    except Exception:
        parsed = {}

    cats = [c for c in parsed.get("categories", []) if c in categories]
    if not cats:
        low = (fallback_title + " " + full_text).lower()
        rules = {
            "geometry": ["геометр", "планиметр", "стереометр"],
            "number_theory": ["теория чисел", "делимость", "диофант", "простые числа"],
            "algebra": ["алгебр", "многочлен", "неравенств", "уравнен"],
            "combinatorics": ["комбинатор", "граф", "дирихле", "перестанов"],
            "higher_math": ["матанализ", "интеграл", "дифференц", "предел"],
            "titu": ["andreescu", "titu"]
        }
        cats = [c for c, words in rules.items() if c in categories and any(w in low for w in words)] or ["algebra"]

    title = str(parsed.get("title") or "").strip()
    if not title or title.lower() in {"document", "math", "без названия"}:
        title = fallback_title or "Математический материал"
    summary = str(parsed.get("summary") or "").strip()
    if len(summary) < 100:
        summary = generate_smart_fallback_description(title, full_text, cats[0])
    audience = str(parsed.get("target_audience") or "Не указано в файле").strip()
    difficulty = str(parsed.get("difficulty", "medium")).lower()
    if difficulty not in {"easy", "medium", "hard", "imo"}:
        difficulty = "medium"
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0) or 0)))
    except Exception:
        confidence = 0.0
    tags = normalize_tags(parsed.get("tags", []), cats)
    if len(tags) < 3:
        tags = normalize_tags(tags + [f"#{c}" for c in cats], cats)

    return {
        "title": title,
        "summary": summary,
        "target_audience": audience,
        "categories": cats,
        "difficulty": difficulty,
        "tags": tags,
        "confidence": confidence,
        "evidence": str(parsed.get("evidence") or "").strip(),
    }

def get_catalog_files_list() -> list:
    """Flatten the catalog and merge duplicate entries stored in multiple categories."""
    files_dict = {}
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        for f in cat_data.get("files", []):
            uid = f.get("file_unique_id")
            if not uid:
                continue
            if uid not in files_dict:
                files_dict[uid] = {
                    "uid": uid,
                    "file_id": f.get("file_id"),
                    "caption": f.get("caption", "Без названия"),
                    "category": cat_data.get("title", cat_key),
                    "categories": [cat_data.get("title", cat_key)],
                    "summary": f.get("summary", ""),
                    "target_audience": f.get("target_audience", ""),
                    "tags": list(f.get("tags", [])),
                    "topics": list(f.get("topics", [])) if isinstance(f.get("topics", []), list) else [],
                    "difficulty": f.get("difficulty") or "medium",
                    "must_read": f.get("must_read", False),
                }
            else:
                item = files_dict[uid]
                cat_title = cat_data.get("title", cat_key)
                if cat_title not in item["categories"]:
                    item["categories"].append(cat_title)
                for tag in f.get("tags", []):
                    if tag not in item["tags"]:
                        item["tags"].append(tag)
                for topic in f.get("topics", []):
                    if topic not in item["topics"]:
                        item["topics"].append(topic)
    return list(files_dict.values())

async def recommend_books_by_criteria(user_query: str) -> tuple:
    files=get_catalog_files_list()
    if not files: return "В библиотеке пока нет доступных материалов.",[]
    q=user_query.lower(); tokens=re.findall(r"[\wа-яё-]{3,}",q)
    scored=[]
    for f in files:
        hay=" ".join([f["caption"],f["summary"],f["target_audience"],f["category"]," ".join(f["tags"]) ]).lower()
        score=sum(12 if t in f["caption"].lower() else 4 if t in hay else 0 for t in tokens)
        scored.append((score,f))
    scored.sort(key=lambda x:x[0],reverse=True)
    candidates=[f for score,f in scored[:80] if score>0] or [f for _,f in scored[:50]]
    compact="\n".join(f"UID={f['uid']} | TITLE={f['caption']} | CATEGORY={f['category']} | LEVEL={f['difficulty']} | AUDIENCE={f['target_audience']} | TAGS={','.join(f['tags'])} | SUMMARY={f['summary'][:500]}" for f in candidates)
    prompt=f'''JSON_ONLY
Запрос: {user_query}
Кандидаты:
{compact}

Выбери 1-5 действительно подходящих материалов. Ранжируй по смыслу, не выдумывай свойства. Верни {{"matches":[{{"uid":"...","reason":"..."}}],"note":"..."}}.'''
    raw=await call_llm_api(prompt,"Ты профессиональный библиограф олимпиадной математики. Точность важнее количества. JSON_ONLY",2200,0.0)
    matches=[]; note=""
    try:
        m=re.search(r"\{.*\}",raw,re.S); data=json.loads(m.group(0)) if m else {}
        note=str(data.get("note",""));
        for item in data.get("matches",[]):
            uid=str(item.get("uid","")); f=get_file_by_uid(uid)
            if f and not any(x[0]==uid for x in matches): matches.append((uid,str(item.get("reason","Подходит по запросу."))))
    except Exception: pass
    if not matches: matches=[(f["uid"],"Наиболее близкое совпадение по названию, темам и тегам.") for _,f in scored[:5]]
    lines=["🔎 <b>Результаты AI-поиска</b>",f"Запрос: <i>{html.escape(user_query)}</i>"]
    if note: lines.append(html.escape(note))
    for i,(uid,reason) in enumerate(matches[:5],1):
        f=get_file_by_uid(uid); lines.append(f"\n<b>{i}. {html.escape(f.get('caption','Без названия'))}</b>\n{html.escape(reason)}\n<i>{html.escape(f.get('summary','')[:500])}</i>")
    return "\n".join(lines),[uid for uid,_ in matches[:5]]

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
    waiting_for_task_text = State()
    waiting_for_solution = State()
    waiting_for_date = State()

class UserTaskSolution(StatesGroup):
    waiting_for_solution = State()

class BroadcastAdmin(StatesGroup):
    waiting_for_message = State()

class AIAssistantState(StatesGroup):
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
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
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
        f"📚 Выбирай раздел в меню или используй <b>AI-поиск</b> для поиска подходящих книг и задачников по всей библиотеке."
    )
    await safe_send_or_edit(message, welcome_text, reply_markup=get_main_menu_keyboard(message.from_user.id))

@dp.message(Command("ai"))
async def cmd_ai(message: types.Message):
    await track_user_activity(message.from_user.id, message.from_user.username or "")
    text = (
        "🔎 <b>AI-поиск по математической библиотеке</b>\n\n"
        "Напишите тему, автора, класс, уровень или цель — AI найдет и ранжирует наиболее подходящие материалы."
    )
    await safe_send_or_edit(message, text, reply_markup=get_ai_choice_keyboard())

@dp.message(Command("search"))
async def cmd_search(message: types.Message, state: FSMContext):
    await state.set_state(AIAssistantState.waiting_for_book_recommendation)
    await message.answer("🔎 Напишите, что ищете: тема, автор, класс, уровень или цель.")

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
        "🔎 <b>AI-поиск по математической библиотеке</b>\n\n"
        "Напишите тему, автора, класс, уровень или цель — AI найдет и ранжирует наиболее подходящие материалы."
    )
    await safe_send_or_edit(callback, text, reply_markup=get_ai_choice_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "ai:find_books")
async def cb_ai_books_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AIAssistantState.waiting_for_book_recommendation)
    text = "📚 <b>Опишите ваши цели, класс и интересующую тему:</b>\n\n(Пример: <i>Я в 9 классе, хочу подтянуть геометрию для регионального этапа Всероса</i>)"
    await safe_send_or_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="ai:menu")]]))
    await callback.answer()

@dp.message(AIAssistantState.waiting_for_book_recommendation, F.text)
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

    f = random.choice(files)
    uid = f["uid"]
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
        logger.error("Failed to send random document: %s", e)
        await callback.answer("Ошибка при отправке файла.", show_alert=True)
        return
    await callback.answer()

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
        await safe_send_or_edit(
            callback,
            "🎯 <b>На сегодня задача пока не опубликована.</b>",
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
    try:
        task_idx = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("Некорректная задача.", show_alert=True)
        return
    tasks = DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", [])
    if task_idx < 0 or task_idx >= len(tasks):
        await callback.answer("Задача не найдена.", show_alert=True)
        return
    await show_daily_task(callback, date_str, task_idx)
    await callback.answer()

@dp.callback_query(F.data.startswith("task:solve:"))
async def cb_task_solve(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    try:
        date_str = parts[2]
        task_idx = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("Некорректная задача.", show_alert=True)
        return
    tasks = DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", [])
    if task_idx < 0 or task_idx >= len(tasks):
        await callback.answer("Задача не найдена.", show_alert=True)
        return

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

    tasks = DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", [])
    if task_idx < 0 or task_idx >= len(tasks):
        await message.answer("❌ Задача не найдена.")
        return

    task = tasks[task_idx]
    if uid_str in task.setdefault("user_solutions", {}):
        await message.answer("ℹ️ Вы уже отправляли решение этой задачи.")
        return

    solution = {
        "text": message.text or message.caption or "Решение в виде файла/фото",
        "submitted_at": datetime.now(YEREVAN_TZ).isoformat()
    }
    if message.photo:
        solution["photo_file_id"] = message.photo[-1].file_id
    elif message.document:
        solution["document_file_id"] = message.document.file_id
    task["user_solutions"][uid_str] = solution

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
    try:
        date_str = parts[2]
        task_idx = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("Некорректная задача.", show_alert=True)
        return
    tasks = DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", [])
    if task_idx < 0 or task_idx >= len(tasks):
        await callback.answer("Задача не найдена.", show_alert=True)
        return
    task = tasks[task_idx]
    sol_text = task.get("solution", "Авторское решение пока не заполнено.")
    sol_photo = task.get("solution_photo_file_id")
    sol_document = task.get("solution_document_file_id")

    text = f"💡 <b>Авторское решение задачи №{task_idx + 1}:</b>\n\n{html.escape(sol_text)}"
    if sol_document:
        try:
            await callback.message.answer_document(sol_document, caption=text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад к задаче", callback_data=f"task:view:{date_str}:{task_idx}")]]))
        except Exception:
            await callback.message.answer(text, parse_mode=ParseMode.HTML)
        await callback.answer()
        return
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

@dp.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True); return
    users=DATABASE.get("users",{}); now=datetime.now(YEREVAN_TZ)
    d7={(now-timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)}; d30={(now-timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)}
    active_today=sum(1 for u in users.values() if u.get("last_active")==now.strftime("%Y-%m-%d"))
    active7=sum(1 for u in users.values() if u.get("last_active") in d7); active30=sum(1 for u in users.values() if u.get("last_active") in d30)
    total_subs=pending=approved=rejected=0
    async for doc in submissions_collection.find({}):
        total_subs+=1; status=doc.get("status")
        if status=="pending": pending+=1
        elif status=="approved": approved+=1
        elif status=="rejected": rejected+=1
    task_count=sum(len(g.get("tasks",[])) for g in DATABASE.get("daily_tasks",{}).values())
    solution_count=sum(len(t.get("user_solutions",{})) for g in DATABASE.get("daily_tasks",{}).values() for t in g.get("tasks",[]))
    total_score=sum(int(u.get("score",0) or 0) for u in users.values())
    text=(f"📊 <b>Статистика MathAm</b>\n\n👥 Пользователей: <b>{len(users)}</b>\n🟢 Активны сегодня: <b>{active_today}</b>\n📅 Активны за 7 дней: <b>{active7}</b>\n📆 Активны за 30 дней: <b>{active30}</b>\n\n📚 Материалов: <b>{len(get_catalog_files_list())}</b>\n🎯 Задач дня: <b>{task_count}</b>\n📝 Решений пользователей: <b>{solution_count}</b>\n🏆 Всего очков: <b>{total_score}</b>\n\n📥 Заявок: <b>{total_subs}</b>\n⏳ На модерации: <b>{pending}</b>\n✅ Одобрено: <b>{approved}</b>\n❌ Отклонено: <b>{rejected}</b>")
    await safe_send_or_edit(callback,text,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Админ-панель",callback_data="admin:main")]])); await callback.answer()

@dp.callback_query(F.data == "admin:submissions")
async def cb_admin_submissions(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return
    docs = []
    async for doc in submissions_collection.find({}).sort("created_at", -1).limit(15):
        docs.append(doc)
    if not docs:
        await safe_send_or_edit(callback, "📥 <b>Заявок пока нет.</b>", reply_markup=get_admin_menu_keyboard())
        await callback.answer()
        return
    lines=["📥 <b>Последние заявки</b>"]
    buttons=[]
    for doc in docs:
        status={"pending":"⏳","approved":"✅","rejected":"❌"}.get(doc.get("status"),"❔")
        sid=doc.get("sub_id", doc.get("_id", "?"))
        name=doc.get("file_name", "документ")
        lines.append(f"{status} <b>#{html.escape(str(sid))}</b> — {html.escape(name[:80])}")
        if doc.get("status")=="pending":
            buttons.append([InlineKeyboardButton(text=f"✅ Принять #{sid}", callback_data=f"admin:sub_approve:{sid}"), InlineKeyboardButton(text=f"❌ Отклонить #{sid}", callback_data=f"admin:sub_reject:{sid}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin:main")])
    await safe_send_or_edit(callback,"\n".join(lines),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data == "admin:upload_edit_title")
async def cb_admin_upload_edit_title(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True); return
    data=await state.get_data()
    if not data.get("ai_meta"):
        await callback.answer("Сессия загрузки устарела.", show_alert=True); return
    await state.set_state(EditFile.waiting_for_title)
    await safe_send_or_edit(callback,"✏️ Пришлите новое название карточки. Можно в формате «Автор — Название».",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад",callback_data="admin:upload")]]))
    await callback.answer()

@dp.message(EditFile.waiting_for_title, F.text)
async def process_admin_upload_edit_title(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): await state.clear(); return
    title=message.text.strip()
    if len(title)<3:
        await message.answer("Название слишком короткое."); return
    data=await state.get_data(); meta=data.get("ai_meta",{}); meta["title"]=title[:250]
    await state.update_data(ai_meta=meta)
    await state.set_state(FileUpload.confirming_ai_data)
    await message.answer(f"✅ Название обновлено: <b>{html.escape(meta['title'])}</b>\nТеперь нажмите «Опубликовать» в предыдущем окне.",parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📂 Выбрать категории",callback_data="admin:upload_edit_cats"),InlineKeyboardButton(text="✅ Опубликовать",callback_data="admin:upload_confirm")]]))

@dp.callback_query(F.data == "admin:upload_edit_cats")
async def cb_admin_upload_edit_cats(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): await callback.answer("Доступ запрещен.",show_alert=True); return
    data=await state.get_data(); meta=data.get("ai_meta",{})
    selected=set(meta.get("categories",[]))
    rows=[]
    for key,cat in DATABASE.get("categories",{}).items():
        mark="✅" if key in selected else "⬜"
        rows.append([InlineKeyboardButton(text=f"{mark} {cat.get('title',key)}",callback_data=f"admin:cat_toggle:{key}")])
    rows.append([InlineKeyboardButton(text="✅ Готово",callback_data="admin:cats_done")])
    await safe_send_or_edit(callback,"📂 <b>Выберите один или несколько разделов.</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer()

@dp.callback_query(F.data.startswith("admin:cat_toggle:"))
async def cb_admin_upload_cat_toggle(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): await callback.answer("Доступ запрещен.",show_alert=True); return
    data=await state.get_data(); meta=data.get("ai_meta",{}); cats=set(meta.get("categories",[])); key=callback.data.split(":")[-1]
    if key in cats: cats.remove(key)
    else: cats.add(key)
    if not cats: cats={key}
    meta["categories"]=list(cats); await state.update_data(ai_meta=meta)
    await cb_admin_upload_edit_cats(callback,state)

@dp.callback_query(F.data == "admin:cats_done")
async def cb_admin_upload_cats_done(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): await callback.answer("Доступ запрещен.",show_alert=True); return
    data=await state.get_data(); meta=data.get("ai_meta",{})
    await safe_send_or_edit(callback,f"📂 <b>Выбрано:</b> {html.escape(', '.join(meta.get('categories',[])))}\n\nГотово к публикации.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Опубликовать",callback_data="admin:upload_confirm")],[InlineKeyboardButton(text="⬅️ Админ-панель",callback_data="admin:main")]])); await callback.answer()

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
        f"📂 <b>Разделы:</b> {', '.join(ai_meta['categories'])}\n"
        f"🎯 <b>Уверенность AI:</b> {ai_meta.get('confidence', 0):.0%}\n"
        f"🔎 <b>Основание:</b> {html.escape(ai_meta.get('evidence', '')[:700])}\n\n"
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
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return
    data = await state.get_data()
    if not data.get("ai_meta") or not data.get("file_id"):
        await callback.answer("Сессия загрузки устарела. Начните загрузку заново.", show_alert=True)
        return
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
        "topics": ai_meta.get("topics", []),
        "authors": ai_meta.get("authors", []),
        "publisher": ai_meta.get("publisher", ""),
        "year": ai_meta.get("year", ""),
        "has_solutions": ai_meta.get("has_solutions"),
        "ai_confidence": ai_meta.get("confidence", 0),
        "ai_evidence": ai_meta.get("evidence", ""),
        "must_read": False
    }

    for cat_key in ai_meta["categories"]:
        if cat_key in DATABASE["categories"]:
            DATABASE["categories"][cat_key]["files"].append(copy.deepcopy(file_obj))

    await save_db(DATABASE)
    await safe_send_or_edit(callback, f"🎉 <b>Материал «{html.escape(ai_meta['title'])}» успешно сохранен в библиотеку!</b>", reply_markup=get_admin_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("admin:sub_approve:"))
async def cb_admin_sub_approve(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return
    sub_id = callback.data.split(":", 2)[2]
    sub = await get_submission(sub_id)
    if not sub:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    if sub.get("status") != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
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
        "topics": ai_meta.get("topics", []),
        "authors": ai_meta.get("authors", []),
        "publisher": ai_meta.get("publisher", ""),
        "year": ai_meta.get("year", ""),
        "has_solutions": ai_meta.get("has_solutions"),
        "ai_confidence": ai_meta.get("confidence", 0),
        "ai_evidence": ai_meta.get("evidence", ""),
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
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return
    sub_id = callback.data.split(":", 2)[2]
    sub = await get_submission(sub_id)
    if sub and sub.get("status") == "pending":
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
        await callback.answer("Доступ запрещен.", show_alert=True)
        return
    await state.set_state(TaskOfDayAdmin.waiting_for_photo)
    await safe_send_or_edit(callback, "🎯 <b>Создание задачи дня</b>\n\nПришлите изображение задачи или /skip.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin:main")]]))
    await callback.answer()

@dp.message(TaskOfDayAdmin.waiting_for_photo)
async def process_admin_task_photo(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear(); return
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.text and message.text.strip().lower() in {"/skip", "skip"}:
        photo_id = None
    else:
        await message.answer("Пришлите изображение или /skip.")
        return
    await state.update_data(photo_file_id=photo_id)
    await state.set_state(TaskOfDayAdmin.waiting_for_date)
    await message.answer("📅 <b>Дата задачи</b>\nНапишите YYYY-MM-DD или /today.", parse_mode=ParseMode.HTML)

@dp.message(TaskOfDayAdmin.waiting_for_date, F.text)
async def process_admin_task_date(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear(); return
    raw = message.text.strip().lower()
    date_str = get_yerevan_date() if raw in {"/today", "today", "сегодня"} else raw
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await message.answer("❌ Неверная дата. Используйте YYYY-MM-DD или /today.")
        return
    await state.update_data(date_str=date_str)
    await state.set_state(TaskOfDayAdmin.waiting_for_task_text)
    await message.answer("📌 <b>Пришлите полный текст задачи.</b>", parse_mode=ParseMode.HTML)

@dp.message(TaskOfDayAdmin.waiting_for_task_text, F.text)
async def process_admin_task_text(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear(); return
    task_text = message.text.strip()
    if len(task_text) < 5:
        await message.answer("Текст задачи слишком короткий.")
        return
    await state.update_data(task_text=task_text)
    await state.set_state(TaskOfDayAdmin.waiting_for_solution)
    await message.answer("💡 <b>Авторское решение</b>\nПришлите текст, фото или документ. Если решения пока нет — /skip.", parse_mode=ParseMode.HTML)

@dp.message(TaskOfDayAdmin.waiting_for_solution)
async def process_admin_task_solution(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear(); return
    data = await state.get_data()
    is_skip = bool(message.text and message.text.strip().lower() in {"/skip", "skip"})
    solution_text = "" if is_skip else (message.text or message.caption or "")
    solution_photo = message.photo[-1].file_id if message.photo else None
    solution_document = message.document.file_id if message.document else None
    if not is_skip and not solution_text and not solution_photo and not solution_document:
        await message.answer("Пришлите текст, фото, документ или /skip.")
        return

    date_str = data.get("date_str", get_yerevan_date())
    group = DATABASE["daily_tasks"].setdefault(date_str, {"tasks": []})
    tasks = group.setdefault("tasks", [])
    task = {
        "task_id": uuid.uuid4().hex[:10],
        "text": data["task_text"],
        "photo_file_id": data.get("photo_file_id"),
        "solution": solution_text,
        "solution_photo_file_id": solution_photo,
        "solution_document_file_id": solution_document,
        "votes": {},
        "user_solutions": {},
        "created_at": datetime.now(YEREVAN_TZ).isoformat(),
        "difficulty": "medium",
        "tags": [],
        "source": "admin"
    }
    tasks.append(task)
    for i, item in enumerate(tasks, 1):
        item["number"] = i
    await save_db(DATABASE)
    await state.clear()
    await message.answer(f"✅ <b>Задача опубликована.</b>\nДата: {date_str}\nНомер: {len(tasks)}\nВсего задач на эту дату: {len(tasks)}", reply_markup=get_admin_menu_keyboard(), parse_mode=ParseMode.HTML)

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
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    await state.clear()
    users = DATABASE.get("users", {})
    count = 0

    for uid_str in list(users.keys()):
        try:
            await message.copy_to(int(uid_str))
            count += 1
            await asyncio.sleep(0.1)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 0.5)
            try:
                await message.copy_to(int(uid_str))
                count += 1
            except Exception:
                pass
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

@dp.message(AddLink.waiting_for_text, F.text)
async def process_add_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    sec_key = data["sec_key"]

    raw = message.text.strip()
    match = re.match(r"^(.+?)\s*-\s*(https?://\S+)$", raw, re.IGNORECASE)
    if match:
        title, url = match.group(1).strip(), match.group(2).strip()
    elif re.match(r"^https?://\S+$", raw, re.IGNORECASE):
        title, url = "Ресурс", raw
    else:
        await message.answer("❌ Некорректная ссылка. Используйте: Название - https://example.com")
        return

    if sec_key not in DATABASE.get("links", {}):
        await message.answer("❌ Раздел ссылок не найден.")
        return

    DATABASE["links"][sec_key]["items"].append({"title": title[:100], "url": url[:2000]})
    await save_db(DATABASE)

    await message.answer("✅ <b>Ссылка добавлена!</b>", reply_markup=get_links_section_keyboard(sec_key, message.from_user.id), parse_mode=ParseMode.HTML)

# ============================================================
# INLINE QUERY SEARCH ENGINE
# ============================================================

@dp.inline_query()
async def inline_search(query: InlineQuery):
    q=query.query.strip().lower(); tokens=re.findall(r"[\wа-яё-]{2,}",q); scored=[]
    for f in get_catalog_files_list():
        hay=" ".join([f["caption"],f["summary"],f["target_audience"]," ".join(f.get("tags",[]))," ".join(f.get("topics",[]))," ".join(f.get("categories",[]))]).lower()
        score=sum(10 if t in f["caption"].lower() else 4 if t in hay else 0 for t in tokens)
        if not tokens: score=1
        if score: scored.append((score,f))
    scored.sort(key=lambda x:x[0],reverse=True)
    results=[InlineQueryResultCachedDocument(id=f["uid"],title=f["caption"][:64],document_file_id=f["file_id"],description=f["summary"][:180],caption=f"📖 <b>{html.escape(f['caption'])}</b>\n{html.escape(f['summary'])}") for _,f in scored[:50]]
    await query.answer(results,cache_time=5,is_personal=True)

dp.message.outer_middleware(UserActivityMiddleware())
dp.callback_query.outer_middleware(UserActivityMiddleware())

# ============================================================
# STARTUP & MAIN RUNNER
# ============================================================

async def on_startup():
    global DATABASE
    DATABASE = await load_db()
    logger.info("Database loaded successfully. Registered %d categories.", len(DATABASE.get("categories", {})))

    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="ai", description="🔎 AI поиск по библиотеке"),
        BotCommand(command="search", description="🔎 AI поиск по библиотеке"),
        BotCommand(command="catalog", description="📚 Каталог литературы"),
    ]
    await bot.set_my_commands(commands)


async def on_shutdown():
    logger.info("Shutting down Telegram webhook service...")
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        logger.exception("Failed to delete Telegram webhook")
    await bot.session.close()
    mongo_client.close()


def get_webhook_url() -> str:
    # Render exposes the public service URL as RENDER_EXTERNAL_URL.
    # WEBHOOK_URL can override it when using a custom domain/path.
    base_url = os.environ.get("WEBHOOK_URL", "").strip().rstrip("/")
    if not base_url:
        base_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError(
            "WEBHOOK_URL or RENDER_EXTERNAL_URL must be configured for webhook mode"
        )
    if not re.match(r"^https://[^\s]+$", base_url, re.IGNORECASE):
        raise RuntimeError("WEBHOOK_URL must be a valid HTTPS URL")
    return f"{base_url}/telegram/webhook"


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def main():
    port_raw = os.environ.get("PORT", "10000")
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid PORT value: {port_raw!r}") from exc

    webhook_url = get_webhook_url()
    secret_token = os.environ.get("WEBHOOK_SECRET", "").strip()
    if secret_token and not re.match(r"^[A-Za-z0-9_-]{1,256}$", secret_token):
        raise RuntimeError("WEBHOOK_SECRET must contain only A-Z, a-z, 0-9, '_' or '-'")

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=secret_token or None,
    )
    handler.register(app, path="/telegram/webhook")
    setup_application(app, dp, bot=bot)

    async def app_startup(app_instance: web.Application):
        await on_startup()
        await bot.set_webhook(
            url=webhook_url,
            secret_token=secret_token or None,
            drop_pending_updates=False,
            allowed_updates=dp.resolve_used_update_types(),
        )
        logger.info("Telegram webhook configured: %s", webhook_url)
        logger.info("Starting Render Web Service on 0.0.0.0:%d", port)

    async def app_shutdown(app_instance: web.Application):
        await on_shutdown()

    app.on_startup.append(app_startup)
    app.on_shutdown.append(app_shutdown)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info("Web service is listening on 0.0.0.0:%d", port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
