import logging
import random
import os
import copy
import uuid
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
#   СТРУКТУРА ПО УМОЛЧАНИЮ (только при первом запуске / после очистки Mongo)
# ==========================================
DEFAULT_STATE = {
    "categories": {
        "geometry": {"title": "📐 Геометрия", "files": []},
        "number_theory": {"title": "🔢 Теория чисел", "files": []},
        "algebra": {"title": "🧮 Алгебра", "files": []},
        "combinatorics": {"title": "🧩 Комбинаторика", "files": []},
        "higher_math": {"title": "🎓 Матанализ и высшая математика", "files": []},
        "titu": {"title": "📘 Titu Andreescu", "files": []}
    },
    "links": {
        "useful_links": {"title": "🔗 Полезные ссылки", "items": []},
        "useful_videos": {"title": "🎥 Полезные видео и YouTube-каналы", "items": []}
    }
}

DATABASE = {}  # заполняется в main() из MongoDB

# заявки пользователей на добавление файла: sub_id -> {...}
PENDING_SUBMISSIONS = {}


async def load_db():
    doc = await db_collection.find_one({"_id": DB_DOC_ID})
    if doc is None:
        logger.info("В MongoDB нет каталога — создаю из DEFAULT_STATE")
        data = copy.deepcopy(DEFAULT_STATE)
        await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": data}}, upsert=True)
        return data
    return doc["data"]


async def save_db(db_data):
    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": db_data}}, upsert=True)


# ==========================================
#        ПРОВЕРКА ДУБЛИКАТОВ ФАЙЛОВ
# ==========================================
def is_file_exists(file_unique_id: str) -> bool:
    for cat_data in DATABASE["categories"].values():
        for f in cat_data["files"]:
            if f.get("file_unique_id") == file_unique_id:
                return True
    return False


# ==========================================
#                FSM СОСТОЯНИЯ
# ==========================================
class FileUpload(StatesGroup):        # админ загружает файл напрямую
    selecting_categories = State()
    waiting_for_caption = State()


class UserSubmit(StatesGroup):        # обычный пользователь предлагает файл
    selecting_categories = State()


class AdminReview(StatesGroup):       # админ меняет название чужой заявки
    editing_title = State()


class AddLink(StatesGroup):           # админ добавляет ссылку
    waiting_for_text = State()


# ==========================================
#                КЛАВИАТУРЫ
# ==========================================
def get_main_menu_keyboard():
    builder = [[InlineKeyboardButton(text=cat_data["title"], callback_data=f"cat:{cat_key}")]
               for cat_key, cat_data in DATABASE["categories"].items()]
    builder.append([InlineKeyboardButton(text="🔗 Полезные материалы", callback_data="links:main")])
    builder.append([InlineKeyboardButton(text="📤 Предложить файл", callback_data="submit:start")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def build_admin_categories_kb(selected: set):
    builder = []
    for cat_key, cat_data in DATABASE["categories"].items():
        mark = "☑️" if cat_key in selected else "▫️"
        builder.append([InlineKeyboardButton(text=f"{mark} {cat_data['title']}", callback_data=f"a_toggle:{cat_key}")])
    builder.append([InlineKeyboardButton(text=f"✅ Готово ({len(selected)})", callback_data="a_done")])
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def build_user_categories_kb(selected: set):
    builder = []
    for cat_key, cat_data in DATABASE["categories"].items():
        mark = "☑️" if cat_key in selected else "▫️"
        builder.append([InlineKeyboardButton(text=f"{mark} {cat_data['title']}", callback_data=f"usub_toggle:{cat_key}")])
    builder.append([InlineKeyboardButton(text=f"✅ Отправить на проверку ({len(selected)})", callback_data="usub_done")])
    builder.append([InlineKeyboardButton(text="❌ Отмена", callback_data="usub_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def build_submission_categories_kb(sub_id: str):
    sub = PENDING_SUBMISSIONS[sub_id]
    selected = set(sub["categories"])
    builder = []
    for cat_key, cat_data in DATABASE["categories"].items():
        mark = "☑️" if cat_key in selected else "▫️"
        builder.append([InlineKeyboardButton(text=f"{mark} {cat_data['title']}", callback_data=f"subcat_toggle:{sub_id}:{cat_key}")])
    builder.append([InlineKeyboardButton(text="✅ Готово", callback_data=f"subcat_done:{sub_id}")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def build_submission_action_kb(sub_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить как есть", callback_data=f"sub_approve:{sub_id}")],
        [InlineKeyboardButton(text="✏️ Изменить разделы", callback_data=f"sub_editcat:{sub_id}")],
        [InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"sub_edittitle:{sub_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"sub_reject:{sub_id}")],
    ])


# ==========================================
#     АДМИН: ПРЯМАЯ ЗАГРУЗКА ФАЙЛА (мультивыбор разделов)
# ==========================================
@dp.message(F.document, F.from_user.id.in_(ADMIN_IDS))
async def admin_doc_received(message: types.Message, state: FSMContext):
    doc = message.document
    
    if is_file_exists(doc.file_unique_id):
        return await message.answer("⚠️ Этот файл уже есть в базе данных!")

    default_name = message.caption if message.caption else doc.file_name

    await state.update_data(
        file_id=doc.file_id, 
        file_unique_id=doc.file_unique_id, 
        default_name=default_name, 
        selected=[]
    )
    await state.set_state(FileUpload.selecting_categories)

    await message.answer(
        f"📥 **Получен файл:** `{default_name}`\n\nОтметь разделы (можно несколько):",
        reply_markup=build_admin_categories_kb(set())
    )


@dp.callback_query(FileUpload.selecting_categories, F.data.startswith("a_toggle:"))
async def admin_toggle_cat(callback: types.CallbackQuery, state: FSMContext):
    cat_key = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = set(data.get("selected", []))
    selected.discard(cat_key) if cat_key in selected else selected.add(cat_key)
    await state.update_data(selected=list(selected))
    await callback.message.edit_reply_markup(reply_markup=build_admin_categories_kb(selected))
    await callback.answer()


@dp.callback_query(FileUpload.selecting_categories, F.data == "a_cancel")
@dp.callback_query(FileUpload.waiting_for_caption, F.data == "a_cancel")
async def admin_cancel_upload(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Загрузка файла отменена.")
    await callback.answer()


@dp.callback_query(FileUpload.selecting_categories, F.data == "a_done")
async def admin_categories_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = set(data.get("selected", []))
    if not selected:
        return await callback.answer("⚠️ Отметь хотя бы один раздел.", show_alert=True)

    await state.set_state(FileUpload.waiting_for_caption)
    default_name = data.get("default_name")
    cats_text = ", ".join(DATABASE["categories"][c]["title"] for c in selected)

    builder = [
        [InlineKeyboardButton(text=f"📝 Оставить: {default_name[:20]}...", callback_data="a_skip_caption")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="a_cancel")]
    ]
    await callback.message.edit_text(
        f"✅ Разделы: {cats_text}\n\n✍️ Введи описание файла, или оставь имя по умолчанию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()


async def _admin_save_file(state: FSMContext, caption: str):
    data = await state.get_data()
    selected = data.get("selected", [])
    for cat_key in selected:
        DATABASE["categories"][cat_key]["files"].append({
            "file_id": data["file_id"], 
            "file_unique_id": data.get("file_unique_id"),
            "caption": caption
        })
    await save_db(DATABASE)
    return selected


@dp.callback_query(FileUpload.waiting_for_caption, F.data == "a_skip_caption")
async def admin_skip_caption(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    default_name = data["default_name"]
    selected = await _admin_save_file(state, default_name)
    cats_text = ", ".join(DATABASE["categories"][c]["title"] for c in selected)
    await callback.message.edit_text(f"✅ Файл сохранён в: {cats_text}\n📄 {default_name}")
    await state.clear()
    await callback.answer()


@dp.message(FileUpload.waiting_for_caption, F.text)
async def admin_save_custom_caption(message: types.Message, state: FSMContext):
    caption = message.text.strip()
    selected = await _admin_save_file(state, caption)
    cats_text = ", ".join(DATABASE["categories"][c]["title"] for c in selected)
    await message.answer(f"✅ Файл сохранён в: {cats_text}\n📄 {caption}")
    await state.clear()


# ==========================================
#   ПОЛЬЗОВАТЕЛЬ: ПРЕДЛОЖИТЬ ФАЙЛ (уходит на проверку админам)
# ==========================================
@dp.callback_query(F.data == "submit:start")
async def submit_start(callback: types.CallbackQuery):
    await callback.message.answer(
        "📤 Просто пришли мне сюда файл (PDF и т.п.), который хочешь предложить для базы — "
        "я передам его админу на проверку."
    )
    await callback.answer()


@dp.message(F.document)
async def user_doc_received(message: types.Message, state: FSMContext):
    doc = message.document

    if is_file_exists(doc.file_unique_id):
        return await message.answer("⚠️ Этот файл уже есть в каталоге! Спасибо, но он нам не нужен дважды 😉")

    default_name = message.caption if message.caption else doc.file_name

    await state.update_data(
        file_id=doc.file_id, 
        file_unique_id=doc.file_unique_id,
        default_name=default_name, 
        selected=[]
    )
    await state.set_state(UserSubmit.selecting_categories)

    await message.answer(
        f"📥 Файл получен: `{default_name}`\n\n"
        f"Можешь подсказать раздел (необязательно — админ сам решит, если не уверен):",
        reply_markup=build_user_categories_kb(set())
    )


@dp.callback_query(UserSubmit.selecting_categories, F.data.startswith("usub_toggle:"))
async def usub_toggle(callback: types.CallbackQuery, state: FSMContext):
    cat_key = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = set(data.get("selected", []))
    selected.discard(cat_key) if cat_key in selected else selected.add(cat_key)
    await state.update_data(selected=list(selected))
    await callback.message.edit_reply_markup(reply_markup=build_user_categories_kb(selected))
    await callback.answer()


@dp.callback_query(UserSubmit.selecting_categories, F.data == "usub_cancel")
async def usub_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отправка файла отменена.")
    await callback.answer()


@dp.callback_query(UserSubmit.selecting_categories, F.data == "usub_done")
async def usub_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = list(set(data.get("selected", [])))

    sub_id = uuid.uuid4().hex[:8]
    username = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name
    PENDING_SUBMISSIONS[sub_id] = {
        "user_id": callback.from_user.id,
        "username": username,
        "file_id": data["file_id"],
        "file_unique_id": data.get("file_unique_id"),
        "title": data["default_name"],
        "categories": selected,
        "status": "pending",
    }
    await state.clear()
    await callback.message.edit_text("📤 Файл отправлен на проверку админу. Спасибо за помощь! 🙌")
    await callback.answer()
    await send_submission_for_review(sub_id)


async def send_submission_for_review(sub_id: str):
    sub = PENDING_SUBMISSIONS[sub_id]
    cats_text = ", ".join(DATABASE["categories"][c]["title"] for c in sub["categories"]) if sub["categories"] else "не указано"
    caption = (
        f"📥 Новый файл на проверку\n"
        f"👤 От: {sub['username']}\n"
        f"📄 Название: {sub['title']}\n"
        f"📁 Разделы: {cats_text}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_document(admin_id, document=sub["file_id"], caption=caption, reply_markup=build_submission_action_kb(sub_id))
        except Exception as e:
            logger.error(f"Не удалось отправить админу {admin_id}: {e}")


# ==========================================
#   АДМИН: ОБРАБОТКА ЗАЯВОК ПОЛЬЗОВАТЕЛЕЙ
# ==========================================
@dp.callback_query(F.data.startswith("sub_approve:"))
async def sub_approve(callback: types.CallbackQuery):
    sub_id = callback.data.split(":", 1)[1]
    sub = PENDING_SUBMISSIONS.get(sub_id)
    if not sub or sub["status"] != "pending":
        return await callback.answer("Уже обработано.", show_alert=True)
    if not sub["categories"]:
        return await callback.answer("Сначала выбери разделы («Изменить разделы»).", show_alert=True)

    for cat_key in sub["categories"]:
        DATABASE["categories"][cat_key]["files"].append({
            "file_id": sub["file_id"], 
            "file_unique_id": sub.get("file_unique_id"),
            "caption": sub["title"]
        })
    await save_db(DATABASE)
    sub["status"] = "approved"

    try:
        await callback.message.edit_caption(caption=(callback.message.caption or "") + "\n\n✅ ОДОБРЕНО", reply_markup=None)
    except Exception:
        pass
    await callback.answer("Добавлено ✅")
    try:
        await bot.send_message(sub["user_id"], f"✅ Твой файл «{sub['title']}» добавлен в каталог! Спасибо 🙌")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("sub_reject:"))
async def sub_reject(callback: types.CallbackQuery):
    sub_id = callback.data.split(":", 1)[1]
    sub = PENDING_SUBMISSIONS.get(sub_id)
    if not sub or sub["status"] != "pending":
        return await callback.answer("Уже обработано.", show_alert=True)

    sub["status"] = "rejected"
    try:
        await callback.message.edit_caption(caption=(callback.message.caption or "") + "\n\n❌ ОТКЛОНЕНО", reply_markup=None)
    except Exception:
        pass
    await callback.answer("Отклонено")
    try:
        await bot.send_message(sub["user_id"], "😔 Твой файл не был принят в каталог.")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("sub_editcat:"))
async def sub_editcat(callback: types.CallbackQuery):
    sub_id = callback.data.split(":", 1)[1]
    if PENDING_SUBMISSIONS.get(sub_id, {}).get("status") != "pending":
        return await callback.answer("Уже обработано.", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=build_submission_categories_kb(sub_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("subcat_toggle:"))
async def subcat_toggle(callback: types.CallbackQuery):
    _, sub_id, cat_key = callback.data.split(":")
    sub = PENDING_SUBMISSIONS.get(sub_id)
    if not sub or sub["status"] != "pending":
        return await callback.answer("Уже обработано.", show_alert=True)
    selected = set(sub["categories"])
    selected.discard(cat_key) if cat_key in selected else selected.add(cat_key)
    sub["categories"] = list(selected)
    await callback.message.edit_reply_markup(reply_markup=build_submission_categories_kb(sub_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("subcat_done:"))
async def subcat_done(callback: types.CallbackQuery):
    sub_id = callback.data.split(":", 1)[1]
    if PENDING_SUBMISSIONS.get(sub_id, {}).get("status") != "pending":
        return await callback.answer("Уже обработано.", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=build_submission_action_kb(sub_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("sub_edittitle:"))
async def sub_edittitle(callback: types.CallbackQuery, state: FSMContext):
    sub_id = callback.data.split(":", 1)[1]
    if PENDING_SUBMISSIONS.get(sub_id, {}).get("status") != "pending":
        return await callback.answer("Уже обработано.", show_alert=True)
    await state.set_state(AdminReview.editing_title)
    await state.update_data(sub_id=sub_id)
    await callback.message.answer("✍️ Введи новое название файла:")
    await callback.answer()


@dp.message(AdminReview.editing_title, F.text)
async def admin_retitle_submission(message: types.Message, state: FSMContext):
    data = await state.get_data()
    sub_id = data.get("sub_id")
    sub = PENDING_SUBMISSIONS.get(sub_id)
    await state.clear()
    if not sub or sub["status"] != "pending":
        return await message.answer("⚠️ Эта заявка уже обработана.")
    sub["title"] = message.text.strip()
    await message.answer(f"✅ Название обновлено: {sub['title']}")


# ==========================================
#           ПОЛЕЗНЫЕ МАТЕРИАЛЫ (ССЫЛКИ)
# ==========================================
@dp.callback_query(F.data == "links:main")
async def links_main(callback: types.CallbackQuery):
    builder = [[InlineKeyboardButton(text=sec["title"], callback_data=f"links:sec:{key}")]
               for key, sec in DATABASE["links"].items()]
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
    await callback.message.edit_text("🔗 **Полезные материалы**\nВыбери раздел:", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("links:sec:"))
async def links_section(callback: types.CallbackQuery):
    key = callback.data.split(":", 2)[2]
    sec = DATABASE["links"][key]
    
    builder = []
    for idx, item in enumerate(sec["items"]):
        row = [InlineKeyboardButton(text=item["title"], url=item["url"])]
        if callback.from_user.id in ADMIN_IDS:
            row.append(InlineKeyboardButton(text="🗑", callback_data=f"del_link:{key}:{idx}"))
        builder.append(row)
        
    if callback.from_user.id in ADMIN_IDS:
        builder.append([InlineKeyboardButton(text="➕ Добавить ссылку", callback_data=f"links:add:{key}")])
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="links:main")])
    text = f"**{sec['title']}**" + ("" if sec["items"] else "\n\nПока пусто.")
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("links:add:"))
async def links_add_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("Только для админов.", show_alert=True)
    key = callback.data.split(":", 2)[2]
    await state.set_state(AddLink.waiting_for_text)
    await state.update_data(link_key=key)
    await callback.message.answer(
        "Отправь в формате:\nНазвание - URL\n\nНапример:\nОфициальный канал - https://t.me/matham"
    )
    await callback.answer()


@dp.message(AddLink.waiting_for_text, F.text)
async def links_add_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    key = data["link_key"]
    text = message.text.strip()

    if " - " in text:
        title, url = text.split(" - ", 1)
    elif "|" in text:
        title, url = text.split("|", 1)
    else:
        return await message.answer("⚠️ Не понял формат. Пришли так:\nНазвание - URL")

    title, url = title.strip(), url.strip()
    DATABASE["links"][key]["items"].append({"title": title, "url": url})
    await save_db(DATABASE)
    await state.clear()
    await message.answer(f"✅ Ссылка добавлена: {title}")


@dp.callback_query(F.data.startswith("del_link:"))
async def admin_delete_link(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("Только для админов", show_alert=True)
        
    _, key, idx = callback.data.split(":")
    idx = int(idx)
    sec = DATABASE["links"][key]
    
    if idx < len(sec["items"]):
        sec["items"].pop(idx)
        await save_db(DATABASE)
        await callback.answer("Ссылка удалена")
        
        # Обновляем сообщение (перерисовываем интерфейс)
        builder = []
        for i, item in enumerate(sec["items"]):
            row = [InlineKeyboardButton(text=item["title"], url=item["url"])]
            row.append(InlineKeyboardButton(text="🗑", callback_data=f"del_link:{key}:{i}"))
            builder.append(row)
        
        builder.append([InlineKeyboardButton(text="➕ Добавить ссылку", callback_data=f"links:add:{key}")])
        builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="links:main")])
        text = f"**{sec['title']}**" + ("" if sec["items"] else "\n\nПока пусто.")
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    else:
        await callback.answer("Ошибка: ссылка не найдена", show_alert=True)


# ==========================================
#   ПОЛЬЗОВАТЕЛЬ: КАТАЛОГ (плоский, без подразделов)
# ==========================================
@dp.callback_query(F.data.startswith("cat:"))
async def process_category_click(callback: types.CallbackQuery):
    cat_key = callback.data.split(":", 1)[1]
    cat_data = DATABASE["categories"][cat_key]

    if not cat_data["files"]:
        builder = [[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]]
        return await callback.message.edit_text(
            f"**{cat_data['title']}**\n\n📁 Пока нет файлов. Попробуй поиск — просто напиши слово в чат!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
        )

    builder = []
    for idx, item in enumerate(cat_data["files"]):
        btn_text = f"📄 {item['caption'][:35]}" + ("..." if len(item['caption']) > 35 else "")
        row = [InlineKeyboardButton(text=btn_text, callback_data=f"file:{cat_key}:{idx}")]
        
        # Добавляем кнопку удаления, если это админ
        if callback.from_user.id in ADMIN_IDS:
            row.append(InlineKeyboardButton(text="🗑", callback_data=f"del_file:{cat_key}:{idx}"))
            
        builder.append(row)
        
    builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])

    await callback.message.edit_text(
        f"**{cat_data['title']}**\n⬇️ Выбери файл, или напиши ключевое слово для поиска:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("del_file:"))
async def admin_delete_file(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("Только для админов", show_alert=True)
        
    _, cat_key, idx = callback.data.split(":")
    idx = int(idx)
    cat_data = DATABASE["categories"][cat_key]
    files = cat_data["files"]
    
    if idx < len(files):
        deleted = files.pop(idx)
        await save_db(DATABASE)
        await callback.answer(f"Удалено: {deleted['caption']}")
        
        # Обновляем меню файлов для категории
        if not files:
            builder = [[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")]]
            return await callback.message.edit_text(
                f"**{cat_data['title']}**\n\n📁 Пока нет файлов. Попробуй поиск — просто напиши слово в чат!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
            )
            
        builder = []
        for i, item in enumerate(files):
            btn_text = f"📄 {item['caption'][:35]}" + ("..." if len(item['caption']) > 35 else "")
            row = [InlineKeyboardButton(text=btn_text, callback_data=f"file:{cat_key}:{i}")]
            row.append(InlineKeyboardButton(text="🗑", callback_data=f"del_file:{cat_key}:{i}"))
            builder.append(row)
            
        builder.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")])
        await callback.message.edit_text(
            f"**{cat_data['title']}**\n⬇️ Выбери файл, или напиши ключевое слово для поиска:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder)
        )
    else:
        await callback.answer("Ошибка: файл не найден", show_alert=True)


@dp.callback_query(F.data.startswith("file:"))
async def process_file_click(callback: types.CallbackQuery):
    _, cat_key, idx = callback.data.split(":")
    idx = int(idx)
    files = DATABASE["categories"][cat_key]["files"]

    if idx >= len(files):
        return await callback.answer("❌ Файл больше не доступен.", show_alert=True)

    item = files[idx]
    await callback.answer("Отправляю... ⏳")
    await callback.message.answer_document(document=item["file_id"], caption=f"📄 {item['caption']}")


@dp.callback_query(F.data == "menu:main")
async def process_back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text("📂 **Каталог файлов**\nВыбери раздел:", reply_markup=get_main_menu_keyboard())
    await callback.answer()


# ==========================================
#     КОМАНДЫ И СИЛЬНЫЙ ПОИСК ПО КЛЮЧЕВЫМ СЛОВАМ
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Здарова! ✌️\nЯ бот канала matham.\n\n"
        "🔎 **Поиск:** Просто напиши слово (или несколько) — найду по всем разделам и ссылкам.\n"
        "📂 **Каталог:** Выбери раздел из меню ниже:",
        reply_markup=get_main_menu_keyboard()
    )


@dp.message(Command("surprise"))
async def cmd_surprise(message: types.Message):
    all_files = []
    for cat_key, cat_data in DATABASE["categories"].items():
        for f in cat_data["files"]:
            all_files.append((f, cat_data["title"]))

    if not all_files:
        return await message.answer("📁 В базе пока нет файлов.")

    selected_file, cat_title = random.choice(all_files)
    await message.answer(f"🎲 Случайный файл из раздела: **{cat_title}**")
    await message.answer_document(document=selected_file["file_id"], caption=f"📄 {selected_file['caption']}")


@dp.message(F.text & ~F.text.startswith("/"))
async def global_search_handler(message: types.Message):
    query = message.text.strip().lower()
    if query in ["удиви меня", "surprise", "рандом"]:
        return await cmd_surprise(message)

    words = [w for w in query.split() if w]
    if not words:
        return

    found_files = []
    for cat_data in DATABASE["categories"].values():
        haystack_cat = cat_data["title"].lower()
        for f in cat_data["files"]:
            haystack = f"{haystack_cat} {f['caption'].lower()}"
            if all(w in haystack for w in words):
                found_files.append((f, cat_data["title"]))

    found_links = []
    for sec in DATABASE["links"].values():
        for item in sec["items"]:
            if all(w in item["title"].lower() for w in words):
                found_links.append(item)

    if not found_files and not found_links:
        return await message.answer(
            "🔍 Ничего не найдено. Попробуй другое слово или открой меню:",
            reply_markup=get_main_menu_keyboard()
        )

    if found_files:
        await message.answer(f"🔍 Найдено файлов: **{len(found_files)}**")
        for file_info, cat_title in found_files[:10]:
            await message.answer_document(
                document=file_info["file_id"],
                caption=f"📄 **{file_info['caption']}**\n📌 {cat_title}"
            )

    if found_links:
        builder = [[InlineKeyboardButton(text=item["title"], url=item["url"])] for item in found_links[:10]]
        await message.answer(f"🔗 Найдено ссылок: **{len(found_links)}**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))


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
    n_files = sum(len(c["files"]) for c in DATABASE["categories"].values())
    n_links = sum(len(s["items"]) for s in DATABASE["links"].values())
    logger.info(f"📦 Каталог загружен: {len(DATABASE['categories'])} категорий, {n_files} файлов, {n_links} ссылок")

    await bot.delete_webhook(drop_pending_updates=True)
    await set_main_menu(bot)
    logger.info("🚀 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())