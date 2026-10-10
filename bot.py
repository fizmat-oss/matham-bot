import asyncio
import copy
import csv
import html
import io
import json
import logging
import os
import random
import re
import uuid
import zipfile
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedDocument,
    InputMediaPhoto,
    InputTextMessageContent,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from motor.motor_asyncio import AsyncIOMotorClient

# ============================================================
# CONFIGURATION & LOGGING
# ============================================================

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("DEBUG", "0").lower() in ("1", "true", "yes") else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("matham_bot")

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not configured")

ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "matham_bot")
YEREVAN_TZ = timezone(timedelta(hours=4))

CHANNEL_ID = os.environ.get("CHANNEL_ID", "@matham123456").strip() or "@matham123456"
TG_TEXT_LIMIT = 4000
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "30"))

mongo_client = AsyncIOMotorClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]
db_collection = mongo_db["catalog"]
submissions_collection = mongo_db["submissions"]
DB_DOC_ID = "catalog_main"

bot = Bot(token=TOKEN)
dp = Dispatcher()
DATABASE: Dict[str, Any] = {}
BOT_USERNAME: str = ""

DIFF_KEYS = ("easy", "medium", "hard", "imo")
DIFF_MULT = {"easy": 1, "medium": 2, "hard": 3, "imo": 5}

# Persistent shared HTTP session for external API calls
HTTP_SESSION: Optional[aiohttp.ClientSession] = None

# ============================================================
# LOCALIZATION & TEXTS
# ============================================================

TEXTS = {
    "ru": {
        "welcome_back": "👋 С возвращением, {nick}!",
        "hello_new": "👋 Привет, {name}!\n\nДобро пожаловать в <b>MathAm</b>!",
        "choose_language": "🌐 <b>Выберите язык / Choose your language:</b>",
        "lang_set": "✅ Язык установлен: <b>Русский</b> 🇷🇺",
        "ask_nickname": "🪪 Напишите ваш <b>никнейм</b> — под ним вас будут видеть в рейтинге, решениях и заявках.",
        "change_nickname": "🪪 Введите новый <b>никнейм</b>:\n/cancel — отмена.",
        "nickname_bad_slash": "⚠️ Никнейм не может начинаться с «/». Напишите другой:",
        "nickname_bad_len": "⚠️ Никнейм должен быть от 2 до 30 символов. Попробуйте ещё раз:",
        "nickname_welcome": "✅ Приятно познакомиться, {nick}! 🎉",
        "nickname_updated": "✅ Ваш никнейм успешно изменён на: {nick}",
        "menu_title": "🏠 <b>Главное меню</b>\nВыберите раздел:",
        "menu_catalog": "📚 Каталог",
        "menu_search": "🏷 Поиск по тегам",
        "menu_task": "🎯 Задача дня",
        "menu_archive": "🗄 Архив задач",
        "menu_task_tags": "🏷 Задачи по тегам",
        "menu_mustread": "⭐ Must-read",
        "menu_fav": "❤️ Избранное",
        "menu_rating": "🏆 Рейтинг",
        "menu_random": "🎲 Случайный материал",
        "menu_links": "🔗 Полезные ссылки",
        "menu_submit": "📤 Предложить файл",
        "menu_name": "🪪 Сменить ник",
        "menu_admin": "👑 Админ-панель",
        "menu_lang": "🌐 Язык / Language",
        "cancel_done": "❌ Отменено. /start — главное меню.",
        "no_file": "Файл не найден.",
        "file_sent": "Файл отправлен ✅",
        "file_send_fail": "Не удалось отправить файл.",
        "get_file": "📥 Получить файл",
        "add_fav": "❤️ В избранное",
        "remove_fav": "💔 Убрать из избранного",
        "fav_added": "❤️ Добавлено в избранное",
        "fav_removed": "💔 Удалено из избранного",
        "edit": "✏️ Изменить",
        "mustread_btn": "⭐ Must-read",
        "delete": "🗑 Удалить",
        "back_catalog": "⬅️ Каталог",
        "back_menu": "⬅️ Главное меню",
        "back_admin": "⬅️ Админ-панель",
        "back_task": "⬅️ К задаче",
        "catalog_title": "📚 <b>Каталог материалов по разделам:</b>",
        "section_missing": "Раздел не найден.",
        "task_missing": "🎯 Задача не найдена.",
        "search_title": "🏷 <b>Поиск по тегам</b>\n\nВыберите теги и нажмите «🔎 Искать».\nИли отправьте тег/слово сообщением.",
        "search_go": "🔎 Искать материалы",
        "search_tasks_btn": "🎯 Искать задачи дня",
        "search_reset": "♻️ Сброс",
        "search_new": "🏷 Новый поиск",
        "search_pick_one": "Выберите хотя бы один тег!",
        "search_tagged": "🔎 <b>Результаты по тегам:</b> {tags}",
        "search_query": "🔎 <b>Результаты по запросу:</b> <i>{q}</i>",
        "search_found": "Найдено материалов: <b>{n}</b>",
        "search_nothing": "😔 Ничего не найдено. Попробуйте другие теги.",
        "search_tag_off": "Тег снят",
        "search_tag_on": "Тег выбран",
        "search_selected_n": "🏷 <b>Поиск по тегам</b>\nВыбрано тегов: {n}",
        "search_reset_done": "🏷 <b>Поиск по тегам</b>\nВыбор сброшен.",
        "tag_db_title": "🏷 <b>База тегов</b> (всего: {n})\n\nНажмите на тег для удаления или выберите «Переименовать».",
        "tag_add_btn": "➕ Добавить тег",
        "tag_rename_btn": "✏️ Переименовать тег",
        "tag_ask_new": "🏷 Отправьте новый тег (можно с # или без, несколько через запятую):",
        "tag_added": "✅ Добавлены теги: {tags}",
        "tag_nothing_added": "⚠️ Новых тегов нет (пусто или дубликаты).",
        "tag_removed": "Удалён {tag}",
        "tag_missing": "Тег не найден.",
        "tag_rename_pick": "✏️ Какой тег переименовать?",
        "tag_rename_ask": "✏️ Отправьте новое название для тега {tag}:",
        "tag_rename_done": "✅ Тег переименован: {old} → {new}. Обновлено файлов: {n}.",
        "tag_rename_no_files": "✅ Тег переименован: {old} → {new}. Файлов с этим тегом не было.",
        "tag_rename_conflict": "⚠️ Тег «{new}» уже существует.",
        "favorites_title": "❤️ <b>Избранное</b>",
        "favorites_empty": "\n\nПока пусто. Откройте материал в каталоге и нажмите «❤️ В избранное».",
        "rating_title": "🏆 <b>Рейтинг MathAm</b>\n<i>Очки начисляются за решения задач дня</i>\n",
        "rating_empty": "Пока никто не набрал очки. Решите задачу дня первым!",
        "rating_you": "\n👤 Вы: {nick} — {score} очк. · ✅ {solved} · ❤️ {favs}",
        "mustread_title": "⭐ <b>Must-read</b>\nМатериалы, рекомендованные к изучению:",
        "mustread_empty": "⭐ <b>Must-read</b>\n\nСписок пока пуст.",
        "mustread_added": "⭐ Добавлено в must-read",
        "mustread_removed": "Убрано из must-read",
        "mustread_remove_btn": "✩ Убрать из must-read",
        "links_title": "🔗 <b>Полезные ресурсы</b>\nВыберите раздел:",
        "links_empty_section": "🔗 <b>{title}</b>\n\nВ этом разделе пока нет ссылок.",
        "links_add": "➕ Добавить ссылку",
        "links_del": "🗑 Удалить #{n}",
        "links_ask": "🔗 Отправьте ссылку в формате:\n<code>Название - https://example.com</code>",
        "links_no_url": "⚠️ URL не найден. Попробуйте ещё раз.",
        "links_added": "✅ Ссылка добавлена в «{title}».",
        "links_section_missing": "Раздел не найден.",
        "links_item_removed": "Удалено: {name}",
        "links_item_missing": "Элемент не найден.",
        "links_only_admin": "Только администратор.",
        "task_of_day": "🎯 <b>Задача дня</b> · {date}\n<i>№ {num} из {total}</i>\n\n{text}",
        "task_text_on_photo": "Текст задачи — на фото.",
        "task_solutions": "👥 Решения участников ({n})",
        "task_send_solution": "📝 Отправить решение",
        "task_solution_pending": "⏳ Решение на проверке",
        "task_solution_ok": "✅ Зачтено · {grade}/10",
        "task_solution_ok_no_grade": "✅ Зачтено",
        "task_author_solution": "💡 Решение автора",
        "task_bcast": "📢 Разослать задачу",
        "task_archive_title": "🗄 <b>Архив задач</b>\nДней с задачами: {n}\nСтраница {page} из {total}",
        "task_archive_empty": "🗄 <b>Архив задач</b>\n\nЗадач пока нет.",
        "task_today": "🎯 Сегодня",
        "task_no_tasks": "🎯 <b>Задача дня</b>\n\nЗадачи пока не опубликованы.",
        "task_solution_sent": "✅ <b>Решение отправлено!</b>\nАдминистраторы проверят его и поставят оценку.",
        "task_sol_author_header": "💡 <b>Решение автора</b> (задача №{num}, {date})",
        "task_sol_not_yet": "Решение пока не добавлено.",
        "task_sols_header": "👥 <b>Решения участников</b> (задача №{num}, {date})\n",
        "task_sols_empty": "Пока нет проверенных решений.",
        "task_sol_grade_full": "{grade}/10",
        "task_sol_ok_mark": "✓",
        "task_sol_not_found": "Решение не найдено.",
        "task_sol_pending_user": "Решение ещё на проверке.",
        "task_sol_view": "👀 {nick} · {grade}",
        "task_sol_empty_content": "Решение без содержимого.",
        "task_sol_show_fail": "Не удалось показать решение.",
        "task_sol_bcast_done": "✅ Задача опубликована.\n👥 Доставлено: {sent} · Ошибок: {failed}.",
        "task_sol_bcast_channel_fail": "\n⚠️ Не удалось отправить в канал.",
        "task_sol_bcast_running": "⏳ Рассылаю...",
        "task_approved_notify": "✅ Ваше решение задачи {date} (№{num}) зачтено!",
        "task_approved_notify_grade": "✅ Ваше решение задачи {date} (№{num}) зачтено!\n⭐ Оценка: {grade}/10",
        "task_grade_updated": "⭐ Оценка обновлена: {grade}/10",
        "task_rejected_notify": "❌ Ваше решение задачи {date} (№{num}) не зачтено.",
        "task_admin_graded": "⭐ Оценка для {nick}: <b>{label}</b>.",
        "task_admin_approved": "✅ Решение от {nick} зачтено.\n⭐ Поставьте оценку:",
        "task_admin_grade_ask": "✓ Без оценки",
        "task_admin_rejected": "❌ Отклонено.",
        "task_admin_sol_rev_not_found": "Решение не найдено.",
        "task_admin_sol_approved_short": "Зачтено",
        "task_admin_sol_rejected_short": "Отклонено",
        "task_grade_saved": "Оценка сохранена",
        "task_grade_zero": "без оценки",
        "submit_start": "📤 Отправьте файл (PDF) для публикации в библиотеку.",
        "submit_ask_title": "✏️ Как называется материал? Отправьте название:",
        "submit_ask_tags": "🏷 Выберите теги:",
        "submit_skip_tags": "⏭ Без тегов",
        "submit_preview": "📋 <b>Заявка на публикацию</b>\n\n📖 Название: {title}\n📄 Файл: {file}\n🏷 Теги: {tags}",
        "submit_send": "✅ Отправить",
        "submit_cancel": "❌ Отмена",
        "submit_sent": "✅ Заявка отправлена!",
        "submit_cancelled": "❌ Отправка отменена.",
        "submit_stale": "Заявка устарела.",
        "submit_first_file": "Сначала отправьте файл!",
        "admin_title": "👑 <b>Админ-панель MathAm</b>\nВыберите действие:",
        "admin_upload": "➕ Загрузить материал",
        "admin_add_task": "🎯 Добавить задачу дня",
        "admin_cats": "📂 Управление разделами",
        "admin_tags": "🏷 Управление тегами",
        "admin_stats": "📊 Статистика",
        "admin_subs": "📥 Заявки на файлы",
        "admin_pending": "🧩 Решения на проверку",
        "admin_bcast": "📢 Рассылка",
        "admin_upload_ask": "📤 Отправьте файл (PDF):",
        "admin_upload_title": "✏️ Отправьте название материала:",
        "admin_upload_desc": "📝 Отправьте описание (необязательно) или «пропустить»:",
        "admin_upload_tags": "🏷 Выберите теги:",
        "admin_upload_diff": "🎯 Выберите уровень сложности:",
        "admin_upload_cats": "📂 Выберите разделы:",
        "admin_upload_publish": "✅ Опубликовать",
        "admin_upload_published": "✅ Материал опубликован!\n📖 <b>{title}</b>\n📂 {cats}",
        "admin_upload_stale": "Загрузка устарела.",
        "admin_upload_no_cat": "Выберите хотя бы один раздел!",
        "admin_upload_cat_missing": "Категория не найдена.",
        "admin_upload_done_short": "Сохранено ✅",
        "admin_diff_easy": "🟢 Easy (Базовый)",
        "admin_diff_medium": "🟡 Medium (Регион)",
        "admin_diff_hard": "🔴 Hard (Всерос / Финал)",
        "admin_diff_imo": "🔥 IMO (Международный)",
        "admin_task_photo": "📸 Отправьте фото задачи, либо напишите «пропустить».",
        "admin_task_text": "✍️ Отправьте текст задачи (или «пропустить»):",
        "admin_task_solution": "💡 Отправьте решение (текстом, фото или «пропустить»):",
        "admin_task_date": "📅 На какую дату?\nФормат: <code>ГГГГ-ММ-ДД</code>, «сегодня» или «завтра»:",
        "admin_task_added": "✅ Задача добавлена на <b>{date}</b> (№ {num}).",
        "admin_task_bad_date": "⚠️ Неверный формат даты.",
        "admin_task_photo_ask": "📸 Отправьте фото или «пропустить».",
        "admin_task_sol_ask": "Отправьте текст, фото, документ или «пропустить».",
        "admin_stats_title": "📊 <b>Статистика MathAm</b>\n\n👥 Пользователей: {users}\n📚 Файлов: {files}\n🏷 Тегов: {tags}\n🎯 Задач: {tasks}\n🧩 Решений: {pending}\n📥 Заявок: {subs}\n\n<b>Топ-5:</b>\n{top}",
        "admin_subs_empty": "📥 Заявок нет.",
        "admin_subs_title": "📥 <b>Заявки на файлы</b>\n",
        "admin_subs_pick_cat": "📂 Выберите раздел:",
        "admin_subs_published": "✅ Опубликовано в «{cat}».",
        "admin_subs_user_notify": "✅ Ваш материал «{title}» одобрен и добавлен в раздел «{cat}»!",
        "admin_subs_reject_notify": "❌ Ваша заявка на публикацию материала «{title}» отклонена.",
        "admin_subs_accept": "✅ Принять",
        "admin_subs_reject": "❌ Отклонить",
        "admin_subs_rejected": "❌ Отклонено.",
        "admin_subs_already": "Уже обработано.",
        "admin_subs_not_found": "Не найдено.",
        "admin_subs_already_pub": "Уже опубликовано.",
        "admin_pending_title": "🧩 <b>Решения на проверку</b>\n",
        "admin_pending_empty": "\nНет решений на проверку. 🎉",
        "admin_pending_shown": "\nПоказано: {n}",
        "admin_bcast_ask": "📢 Отправьте сообщение для рассылки.\n/cancel — отмена.",
        "admin_bcast_running": "⏳ Рассылка запущена...",
        "admin_bcast_done": "✅ Рассылка завершена.\nДоставлено: {sent} · Ошибок: {failed}",
        "admin_edit_title": "⚙️ <b>Редактирование</b>\n📖 {title}",
        "admin_edit_replace": "📄 Заменить файл",
        "admin_edit_rename": "✏️ Название",
        "admin_edit_desc": "📝 Описание",
        "admin_edit_tags": "🏷 Теги",
        "admin_edit_back": "⬅️ Назад",
        "admin_edit_ask_doc": "📄 Отправьте новый файл:",
        "admin_edit_ask_title": "✏️ Отправьте новое название:",
        "admin_edit_ask_desc": "📝 Отправьте новое описание (или «очистить»):",
        "admin_edit_ask_tags": "🏷 Отправьте теги через запятую (или «очистить»):",
        "admin_edit_doc_done": "✅ Файл заменён (записей: {n}).",
        "admin_edit_title_done": "✅ Название обновлено (записей: {n}).",
        "admin_edit_desc_done": "✅ Описание обновлено (записей: {n}).",
        "admin_edit_tags_done": "✅ Теги обновлены (записей: {n}).",
        "admin_del_confirm": "⚠️ Удалить «{title}»?",
        "admin_del_yes": "🗑 Да, удалить",
        "admin_del_done": "🗑 Удалено записей: {n}.",
        "file_card_title": "📖 <b>{title}</b>",
        "file_card_section": "📂 Раздел: {cats}",
        "file_card_diff": "🎯 Уровень: {diff}",
        "file_card_tags": "🏷 {tags}",
        "file_card_summary": "\n📝 {summary}",
        "unknown_text": "🤖 Команда не распознана. Откройте /start для меню.",
        "expect_file": "📤 Ожидаю файл.",
        "expect_doc": "📄 Ожидаю документ.",
        "only_admin": "Недоступно.",
        "choose_tags_n": "🏷 Выберите теги (выбрано: {n}):",
        "rating_line": "{medal} {name} — {score} очк. · ✅ {solved} · 🔥 {streak} дн.",
        "rating_medal_1": "🥇",
        "rating_medal_2": "🥈",
        "rating_medal_3": "🥉",
        "download_all_zip": "📦 Скачать все материалы (ZIP)",
        "zip_preparing": "⏳ Собираем ZIP-архив ({current}/{total})...",
        "zip_empty": "⚠️ В каталоге нет файлов для скачивания.",
        "zip_ready": "📦 <b>Архив библиотеки MathAm</b>\n📚 Файлов: {count}\n💾 Размер: {size_mb:.1f} МБ",
        "zip_part": "📦 <b>Архив библиотеки MathAm (часть {part}/{total_parts})</b>\n📚 Файлов: {count}\n💾 Размер: {size_mb:.1f} МБ",
    },
    "en": {
        "welcome_back": "👋 Welcome back, {nick}!",
        "hello_new": "👋 Hello, {name}!\n\nWelcome to <b>MathAm</b>!",
        "choose_language": "🌐 <b>Choose your language / Выберите язык:</b>",
        "lang_set": "✅ Language set: <b>English</b> 🇬🇧",
        "ask_nickname": "🪪 Please enter your <b>nickname</b>:",
        "change_nickname": "🪪 Enter new <b>nickname</b>:\n/cancel — cancel.",
        "nickname_bad_slash": "⚠️ Nickname cannot start with «/». Try another:",
        "nickname_bad_len": "⚠️ Nickname must be 2–30 chars:",
        "nickname_welcome": "✅ Nice to meet you, {nick}! 🎉",
        "nickname_updated": "✅ Your nickname has been updated to: {nick}",
        "menu_title": "🏠 <b>Main menu</b>\nChoose a section:",
        "menu_catalog": "📚 Catalog",
        "menu_search": "🏷 Tag search",
        "menu_task": "🎯 Task of the day",
        "menu_archive": "🗄 Task archive",
        "menu_task_tags": "🏷 Tasks by tags",
        "menu_mustread": "⭐ Must-read",
        "menu_fav": "❤️ Favorites",
        "menu_rating": "🏆 Rating",
        "menu_random": "🎲 Random material",
        "menu_links": "🔗 Useful links",
        "menu_submit": "📤 Submit a file",
        "menu_name": "🪪 Change nickname",
        "menu_admin": "👑 Admin panel",
        "menu_lang": "🌐 Language / Язык",
        "cancel_done": "❌ Cancelled. /start — main menu.",
        "no_file": "File not found.",
        "file_sent": "File sent ✅",
        "file_send_fail": "Failed to send file.",
        "get_file": "📥 Get file",
        "add_fav": "❤️ Add to favorites",
        "remove_fav": "💔 Remove from favorites",
        "fav_added": "❤️ Added to favorites",
        "fav_removed": "💔 Removed from favorites",
        "edit": "✏️ Edit",
        "mustread_btn": "⭐ Must-read",
        "delete": "🗑 Delete",
        "back_catalog": "⬅️ Catalog",
        "back_menu": "⬅️ Main menu",
        "back_admin": "⬅️ Admin panel",
        "back_task": "⬅️ Back to task",
        "catalog_title": "📚 <b>Catalog by sections:</b>",
        "section_missing": "Section not found.",
        "task_missing": "🎯 Task not found.",
        "search_title": "🏷 <b>Tag search</b>\n\nPick tags and press «🔎 Search».",
        "search_go": "🔎 Search materials",
        "search_tasks_btn": "🎯 Search daily tasks",
        "search_reset": "♻️ Reset",
        "search_new": "🏷 New search",
        "search_pick_one": "Pick at least one tag!",
        "search_tagged": "🔎 <b>Results by tags:</b> {tags}",
        "search_query": "🔎 <b>Results for:</b> <i>{q}</i>",
        "search_found": "Materials found: <b>{n}</b>",
        "search_nothing": "😔 Nothing found.",
        "search_tag_off": "Tag removed",
        "search_tag_on": "Tag selected",
        "search_selected_n": "🏷 <b>Tag search</b>\nSelected: {n}",
        "search_reset_done": "🏷 Selection cleared.",
        "tag_db_title": "🏷 <b>Tag database</b> (total: {n})",
        "tag_add_btn": "➕ Add tag",
        "tag_rename_btn": "✏️ Rename tag",
        "tag_ask_new": "🏷 Send new tag(s):",
        "tag_added": "✅ Tags added: {tags}",
        "tag_nothing_added": "⚠️ No new tags.",
        "tag_removed": "Removed {tag}",
        "tag_missing": "Tag not found.",
        "tag_rename_pick": "✏️ Which tag?",
        "tag_rename_ask": "✏️ New name for {tag}:",
        "tag_rename_done": "✅ Renamed: {old} → {new}. Files: {n}.",
        "tag_rename_no_files": "✅ Renamed: {old} → {new}.",
        "tag_rename_conflict": "⚠️ Tag «{new}» exists.",
        "favorites_title": "❤️ <b>Favorites</b>",
        "favorites_empty": "\n\nEmpty.",
        "rating_title": "🏆 <b>MathAm rating</b>\n",
        "rating_empty": "Nobody has scored yet.",
        "rating_you": "\n👤 You: {nick} — {score} pts · ✅ {solved} · ❤️ {favs}",
        "mustread_title": "⭐ <b>Must-read</b>",
        "mustread_empty": "⭐ <b>Must-read</b>\n\nEmpty.",
        "mustread_added": "⭐ Added to must-read",
        "mustread_removed": "Removed from must-read",
        "mustread_remove_btn": "✩ Remove",
        "links_title": "🔗 <b>Useful resources</b>",
        "links_empty_section": "🔗 <b>{title}</b>\n\nNo links.",
        "links_add": "➕ Add link",
        "links_del": "🗑 Delete #{n}",
        "links_ask": "🔗 Format: <code>Title - https://example.com</code>",
        "links_no_url": "⚠️ No URL found.",
        "links_added": "✅ Added to «{title}».",
        "links_section_missing": "Section not found.",
        "links_item_removed": "Removed: {name}",
        "links_item_missing": "Not found.",
        "links_only_admin": "Admins only.",
        "task_of_day": "🎯 <b>Task of the day</b> · {date}\n<i>№ {num} of {total}</i>\n\n{text}",
        "task_text_on_photo": "Text is on the photo.",
        "task_solutions": "👥 Solutions ({n})",
        "task_send_solution": "📝 Submit solution",
        "task_solution_pending": "⏳ Pending review",
        "task_solution_ok": "✅ Approved · {grade}/10",
        "task_solution_ok_no_grade": "✅ Approved",
        "task_author_solution": "💡 Author's solution",
        "task_bcast": "📢 Broadcast",
        "task_archive_title": "🗄 <b>Archive</b>\nDays: {n}\nPage {page}/{total}",
        "task_archive_empty": "🗄 <b>Archive</b>\n\nEmpty.",
        "task_today": "🎯 Today",
        "task_no_tasks": "🎯 <b>Task of the day</b>\n\nNo tasks yet.",
        "task_solution_sent": "✅ <b>Solution sent!</b>",
        "task_sol_author_header": "💡 <b>Author's solution</b> (№{num}, {date})",
        "task_sol_not_yet": "No solution yet.",
        "task_sols_header": "👥 <b>Solutions</b> (№{num}, {date})\n",
        "task_sols_empty": "No approved solutions yet.",
        "task_sol_grade_full": "{grade}/10",
        "task_sol_ok_mark": "✓",
        "task_sol_not_found": "Not found.",
        "task_sol_pending_user": "Pending review.",
        "task_sol_view": "👀 {nick} · {grade}",
        "task_sol_empty_content": "Empty solution.",
        "task_sol_show_fail": "Failed to show.",
        "task_sol_bcast_done": "✅ Published.\nDelivered: {sent} · Errors: {failed}.",
        "task_sol_bcast_channel_fail": "\n⚠️ Channel post failed.",
        "task_sol_bcast_running": "⏳ Broadcasting...",
        "task_approved_notify": "✅ Your solution for {date} (№{num}) approved!",
        "task_approved_notify_grade": "✅ Approved! ⭐ {grade}/10",
        "task_grade_updated": "⭐ Grade updated: {grade}/10",
        "task_rejected_notify": "❌ Not accepted.",
        "task_admin_graded": "⭐ Grade for {nick}: <b>{label}</b>.",
        "task_admin_approved": "✅ Approved.\n⭐ Assign grade:",
        "task_admin_grade_ask": "✓ No grade",
        "task_admin_rejected": "❌ Rejected.",
        "task_admin_sol_rev_not_found": "Not found.",
        "task_admin_sol_approved_short": "Approved",
        "task_admin_sol_rejected_short": "Rejected",
        "task_grade_saved": "Grade saved",
        "task_grade_zero": "no grade",
        "submit_start": "📤 Send a file (PDF):",
        "submit_ask_title": "✏️ Title:",
        "submit_ask_tags": "🏷 Pick tags:",
        "submit_skip_tags": "⏭ No tags",
        "submit_preview": "📋 <b>Preview</b>\n\n📖 {title}\n📄 {file}\n🏷 {tags}",
        "submit_send": "✅ Submit",
        "submit_cancel": "❌ Cancel",
        "submit_sent": "✅ Sent!",
        "submit_cancelled": "❌ Cancelled.",
        "submit_stale": "Expired.",
        "submit_first_file": "Send a file first!",
        "admin_title": "👑 <b>Admin panel</b>",
        "admin_upload": "➕ Upload material",
        "admin_add_task": "🎯 Add task",
        "admin_cats": "📂 Category management",
        "admin_tags": "🏷 Tags",
        "admin_stats": "📊 Stats",
        "admin_subs": "📥 Submissions",
        "admin_pending": "🧩 Solutions",
        "admin_bcast": "📢 Broadcast",
        "admin_upload_ask": "📤 Send a file:",
        "admin_upload_title": "✏️ Title:",
        "admin_upload_desc": "📝 Description (or «skip»):",
        "admin_upload_tags": "🏷 Tags:",
        "admin_upload_diff": "🎯 Difficulty:",
        "admin_upload_cats": "📂 Sections:",
        "admin_upload_publish": "✅ Publish",
        "admin_upload_published": "✅ Published!\n📖 <b>{title}</b>\n📂 {cats}",
        "admin_upload_stale": "Expired.",
        "admin_upload_no_cat": "Pick at least one!",
        "admin_upload_cat_missing": "Not found.",
        "admin_upload_done_short": "Saved ✅",
        "admin_diff_easy": "🟢 Easy",
        "admin_diff_medium": "🟡 Medium",
        "admin_diff_hard": "🔴 Hard",
        "admin_diff_imo": "🔥 IMO",
        "admin_task_photo": "📸 Photo of the task (or «skip»):",
        "admin_task_text": "✍️ Task text (or «skip»):",
        "admin_task_solution": "💡 Solution (or «skip»):",
        "admin_task_date": "📅 Date: <code>YYYY-MM-DD</code>, «today» or «tomorrow»:",
        "admin_task_added": "✅ Task added for <b>{date}</b> (№ {num}).",
        "admin_task_bad_date": "⚠️ Wrong format.",
        "admin_task_photo_ask": "📸 Photo or «skip».",
        "admin_task_sol_ask": "Text/photo/document/«skip».",
        "admin_stats_title": "📊 <b>Stats</b>\n\n👥 Users: {users}\n📚 Files: {files}\n🏷 Tags: {tags}\n🎯 Tasks: {tasks}\n🧩 Pending: {pending}\n📥 Subs: {subs}\n\n<b>Top-5:</b>\n{top}",
        "admin_subs_empty": "📥 No submissions.",
        "admin_subs_title": "📥 <b>Submissions</b>\n",
        "admin_subs_pick_cat": "📂 Section:",
        "admin_subs_published": "✅ Published to «{cat}».",
        "admin_subs_user_notify": "✅ Your material «{title}» has been approved and added to «{cat}»!",
        "admin_subs_reject_notify": "❌ Your material submission «{title}» was rejected.",
        "admin_subs_accept": "✅ Accept",
        "admin_subs_reject": "❌ Reject",
        "admin_subs_rejected": "❌ Rejected.",
        "admin_subs_already": "Already processed.",
        "admin_subs_not_found": "Not found.",
        "admin_subs_already_pub": "Already published.",
        "admin_pending_title": "🧩 <b>Pending solutions</b>\n",
        "admin_pending_empty": "\nNo pending. 🎉",
        "admin_pending_shown": "\nShown: {n}",
        "admin_bcast_ask": "📢 Message to broadcast. /cancel to cancel.",
        "admin_bcast_running": "⏳ Broadcasting...",
        "admin_bcast_done": "✅ Done.\nDelivered: {sent} · Errors: {failed}",
        "admin_edit_title": "⚙️ <b>Editing</b>\n📖 {title}",
        "admin_edit_replace": "📄 Replace file",
        "admin_edit_rename": "✏️ Title",
        "admin_edit_desc": "📝 Description",
        "admin_edit_tags": "🏷 Tags",
        "admin_edit_back": "⬅️ Back",
        "admin_edit_ask_doc": "📄 New file:",
        "admin_edit_ask_title": "✏️ New title:",
        "admin_edit_ask_desc": "📝 New description (or «clear»):",
        "admin_edit_ask_tags": "🏷 Tags (or «clear»):",
        "admin_edit_doc_done": "✅ File replaced ({n}).",
        "admin_edit_title_done": "✅ Title updated ({n}).",
        "admin_edit_desc_done": "✅ Description updated ({n}).",
        "admin_edit_tags_done": "✅ Tags updated ({n}).",
        "admin_del_confirm": "⚠️ Delete «{title}»?",
        "admin_del_yes": "🗑 Yes",
        "admin_del_done": "🗑 Deleted: {n}.",
        "file_card_title": "📖 <b>{title}</b>",
        "file_card_section": "📂 Section: {cats}",
        "file_card_diff": "🎯 Level: {diff}",
        "file_card_tags": "🏷 {tags}",
        "file_card_summary": "\n📝 {summary}",
        "unknown_text": "🤖 Unknown command. Type /start.",
        "expect_file": "📤 Waiting for a file.",
        "expect_doc": "📄 Waiting for a document.",
        "only_admin": "Not available.",
        "choose_tags_n": "🏷 Pick tags ({n}):",
        "rating_line": "{medal} {name} — {score} pts · ✅ {solved} · 🔥 {streak} d.",
        "rating_medal_1": "🥇",
        "rating_medal_2": "🥈",
        "rating_medal_3": "🥉",
        "download_all_zip": "📦 Download all materials (ZIP)",
        "zip_preparing": "⏳ Preparing ZIP archive ({current}/{total})...",
        "zip_empty": "⚠️ No files in catalog.",
        "zip_ready": "📦 <b>MathAm Library Archive</b>\n📚 Files: {count}\n💾 Size: {size_mb:.1f} MB",
        "zip_part": "📦 <b>MathAm Library Archive (Part {part}/{total_parts})</b>\n📚 Files: {count}\n💾 Size: {size_mb:.1f} MB",
    },
}


def get_user_lang(user_id: int) -> str:
    uid_str = str(user_id)
    u = DATABASE.get("users", {}).get(uid_str, {})
    lang = u.get("language") or "ru"
    return lang if lang in TEXTS else "ru"


def t(user_id: int, key: str, **kwargs: Any) -> str:
    lang = get_user_lang(user_id)
    text = TEXTS.get(lang, TEXTS["ru"]).get(key) or TEXTS["ru"].get(key, key)
    try:
        return text.format(**kwargs)
    except Exception:
        return text


# ============================================================
# TRANSLATION & MATH PRESERVATION
# ============================================================

GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"

_MATH_PATTERNS = [
    re.compile(r"\$\$[\s\S]+?\$\$"),
    re.compile(r"\\\[[\s\S]+?\\\]"),
    re.compile(r"\\begin\{([a-zA-Z*]+)\}[\s\S]*?\\end\{\1\}"),
    re.compile(r"\\\([\s\S]+?\\\)"),
    re.compile(r"\$[^\$\n]+?\$"),
    re.compile(r"\\([a-zA-Z]+)(?:\[[^\]]*\])?(?:\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})+"),
    re.compile(r"\\[a-zA-Z]+"),
    re.compile(r"(?<![A-Za-zА-Яа-я0-9])[A-Za-z]\s*[\^_]\s*(?:\{[^{}]*\}|[A-Za-z0-9]+)"),
]

# Thread-safe LRU translation cache using OrderedDict
_translation_cache: "OrderedDict[Tuple[str, str], str]" = OrderedDict()
MAX_TRANSLATION_CACHE = 4000


def _protect_math(text: str) -> Tuple[str, List[str]]:
    protected: List[str] = []

    def repl(m: re.Match) -> str:
        protected.append(m.group(0))
        return f"_MTH_TOKEN_{len(protected) - 1}_"

    for pat in _MATH_PATTERNS:
        text = pat.sub(repl, text)
    return text, protected


def _restore_math(text: str, protected: List[str]) -> str:
    pattern = re.compile(
        r"(?:_MTH_TOKEN_|<<\s*M\s*|«\s*M\s*|MTH_TOKEN_)\s*(\d+)(?:\s*(?:>>|»|_))?",
        re.IGNORECASE,
    )

    def repl(m: re.Match) -> str:
        idx = int(m.group(1))
        if 0 <= idx < len(protected):
            return protected[idx]
        return m.group(0)

    for _ in range(5):
        new_text = pattern.sub(repl, text)
        if new_text == text:
            break
        text = new_text
    return text


def _chunk_text(text: str, max_chunk_len: int = 1200) -> List[str]:
    if len(text) <= max_chunk_len:
        return [text]
    lines = text.split("\n")
    chunks: List[str] = []
    curr: List[str] = []
    curr_len = 0
    for line in lines:
        if len(line) > max_chunk_len:
            words = line.split(" ")
            w_curr: List[str] = []
            w_len = 0
            for w in words:
                if w_len + len(w) + 1 > max_chunk_len and w_curr:
                    if curr:
                        chunks.append("\n".join(curr))
                        curr = []
                        curr_len = 0
                    chunks.append(" ".join(w_curr))
                    w_curr = [w]
                    w_len = len(w)
                else:
                    w_curr.append(w)
                    w_len += len(w) + 1
            if w_curr:
                curr.append(" ".join(w_curr))
                curr_len += len(curr[-1]) + 1
        elif curr_len + len(line) + 1 > max_chunk_len and curr:
            chunks.append("\n".join(curr))
            curr = [line]
            curr_len = len(line)
        else:
            curr.append(line)
            curr_len += len(line) + 1
    if curr:
        chunks.append("\n".join(curr))
    return chunks


async def _fetch_gt_segment(session: aiohttp.ClientSession, segment: str, target_lang: str) -> str:
    if not segment.strip():
        return segment
    try:
        params = {"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t", "q": segment}
        async with session.get(GOOGLE_TRANSLATE_URL, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            data = await resp.json()
            parts = [seg[0] for seg in data[0] if seg and seg[0]]
            return "".join(parts)
    except Exception:
        logger.warning("Google translate segment failed, returning raw segment")
        return segment


async def translate_text(text: str, target_lang: str) -> str:
    global HTTP_SESSION
    if not text or not text.strip() or target_lang not in ("ru", "en"):
        return text

    cache_key = (text, target_lang)
    if cache_key in _translation_cache:
        _translation_cache.move_to_end(cache_key)
        return _translation_cache[cache_key]

    working, protected = _protect_math(text)
    stripped = re.sub(r"(?:_MTH_TOKEN_|<<\s*M\s*|«\s*M\s*|MTH_TOKEN_)\s*(\d+)(?:\s*(?:>>|»|_))?", "", working)
    if not re.findall(r"[a-zA-Zа-яА-ЯёЁ]{2,}", stripped):
        return text

    chunks = _chunk_text(working, 1200)
    translated_chunks: List[str] = []

    session = HTTP_SESSION
    is_temp_session = False
    if session is None or session.closed:
        session = aiohttp.ClientSession()
        is_temp_session = True

    try:
        for ch in chunks:
            tr = await _fetch_gt_segment(session, ch, target_lang)
            translated_chunks.append(tr)
        raw_translated = "\n".join(translated_chunks)
    except Exception:
        logger.exception("Translation batch failed")
        raw_translated = working
    finally:
        if is_temp_session:
            await session.close()

    translated = _restore_math(raw_translated, protected)
    if len(_translation_cache) >= MAX_TRANSLATION_CACHE:
        _translation_cache.popitem(last=False)
    _translation_cache[cache_key] = translated
    return translated


def _needs_translation(text: str, target_lang: str) -> bool:
    if not text or not text.strip():
        return False
    has_cyrillic = bool(re.search(r"[\u0400-\u04FF]", text))
    has_latin = bool(re.search(r"[a-zA-Z]", text))
    if target_lang == "en":
        return has_cyrillic
    elif target_lang == "ru":
        return (not has_cyrillic) and has_latin
    return False


async def localize(text: str, user_id: int) -> str:
    if not text or not text.strip():
        return text
    lang = get_user_lang(user_id)
    if not _needs_translation(text, lang):
        return text
    return await translate_text(text, lang)


async def localize_list(items: List[str], user_id: int) -> List[str]:
    return [await localize(x, user_id) for x in items]


# ============================================================
# DEFAULT STATE & MIGRATION SCHEMA
# ============================================================

DEFAULT_TAGS = [
    "#геометрия", "#планиметрия", "#стереометрия", "#алгебра", "#неравенства",
    "#уравнения", "#функции", "#теориячисел", "#делимость", "#комбинаторика",
    "#графы", "#инварианты", "#матанализ", "#олимпиаднаяматематика",
    "#начинающим", "#всерос", "#подготовка",
]

DEFAULT_STATE = {
    "categories": {
        "geometry": {"title": "📐 Геометрия", "files": []},
        "number_theory": {"title": "🔢 Теория чисел", "files": []},
        "algebra": {"title": "🧮 Алгебра", "files": []},
        "combinatorics": {"title": "🧩 Комбинаторика", "files": []},
        "higher_math": {"title": "🎓 Матанализ и высшая математика", "files": []},
        "titu": {"title": "📘 Titu Andreescu", "files": []},
    },
    "links": {
        "useful_links": {"title": "🔗 Полезные сайты и базы задач", "items": [
            {"title": "AoPS (Art of Problem Solving)", "url": "https://artofproblemsolving.com"},
            {"title": "Imomath (IMO Training)", "url": "https://imomath.com"},
            {"title": "МЦНМО", "url": "https://mccme.ru"},
        ]},
        "useful_videos": {"title": "🎥 Полезные YouTube видео", "items": [
            {"title": "3Blue1Brown", "url": "https://www.youtube.com/@3blue1brown"},
            {"title": "Numberphile", "url": "https://www.youtube.com/@numberphile"},
            {"title": "Mathologer", "url": "https://www.youtube.com/@Mathologer"},
            {"title": "Лекторий ФПМИ МФТИ", "url": "https://www.youtube.com/@mipt_lectures"},
            {"title": "Борис Трушин", "url": "https://www.youtube.com/@TrushinBV"},
            {"title": "Stand-up Maths", "url": "https://www.youtube.com/@standupmaths"},
            {"title": "Welch Labs", "url": "https://www.youtube.com/@WelchLabsVideo"},
        ]},
    },
    "must_read": {"title": "⭐ Must-read", "files": []},
    "daily_tasks": {},
    "tags": list(DEFAULT_TAGS),
    "users": {},
}


# ============================================================
# MIDDLEWARES
# ============================================================

class UserActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and not user.is_bot:
            try:
                await track_user_activity(user.id, user.username or "", user.first_name or "")
            except Exception:
                logger.exception("UserActivityMiddleware error")
        return await handler(event, data)


class SimpleRateLimitMiddleware(BaseMiddleware):
    def __init__(self, per_minute: int = 30):
        self.per_minute = per_minute
        self.buckets: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and not is_admin(user.id):
            now = datetime.now(timezone.utc)
            minute = now.strftime("%Y%m%d%H%M")
            key = f"{user.id}:{minute}"

            async with self._lock:
                cnt = self.buckets.get(key, 0)
                if cnt >= self.per_minute:
                    if isinstance(event, types.CallbackQuery):
                        try:
                            await event.answer("⏱ Слишком часто. Подождите.", show_alert=False)
                        except Exception:
                            pass
                    return
                self.buckets[key] = cnt + 1

                if len(self.buckets) > 3000:
                    cutoff = (now - timedelta(minutes=3)).strftime("%Y%m%d%H%M")
                    self.buckets = {k: v for k, v in self.buckets.items() if k.split(":")[1] >= cutoff}

        return await handler(event, data)


# ============================================================
# HELPERS
# ============================================================

def get_yerevan_date() -> str:
    return datetime.now(YEREVAN_TZ).strftime("%Y-%m-%d")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_file_by_uid(uid: str) -> dict:
    for cat_data in DATABASE.get("categories", {}).values():
        for f in cat_data.get("files", []):
            if f.get("file_unique_id") == uid:
                return f
    return {}


def get_file_categories(uid: str) -> List[str]:
    cats = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        for f in cat_data.get("files", []):
            if f.get("file_unique_id") == uid:
                cats.append(cat_data.get("title", cat_key))
                break
    return cats


def get_catalog_files_list() -> List[dict]:
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
                    "caption": f.get("caption", "—"),
                    "category": cat_data.get("title", cat_key),
                    "categories": [cat_data.get("title", cat_key)],
                    "summary": f.get("summary", ""),
                    "tags": list(f.get("tags", [])),
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
    return list(files_dict.values())


def get_similar_files(uid: str, limit: int = 5) -> List[dict]:
    current = get_file_by_uid(uid)
    if not current:
        return []
    curr_tags = set(t.lower() for t in current.get("tags", []))
    all_files = get_catalog_files_list()
    scored = []
    for f in all_files:
        if f["uid"] == uid:
            continue
        common = len(curr_tags & set(t.lower() for t in f.get("tags", [])))
        if common > 0:
            scored.append((common, f))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:limit]]


def _split_text(text: str, limit: int = TG_TEXT_LIMIT) -> List[str]:
    parts = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        split = remaining.rfind("\n", 0, limit)
        if split < limit // 2:
            split = limit
        parts.append(remaining[:split])
        remaining = remaining[split:].lstrip("\n")
    return parts


async def safe_send_or_edit(
    target: Union[types.Message, types.CallbackQuery],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    photo_id: Optional[str] = None,
    parse_mode: str = ParseMode.HTML,
):
    is_message = isinstance(target, types.Message)
    chat_id = target.chat.id if is_message else target.message.chat.id

    if photo_id:
        if len(text) <= 1024:
            if is_message:
                return await target.answer_photo(photo=photo_id, caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
            try:
                await target.message.delete()
            except Exception:
                pass
            return await target.message.answer_photo(photo=photo_id, caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            if is_message:
                await target.answer_photo(photo=photo_id, caption="📄")
            else:
                try:
                    await target.message.delete()
                except Exception:
                    pass
                await target.message.answer_photo(photo=photo_id, caption="📄")
            parts = _split_text(text, TG_TEXT_LIMIT)
            for i, part in enumerate(parts):
                mk = reply_markup if i == len(parts) - 1 else None
                await bot.send_message(chat_id, part, parse_mode=parse_mode, reply_markup=mk)
            return None

    if len(text) <= TG_TEXT_LIMIT:
        if is_message:
            return await target.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
        msg = target.message
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
    else:
        parts = _split_text(text, TG_TEXT_LIMIT)
        first, rest = parts[0], parts[1:]
        if is_message:
            await target.answer(first, parse_mode=parse_mode)
        else:
            msg = target.message
            if msg.photo or msg.document:
                try:
                    await msg.delete()
                except Exception:
                    pass
                await msg.answer(first, parse_mode=parse_mode)
            else:
                try:
                    await msg.edit_text(first, parse_mode=parse_mode)
                except Exception:
                    await msg.answer(first, parse_mode=parse_mode)
        for part in rest:
            await bot.send_message(chat_id, part, parse_mode=parse_mode)
        if reply_markup:
            return await bot.send_message(chat_id, "⬇️", reply_markup=reply_markup)
        return None


async def track_user_activity(user_id: int, username: str = "", first_name: str = ""):
    uid_str = str(user_id)
    today = get_yerevan_date()
    yesterday = (datetime.now(YEREVAN_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    DATABASE.setdefault("users", {})
    if uid_str not in DATABASE["users"]:
        user_data = {
            "username": username,
            "first_name": first_name,
            "nickname": "",
            "language": "",
            "created_at": datetime.now(YEREVAN_TZ).isoformat(),
            "streak": 1,
            "last_active": today,
            "score": 0,
            "favorites": [],
            "notes": {},
        }
        DATABASE["users"][uid_str] = user_data
        await db_collection.update_one(
            {"_id": DB_DOC_ID},
            {"$set": {f"data.users.{uid_str}": user_data}},
            upsert=True,
        )
        return

    user = DATABASE["users"][uid_str]
    updates = {}
    if username and user.get("username") != username:
        user["username"] = username
        updates[f"data.users.{uid_str}.username"] = username
    if first_name and user.get("first_name") != first_name:
        user["first_name"] = first_name
        updates[f"data.users.{uid_str}.first_name"] = first_name

    user.setdefault("favorites", [])
    user.setdefault("nickname", "")
    user.setdefault("language", "")
    user.setdefault("notes", {})

    if user.get("last_active") != today:
        if user.get("last_active") == yesterday:
            user["streak"] = user.get("streak", 0) + 1
        else:
            user["streak"] = 1
        user["last_active"] = today
        updates[f"data.users.{uid_str}.streak"] = user["streak"]
        updates[f"data.users.{uid_str}.last_active"] = today

    if updates:
        await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": updates})


async def award_points(user_id: int, points: int):
    uid_str = str(user_id)
    if uid_str not in DATABASE.get("users", {}):
        await track_user_activity(user_id, "", "")
    if uid_str not in DATABASE.get("users", {}):
        return
    current_score = DATABASE["users"][uid_str].get("score", 0) + points
    DATABASE["users"][uid_str]["score"] = max(0, current_score)
    await db_collection.update_one(
        {"_id": DB_DOC_ID},
        {"$set": {f"data.users.{uid_str}.score": DATABASE["users"][uid_str]["score"]}},
    )


def get_nickname(uid_str: str) -> str:
    u = DATABASE.get("users", {}).get(uid_str, {})
    return u.get("nickname") or u.get("username") or u.get("first_name") or f"id{uid_str}"


def user_display(uid_str: str) -> str:
    u = DATABASE.get("users", {}).get(uid_str, {})
    nick = u.get("nickname") or u.get("username") or f"id{uid_str}"
    tg = u.get("first_name") or ""
    uname = u.get("username") or ""
    parts = []
    if tg:
        parts.append(html.escape(tg))
    if uname:
        parts.append("@" + html.escape(uname))
    suffix = f" <i>({', '.join(parts)})</i>" if parts else ""
    return f"{html.escape(nick)}{suffix}"


def sol_display(s: dict, uid_str: str) -> str:
    u = DATABASE.get("users", {}).get(uid_str, {})
    nick = s.get("nickname") or u.get("nickname") or f"id{uid_str}"
    tg = s.get("first_name") or u.get("first_name") or ""
    uname = s.get("username") or u.get("username") or ""
    parts = []
    if tg:
        parts.append(html.escape(tg))
    if uname:
        parts.append("@" + html.escape(uname))
    suffix = f" <i>({', '.join(parts)})</i>" if parts else ""
    return f"{html.escape(nick)}{suffix}"


def sol_button_name(s: dict, uid_str: str) -> str:
    u = DATABASE.get("users", {}).get(uid_str, {})
    return s.get("nickname") or u.get("nickname") or f"id{uid_str}"


def get_task(date_str: str, idx: int) -> dict:
    group = DATABASE.get("daily_tasks", {}).get(date_str, {})
    tasks = group.get("tasks", [])
    if 0 <= idx < len(tasks):
        return tasks[idx]
    return {}


def get_dates_sorted() -> List[str]:
    return sorted(DATABASE.get("daily_tasks", {}).keys(), reverse=True)


def count_solved(uid_str: str) -> int:
    n = 0
    for group in DATABASE.get("daily_tasks", {}).values():
        for task in group.get("tasks", []):
            s = (task.get("user_solutions") or {}).get(uid_str)
            if s and s.get("status") == "approved" and (s.get("grade") or 0) > 0:
                n += 1
    return n


def update_file_field(uid: str, field: str, value: Any) -> int:
    count = 0
    for cat_data in DATABASE.get("categories", {}).values():
        for f in cat_data.get("files", []):
            if f.get("file_unique_id") == uid:
                f[field] = value
                count += 1
    return count


def rename_tag_everywhere(old_tag: str, new_tag: str) -> int:
    tags = DATABASE.setdefault("tags", [])
    if old_tag in tags:
        tags[tags.index(old_tag)] = new_tag
    count = 0
    for cat_data in DATABASE.get("categories", {}).values():
        for f in cat_data.get("files", []):
            file_tags = f.get("tags", [])
            if old_tag in file_tags:
                f["tags"] = [new_tag if x == old_tag else x for x in file_tags]
                count += 1
    for group in DATABASE.get("daily_tasks", {}).values():
        for task in group.get("tasks", []):
            task_tags = task.get("tags", [])
            if old_tag in task_tags:
                task["tags"] = [new_tag if x == old_tag else x for x in task_tags]
    return count


def normalize_tags_input(raw: str) -> List[str]:
    tags: List[str] = []
    for part in re.split(r"[,;\n]", raw):
        tag = re.sub(r"[^#\wа-яА-ЯёЁ-]", "", part.strip().replace(" ", "-"))
        if tag and not tag.startswith("#"):
            tag = "#" + tag
        if tag and 2 <= len(tag) <= 40 and tag.lower() not in {x.lower() for x in tags}:
            tags.append(tag)
    return tags[:10]


# ============================================================
# DATABASE LOAD / SAVE & CRON RESTORE
# ============================================================

async def load_db() -> Dict[str, Any]:
    doc = await db_collection.find_one({"_id": DB_DOC_ID})
    if doc is None:
        data = copy.deepcopy(DEFAULT_STATE)
        await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": data}}, upsert=True)
        return data

    data = doc.get("data", copy.deepcopy(DEFAULT_STATE))
    for key, value in DEFAULT_STATE.items():
        if key not in data:
            data[key] = copy.deepcopy(value)

    for cat_key, default_cat in DEFAULT_STATE["categories"].items():
        if cat_key not in data["categories"]:
            data["categories"][cat_key] = copy.deepcopy(default_cat)
        cat_data = data["categories"][cat_key]
        cat_data.setdefault("title", default_cat["title"])
        cat_data.setdefault("files", [])
        for f in cat_data["files"]:
            f.setdefault("file_unique_id", str(uuid.uuid4()))
            f.setdefault("file_id", None)
            f.setdefault("caption", "—")
            f.setdefault("summary", "")
            f.setdefault("tags", [])
            f.setdefault("difficulty", "medium")
            f.setdefault("must_read", False)
            f.setdefault("added_at", get_yerevan_date())
            f.setdefault("likes", [])
            f.setdefault("comments", [])

    for sec_key, default_sec in DEFAULT_STATE["links"].items():
        if sec_key not in data["links"]:
            data["links"][sec_key] = copy.deepcopy(default_sec)
        data["links"][sec_key].setdefault("title", default_sec["title"])
        data["links"][sec_key].setdefault("items", [])

    data.setdefault("links", {})["useful_videos"] = copy.deepcopy(DEFAULT_STATE["links"]["useful_videos"])

    if not data.get("tags"):
        data["tags"] = list(DEFAULT_TAGS)

    for uid, user in data["users"].items():
        user.setdefault("username", "")
        user.setdefault("first_name", "")
        user.setdefault("nickname", "")
        user.setdefault("language", "")
        user.setdefault("created_at", datetime.now(YEREVAN_TZ).isoformat())
        user.setdefault("streak", 1)
        user.setdefault("last_active", get_yerevan_date())
        user.setdefault("score", 0)
        user.setdefault("favorites", [])
        user.setdefault("notes", {})

    for date_str, group in list(data["daily_tasks"].items()):
        if isinstance(group, list) or (isinstance(group, dict) and "tasks" not in group):
            group = {"tasks": [group] if isinstance(group, dict) else group}
            data["daily_tasks"][date_str] = group
        group.setdefault("tasks", [])
        for i, task in enumerate(group["tasks"]):
            task.setdefault("task_id", uuid.uuid4().hex[:10])
            task.setdefault("text", "")
            task.setdefault("photo_file_id", None)
            task.setdefault("solution", "")
            task.setdefault("solution_photo_file_id", None)
            task.setdefault("solution_document_file_id", None)
            task.setdefault("difficulty", "medium")
            task.setdefault("tags", [])
            task.setdefault("status", "published")
            task.setdefault("source", "admin")
            task.setdefault("created_at", get_yerevan_date())
            task.setdefault("user_solutions", {})
            task.setdefault("numeric_answer", None)
            task["number"] = i + 1

    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": data}}, upsert=True)
    return data


async def save_db(db_data: dict):
    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": db_data}}, upsert=True)


async def save_submission(sub_id: str, data: dict):
    await submissions_collection.update_one({"_id": sub_id}, {"$set": data}, upsert=True)


async def get_submission(sub_id: str) -> dict:
    doc = await submissions_collection.find_one({"_id": sub_id})
    return doc if doc else {}


async def restore_scheduled_tasks():
    """Restores any pending scheduled tasks after server restart."""
    now = datetime.now(YEREVAN_TZ)
    daily = DATABASE.get("daily_tasks", {})
    for date_str, group in daily.items():
        for idx, task in enumerate(group.get("tasks", [])):
            if task.get("status") == "scheduled" and task.get("publish_at"):
                try:
                    sched_time = datetime.fromisoformat(task["publish_at"])
                    if sched_time <= now:
                        logger.info("Executing overdue task for %s #%s", date_str, idx + 1)
                        asyncio.create_task(_schedule_publish(date_str, idx, now))
                    else:
                        logger.info("Restoring future schedule for %s #%s at %s", date_str, idx + 1, sched_time)
                        asyncio.create_task(_schedule_publish(date_str, idx, sched_time))
                except Exception as e:
                    logger.warning("Could not parse publish_at for task %s #%s: %s", date_str, idx, e)


# ============================================================
# FSM STATES
# ============================================================

class Registration(StatesGroup):
    choosing_language = State()
    waiting_for_nickname = State()

class ChangeNicknameState(StatesGroup):
    waiting_new_name = State()

class TagSearch(StatesGroup):
    selecting = State()

class TaskTagSearch(StatesGroup):
    selecting = State()

class AdminUpload(StatesGroup):
    waiting_document = State()
    waiting_title = State()
    waiting_description = State()
    choosing_tags = State()
    choosing_difficulty = State()
    choosing_categories = State()

class AdminAddCategory(StatesGroup):
    waiting_for_title = State()

class UserSubmit(StatesGroup):
    waiting_file = State()
    waiting_title = State()
    choosing_tags = State()

class AddTag(StatesGroup):
    waiting_for_text = State()

class RenameTag(StatesGroup):
    choosing = State()
    waiting_for_new_name = State()

class AddLink(StatesGroup):
    waiting_for_text = State()

class EditFile(StatesGroup):
    waiting_for_document = State()
    waiting_for_title = State()
    waiting_for_desc = State()
    waiting_for_tags = State()

class TaskOfDayAdmin(StatesGroup):
    waiting_for_photo = State()
    waiting_for_task_text = State()
    waiting_for_solution = State()
    waiting_numeric_answer = State()
    choosing_difficulty = State()
    choosing_tags = State()
    waiting_for_date = State()

class UserTaskSolution(StatesGroup):
    waiting_for_solution = State()

class UserNumericAnswer(StatesGroup):
    waiting = State()

class FileComment(StatesGroup):
    waiting = State()

class FileNote(StatesGroup):
    waiting = State()

class BroadcastAdmin(StatesGroup):
    waiting_for_message = State()

class TaskEdit(StatesGroup):
    text = State()
    photo = State()
    solution = State()

class TaskSchedule(StatesGroup):
    waiting_datetime = State()


# ============================================================
# UI KEYBOARDS
# ============================================================

def get_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = [
        [InlineKeyboardButton(text=t(user_id, "menu_catalog"), callback_data="menu:catalog"),
         InlineKeyboardButton(text=t(user_id, "menu_search"), callback_data="search:main")],
        [InlineKeyboardButton(text=t(user_id, "menu_task"), callback_data="task:show"),
         InlineKeyboardButton(text=t(user_id, "menu_archive"), callback_data="task:archive")],
        [InlineKeyboardButton(text=t(user_id, "menu_task_tags"), callback_data="tasktagsearch:main"),
         InlineKeyboardButton(text=t(user_id, "menu_mustread"), callback_data="mustread:main")],
        [InlineKeyboardButton(text=t(user_id, "menu_fav"), callback_data="favorites:main"),
         InlineKeyboardButton(text=t(user_id, "menu_rating"), callback_data="rating:main")],
        [InlineKeyboardButton(text=t(user_id, "menu_random"), callback_data="challenge:main"),
         InlineKeyboardButton(text=t(user_id, "menu_links"), callback_data="links:main")],
        [InlineKeyboardButton(text=t(user_id, "menu_submit"), callback_data="submit:start"),
         InlineKeyboardButton(text=t(user_id, "menu_name"), callback_data="user:chname")],
        [InlineKeyboardButton(text=t(user_id, "menu_lang"), callback_data="lang:menu")],
    ]
    if is_admin(user_id):
        builder.append([InlineKeyboardButton(text=t(user_id, "menu_admin"), callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


async def get_catalog_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        count = len(cat_data.get("files", []))
        title = await localize(cat_data.get("title", cat_key), user_id)
        builder.append([InlineKeyboardButton(text=f"{title} ({count})", callback_data=f"cat:{cat_key}")])
    builder.append([InlineKeyboardButton(text=t(user_id, "download_all_zip"), callback_data="catalog:zip_all")])
    if is_admin(user_id):
        builder.append([InlineKeyboardButton(text="➕ Добавить раздел", callback_data="admin:add_cat")])
    builder.append([InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def get_file_view_keyboard(uid: str, user_id: int) -> InlineKeyboardMarkup:
    uid_str = str(user_id)
    user_favs = DATABASE.get("users", {}).get(uid_str, {}).get("favorites", [])
    is_fav = uid in user_favs
    fav_text = t(user_id, "remove_fav") if is_fav else t(user_id, "add_fav")

    f = get_file_by_uid(uid) or {}
    likes = f.get("likes") or []
    comments = f.get("comments") or []
    user_note = (DATABASE.get("users", {}).get(uid_str, {}).get("notes") or {}).get(uid)
    is_liked = uid_str in likes
    like_emoji = "💔" if is_liked else "👍"

    rows = [
        [InlineKeyboardButton(text=t(user_id, "get_file"), callback_data=f"file:get:{uid}")],
        [InlineKeyboardButton(text=fav_text, callback_data=f"fav:toggle:{uid}")],
        [InlineKeyboardButton(text=f"{like_emoji} {len(likes)}", callback_data=f"file:like:{uid}"),
         InlineKeyboardButton(text=f"💬 {len(comments)}", callback_data=f"file:comments:{uid}")],
        [InlineKeyboardButton(text=f"📝 Заметка{' ✓' if user_note else ''}", callback_data=f"file:note:{uid}"),
         InlineKeyboardButton(text="🔍 Похожие", callback_data=f"file:similar:{uid}")],
        [InlineKeyboardButton(text="🔗 Поделиться", callback_data=f"file:share:{uid}")],
    ]
    if is_admin(user_id):
        rows.append([
            InlineKeyboardButton(text=t(user_id, "edit"), callback_data=f"admin:edit_file:{uid}"),
            InlineKeyboardButton(text=t(user_id, "mustread_btn"), callback_data=f"mustread:toggle:{uid}"),
        ])
        rows.append([InlineKeyboardButton(text=t(user_id, "delete"), callback_data=f"admin:del_file:{uid}")])
    rows.append([InlineKeyboardButton(text=t(user_id, "back_catalog"), callback_data="menu:catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_task_keyboard(date_str: str, task_idx: int, user_id: int) -> InlineKeyboardMarkup:
    task = get_task(date_str, task_idx)
    if not task:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")]])
    uid_str = str(user_id)
    sol = (task.get("user_solutions") or {}).get(uid_str)
    rows = []
    if sol is None or sol.get("status") == "rejected":
        rows.append([InlineKeyboardButton(text=t(user_id, "task_send_solution"), callback_data=f"task:solve:{date_str}:{task_idx}")])
        if task.get("numeric_answer"):
            rows.append([InlineKeyboardButton(text="🔢 Ввести ответ", callback_data=f"task:numans:{date_str}:{task_idx}")])
    elif sol.get("status") == "pending":
        rows.append([InlineKeyboardButton(text=t(user_id, "task_solution_pending"), callback_data="noop")])
    else:
        grade = sol.get("grade")
        label = t(user_id, "task_solution_ok", grade=grade) if grade else t(user_id, "task_solution_ok_no_grade")
        rows.append([InlineKeyboardButton(text=label, callback_data="noop")])

    if task.get("solution") or task.get("solution_photo_file_id") or task.get("solution_document_file_id"):
        rows.append([InlineKeyboardButton(text=t(user_id, "task_author_solution"), callback_data=f"task:show_sol:{date_str}:{task_idx}")])

    approved = [s for s in (task.get("user_solutions") or {}).values() if s.get("status") == "approved"]
    rows.append([InlineKeyboardButton(text=t(user_id, "task_solutions", n=len(approved)), callback_data=f"task:sols:{date_str}:{task_idx}")])

    if is_admin(user_id):
        rows.append([InlineKeyboardButton(text=t(user_id, "task_bcast"), callback_data=f"task:bcast:{date_str}:{task_idx}")])
        rows.append([
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"task:edit:{date_str}:{task_idx}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"task:del:{date_str}:{task_idx}"),
        ])

    tasks_total = len(DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", []))
    nav = []
    if task_idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"task:view:{date_str}:{task_idx - 1}"))
    if task_idx < tasks_total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"task:view:{date_str}:{task_idx + 1}"))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(text="🗄", callback_data="task:archive"),
        InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def get_tag_toggle_keyboard(selected: list, prefix: str, done_cb: str, user_id: int, skip_text: str = None, skip_cb: str = None):
    tags = DATABASE.get("tags", [])
    rows, row = [], []
    for i, tag in enumerate(tags):
        mark = "✅ " if tag in selected else ""
        label = await localize(tag, user_id)
        row.append(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"{prefix}:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    done_row = [InlineKeyboardButton(text="💾 OK", callback_data=done_cb)]
    if skip_text and skip_cb:
        done_row.append(InlineKeyboardButton(text=skip_text, callback_data=skip_cb))
    rows.append(done_row)
    rows.append([InlineKeyboardButton(text="❌", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def get_category_toggle_keyboard(selected: list, user_id: int, publish_cb: str = "upl:publish"):
    rows = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        mark = "✅ " if cat_key in selected else "▫️ "
        title = await localize(cat_data.get("title", cat_key), user_id)
        rows.append([InlineKeyboardButton(text=f"{mark}{title}", callback_data=f"upl:cat:{cat_key}")])
    rows.append([InlineKeyboardButton(text=t(user_id, "admin_upload_publish"), callback_data=publish_cb)])
    rows.append([InlineKeyboardButton(text="❌", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def get_links_keyboard(user_id: int):
    builder = []
    ordered_keys = ["useful_links", "useful_videos"]
    for sec_key in ordered_keys:
        if sec_key in DATABASE.get("links", {}):
            sec_data = DATABASE["links"][sec_key]
            title = await localize(sec_data.get("title", sec_key), user_id)
            builder.append([InlineKeyboardButton(text=title, callback_data=f"links:sec:{sec_key}")])
    for sec_key, sec_data in DATABASE.get("links", {}).items():
        if sec_key in ordered_keys:
            continue
        title = await localize(sec_data.get("title", sec_key), user_id)
        builder.append([InlineKeyboardButton(text=title, callback_data=f"links:sec:{sec_key}")])
    builder.append([InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def get_links_section_keyboard(sec_key: str, user_id: int):
    sec = DATABASE.get("links", {}).get(sec_key, {})
    items = [it for it in sec.get("items", []) if (it.get("url") or "").strip()]
    builder = []
    for idx, item in enumerate(items):
        url = (item.get("url") or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            url = f"https://{url}"
        title = item.get("title") or f"Link #{idx + 1}"
        icon = "▶️ " if sec_key == "useful_videos" else "🔗 "
        builder.append([InlineKeyboardButton(text=f"{icon}{title}", url=url)])
        if is_admin(user_id):
            builder.append([InlineKeyboardButton(text=t(user_id, "links_del", n=idx + 1), callback_data=f"links:del:{sec_key}:{idx}")])
    if is_admin(user_id):
        builder.append([InlineKeyboardButton(text=t(user_id, "links_add"), callback_data=f"links:add:{sec_key}")])
    builder.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="links:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def get_admin_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(user_id, "admin_upload"), callback_data="admin:upload")],
        [InlineKeyboardButton(text=t(user_id, "admin_add_task"), callback_data="admin:add_task")],
        [InlineKeyboardButton(text=t(user_id, "admin_cats"), callback_data="admin:cats")],
        [InlineKeyboardButton(text=t(user_id, "admin_tags"), callback_data="admin:tags")],
        [InlineKeyboardButton(text=t(user_id, "admin_stats"), callback_data="admin:stats")],
        [InlineKeyboardButton(text="📊 Экспорт CSV", callback_data="admin:stats_csv")],
        [InlineKeyboardButton(text="📦 Экспорт всех PDF (ZIP)", callback_data="catalog:zip_all")],
        [InlineKeyboardButton(text=t(user_id, "admin_subs"), callback_data="admin:submissions")],
        [InlineKeyboardButton(text=t(user_id, "admin_pending"), callback_data="admin:pending_sols")],
        [InlineKeyboardButton(text=t(user_id, "admin_bcast"), callback_data="admin:broadcast")],
        [InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")],
    ])


def get_language_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:set:ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:set:en")],
        [InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")],
    ])


def sanitize_filename(name: str) -> str:
    clean = re.sub(r'[\\/*?:"<>|]', "_", name).strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean[:60] if clean else "material"


# ============================================================
# ARCHIVE DOWNLOAD (STREAMING BUFFER SAFE)
# ============================================================

async def create_and_send_zip(chat_id: int, user_id: int, files_to_download: list, archive_title: str):
    if not files_to_download:
        await bot.send_message(chat_id, t(user_id, "zip_empty"))
        return

    total = len(files_to_download)
    status_msg = await bot.send_message(chat_id, t(user_id, "zip_preparing", current=0, total=total))

    sem = asyncio.Semaphore(4)
    downloaded_files: List[Tuple[str, bytes]] = []
    completed_count = 0
    lock = asyncio.Lock()

    async def _fetch_file(item: dict):
        nonlocal completed_count
        file_id = item.get("file_id")
        if not file_id:
            return
        async with sem:
            try:
                tg_file = await bot.get_file(file_id)
                buf = io.BytesIO()
                await bot.download_file(tg_file.file_path, destination=buf)
                content = buf.getvalue()
                if content:
                    folder = sanitize_filename(item.get("category", "General"))
                    fname = sanitize_filename(item.get("filename", "material"))
                    if not fname.lower().endswith(".pdf"):
                        fname += ".pdf"
                    async with lock:
                        downloaded_files.append((f"{folder}/{fname}", content))
                        completed_count += 1
                        if completed_count % 5 == 0 or completed_count == total:
                            try:
                                await status_msg.edit_text(t(user_id, "zip_preparing", current=completed_count, total=total))
                            except Exception:
                                pass
            except Exception as e:
                logger.warning("Failed to download file %s for zip: %s", file_id, e)
                async with lock:
                    completed_count += 1

    await asyncio.gather(*[_fetch_file(item) for item in files_to_download])

    if not downloaded_files:
        try:
            await status_msg.edit_text(t(user_id, "zip_empty"))
        except Exception:
            await bot.send_message(chat_id, t(user_id, "zip_empty"))
        return

    used_names = set()
    unique_files = []
    for path, content in downloaded_files:
        cand = path
        counter = 1
        folder, fname = path.split("/", 1) if "/" in path else ("General", path)
        base_name, ext = os.path.splitext(fname)
        while cand.lower() in used_names:
            cand = f"{folder}/{base_name}_{counter}{ext}"
            counter += 1
        used_names.add(cand.lower())
        unique_files.append((cand, content))

    MAX_VOLUME_BYTES = 45 * 1024 * 1024
    volumes = []
    curr_vol = []
    curr_size = 0
    for path, content in unique_files:
        if curr_size + len(content) > MAX_VOLUME_BYTES and curr_vol:
            volumes.append(curr_vol)
            curr_vol = [(path, content)]
            curr_size = len(content)
        else:
            curr_vol.append((path, content))
            curr_size += len(content)
    if curr_vol:
        volumes.append(curr_vol)

    total_vols = len(volumes)
    date_str = datetime.now().strftime("%Y%m%d")

    for part_idx, vol in enumerate(volumes, 1):
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path, content in vol:
                zf.writestr(path, content)
        zip_bytes = zip_buf.getvalue()
        size_mb = len(zip_bytes) / (1024 * 1024)

        safe_title = sanitize_filename(archive_title)
        if total_vols > 1:
            fname = f"MathAm_{safe_title}_part{part_idx}_of_{total_vols}_{date_str}.zip"
            caption = t(user_id, "zip_part", part=part_idx, total_parts=total_vols, count=len(vol), size_mb=size_mb)
        else:
            fname = f"MathAm_{safe_title}_{date_str}.zip"
            caption = t(user_id, "zip_ready", count=len(vol), size_mb=size_mb)

        doc = BufferedInputFile(zip_bytes, filename=fname)
        await bot.send_document(chat_id, document=doc, caption=caption, parse_mode=ParseMode.HTML)

    try:
        await status_msg.delete()
    except Exception:
        pass


# ============================================================
# CARD RENDERERS
# ============================================================

async def format_file_info(f: dict, cats: list, user_id: int) -> str:
    title = f.get("caption") or "—"
    summary = (f.get("summary") or "").strip()
    title = await localize(title, user_id)
    if summary:
        summary = await localize(summary, user_id)
    cats_tr = await localize_list(cats, user_id)
    lines = [t(user_id, "file_card_title", title=html.escape(title))]
    if cats_tr:
        lines.append(t(user_id, "file_card_section", cats=html.escape(" · ".join(cats_tr))))
    diff_key = f"admin_diff_{f.get('difficulty') or 'medium'}"
    lines.append(t(user_id, "file_card_diff", diff=t(user_id, diff_key)))
    tags = " ".join(f.get("tags") or [])
    if tags:
        tags_tr = await localize(tags, user_id)
        lines.append(t(user_id, "file_card_tags", tags=html.escape(tags_tr)))
    if summary:
        lines.append(t(user_id, "file_card_summary", summary=html.escape(summary)))
    uid_str = str(user_id)
    note = (DATABASE.get("users", {}).get(uid_str, {}).get("notes") or {}).get(f.get("file_unique_id"))
    if note:
        lines.append(f"\n📝 <b>Ваша заметка:</b>\n<i>{html.escape(note[:300])}</i>")
    likes = f.get("likes") or []
    comments = f.get("comments") or []
    if likes or comments:
        lines.append(f"\n👍 {len(likes)} · 💬 {len(comments)}")
    return "\n".join(lines)


async def show_file_card(target: Union[types.Message, types.CallbackQuery], uid: str, user_id: int) -> bool:
    f = get_file_by_uid(uid)
    if not f:
        return False
    text = await format_file_info(f, get_file_categories(uid), user_id)
    await safe_send_or_edit(target, text, reply_markup=get_file_view_keyboard(uid, user_id))
    return True


async def show_task(target: Union[types.Message, types.CallbackQuery], date_str: str, task_idx: int, user_id: int = None):
    if user_id is None:
        user_id = target.from_user.id
    task = get_task(date_str, task_idx)
    total = len(DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", []))
    if not task:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")]])
        await safe_send_or_edit(target, t(user_id, "task_missing"), reply_markup=markup)
        return
    task_text = (task.get("text") or "").strip() or t(user_id, "task_text_on_photo")
    task_text = await localize(task_text, user_id)
    text = t(user_id, "task_of_day", date=date_str, num=task_idx + 1, total=total, text=html.escape(task_text))
    if task.get("tags"):
        text += "\n\n🏷 " + " ".join(html.escape(x) for x in task["tags"])
    await safe_send_or_edit(
        target,
        text,
        reply_markup=get_task_keyboard(date_str, task_idx, user_id),
        photo_id=task.get("photo_file_id"),
    )


async def render_mustread(target, user_id: int):
    files = [f for f in get_catalog_files_list() if f.get("must_read")]
    builder = []
    if files:
        for f in files:
            caption = await localize(f["caption"], user_id)
            builder.append([InlineKeyboardButton(text=f"⭐ {caption[:55]}", callback_data=f"file:view:{f['uid']}")])
            if is_admin(user_id):
                builder.append([InlineKeyboardButton(text=t(user_id, "mustread_remove_btn"), callback_data=f"mustread:toggle:{f['uid']}")])
        text = t(user_id, "mustread_title")
    else:
        text = t(user_id, "mustread_empty")
    builder.append([InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")])
    await safe_send_or_edit(target, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))


async def show_links_section(target, sec_key: str, user_id: int):
    sec = DATABASE.get("links", {}).get(sec_key, {})
    items = [it for it in sec.get("items", []) if (it.get("url") or "").strip()]
    title_tr = await localize(sec.get("title", sec_key), user_id)
    title = html.escape(title_tr)
    if items:
        lines = [f"🔗 <b>{title}</b>\n"]
        for i, item in enumerate(items, 1):
            raw_url = (item.get("url") or "").strip()
            if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
                raw_url = f"https://{raw_url}"
            url = html.escape(raw_url, quote=True)
            item_title = item.get("title") or raw_url
            item_title_tr = await localize(item_title, user_id)
            lines.append(f'{i}. <a href="{url}">{html.escape(item_title_tr)}</a>')
        text = "\n".join(lines)
    else:
        text = t(user_id, "links_empty_section", title=title)
        if is_admin(user_id):
            text += "\n\n<i>Секция пуста. Добавьте ссылку кнопкой ниже.</i>"
    await safe_send_or_edit(target, text, reply_markup=get_links_section_keyboard(sec_key, user_id))


ARCHIVE_PAGE_SIZE = 8


async def render_archive(target, page: int, user_id: int):
    dates = get_dates_sorted()
    markup_empty = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")]])
    if not dates:
        await safe_send_or_edit(target, t(user_id, "task_archive_empty"), reply_markup=markup_empty)
        return
    total_pages = (len(dates) + ARCHIVE_PAGE_SIZE - 1) // ARCHIVE_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    chunk = dates[page * ARCHIVE_PAGE_SIZE : (page + 1) * ARCHIVE_PAGE_SIZE]
    rows = []
    for d in chunk:
        n = len(DATABASE.get("daily_tasks", {}).get(d, {}).get("tasks", []))
        rows.append([InlineKeyboardButton(text=f"📅 {d} · {n}", callback_data=f"task:view:{d}:0")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"arch:page:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"arch:page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=t(user_id, "task_today"), callback_data="task:show")])
    rows.append([InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")])
    text = t(user_id, "task_archive_title", n=len(dates), page=page + 1, total=total_pages)
    await safe_send_or_edit(target, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


# ============================================================
# BROADCAST & NOTIFICATIONS
# ============================================================

async def broadcast_task(date_str: str, task_idx: int, report_msg: types.Message = None):
    task = get_task(date_str, task_idx)
    if not task:
        return
    tasks_total = len(DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", []))
    task_text = (task.get("text") or "").strip() or "Текст задачи — на фото."
    text_ru = f"🎯 <b>Задача дня</b> · {date_str}\n<i>№ {task_idx + 1} из {tasks_total}</i>\n\n{html.escape(task_text)}"
    if task.get("tags"):
        text_ru += "\n\n🏷 " + " ".join(html.escape(x) for x in task["tags"])

    markup_ru = None
    if BOT_USERNAME:
        markup_ru = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🤖 Решить в боте", url=f"https://t.me/{BOT_USERNAME}?start=task_{date_str}_{task_idx}")
        ]])

    channel_ok = True
    try:
        if task.get("photo_file_id"):
            await bot.send_photo(CHANNEL_ID, photo=task["photo_file_id"], caption=text_ru[:1024], parse_mode=ParseMode.HTML, reply_markup=markup_ru)
        else:
            await bot.send_message(CHANNEL_ID, text_ru, parse_mode=ParseMode.HTML, reply_markup=markup_ru)
    except Exception as e:
        channel_ok = False
        logger.warning("Channel post failed: %s", e)

    text_en_cache = {"value": None}
    sem = asyncio.Semaphore(15)
    sent = 0
    failed = 0
    lock = asyncio.Lock()

    async def _send_one(uid_str: str):
        nonlocal sent, failed
        user_lang = DATABASE["users"].get(uid_str, {}).get("language", "ru")
        if user_lang == "en":
            if text_en_cache["value"] is None:
                translated = await translate_text(task_text, "en")
                text_en_cache["value"] = (
                    f"🎯 <b>Task of the day</b> · {date_str}\n<i>№ {task_idx + 1} of {tasks_total}</i>\n\n{html.escape(translated)}"
                )
                if task.get("tags"):
                    text_en_cache["value"] += "\n\n🏷 " + " ".join(html.escape(x) for x in task["tags"])
            text = text_en_cache["value"]
            markup = None
            if BOT_USERNAME:
                markup = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🤖 Solve in bot", url=f"https://t.me/{BOT_USERNAME}?start=task_{date_str}_{task_idx}")
                ]])
        else:
            text = text_ru
            markup = markup_ru

        try:
            if task.get("photo_file_id"):
                await bot.send_photo(int(uid_str), photo=task["photo_file_id"], caption=text[:1024], parse_mode=ParseMode.HTML, reply_markup=markup)
            else:
                await bot.send_message(int(uid_str), text, parse_mode=ParseMode.HTML, reply_markup=markup)
            async with lock:
                sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                if task.get("photo_file_id"):
                    await bot.send_photo(int(uid_str), photo=task["photo_file_id"], caption=text[:1024], parse_mode=ParseMode.HTML, reply_markup=markup)
                else:
                    await bot.send_message(int(uid_str), text, parse_mode=ParseMode.HTML, reply_markup=markup)
                async with lock:
                    sent += 1
            except Exception:
                async with lock:
                    failed += 1
        except Exception:
            async with lock:
                failed += 1
        await asyncio.sleep(0.04)

    async def _guarded(uid_str):
        async with sem:
            await _send_one(uid_str)

    await asyncio.gather(*[_guarded(u) for u in list(DATABASE.get("users", {}).keys())])

    if report_msg:
        report = t(report_msg.from_user.id, "task_sol_bcast_done", sent=sent, failed=failed)
        if not channel_ok:
            report += t(report_msg.from_user.id, "task_sol_bcast_channel_fail")
        await report_msg.answer(report)


async def announce_file_to_channel(entry: dict, cat_titles: list):
    if not entry.get("file_id"):
        return
    tags = " ".join(entry.get("tags", []))
    lines = [
        "📚 <b>Новый материал в библиотеке MathAm</b>",
        "",
        f"📖 <b>{html.escape(entry.get('caption') or '—')}</b>",
        f"📂 {html.escape(' · '.join(cat_titles) or '—')}",
    ]
    if tags:
        lines.append(f"🏷 {html.escape(tags)}")
    summary = (entry.get("summary") or "").strip()
    if summary:
        lines.append(f"\n📝 {html.escape(summary)}")
    text = "\n".join(lines)
    markup = None
    if BOT_USERNAME:
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🤖 Открыть в боте", url=f"https://t.me/{BOT_USERNAME}?start=file_{entry['file_unique_id']}")
        ]])
    try:
        await bot.send_document(CHANNEL_ID, document=entry["file_id"], caption=text[:1024], parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception as e:
        logger.warning("Channel file post failed: %s", e)
        try:
            await bot.send_message(CHANNEL_ID, text[:4000], parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            logger.warning("Channel file text message also failed")


async def notify_admins_about_solution(date_str: str, idx: int, uid_str: str, entry: dict):
    u = DATABASE.get("users", {}).get(uid_str, {})
    nick = entry.get("nickname") or u.get("nickname") or "—"
    tg = entry.get("first_name") or u.get("first_name") or ""
    uname = entry.get("username") or u.get("username") or ""

    context = (
        f"🧩 <b>Новое решение задачи</b>\n"
        f"📅 Задача: <b>{date_str}</b> · №<b>{idx + 1}</b>\n"
        f"🪪 Ник: <b>{html.escape(nick)}</b>\n"
        f"👤 TG: {html.escape(tg)}" + (f" · @{html.escape(uname)}" if uname else "")
    )

    review_markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Засчитать", callback_data=f"solrev:ok:{date_str}:{idx}:{uid_str}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"solrev:no:{date_str}:{idx}:{uid_str}"),
    ]])

    photos = entry.get("photo_file_ids") or ([entry["photo_file_id"]] if entry.get("photo_file_id") else [])
    docs = entry.get("document_file_ids") or ([entry["document_file_id"]] if entry.get("document_file_id") else [])
    raw_text = (entry.get("text") or "").strip()
    escaped_user_text = html.escape(raw_text)

    for admin_id in ADMIN_IDS:
        try:
            if photos:
                if len(photos) == 1:
                    caption_body = f"{context}\n\n{escaped_user_text}" if raw_text else context
                    if len(caption_body) <= 1000 and not docs:
                        await bot.send_photo(admin_id, photo=photos[0], caption=caption_body, parse_mode=ParseMode.HTML, reply_markup=review_markup)
                        continue
                    else:
                        await bot.send_photo(admin_id, photo=photos[0], caption=context, parse_mode=ParseMode.HTML)
                else:
                    media = []
                    for i, p in enumerate(photos[:10]):
                        cap = context if i == 0 else None
                        media.append(InputMediaPhoto(media=p, caption=cap, parse_mode=ParseMode.HTML))
                    await bot.send_media_group(admin_id, media=media)

            for d in docs:
                await bot.send_document(admin_id, document=d)

            full_body = f"{context}\n\n{escaped_user_text}" if (not photos and raw_text) else escaped_user_text
            if full_body:
                parts = _split_text(full_body, TG_TEXT_LIMIT)
                for i, part in enumerate(parts):
                    mk = review_markup if i == len(parts) - 1 else None
                    await bot.send_message(admin_id, part, parse_mode=ParseMode.HTML, reply_markup=mk)
            elif photos or docs:
                await bot.send_message(admin_id, "⬇️ Управление решением выше:", reply_markup=review_markup)
        except Exception:
            logger.exception("Failed to notify admin %s about solution", admin_id)


# ============================================================
# USER & COMMON COMMAND HANDLERS
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    await track_user_activity(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")

    args = (command.args or "").strip()
    target = None
    if args.startswith("task_"):
        parts = args[5:].split("_")
        date_str = parts[0] if parts else ""
        try:
            idx = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            idx = 0
        if get_task(date_str, idx):
            target = ("task", date_str, idx)
    elif args.startswith("file_"):
        fuid = args[5:]
        if get_file_by_uid(fuid):
            target = ("file", fuid)

    uid_str = str(message.from_user.id)
    user = DATABASE.get("users", {}).get(uid_str, {})

    if not user.get("language"):
        await state.set_state(Registration.choosing_language)
        await state.update_data(after_register=target)
        await message.answer(
            t(message.from_user.id, "hello_new", name=html.escape(message.from_user.first_name or ""))
            + "\n\n"
            + t(message.from_user.id, "choose_language"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="reg:lang:ru")],
                [InlineKeyboardButton(text="🇬🇧 English", callback_data="reg:lang:en")],
            ]),
        )
        return

    if not user.get("nickname"):
        await state.set_state(Registration.waiting_for_nickname)
        await state.update_data(after_register=target)
        await message.answer(t(message.from_user.id, "ask_nickname"))
        return

    greeting = t(message.from_user.id, "welcome_back", nick=html.escape(user.get("nickname")))
    if target:
        await message.answer(greeting)
        if target[0] == "task":
            await show_task(message, target[1], target[2], message.from_user.id)
        else:
            await show_file_card(message, target[1], message.from_user.id)
        return

    welcome_text = f"{greeting}\n\n" + t(message.from_user.id, "menu_title")
    await safe_send_or_edit(message, welcome_text, reply_markup=get_main_menu_keyboard(message.from_user.id))


@dp.message(Command("task"))
async def cmd_task(message: types.Message, state: FSMContext):
    """Missing /task command handler added."""
    await state.clear()
    daily = DATABASE.get("daily_tasks", {})
    today = get_yerevan_date()
    date_str = today if (today in daily and daily[today].get("tasks")) else (get_dates_sorted()[0] if get_dates_sorted() else None)
    if not date_str:
        await message.answer(t(message.from_user.id, "task_no_tasks"), reply_markup=get_main_menu_keyboard(message.from_user.id))
        return
    await show_task(message, date_str, 0, message.from_user.id)


@dp.message(Command("catalog"))
async def cmd_catalog(message: types.Message, state: FSMContext):
    await state.clear()
    await track_user_activity(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    await safe_send_or_edit(message, t(message.from_user.id, "catalog_title"), reply_markup=await get_catalog_keyboard(message.from_user.id))


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(t(message.from_user.id, "cancel_done"), reply_markup=get_main_menu_keyboard(message.from_user.id))


@dp.message(Command("language", "lang"))
async def cmd_language(message: types.Message, state: FSMContext):
    await state.clear()
    await safe_send_or_edit(message, t(message.from_user.id, "choose_language"), reply_markup=get_language_keyboard(message.from_user.id))


@dp.message(Command("nickname"))
async def cmd_change_nickname(message: types.Message, state: FSMContext):
    await state.set_state(ChangeNicknameState.waiting_new_name)
    await message.answer(t(message.from_user.id, "change_nickname"))


# ============================================================
# REGISTRATION & PROFILE
# ============================================================

@dp.callback_query(StateFilter(Registration.choosing_language), F.data.startswith("reg:lang:"))
async def cb_reg_lang(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split(":")[2]
    if lang not in ("ru", "en"):
        await callback.answer("Error", show_alert=True)
        return
    uid_str = str(callback.from_user.id)
    DATABASE.setdefault("users", {}).setdefault(uid_str, {})
    DATABASE["users"][uid_str]["language"] = lang
    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {f"data.users.{uid_str}.language": lang}}, upsert=True)
    await callback.answer(t(callback.from_user.id, "lang_set"))
    await state.set_state(Registration.waiting_for_nickname)
    await safe_send_or_edit(callback, t(callback.from_user.id, "ask_nickname"))


@dp.message(StateFilter(Registration.waiting_for_nickname), F.text)
async def process_nickname(message: types.Message, state: FSMContext):
    nick = message.text.strip()
    if nick.startswith("/"):
        await message.answer(t(message.from_user.id, "nickname_bad_slash"))
        return
    if not (2 <= len(nick) <= 30):
        await message.answer(t(message.from_user.id, "nickname_bad_len"))
        return
    uid_str = str(message.from_user.id)
    DATABASE.setdefault("users", {}).setdefault(uid_str, {})
    DATABASE["users"][uid_str]["nickname"] = nick
    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {f"data.users.{uid_str}.nickname": nick}}, upsert=True)
    data = await state.get_data()
    target = data.get("after_register")
    await state.clear()
    await message.answer(t(message.from_user.id, "nickname_welcome", nick=html.escape(nick)))
    if target:
        if target[0] == "task" and get_task(target[1], target[2]):
            await show_task(message, target[1], target[2], message.from_user.id)
        elif target[0] == "file":
            await show_file_card(message, target[1], message.from_user.id)
        return
    await message.answer(t(message.from_user.id, "menu_title"), reply_markup=get_main_menu_keyboard(message.from_user.id))


@dp.callback_query(F.data == "user:chname")
async def cb_user_chname(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ChangeNicknameState.waiting_new_name)
    await callback.message.answer(t(callback.from_user.id, "change_nickname"))
    await callback.answer()


@dp.message(StateFilter(ChangeNicknameState.waiting_new_name), F.text)
async def process_new_nickname(message: types.Message, state: FSMContext):
    nick = message.text.strip()
    if nick.startswith("/"):
        await message.answer(t(message.from_user.id, "nickname_bad_slash"))
        return
    if not (2 <= len(nick) <= 30):
        await message.answer(t(message.from_user.id, "nickname_bad_len"))
        return
    uid_str = str(message.from_user.id)
    DATABASE.setdefault("users", {}).setdefault(uid_str, {})
    DATABASE["users"][uid_str]["nickname"] = nick
    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {f"data.users.{uid_str}.nickname": nick}}, upsert=True)
    await state.clear()
    await message.answer(
        t(message.from_user.id, "nickname_updated", nick=html.escape(nick)),
        reply_markup=get_main_menu_keyboard(message.from_user.id),
    )


# ============================================================
# MENU & LANGUAGE CALLBACKS
# ============================================================

@dp.callback_query(F.data == "lang:menu")
async def cb_lang_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_send_or_edit(callback, t(callback.from_user.id, "choose_language"), reply_markup=get_language_keyboard(callback.from_user.id))
    await callback.answer()


@dp.callback_query(F.data.startswith("lang:set:"))
async def cb_lang_set(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split(":")[2]
    if lang not in ("ru", "en"):
        await callback.answer("Error", show_alert=True)
        return
    uid_str = str(callback.from_user.id)
    DATABASE.setdefault("users", {}).setdefault(uid_str, {})
    DATABASE["users"][uid_str]["language"] = lang
    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {f"data.users.{uid_str}.language": lang}}, upsert=True)
    await state.clear()
    await callback.answer(t(callback.from_user.id, "lang_set"))
    await safe_send_or_edit(callback, t(callback.from_user.id, "menu_title"), reply_markup=get_main_menu_keyboard(callback.from_user.id))


@dp.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_send_or_edit(callback, t(callback.from_user.id, "menu_title"), reply_markup=get_main_menu_keyboard(callback.from_user.id))
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data == "menu:catalog")
async def cb_catalog(callback: types.CallbackQuery):
    await safe_send_or_edit(callback, t(callback.from_user.id, "catalog_title"), reply_markup=await get_catalog_keyboard(callback.from_user.id))
    await callback.answer()


# ============================================================
# ADMIN: CATEGORIES MANAGEMENT (BUG FIX: delcat state=None crash)
# ============================================================

@dp.callback_query(F.data == "admin:cats")
async def cb_admin_cats(callback: types.CallbackQuery, state: Optional[FSMContext] = None):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    if state:
        await state.clear()
    cats = DATABASE.get("categories", {})
    lines = ["📂 <b>Управление разделами каталога</b>\n"]
    rows = []
    for k, v in cats.items():
        cnt = len(v.get("files", []))
        lines.append(f"• <b>{html.escape(v.get('title', k))}</b>: {cnt} файлов (код: <code>{k}</code>)")
        rows.append([InlineKeyboardButton(text=f"🗑 Удалить «{v.get('title', k)}»", callback_data=f"admin:delcat:{k}")])
    rows.append([InlineKeyboardButton(text="➕ Создать новый раздел", callback_data="admin:add_cat")])
    rows.append([InlineKeyboardButton(text=t(callback.from_user.id, "back_admin"), callback_data="admin:main")])
    await safe_send_or_edit(callback, "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@dp.callback_query(F.data == "admin:add_cat")
async def cb_admin_add_cat(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.set_state(AdminAddCategory.waiting_for_title)
    await callback.message.answer(
        "📂 Введите название нового раздела (можно с эмодзи):\nНапример: <code>📖 Зарубежные олимпиады</code>\n/cancel — отмена"
    )
    await callback.answer()


@dp.message(StateFilter(AdminAddCategory.waiting_for_title), F.text)
async def process_add_category_title(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    title = message.text.strip()
    if not title:
        await message.answer("⚠️ Введите название раздела:")
        return
    base_key = re.sub(r"[^a-zA-Z0-9_]", "", title.lower())[:20] or f"cat_{uuid.uuid4().hex[:6]}"
    cat_key = base_key
    counter = 1
    while cat_key in DATABASE.get("categories", {}):
        cat_key = f"{base_key}_{counter}"
        counter += 1

    DATABASE.setdefault("categories", {})[cat_key] = {"title": title, "files": []}
    await save_db(DATABASE)
    await state.clear()
    await message.answer(f"✅ Раздел «{html.escape(title)}» успешно создан!", reply_markup=await get_catalog_keyboard(message.from_user.id))


@dp.callback_query(F.data.startswith("admin:delcat:"))
async def cb_admin_delcat(callback: types.CallbackQuery, state: Optional[FSMContext] = None):
    """Crash fix: safely handles state parameter when refreshing the category view."""
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    cat_key = callback.data.split(":", 2)[2]
    cats = DATABASE.get("categories", {})
    if cat_key not in cats:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    cat_title = cats[cat_key].get("title", cat_key)
    del cats[cat_key]
    await save_db(DATABASE)
    await callback.message.answer(f"🗑 Раздел «{html.escape(cat_title)}» удалён.")
    await cb_admin_cats(callback, state)


# ============================================================
# SCHEDULE PUBLISH IMPLEMENTATION
# ============================================================

async def _schedule_publish(date_str: str, idx: int, when: datetime):
    try:
        delay = (when - datetime.now(YEREVAN_TZ)).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        task = get_task(date_str, idx)
        if not task:
            return
        task["status"] = "published"
        task.pop("publish_at", None)
        await save_db(DATABASE)
        await broadcast_task(date_str, idx)
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, f"✅ Задача {date_str} #{idx + 1} успешно опубликована по расписанию.")
            except Exception:
                pass
    except Exception:
        logger.exception("Scheduled publish failed for %s #%s", date_str, idx)


# ============================================================
# LIFECYCLE & STARTUP
# ============================================================

async def on_startup(bot: Bot):
    global DATABASE, BOT_USERNAME, HTTP_SESSION
    HTTP_SESSION = aiohttp.ClientSession()
    DATABASE = await load_db()
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""

    commands = [
        BotCommand(command="start", description="🏠 Menu / Меню"),
        BotCommand(command="catalog", description="📚 Catalog / Каталог"),
        BotCommand(command="task", description="🎯 Task of day / Задача дня"),
        BotCommand(command="zip", description="📦 Download all PDFs / Скачать PDF (ZIP)"),
        BotCommand(command="language", description="🌐 Language / Язык"),
        BotCommand(command="nickname", description="🪪 Nickname / Никнейм"),
        BotCommand(command="cancel", description="❌ Cancel / Отмена"),
    ]
    await bot.set_my_commands(commands)
    await restore_scheduled_tasks()

    total_files = sum(len(c.get("files", [])) for c in DATABASE.get("categories", {}).values())
    logger.info("Bot started: @%s, %s users, %s files, %s tags", BOT_USERNAME, len(DATABASE.get("users", {})), total_files, len(DATABASE.get("tags", [])))


async def on_shutdown(bot: Bot):
    global HTTP_SESSION
    if HTTP_SESSION and not HTTP_SESSION.closed:
        await HTTP_SESSION.close()
    logger.info("Bot shutdown completed.")


def register_middlewares():
    dp.message.outer_middleware(SimpleRateLimitMiddleware(RATE_LIMIT_PER_MIN))
    dp.callback_query.outer_middleware(SimpleRateLimitMiddleware(RATE_LIMIT_PER_MIN))
    dp.message.outer_middleware(UserActivityMiddleware())
    dp.callback_query.outer_middleware(UserActivityMiddleware())
    dp.inline_query.outer_middleware(UserActivityMiddleware())


async def health_endpoint(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "bot": BOT_USERNAME})


async def run_polling():
    register_middlewares()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await bot.delete_webhook(drop_pending_updates=True)

    port = os.environ.get("PORT")
    if port:
        app = web.Application()
        app.router.add_get("/", health_endpoint)
        app.router.add_get("/health", health_endpoint)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=int(port))
        await site.start()
        logger.info("Health server listening on port %s", port)

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def run_webhook():
    webhook_url = os.environ.get("WEBHOOK_URL", "").strip().rstrip("/")
    webhook_path = os.environ.get("WEBHOOK_PATH", "/tgbot").strip() or "/tgbot"

    async def set_webhook(bot: Bot):
        await bot.set_webhook(webhook_url + webhook_path, drop_pending_updates=True)
        logger.info("Webhook set to: %s", webhook_url + webhook_path)

    register_middlewares()
    dp.startup.register(on_startup)
    dp.startup.register(set_webhook)
    dp.shutdown.register(on_shutdown)
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=webhook_path)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    if os.environ.get("WEBHOOK_URL", "").strip():
        logger.info("Starting in WEBHOOK mode")
        run_webhook()
    else:
        logger.info("Starting in POLLING mode")
        asyncio.run(run_polling())
