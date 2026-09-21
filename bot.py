import asyncio
import copy
import html
import logging
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone

import aiohttp
from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQuery, InlineQueryResultArticle, InlineQueryResultCachedDocument,
    InputTextMessageContent,
)
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient

# ============================================================
# CONFIG
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
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "matham_bot")
YEREVAN_TZ = timezone(timedelta(hours=4))
MSK_TZ = timezone(timedelta(hours=3))

CHANNEL_ID = os.environ.get("CHANNEL_ID", "@matham123456").strip() or "@matham123456"
TG_TEXT_LIMIT = 4000

mongo_client = AsyncIOMotorClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]
db_collection = mongo_db["catalog"]
submissions_collection = mongo_db["submissions"]
DB_DOC_ID = "catalog_main"

bot = Bot(token=TOKEN)
dp = Dispatcher()
DATABASE = {}
BOT_USERNAME = ""
REMINDER_TASK = None

# ============================================================
# LOCALIZATION
# ============================================================

TEXTS = {
    "ru": {
        "welcome_back": "👋 <b>С возвращением, {nick}!</b>",
        "hello_new": "👋 Привет, {name}!\n\nДобро пожаловать в <b>MathAm</b>!",
        "choose_language": "🌐 <b>Выберите язык / Choose your language:</b>",
        "lang_set": "✅ Язык установлен: <b>Русский</b> 🇷🇺",
        "ask_nickname": "🪪 Напишите ваш <b>никнейм</b> — под ним вас будут видеть в рейтинге, решениях и заявках.",
        "nickname_bad_slash": "⚠️ Никнейм не может начинаться с «/». Напишите другой:",
        "nickname_bad_len": "⚠️ Никнейм должен быть от 2 до 30 символов. Попробуйте ещё раз:",
        "nickname_welcome": "✅ Приятно познакомиться, <b>{nick}</b>! 🎉",
        "menu_title": "🏠 <b>Главное меню</b>\nВыберите раздел:",
        "menu_catalog": "📚 Каталог",
        "menu_search": "🏷 Поиск по тегам",
        "menu_task": "🎯 Задача дня",
        "menu_archive": "🗄 Архив задач",
        "menu_mustread": "⭐ Must-read",
        "menu_fav": "❤️ Избранное",
        "menu_rating": "🏆 Рейтинг",
        "menu_random": "🎲 Случайный материал",
        "menu_links": "🔗 Полезные ссылки",
        "menu_submit": "📤 Предложить файл",
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
        "search_title": "🏷 <b>Поиск по тегам</b>\n\nВыберите один или несколько тегов и нажмите «🔎 Искать».\nИли просто напишите тег/слово текстом.",
        "search_go": "🔎 Искать",
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
        "tag_db_title": "🏷 <b>База тегов</b> (всего: {n})\n\nНажмите на тег, чтобы удалить, или выберите «Переименовать».\nЭти теги видят все пользователи в «Поиске по тегам».",
        "tag_add_btn": "➕ Добавить тег",
        "tag_rename_btn": "✏️ Переименовать тег",
        "tag_ask_new": "🏷 Отправьте новый тег (можно с # или без, можно несколько через запятую):",
        "tag_added": "✅ Добавлены теги: {tags}",
        "tag_nothing_added": "⚠️ Новых тегов нет (пусто или дубликаты).",
        "tag_removed": "Удалён {tag}",
        "tag_missing": "Тег не найден.",
        "tag_rename_pick": "✏️ Какой тег переименовать?",
        "tag_rename_ask": "✏️ Отправьте новое название для тега {tag} (текст без #):",
        "tag_rename_done": "✅ Тег переименован: {old} → {new}. Обновлено файлов: {n}.",
        "tag_rename_no_files": "✅ Тег переименован: {old} → {new}. Файлов с этим тегом не было.",
        "tag_rename_conflict": "⚠️ Тег «{new}» уже существует.",
        "favorites_title": "❤️ <b>Избранное</b>",
        "favorites_empty": "\n\nПока пусто. Откройте материал в каталоге и нажмите «❤️ В избранное».",
        "rating_title": "🏆 <b>Рейтинг MathAm</b>\n<i>Очки — за зачтённые решения задач дня</i>\n",
        "rating_empty": "Пока никто не набрал очки. Решите задачу дня первым!",
        "rating_you": "\n👤 Вы: 🪪 <b>{nick}</b> — {score} очк. · ✅ {solved} · ❤️ {favs}",
        "mustread_title": "⭐ <b>Must-read</b>\nМатериалы, которые стоит изучить каждому олимпиаднику:",
        "mustread_empty": "⭐ <b>Must-read</b>\n\nСписок пока пуст.",
        "mustread_added": "⭐ Добавлено в must-read",
        "mustread_removed": "Убрано из must-read",
        "mustread_remove_btn": "✩ Убрать из must-read",
        "links_title": "🔗 <b>Полезные ресурсы</b>\nВыберите раздел:",
        "links_empty_section": "🔗 <b>{title}</b>\n\nВ этом разделе пока нет ссылок.",
        "links_add": "➕ Добавить ссылку",
        "links_del": "🗑 Удалить #{n}",
        "links_ask": "🔗 Отправьте ссылку в формате:\n<code>Название - https://example.com</code>",
        "links_no_url": "⚠️ Не нашёл URL. Попробуйте ещё раз.",
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
        "task_ask_solution": "✍️ Отправьте ваше решение (текстом, фото или файлом).\nОно уйдёт администраторам на проверку. /cancel — отмена.",
        "task_solution_sent": "✅ <b>Решение отправлено!</b>\nАдминистраторы проверят его и поставят оценку — результат придёт вам в личку.",
        "task_solution_send_any": "⚠️ Отправьте решение текстом, фото или файлом.",
        "task_sol_author_header": "💡 <b>Решение автора</b> (задача №{num}, {date})",
        "task_sol_not_yet": "Решение пока не добавлено.",
        "task_sols_header": "👥 <b>Решения участников</b> (задача №{num}, {date})\n",
        "task_sols_empty": "Пока нет проверенных решений. Отправьте своё — и, возможно, оно появится здесь первым! 🚀",
        "task_sol_grade": "⭐ {grade}/10",
        "task_sol_grade_full": "{grade}/10",
        "task_sol_ok_mark": "✓",
        "task_sol_not_found": "Решение не найдено.",
        "task_sol_pending_user": "Решение ещё на проверке.",
        "task_sol_view": "👀 {nick} · {grade}",
        "task_sol_empty_content": "Решение без содержимого.",
        "task_sol_show_fail": "Не удалось показать решение.",
        "task_sol_bcast_done": "✅ Задача опубликована.\n👥 Доставлено: {sent} · Ошибок: {failed}.",
        "task_sol_bcast_channel_fail": "\n⚠️ Не удалось отправить в канал — добавьте бота администратором канала.",
        "task_sol_bcast_running": "⏳ Рассылаю...",
        "task_approved_notify": "✅ Ваше решение задачи {date} (№{num}) зачтено!",
        "task_approved_notify_grade": "✅ Ваше решение задачи {date} (№{num}) зачтено!\n⭐ Оценка: {grade}/10 (+{grade} очков)\nТеперь его могут увидеть другие участники.",
        "task_grade_updated": "⭐ Оценка вашего решения (задача {date}, №{num}) обновлена: {grade}/10 (очки: {grade}).",
        "task_rejected_notify": "❌ Ваше решение задачи {date} (№{num}) не зачтено. Попробуйте ещё раз!",
        "task_admin_graded": "⭐ Оценка для 🪪 <b>{nick}</b>: <b>{label}</b>. Решение теперь видно всем участникам.",
        "task_admin_approved": "✅ Решение от 🪪 <b>{nick}</b> зачтено.\n⭐ Поставьте оценку (очки = оценка):",
        "task_admin_grade_ask": "✓ Без оценки",
        "task_admin_rejected": "❌ Отклонено.",
        "task_admin_sol_rev_not_found": "Решение не найдено.",
        "task_admin_sol_approved_short": "Засчитано",
        "task_admin_sol_rejected_short": "Отклонено",
        "task_admin_only": "Недоступно.",
        "task_grade_saved": "Оценка сохранена",
        "task_grade_zero": "без оценки",
        "task_grade_prefix": "⭐ Поставьте оценку:",
        "submit_start": "📤 Отправьте файл (лучше PDF) для публикации в библиотеку.\nОн попадёт в каталог и в канал после проверки администратором.",
        "submit_ask_title": "✏️ Как называется материал? Отправьте название:",
        "submit_ask_tags": "🏷 Выберите теги:",
        "submit_skip_tags": "⏭ Без тегов",
        "submit_preview": "📋 <b>Заявка на публикацию</b>\n\n📖 Название: {title}\n📄 Файл: {file}\n🏷 Теги: {tags}",
        "submit_send": "✅ Отправить",
        "submit_cancel": "❌ Отмена",
        "submit_sent": "✅ Заявка отправлена! Мы сообщим, когда материал попадёт в каталог.",
        "submit_cancelled": "❌ Отправка отменена. /start — главное меню.",
        "submit_stale": "Заявка устарела. Начните заново: /start → «📤 Предложить файл».",
        "submit_first_file": "Сначала отправьте файл!",
        "admin_title": "👑 <b>Админ-панель MathAm</b>\nВыберите действие:",
        "admin_upload": "➕ Загрузить материал",
        "admin_add_task": "🎯 Добавить задачу дня",
        "admin_tags": "🏷 Управление тегами",
        "admin_stats": "📊 Статистика",
        "admin_subs": "📥 Заявки на файлы",
        "admin_pending": "🧩 Решения на проверку",
        "admin_bcast": "📢 Рассылка",
        "admin_reminder": "⏰ Напоминание",
        "admin_upload_ask": "📤 Отправьте файл (PDF):",
        "admin_upload_title": "✏️ Отправьте название материала:",
        "admin_upload_desc": "📝 Отправьте описание (необязательно) или напишите «пропустить»:",
        "admin_upload_tags": "🏷 Выберите теги:",
        "admin_upload_diff": "🎯 Выберите уровень сложности:",
        "admin_upload_cats": "📂 Выберите разделы (можно несколько):",
        "admin_upload_publish": "✅ Опубликовать",
        "admin_upload_published": "✅ Материал опубликован!\n📖 <b>{title}</b>\n📂 {cats}\n⏳ Отправляю файл в канал...",
        "admin_upload_stale": "Загрузка устарела. Начните заново.",
        "admin_upload_no_cat": "Выберите хотя бы один раздел!",
        "admin_upload_cat_missing": "Категория не найдена.",
        "admin_upload_done_short": "Сохранено ✅",
        "admin_diff_easy": "🟢 Easy (Базовый)",
        "admin_diff_medium": "🟡 Medium (Регион)",
        "admin_diff_hard": "🔴 Hard (Всерос / Финал)",
        "admin_diff_imo": "🔥 IMO (Международный)",
        "admin_task_photo": "📸 Отправьте фото задачи, либо напишите «пропустить».",
        "admin_task_text": "✍️ Отправьте текст задачи (или «пропустить», если всё на фото):",
        "admin_task_solution": "💡 Отправьте решение (текстом, фото с подписью или «пропустить»):",
        "admin_task_date": "📅 На какую дату опубликовать задачу?\nФормат: <code>ГГГГ-ММ-ДД</code>, либо «сегодня» / «завтра»:",
        "admin_task_added": "✅ Задача добавлена на <b>{date}</b> (№ {num}).\n⏳ Автоматически рассылаю всем пользователям и публикую в канал...",
        "admin_task_bad_date": "⚠️ Неверный формат. Отправьте дату как <code>2025-06-01</code> или «сегодня».",
        "admin_task_photo_ask": "📸 Отправьте фото задачи или напишите «пропустить».",
        "admin_task_sol_ask": "Отправьте текст, фото, документ или «пропустить».",
        "admin_stats_title": "📊 <b>Статистика MathAm</b>\n\n👥 Пользователей: {users}\n📚 Файлов в каталоге: {files}\n🏷 Тегов в базе: {tags}\n🎯 Задач опубликовано: {tasks}\n🧩 Решений на проверке: {pending}\n📥 Заявок на файлы: {subs}\n\n<b>Топ по очкам (ник · TG):</b>\n{top}",
        "admin_subs_empty": "📥 <b>Заявки на файлы</b>\n\nНовых заявок нет.",
        "admin_subs_title": "📥 <b>Заявки на файлы</b>\n",
        "admin_subs_pick_cat": "📂 Выберите раздел для публикации:",
        "admin_subs_published": "✅ Опубликовано в «{cat}».\n⏳ Отправляю файл в канал...",
        "admin_subs_user_notify": "✅ Ваш материал «{title}» добавлен в каталог и опубликован в канале! Спасибо 🙌",
        "admin_subs_reject_notify": "❌ К сожалению, ваш материал не подошёл для каталога. Спасибо, что поделились!",
        "admin_subs_accept": "✅ Принять",
        "admin_subs_reject": "❌ Отклонить",
        "admin_subs_rejected": "❌ Заявка отклонена.",
        "admin_subs_already": "Заявка уже обработана.",
        "admin_subs_not_found": "Заявка не найдена.",
        "admin_subs_already_pub": "Уже опубликовано.",
        "admin_pending_title": "🧩 <b>Решения на проверку</b>\n",
        "admin_pending_empty": "\nНет решений на проверку. 🎉",
        "admin_pending_shown": "\nВсего на проверке показано: {n}",
        "admin_bcast_ask": "📢 Отправьте сообщение для рассылки всем пользователям (текст, фото, любой контент).\n/cancel — отмена.",
        "admin_bcast_running": "⏳ Рассылка запущена...",
        "admin_bcast_done": "✅ Рассылка завершена.\nДоставлено: {sent} · Ошибок: {failed}",
        "admin_edit_title": "⚙️ <b>Редактирование</b>\n📖 {title}",
        "admin_edit_replace": "📄 Заменить файл",
        "admin_edit_rename": "✏️ Название",
        "admin_edit_tags": "🏷 Теги",
        "admin_edit_back": "⬅️ Назад к файлу",
        "admin_edit_ask_doc": "📄 Отправьте новый файл-документ (заменит текущий):",
        "admin_edit_ask_title": "✏️ Отправьте новое название материала:",
        "admin_edit_ask_tags": "🏷 Отправьте теги через запятую (или «очистить»):\nНовые теги автоматически попадут в базу тегов.",
        "admin_edit_doc_done": "✅ Файл заменён (обновлено записей: {n}).",
        "admin_edit_title_done": "✅ Название обновлено (записей: {n}).",
        "admin_edit_tags_done": "✅ Теги обновлены (записей: {n}).",
        "admin_del_confirm": "⚠️ Удалить «{title}» из всех разделов?",
        "admin_del_yes": "🗑 Да, удалить",
        "admin_del_done": "🗑 Удалено записей: {n}.",
        "file_card_title": "📖 <b>{title}</b>",
        "file_card_section": "📂 Раздел: {cats}",
        "file_card_diff": "🎯 Уровень: {diff}",
        "file_card_tags": "🏷 {tags}",
        "file_card_summary": "\n📝 {summary}",
        "new_material": "📚 <b>Новый материал в библиотеке MathAm</b>",
        "open_in_bot": "🤖 Открыть в боте",
        "solve_in_bot": "🤖 Решить в боте",
        "user_sol_new": "🧩 <b>Новое решение</b>\nЗадача: {date} · №{num}\n🪪 Ник: <b>{nick}</b>\n👤 TG: {tg}",
        "unknown_text": "🤖 Не совсем понял. Откройте /start и воспользуйтесь меню.",
        "expect_file": "📤 Ожидаю файл. Отправьте документ или /cancel.",
        "expect_doc": "📄 Ожидаю файл. Отправьте документ или /cancel.",
        "only_admin": "Недоступно.",
        "choose_tags_n": "🏷 Выберите теги (выбрано: {n}):",
        "rating_line": "{medal} {name} — {score} очк. · ✅ {solved} · 🔥 {streak} дн.",
        "rating_medal_1": "🥇",
        "rating_medal_2": "🥈",
        "rating_medal_3": "🥉",
        "reminder": "День {n}/365 (Ежедневное напоминание о ваших целях)🥳",
        # Reminder admin
        "rem_title": "⏰ <b>Настройки напоминания</b>\n\n⏱ Время (МСК): <b>{time}</b>\n📢 Канал: <b>{channel}</b>\n🎯 Режим: <b>{target}</b>\n📆 Стартовый день: <b>{start_day}</b>\n🗓 Стартовая дата: <b>{start_date}</b>\n\n🇷🇺 Текст (RU):\n<code>{text_ru}</code>\n\n🇬🇧 Text (EN):\n<code>{text_en}</code>\n\n💡 Сегодня пользователям придёт: <b>{preview}</b>",
        "rem_edit_time": "⏱ Изменить время",
        "rem_edit_text_ru": "🇷🇺 Изменить текст (RU)",
        "rem_edit_text_en": "🇬🇧 Change text (EN)",
        "rem_edit_start": "📆 Стартовый день и дата",
        "rem_edit_channel": "📢 Канал",
        "rem_edit_target": "🎯 Режим отправки",
        "rem_test": "🚀 Отправить сейчас",
        "rem_ask_time": "⏱ Отправьте время в формате <code>ЧЧ:ММ</code> (МСК), например <code>19:00</code>:",
        "rem_ask_text_ru": "🇷🇺 Отправьте новый текст (используйте <code>{n}</code> для номера дня):",
        "rem_ask_text_en": "🇬🇧 Send new text (use <code>{n}</code> for the day number):",
        "rem_ask_start": "📆 Отправьте в формате <code>СТАРТОВЫЙ_ДЕНЬ YYYY-MM-DD</code>\nНапример: <code>19 2026-09-21</code>\n\nЕсли дата не нужна (считать с сегодня) — просто <code>19</code>.",
        "rem_ask_channel": "📢 Отправьте @username канала или -100... ID. Пример: <code>@matham123456</code>",
        "rem_bad_time": "⚠️ Неверный формат времени. Отправьте <code>ЧЧ:ММ</code>.",
        "rem_bad_start": "⚠️ Неверный формат. Отправьте <code>19</code> или <code>19 2026-09-21</code>.",
        "rem_bad_date": "⚠️ Неверная дата. Формат: <code>YYYY-MM-DD</code>.",
        "rem_saved": "✅ Сохранено.",
        "rem_target_channel": "📢 только канал",
        "rem_target_users": "👥 только пользователи",
        "rem_target_both": "📢+👥 канал и пользователи",
        "rem_target_pick": "🎯 Куда отправлять напоминание?",
        "rem_test_ok": "🚀 Тестовое напоминание отправлено.",
        "rem_test_fail": "⚠️ Ошибка отправки в канал: {err}",
        "rem_preview_day_unknown": "—",
        "rem_back": "⬅️ Настройки напоминания",
    },
    "en": {
        "welcome_back": "👋 <b>Welcome back, {nick}!</b>",
        "hello_new": "👋 Hello, {name}!\n\nWelcome to <b>MathAm</b>!",
        "choose_language": "🌐 <b>Choose your language / Выберите язык:</b>",
        "lang_set": "✅ Language set: <b>English</b> 🇬🇧",
        "ask_nickname": "🪪 Please enter your <b>nickname</b> — that's how you'll appear in ratings, solutions and submissions.",
        "nickname_bad_slash": "⚠️ Nickname cannot start with «/». Please enter another:",
        "nickname_bad_len": "⚠️ Nickname must be 2–30 characters long. Try again:",
        "nickname_welcome": "✅ Nice to meet you, <b>{nick}</b>! 🎉",
        "menu_title": "🏠 <b>Main menu</b>\nChoose a section:",
        "menu_catalog": "📚 Catalog",
        "menu_search": "🏷 Tag search",
        "menu_task": "🎯 Task of the day",
        "menu_archive": "🗄 Task archive",
        "menu_mustread": "⭐ Must-read",
        "menu_fav": "❤️ Favorites",
        "menu_rating": "🏆 Rating",
        "menu_random": "🎲 Random material",
        "menu_links": "🔗 Useful links",
        "menu_submit": "📤 Submit a file",
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
        "search_title": "🏷 <b>Tag search</b>\n\nPick one or more tags and press «🔎 Search».\nOr just type a tag/word.",
        "search_go": "🔎 Search",
        "search_reset": "♻️ Reset",
        "search_new": "🏷 New search",
        "search_pick_one": "Pick at least one tag!",
        "search_tagged": "🔎 <b>Results by tags:</b> {tags}",
        "search_query": "🔎 <b>Results for:</b> <i>{q}</i>",
        "search_found": "Materials found: <b>{n}</b>",
        "search_nothing": "😔 Nothing found. Try other tags.",
        "search_tag_off": "Tag removed",
        "search_tag_on": "Tag selected",
        "search_selected_n": "🏷 <b>Tag search</b>\nTags selected: {n}",
        "search_reset_done": "🏷 <b>Tag search</b>\nSelection cleared.",
        "tag_db_title": "🏷 <b>Tag database</b> (total: {n})\n\nTap a tag to delete, or use «Rename».\nThese tags appear in every user's tag search.",
        "tag_add_btn": "➕ Add tag",
        "tag_rename_btn": "✏️ Rename tag",
        "tag_ask_new": "🏷 Send a new tag (with or without #; multiple allowed, separated by commas):",
        "tag_added": "✅ Tags added: {tags}",
        "tag_nothing_added": "⚠️ No new tags (empty or duplicates).",
        "tag_removed": "Removed {tag}",
        "tag_missing": "Tag not found.",
        "tag_rename_pick": "✏️ Which tag to rename?",
        "tag_rename_ask": "✏️ Send the new name for {tag} (text only, no #):",
        "tag_rename_done": "✅ Tag renamed: {old} → {new}. Files updated: {n}.",
        "tag_rename_no_files": "✅ Tag renamed: {old} → {new}. No files had it.",
        "tag_rename_conflict": "⚠️ Tag «{new}» already exists.",
        "favorites_title": "❤️ <b>Favorites</b>",
        "favorites_empty": "\n\nEmpty for now. Open any material and press «❤️ Add to favorites».",
        "rating_title": "🏆 <b>MathAm rating</b>\n<i>Points for approved solutions of daily tasks</i>\n",
        "rating_empty": "Nobody has scored yet. Be the first to solve the daily task!",
        "rating_you": "\n👤 You: 🪪 <b>{nick}</b> — {score} pts · ✅ {solved} · ❤️ {favs}",
        "mustread_title": "⭐ <b>Must-read</b>\nMaterials every olympiad student should study:",
        "mustread_empty": "⭐ <b>Must-read</b>\n\nList is empty.",
        "mustread_added": "⭐ Added to must-read",
        "mustread_removed": "Removed from must-read",
        "mustread_remove_btn": "✩ Remove from must-read",
        "links_title": "🔗 <b>Useful resources</b>\nChoose a section:",
        "links_empty_section": "🔗 <b>{title}</b>\n\nNo links in this section yet.",
        "links_add": "➕ Add link",
        "links_del": "🗑 Delete #{n}",
        "links_ask": "🔗 Send a link in the format:\n<code>Title - https://example.com</code>",
        "links_no_url": "⚠️ No URL found. Try again.",
        "links_added": "✅ Link added to «{title}».",
        "links_section_missing": "Section not found.",
        "links_item_removed": "Removed: {name}",
        "links_item_missing": "Item not found.",
        "links_only_admin": "Admins only.",
        "task_of_day": "🎯 <b>Task of the day</b> · {date}\n<i>№ {num} of {total}</i>\n\n{text}",
        "task_text_on_photo": "Task text is on the photo.",
        "task_solutions": "👥 Participant solutions ({n})",
        "task_send_solution": "📝 Submit solution",
        "task_solution_pending": "⏳ Solution pending review",
        "task_solution_ok": "✅ Approved · {grade}/10",
        "task_solution_ok_no_grade": "✅ Approved",
        "task_author_solution": "💡 Author's solution",
        "task_bcast": "📢 Broadcast task",
        "task_archive_title": "🗄 <b>Task archive</b>\nDays with tasks: {n}\nPage {page} of {total}",
        "task_archive_empty": "🗄 <b>Task archive</b>\n\nNo tasks yet.",
        "task_today": "🎯 Today",
        "task_no_tasks": "🎯 <b>Task of the day</b>\n\nNo tasks published yet.",
        "task_ask_solution": "✍️ Send your solution (text, photo or file).\nIt will be sent to admins for review. /cancel to cancel.",
        "task_solution_sent": "✅ <b>Solution sent!</b>\nAdmins will review it and grade — you'll get a DM with the result.",
        "task_solution_send_any": "⚠️ Send your solution as text, photo or file.",
        "task_sol_author_header": "💡 <b>Author's solution</b> (task №{num}, {date})",
        "task_sol_not_yet": "Solution not added yet.",
        "task_sols_header": "👥 <b>Participant solutions</b> (task №{num}, {date})\n",
        "task_sols_empty": "No approved solutions yet. Submit yours — maybe it'll be the first! 🚀",
        "task_sol_grade": "⭐ {grade}/10",
        "task_sol_grade_full": "{grade}/10",
        "task_sol_ok_mark": "✓",
        "task_sol_not_found": "Solution not found.",
        "task_sol_pending_user": "Solution is still pending review.",
        "task_sol_view": "👀 {nick} · {grade}",
        "task_sol_empty_content": "Empty solution.",
        "task_sol_show_fail": "Failed to show solution.",
        "task_sol_bcast_done": "✅ Task published.\n👥 Delivered: {sent} · Errors: {failed}.",
        "task_sol_bcast_channel_fail": "\n⚠️ Could not post to channel — please make bot an admin of the channel.",
        "task_sol_bcast_running": "⏳ Broadcasting...",
        "task_approved_notify": "✅ Your solution for {date} (№{num}) has been approved!",
        "task_approved_notify_grade": "✅ Your solution for {date} (№{num}) has been approved!\n⭐ Grade: {grade}/10 (+{grade} pts)\nIt is now visible to other participants.",
        "task_grade_updated": "⭐ Grade for your solution ({date}, №{num}) updated: {grade}/10 (pts: {grade}).",
        "task_rejected_notify": "❌ Your solution for {date} (№{num}) was not accepted. Try again!",
        "task_admin_graded": "⭐ Grade for 🪪 <b>{nick}</b>: <b>{label}</b>. Solution is now visible to all participants.",
        "task_admin_approved": "✅ Solution from 🪪 <b>{nick}</b> approved.\n⭐ Assign a grade (points = grade):",
        "task_admin_grade_ask": "✓ No grade",
        "task_admin_rejected": "❌ Rejected.",
        "task_admin_sol_rev_not_found": "Solution not found.",
        "task_admin_sol_approved_short": "Approved",
        "task_admin_sol_rejected_short": "Rejected",
        "task_admin_only": "Not available.",
        "task_grade_saved": "Grade saved",
        "task_grade_zero": "no grade",
        "task_grade_prefix": "⭐ Assign a grade:",
        "submit_start": "📤 Send a file (PDF is best) to publish in the library.\nIt will go to catalog and channel after admin review.",
        "submit_ask_title": "✏️ What is the material called? Send a title:",
        "submit_ask_tags": "🏷 Pick tags:",
        "submit_skip_tags": "⏭ No tags",
        "submit_preview": "📋 <b>Submission preview</b>\n\n📖 Title: {title}\n📄 File: {file}\n🏷 Tags: {tags}",
        "submit_send": "✅ Submit",
        "submit_cancel": "❌ Cancel",
        "submit_sent": "✅ Submission sent! We'll notify you once the material is added to the catalog.",
        "submit_cancelled": "❌ Submission cancelled. /start — main menu.",
        "submit_stale": "Submission expired. Start again: /start → «📤 Submit a file».",
        "submit_first_file": "Send a file first!",
        "admin_title": "👑 <b>MathAm admin panel</b>\nChoose an action:",
        "admin_upload": "➕ Upload material",
        "admin_add_task": "🎯 Add daily task",
        "admin_tags": "🏷 Tag management",
        "admin_stats": "📊 Stats",
        "admin_subs": "📥 File submissions",
        "admin_pending": "🧩 Solutions for review",
        "admin_bcast": "📢 Broadcast",
        "admin_reminder": "⏰ Reminder",
        "admin_upload_ask": "📤 Send a file (PDF):",
        "admin_upload_title": "✏️ Send a title:",
        "admin_upload_desc": "📝 Send a description (optional) or type «skip»:",
        "admin_upload_tags": "🏷 Pick tags:",
        "admin_upload_diff": "🎯 Choose difficulty:",
        "admin_upload_cats": "📂 Choose sections (multiple allowed):",
        "admin_upload_publish": "✅ Publish",
        "admin_upload_published": "✅ Material published!\n📖 <b>{title}</b>\n📂 {cats}\n⏳ Posting file to channel...",
        "admin_upload_stale": "Upload expired. Please start again.",
        "admin_upload_no_cat": "Pick at least one section!",
        "admin_upload_cat_missing": "Category not found.",
        "admin_upload_done_short": "Saved ✅",
        "admin_diff_easy": "🟢 Easy (Basic)",
        "admin_diff_medium": "🟡 Medium (Regional)",
        "admin_diff_hard": "🔴 Hard (National / Final)",
        "admin_diff_imo": "🔥 IMO (International)",
        "admin_task_photo": "📸 Send a photo of the task, or type «skip».",
        "admin_task_text": "✍️ Send the task text (or «skip» if it's on the photo):",
        "admin_task_solution": "💡 Send the solution (text, photo with caption or «skip»):",
        "admin_task_date": "📅 For which date to publish?\nFormat: <code>YYYY-MM-DD</code>, or «today» / «tomorrow»:",
        "admin_task_added": "✅ Task added for <b>{date}</b> (№ {num}).\n⏳ Broadcasting to all users and posting to channel...",
        "admin_task_bad_date": "⚠️ Wrong format. Send date like <code>2025-06-01</code> or «today».",
        "admin_task_photo_ask": "📸 Send photo or type «skip».",
        "admin_task_sol_ask": "Send text, photo, document or «skip».",
        "admin_stats_title": "📊 <b>MathAm stats</b>\n\n👥 Users: {users}\n📚 Files in catalog: {files}\n🏷 Tags in DB: {tags}\n🎯 Tasks published: {tasks}\n🧩 Solutions pending: {pending}\n📥 File submissions: {subs}\n\n<b>Top by points (nick · TG):</b>\n{top}",
        "admin_subs_empty": "📥 <b>File submissions</b>\n\nNo new submissions.",
        "admin_subs_title": "📥 <b>File submissions</b>\n",
        "admin_subs_pick_cat": "📂 Pick a section for publishing:",
        "admin_subs_published": "✅ Published to «{cat}».\n⏳ Posting file to channel...",
        "admin_subs_user_notify": "✅ Your material «{title}» has been added to catalog and posted to the channel! Thanks 🙌",
        "admin_subs_reject_notify": "❌ Unfortunately your material didn't fit the catalog. Thanks for sharing!",
        "admin_subs_accept": "✅ Accept",
        "admin_subs_reject": "❌ Reject",
        "admin_subs_rejected": "❌ Submission rejected.",
        "admin_subs_already": "Submission already processed.",
        "admin_subs_not_found": "Submission not found.",
        "admin_subs_already_pub": "Already published.",
        "admin_pending_title": "🧩 <b>Solutions for review</b>\n",
        "admin_pending_empty": "\nNo solutions to review. 🎉",
        "admin_pending_shown": "\nTotal shown: {n}",
        "admin_bcast_ask": "📢 Send a message to broadcast to all users (text, photo, anything).\n/cancel to cancel.",
        "admin_bcast_running": "⏳ Broadcasting...",
        "admin_bcast_done": "✅ Broadcast finished.\nDelivered: {sent} · Errors: {failed}",
        "admin_edit_title": "⚙️ <b>Editing</b>\n📖 {title}",
        "admin_edit_replace": "📄 Replace file",
        "admin_edit_rename": "✏️ Title",
        "admin_edit_tags": "🏷 Tags",
        "admin_edit_back": "⬅️ Back to file",
        "admin_edit_ask_doc": "📄 Send a new file (will replace the current one):",
        "admin_edit_ask_title": "✏️ Send the new material title:",
        "admin_edit_ask_tags": "🏷 Send tags separated by commas (or «clear»):\nNew tags will be added to the tag DB automatically.",
        "admin_edit_doc_done": "✅ File replaced (records updated: {n}).",
        "admin_edit_title_done": "✅ Title updated (records: {n}).",
        "admin_edit_tags_done": "✅ Tags updated (records: {n}).",
        "admin_del_confirm": "⚠️ Delete «{title}» from all sections?",
        "admin_del_yes": "🗑 Yes, delete",
        "admin_del_done": "🗑 Records deleted: {n}.",
        "file_card_title": "📖 <b>{title}</b>",
        "file_card_section": "📂 Section: {cats}",
        "file_card_diff": "🎯 Level: {diff}",
        "file_card_tags": "🏷 {tags}",
        "file_card_summary": "\n📝 {summary}",
        "new_material": "📚 <b>New material in the MathAm library</b>",
        "open_in_bot": "🤖 Open in bot",
        "solve_in_bot": "🤖 Solve in bot",
        "user_sol_new": "🧩 <b>New solution</b>\nTask: {date} · №{num}\n🪪 Nick: <b>{nick}</b>\n👤 TG: {tg}",
        "unknown_text": "🤖 I didn't get that. Open /start and use the menu.",
        "expect_file": "📤 Waiting for a file. Send a document or /cancel.",
        "expect_doc": "📄 Waiting for a file. Send a document or /cancel.",
        "only_admin": "Not available.",
        "choose_tags_n": "🏷 Pick tags (selected: {n}):",
        "rating_line": "{medal} {name} — {score} pts · ✅ {solved} · 🔥 {streak} d.",
        "rating_medal_1": "🥇",
        "rating_medal_2": "🥈",
        "rating_medal_3": "🥉",
        "reminder": "Day {n}/365 (Daily reminder about your goals)🥳",
        "rem_title": "⏰ <b>Reminder settings</b>\n\n⏱ Time (MSK): <b>{time}</b>\n📢 Channel: <b>{channel}</b>\n🎯 Target: <b>{target}</b>\n📆 Start day: <b>{start_day}</b>\n🗓 Start date: <b>{start_date}</b>\n\n🇷🇺 Text (RU):\n<code>{text_ru}</code>\n\n🇬🇧 Text (EN):\n<code>{text_en}</code>\n\n💡 Today users will see: <b>{preview}</b>",
        "rem_edit_time": "⏱ Change time",
        "rem_edit_text_ru": "🇷🇺 Change text (RU)",
        "rem_edit_text_en": "🇬🇧 Change text (EN)",
        "rem_edit_start": "📆 Start day and date",
        "rem_edit_channel": "📢 Channel",
        "rem_edit_target": "🎯 Delivery target",
        "rem_test": "🚀 Send now",
        "rem_ask_time": "⏱ Send time as <code>HH:MM</code> (MSK), e.g. <code>19:00</code>:",
        "rem_ask_text_ru": "🇷🇺 Send new text (use <code>{n}</code> for day number):",
        "rem_ask_text_en": "🇬🇧 Send new text (use <code>{n}</code> for day number):",
        "rem_ask_start": "📆 Send as <code>START_DAY YYYY-MM-DD</code>\nExample: <code>19 2026-09-21</code>\n\nOr just <code>19</code> to start counting from today.",
        "rem_ask_channel": "📢 Send channel @username or -100... ID. Example: <code>@matham123456</code>",
        "rem_bad_time": "⚠️ Invalid time format. Send <code>HH:MM</code>.",
        "rem_bad_start": "⚠️ Invalid format. Send <code>19</code> or <code>19 2026-09-21</code>.",
        "rem_bad_date": "⚠️ Invalid date. Format: <code>YYYY-MM-DD</code>.",
        "rem_saved": "✅ Saved.",
        "rem_target_channel": "📢 channel only",
        "rem_target_users": "👥 users only",
        "rem_target_both": "📢+👥 channel and users",
        "rem_target_pick": "🎯 Where to send the reminder?",
        "rem_test_ok": "🚀 Test reminder sent.",
        "rem_test_fail": "⚠️ Failed to send to channel: {err}",
        "rem_preview_day_unknown": "—",
        "rem_back": "⬅️ Reminder settings",
    },
}


def get_user_lang(user_id: int) -> str:
    uid_str = str(user_id)
    u = DATABASE.get("users", {}).get(uid_str, {})
    lang = u.get("language") or "ru"
    return lang if lang in TEXTS else "ru"


def t(user_id: int, key: str, **kwargs) -> str:
    lang = get_user_lang(user_id)
    text = TEXTS.get(lang, TEXTS["ru"]).get(key) or TEXTS["ru"].get(key, key)
    try:
        return text.format(**kwargs)
    except Exception:
        return text


# ============================================================
# TRANSLATION
# ============================================================

GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"

_MATH_PATTERNS = [
    re.compile(r"\$\$[\s\S]+?\$\$"),
    re.compile(r"\$[^\$\n]+?\$"),
    re.compile(r"\\[a-zA-Z]+(?:\{[^{}]*\})*"),
    re.compile(r"(?<![A-Za-zА-Яа-я0-9])[A-Za-z]\s*[\^_]\s*\{?[A-Za-z0-9]+"),
    re.compile(r"\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\}"),
]

_translation_cache: dict = {}


def _protect_math(text: str):
    protected = []

    def repl(m):
        protected.append(m.group(0))
        return f"<<M{len(protected) - 1}>>"

    for pat in _MATH_PATTERNS:
        text = pat.sub(repl, text)
    return text, protected


def _restore_math(text: str, protected):
    for i, orig in enumerate(protected):
        text = text.replace(f"<<M{i}>>", orig)
    return text


async def translate_text(text: str, target_lang: str) -> str:
    if not text or not text.strip():
        return text
    if target_lang not in ("ru", "en"):
        return text

    key = (text, target_lang)
    if key in _translation_cache:
        return _translation_cache[key]

    working, protected = _protect_math(text)
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            params = {"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t", "q": working}
            async with session.get(GOOGLE_TRANSLATE_URL, params=params) as resp:
                data = await resp.json()
                parts = []
                for seg in data[0]:
                    if seg and seg[0]:
                        parts.append(seg[0])
                translated = "".join(parts)
    except Exception:
        logger.exception("Translation failed")
        translated = working

    translated = _restore_math(translated, protected)
    if len(_translation_cache) > 1500:
        _translation_cache.clear()
    _translation_cache[key] = translated
    return translated


async def localize(text: str, user_id: int) -> str:
    if not text or not text.strip():
        return text
    lang = get_user_lang(user_id)
    if lang == "ru":
        return text
    return await translate_text(text, lang)


async def localize_list(items: list, user_id: int) -> list:
    out = []
    for x in items:
        out.append(await localize(x, user_id))
    return out


# ============================================================
# DEFAULT STATE
# ============================================================

DEFAULT_TAGS = [
    "#геометрия", "#планиметрия", "#стереометрия", "#алгебра", "#неравенства",
    "#уравнения", "#функции", "#теориячисел", "#делимость", "#комбинаторика",
    "#графы", "#инварианты", "#матанализ", "#олимпиаднаяматематика",
    "#начинающим", "#всерос", "#подготовка",
]

DEFAULT_REMINDER = {
    "enabled": True,
    "time": "19:00",
    "start_day": 1,
    "start_date": None,
    "text_ru": "День {n}/365 (Ежедневное напоминание о ваших целях)🥳",
    "text_en": "Day {n}/365 (Daily reminder about your goals)🥳",
    "channel": CHANNEL_ID,
    "target": "channel",  # channel / users / both
}

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
        "useful_links": {"title": "🔗 Полезные сайты и базы задач", "items": []},
        "useful_videos": {"title": "🎥 Видеолекции и каналы", "items": []},
    },
    "must_read": {"title": "⭐ Must-read", "files": []},
    "daily_tasks": {},
    "tags": list(DEFAULT_TAGS),
    "users": {},
    "settings": {"reminder": dict(DEFAULT_REMINDER)},
}


# ============================================================
# MIDDLEWARE
# ============================================================

class UserActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user:
            try:
                await track_user_activity(user.id, user.username or "", user.first_name or "")
            except Exception:
                logger.exception("Failed to track user activity")
        return await handler(event, data)


# ============================================================
# HELPERS
# ============================================================

def get_yerevan_date() -> str:
    return datetime.now(YEREVAN_TZ).strftime("%Y-%m-%d")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_reminder_settings() -> dict:
    DATABASE.setdefault("settings", {})
    rem = DATABASE["settings"].setdefault("reminder", dict(DEFAULT_REMINDER))
    for k, v in DEFAULT_REMINDER.items():
        rem.setdefault(k, v)
    return rem


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
                cats.append(cat_data.get("title", cat_key))
                break
    return cats


def get_catalog_files_list() -> list:
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


def _split_text(text: str, limit: int) -> list:
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


async def safe_send_or_edit(target, text: str, reply_markup=None, photo_id=None, parse_mode=ParseMode.HTML):
    is_message = isinstance(target, types.Message)
    chat_id = target.chat.id if is_message else target.message.chat.id

    if photo_id:
        if len(text) <= 1024:
            if is_message:
                return await target.answer_photo(photo=photo_id, caption=text,
                                                 parse_mode=parse_mode, reply_markup=reply_markup)
            msg = target.message
            try:
                await msg.delete()
            except Exception:
                pass
            return await msg.answer_photo(photo=photo_id, caption=text,
                                          parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            if is_message:
                await target.answer_photo(photo=photo_id, caption="📄")
            else:
                msg = target.message
                try:
                    await msg.delete()
                except Exception:
                    pass
                await msg.answer_photo(photo=photo_id, caption="📄")
            parts = _split_text(text, TG_TEXT_LIMIT)
            for i, part in enumerate(parts):
                mk = reply_markup if i == len(parts) - 1 else None
                try:
                    await bot.send_message(chat_id, part, parse_mode=parse_mode, reply_markup=mk)
                except Exception:
                    logger.exception("Failed to send long text part")
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
            try:
                await bot.send_message(chat_id, part, parse_mode=parse_mode)
            except Exception:
                logger.exception("Failed to send long text part")
        if reply_markup:
            try:
                return await bot.send_message(chat_id, "⬇️", reply_markup=reply_markup)
            except Exception:
                pass
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
            "language": "ru",
            "created_at": datetime.now(YEREVAN_TZ).isoformat(),
            "streak": 1,
            "last_active": today,
            "score": 0,
            "favorites": [],
        }
        DATABASE["users"][uid_str] = user_data
        await db_collection.update_one({"_id": DB_DOC_ID},
                                       {"$set": {f"data.users.{uid_str}": user_data}}, upsert=True)
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
        await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": updates})


async def award_points(user_id: int, points: int):
    uid_str = str(user_id)
    if uid_str not in DATABASE.get("users", {}):
        await track_user_activity(user_id, "", "")
    if uid_str not in DATABASE.get("users", {}):
        return
    DATABASE["users"][uid_str]["score"] = DATABASE["users"][uid_str].get("score", 0) + points
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


def get_dates_sorted() -> list:
    return sorted(DATABASE.get("daily_tasks", {}).keys(), reverse=True)


def count_solved(uid_str: str) -> int:
    n = 0
    for group in DATABASE.get("daily_tasks", {}).values():
        for task in group.get("tasks", []):
            s = (task.get("user_solutions") or {}).get(uid_str)
            if s and s.get("status") == "approved":
                n += 1
    return n


def update_file_field(uid: str, field: str, value) -> int:
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
    return count


def normalize_tags_input(raw: str) -> list:
    tags = []
    for part in re.split(r"[,;\n]", raw):
        tag = re.sub(r"[^#\wа-яА-ЯёЁ-]", "", part.strip().replace(" ", "-"))
        if tag and not tag.startswith("#"):
            tag = "#" + tag
        if tag and 2 <= len(tag) <= 40 and tag.lower() not in {x.lower() for x in tags}:
            tags.append(tag)
    return tags[:10]


# ============================================================
# DATABASE LOAD
# ============================================================

async def load_db():
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

    for sec_key, default_sec in DEFAULT_STATE["links"].items():
        if sec_key not in data["links"]:
            data["links"][sec_key] = copy.deepcopy(default_sec)
        data["links"][sec_key].setdefault("title", default_sec["title"])
        data["links"][sec_key].setdefault("items", [])

    if not data.get("tags"):
        data["tags"] = list(DEFAULT_TAGS)

    # settings
    data.setdefault("settings", {})
    rem = data["settings"].setdefault("reminder", dict(DEFAULT_REMINDER))
    for k, v in DEFAULT_REMINDER.items():
        rem.setdefault(k, v)

    for uid, user in data["users"].items():
        user.setdefault("username", "")
        user.setdefault("first_name", "")
        user.setdefault("nickname", "")
        user.setdefault("language", "ru")
        user.setdefault("created_at", datetime.now(YEREVAN_TZ).isoformat())
        user.setdefault("streak", 1)
        user.setdefault("last_active", get_yerevan_date())
        user.setdefault("score", 0)
        user.setdefault("favorites", [])

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
            task.setdefault("source", "admin")
            task.setdefault("created_at", get_yerevan_date())
            task.setdefault("user_solutions", {})
            task["number"] = i + 1
            for uid_str, sol in task["user_solutions"].items():
                sol.setdefault("text", "")
                sol.setdefault("photo_file_id", None)
                sol.setdefault("document_file_id", None)
                sol.setdefault("username", "")
                sol.setdefault("first_name", "")
                sol.setdefault("nickname", "")
                sol.setdefault("status", "approved")
                sol.setdefault("grade", None)
                sol.setdefault("submitted_at", get_yerevan_date())

    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": data}}, upsert=True)
    return data


async def save_db(db_data):
    await db_collection.update_one({"_id": DB_DOC_ID}, {"$set": {"data": db_data}}, upsert=True)


async def save_submission(sub_id: str, data: dict):
    await submissions_collection.update_one({"_id": sub_id}, {"$set": data}, upsert=True)


async def get_submission(sub_id: str) -> dict:
    doc = await submissions_collection.find_one({"_id": sub_id})
    return doc if doc else {}


# ============================================================
# FSM STATES
# ============================================================

class Registration(StatesGroup):
    choosing_language = State()
    waiting_for_nickname = State()


class TagSearch(StatesGroup):
    selecting = State()


class AdminUpload(StatesGroup):
    waiting_document = State()
    waiting_title = State()
    waiting_description = State()
    choosing_tags = State()
    choosing_difficulty = State()
    choosing_categories = State()


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


class ReminderAdmin(StatesGroup):
    waiting_time = State()
    waiting_text_ru = State()
    waiting_text_en = State()
    waiting_start = State()
    waiting_channel = State()


# ============================================================
# KEYBOARDS (async, translated)
# ============================================================

DIFF_KEYS = ("easy", "medium", "hard", "imo")


def get_main_menu_keyboard(user_id: int):
    builder = [
        [InlineKeyboardButton(text=t(user_id, "menu_catalog"), callback_data="menu:catalog"),
         InlineKeyboardButton(text=t(user_id, "menu_search"), callback_data="search:main")],
        [InlineKeyboardButton(text=t(user_id, "menu_task"), callback_data="task:show"),
         InlineKeyboardButton(text=t(user_id, "menu_archive"), callback_data="task:archive")],
        [InlineKeyboardButton(text=t(user_id, "menu_mustread"), callback_data="mustread:main"),
         InlineKeyboardButton(text=t(user_id, "menu_fav"), callback_data="favorites:main")],
        [InlineKeyboardButton(text=t(user_id, "menu_rating"), callback_data="rating:main"),
         InlineKeyboardButton(text=t(user_id, "menu_random"), callback_data="challenge:main")],
        [InlineKeyboardButton(text=t(user_id, "menu_links"), callback_data="links:main")],
        [InlineKeyboardButton(text=t(user_id, "menu_submit"), callback_data="submit:start")],
        [InlineKeyboardButton(text=t(user_id, "menu_lang"), callback_data="lang:menu")],
    ]
    if is_admin(user_id):
        builder.append([InlineKeyboardButton(text=t(user_id, "menu_admin"), callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


async def get_catalog_keyboard(user_id: int):
    """Categories with translated titles."""
    builder = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        count = len(cat_data.get("files", []))
        title = await localize(cat_data.get("title", cat_key), user_id)
        builder.append([InlineKeyboardButton(
            text=f"{title} ({count})",
            callback_data=f"cat:{cat_key}",
        )])
    builder.append([InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def get_file_view_keyboard(uid: str, user_id: int):
    uid_str = str(user_id)
    user_favs = DATABASE.get("users", {}).get(uid_str, {}).get("favorites", [])
    is_fav = uid in user_favs
    fav_text = t(user_id, "remove_fav") if is_fav else t(user_id, "add_fav")

    rows = [
        [InlineKeyboardButton(text=t(user_id, "get_file"), callback_data=f"file:get:{uid}")],
        [InlineKeyboardButton(text=fav_text, callback_data=f"fav:toggle:{uid}")],
    ]
    if is_admin(user_id):
        rows.append([
            InlineKeyboardButton(text=t(user_id, "edit"), callback_data=f"admin:edit_file:{uid}"),
            InlineKeyboardButton(text=t(user_id, "mustread_btn"), callback_data=f"mustread:toggle:{uid}"),
        ])
        rows.append([InlineKeyboardButton(text=t(user_id, "delete"), callback_data=f"admin:del_file:{uid}")])
    rows.append([InlineKeyboardButton(text=t(user_id, "back_catalog"), callback_data="menu:catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_task_keyboard(date_str: str, task_idx: int, user_id: int):
    task = get_task(date_str, task_idx)
    if not task:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=t(user_id, "back_menu"), callback_data="menu:main")]])
    uid_str = str(user_id)
    sol = (task.get("user_solutions") or {}).get(uid_str)
    rows = []
    if sol is None or sol.get("status") == "rejected":
        rows.append([InlineKeyboardButton(text=t(user_id, "task_send_solution"),
                                          callback_data=f"task:solve:{date_str}:{task_idx}")])
    elif sol.get("status") == "pending":
        rows.append([InlineKeyboardButton(text=t(user_id, "task_solution_pending"), callback_data="noop")])
    else:
        grade = sol.get("grade")
        label = t(user_id, "task_solution_ok", grade=grade) if grade else t(user_id, "task_solution_ok_no_grade")
        rows.append([InlineKeyboardButton(text=label, callback_data="noop")])

    if task.get("solution") or task.get("solution_photo_file_id") or task.get("solution_document_file_id"):
        rows.append([InlineKeyboardButton(text=t(user_id, "task_author_solution"),
                                          callback_data=f"task:show_sol:{date_str}:{task_idx}")])

    approved = [s for s in (task.get("user_solutions") or {}).values() if s.get("status") == "approved"]
    rows.append([InlineKeyboardButton(text=t(user_id, "task_solutions", n=len(approved)),
                                      callback_data=f"task:sols:{date_str}:{task_idx}")])

    if is_admin(user_id):
        rows.append([InlineKeyboardButton(text=t(user_id, "task_bcast"),
                                          callback_data=f"task:bcast:{date_str}:{task_idx}")])

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


async def get_tag_toggle_keyboard(selected: list, prefix: str, done_cb: str,
                                  user_id: int, skip_text: str = None, skip_cb: str = None):
    """Tags with translated labels. selected stores ORIGINAL tags."""
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
    for sec_key, sec_data in DATABASE.get("links", {}).items():
        title = await localize(sec_data.get("title", sec_key), user_id)
        builder.append([InlineKeyboardButton(text=title, callback_data=f"links:sec:{sec_key}")])
    builder.append([InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def get_links_section_keyboard(sec_key: str, user_id: int):
    sec = DATABASE.get("links", {}).get(sec_key, {})
    items = sec.get("items", [])
    builder = []
    for idx, item in enumerate(items):
        builder.append([InlineKeyboardButton(text=item.get("title", f"Link #{idx + 1}"),
                                             url=item.get("url", ""))])
        if is_admin(user_id):
            builder.append([InlineKeyboardButton(text=t(user_id, "links_del", n=idx + 1),
                                                 callback_data=f"links:del:{sec_key}:{idx}")])
    if is_admin(user_id):
        builder.append([InlineKeyboardButton(text=t(user_id, "links_add"), callback_data=f"links:add:{sec_key}")])
    builder.append([InlineKeyboardButton(text="⬅️", callback_data="links:main")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def get_admin_menu_keyboard(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(user_id, "admin_upload"), callback_data="admin:upload")],
        [InlineKeyboardButton(text=t(user_id, "admin_add_task"), callback_data="admin:add_task")],
        [InlineKeyboardButton(text=t(user_id, "admin_tags"), callback_data="admin:tags")],
        [InlineKeyboardButton(text=t(user_id, "admin_reminder"), callback_data="admin:reminder")],
        [InlineKeyboardButton(text=t(user_id, "admin_stats"), callback_data="admin:stats")],
        [InlineKeyboardButton(text=t(user_id, "admin_subs"), callback_data="admin:submissions")],
        [InlineKeyboardButton(text=t(user_id, "admin_pending"), callback_data="admin:pending_sols")],
        [InlineKeyboardButton(text=t(user_id, "admin_bcast"), callback_data="admin:broadcast")],
        [InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")],
    ])


def get_language_keyboard(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:set:ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:set:en")],
        [InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")],
    ])


def get_reminder_settings_keyboard(user_id: int):
    rem = get_reminder_settings()
    target = rem.get("target", "channel")
    rows = [
        [InlineKeyboardButton(text=t(user_id, "rem_edit_time"), callback_data="rem:edit:time")],
        [InlineKeyboardButton(text=t(user_id, "rem_edit_text_ru"), callback_data="rem:edit:text_ru")],
        [InlineKeyboardButton(text=t(user_id, "rem_edit_text_en"), callback_data="rem:edit:text_en")],
        [InlineKeyboardButton(text=t(user_id, "rem_edit_start"), callback_data="rem:edit:start")],
        [InlineKeyboardButton(text=t(user_id, "rem_edit_channel"), callback_data="rem:edit:channel")],
        [InlineKeyboardButton(text=t(user_id, "rem_edit_target"), callback_data="rem:edit:target")],
        [InlineKeyboardButton(text=t(user_id, "rem_test"), callback_data="rem:test")],
        [InlineKeyboardButton(text=t(user_id, "back_admin"), callback_data="admin:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# RENDER HELPERS
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
    return "\n".join(lines)


async def show_file_card(target, uid: str, user_id: int) -> bool:
    f = get_file_by_uid(uid)
    if not f:
        return False
    text = await format_file_info(f, get_file_categories(uid), user_id)
    await safe_send_or_edit(target, text, reply_markup=get_file_view_keyboard(uid, user_id))
    return True


async def show_task(target, date_str: str, task_idx: int, user_id: int = None):
    if user_id is None:
        user_id = target.from_user.id
    task = get_task(date_str, task_idx)
    total = len(DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", []))
    if not task:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=t(user_id, "back_menu"), callback_data="menu:main")]])
        await safe_send_or_edit(target, t(user_id, "task_missing"), reply_markup=markup)
        return
    task_text = (task.get("text") or "").strip() or t(user_id, "task_text_on_photo")
    task_text = await localize(task_text, user_id)
    text = t(user_id, "task_of_day",
             date=date_str, num=task_idx + 1, total=total,
             text=html.escape(task_text))
    await safe_send_or_edit(target, text,
                            reply_markup=get_task_keyboard(date_str, task_idx, user_id),
                            photo_id=task.get("photo_file_id"))


async def render_mustread(target, user_id: int):
    files = [f for f in get_catalog_files_list() if f.get("must_read")]
    builder = []
    if files:
        for f in files:
            caption = await localize(f['caption'], user_id)
            builder.append([InlineKeyboardButton(text=f"⭐ {caption[:55]}",
                                                 callback_data=f"file:view:{f['uid']}")])
            if is_admin(user_id):
                builder.append([InlineKeyboardButton(text=t(user_id, "mustread_remove_btn"),
                                                     callback_data=f"mustread:toggle:{f['uid']}")])
        text = t(user_id, "mustread_title")
    else:
        text = t(user_id, "mustread_empty")
    builder.append([InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")])
    await safe_send_or_edit(target, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))


async def show_links_section(target, sec_key: str, user_id: int):
    sec = DATABASE.get("links", {}).get(sec_key, {})
    items = sec.get("items", [])
    title_tr = await localize(sec.get("title", sec_key), user_id)
    title = html.escape(title_tr)
    if items:
        lines = [f"🔗 <b>{title}</b>\n"]
        for i, item in enumerate(items, 1):
            url = html.escape(item.get("url", ""))
            item_title = item.get("title") or item.get("url", "Link")
            item_title_tr = await localize(item_title, user_id)
            lines.append(f"{i}. <a href=\"{url}\">{html.escape(item_title_tr)}</a>")
        text = "\n".join(lines)
    else:
        text = t(user_id, "links_empty_section", title=title)
    await safe_send_or_edit(target, text, reply_markup=get_links_section_keyboard(sec_key, user_id))


ARCHIVE_PAGE_SIZE = 8


async def render_archive(target, page: int, user_id: int):
    dates = get_dates_sorted()
    markup_empty = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=t(user_id, "back_menu"), callback_data="menu:main")]])
    if not dates:
        await safe_send_or_edit(target, t(user_id, "task_archive_empty"), reply_markup=markup_empty)
        return
    total_pages = (len(dates) + ARCHIVE_PAGE_SIZE - 1) // ARCHIVE_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    chunk = dates[page * ARCHIVE_PAGE_SIZE:(page + 1) * ARCHIVE_PAGE_SIZE]
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
# TASK BROADCAST
# ============================================================

async def broadcast_task(date_str: str, task_idx: int, report_msg: types.Message = None):
    task = get_task(date_str, task_idx)
    if not task:
        return
    tasks_total = len(DATABASE.get("daily_tasks", {}).get(date_str, {}).get("tasks", []))
    task_text = (task.get("text") or "").strip() or "Текст задачи — на фото."
    text_ru = (
        f"🎯 <b>Задача дня</b> · {date_str}\n"
        f"<i>№ {task_idx + 1} из {tasks_total}</i>\n\n"
        f"{html.escape(task_text)}"
    )
    text_en = None
    if BOT_USERNAME:
        markup_ru = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🤖 Решить в боте",
                                 url=f"https://t.me/{BOT_USERNAME}?start=task_{date_str}_{task_idx}")
        ]])
    else:
        markup_ru = None

    channel_ok = True
    try:
        if task.get("photo_file_id"):
            await bot.send_photo(CHANNEL_ID, photo=task["photo_file_id"],
                                 caption=text_ru[:1024], parse_mode=ParseMode.HTML, reply_markup=markup_ru)
        else:
            await bot.send_message(CHANNEL_ID, text_ru, parse_mode=ParseMode.HTML, reply_markup=markup_ru)
    except Exception as e:
        channel_ok = False
        logger.warning("Channel post failed: %s", e)

    sent, failed = 0, 0
    for uid_str in list(DATABASE.get("users", {}).keys()):
        user_lang = DATABASE["users"].get(uid_str, {}).get("language", "ru")
        if user_lang == "en":
            if text_en is None:
                translated = await translate_text(task_text, "en")
                text_en = (
                    f"🎯 <b>Task of the day</b> · {date_str}\n"
                    f"<i>№ {task_idx + 1} of {tasks_total}</i>\n\n"
                    f"{html.escape(translated)}"
                )
            text = text_en
            if BOT_USERNAME:
                markup = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🤖 Solve in bot",
                                         url=f"https://t.me/{BOT_USERNAME}?start=task_{date_str}_{task_idx}")
                ]])
            else:
                markup = None
        else:
            text = text_ru
            markup = markup_ru

        try:
            if task.get("photo_file_id"):
                await bot.send_photo(int(uid_str), photo=task["photo_file_id"],
                                     caption=text[:1024], parse_mode=ParseMode.HTML, reply_markup=markup)
            else:
                await bot.send_message(int(uid_str), text, parse_mode=ParseMode.HTML, reply_markup=markup)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                if task.get("photo_file_id"):
                    await bot.send_photo(int(uid_str), photo=task["photo_file_id"],
                                         caption=text[:1024], parse_mode=ParseMode.HTML, reply_markup=markup)
                else:
                    await bot.send_message(int(uid_str), text, parse_mode=ParseMode.HTML, reply_markup=markup)
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

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
            InlineKeyboardButton(text="🤖 Открыть в боте",
                                 url=f"https://t.me/{BOT_USERNAME}?start=file_{entry['file_unique_id']}")
        ]])
    try:
        await bot.send_document(CHANNEL_ID, document=entry["file_id"],
                                caption=text[:1024], parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception as e:
        logger.warning("Channel file post failed: %s", e)
        try:
            await bot.send_message(CHANNEL_ID, text[:4000], parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            logger.warning("Channel file message also failed")


# ============================================================
# TAG TOGGLE (shared)
# ============================================================

async def toggle_tag_by_index(callback: types.CallbackQuery, state: FSMContext):
    try:
        i = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("Error", show_alert=True)
        return None
    tags = DATABASE.get("tags", [])
    if not (0 <= i < len(tags)):
        await callback.answer(t(callback.from_user.id, "tag_missing"), show_alert=True)
        return None
    tag = tags[i]
    data = await state.get_data()
    selected = list(data.get("selected_tags", []))
    if tag in selected:
        selected.remove(tag)
        removed = True
    else:
        selected.append(tag)
        removed = False
    await state.update_data(selected_tags=selected)
    return selected, tag, removed


# ============================================================
# COMMANDS
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    await track_user_activity(message.from_user.id, message.from_user.username or "",
                              message.from_user.first_name or "")

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
            t(message.from_user.id, "hello_new", name=html.escape(message.from_user.first_name or "")) + "\n\n" +
            t(message.from_user.id, "choose_language"),
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
    await safe_send_or_edit(message, welcome_text,
                            reply_markup=get_main_menu_keyboard(message.from_user.id))


@dp.callback_query(StateFilter(Registration.choosing_language), F.data.startswith("reg:lang:"))
async def cb_reg_lang(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split(":")[2]
    if lang not in ("ru", "en"):
        await callback.answer("Error", show_alert=True)
        return
    uid_str = str(callback.from_user.id)
    DATABASE.setdefault("users", {}).setdefault(uid_str, {})
    DATABASE["users"][uid_str]["language"] = lang
    await db_collection.update_one({"_id": DB_DOC_ID},
                                   {"$set": {f"data.users.{uid_str}.language": lang}}, upsert=True)
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
    await db_collection.update_one({"_id": DB_DOC_ID},
                                   {"$set": {f"data.users.{uid_str}.nickname": nick}}, upsert=True)
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
    await message.answer(t(message.from_user.id, "menu_title"),
                         reply_markup=get_main_menu_keyboard(message.from_user.id))


@dp.message(StateFilter(Registration.waiting_for_nickname))
async def process_nickname_any(message: types.Message, state: FSMContext):
    await message.answer(t(message.from_user.id, "ask_nickname"))


@dp.message(Command("catalog"))
async def cmd_catalog(message: types.Message, state: FSMContext):
    await state.clear()
    await track_user_activity(message.from_user.id, message.from_user.username or "",
                              message.from_user.first_name or "")
    await safe_send_or_edit(message, t(message.from_user.id, "catalog_title"),
                            reply_markup=await get_catalog_keyboard(message.from_user.id))


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(t(message.from_user.id, "cancel_done"),
                         reply_markup=get_main_menu_keyboard(message.from_user.id))


@dp.message(Command("language"))
async def cmd_language(message: types.Message, state: FSMContext):
    await state.clear()
    await safe_send_or_edit(message, t(message.from_user.id, "choose_language"),
                            reply_markup=get_language_keyboard(message.from_user.id))


# ============================================================
# LANGUAGE MENU
# ============================================================

@dp.callback_query(F.data == "lang:menu")
async def cb_lang_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_send_or_edit(callback, t(callback.from_user.id, "choose_language"),
                            reply_markup=get_language_keyboard(callback.from_user.id))
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
    await db_collection.update_one({"_id": DB_DOC_ID},
                                   {"$set": {f"data.users.{uid_str}.language": lang}}, upsert=True)
    await state.clear()
    await callback.answer(t(callback.from_user.id, "lang_set"))
    await safe_send_or_edit(callback, t(callback.from_user.id, "menu_title"),
                            reply_markup=get_main_menu_keyboard(callback.from_user.id))


# ============================================================
# MAIN MENU
# ============================================================

@dp.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_send_or_edit(callback, t(callback.from_user.id, "menu_title"),
                            reply_markup=get_main_menu_keyboard(callback.from_user.id))
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data == "menu:catalog")
async def cb_catalog(callback: types.CallbackQuery):
    await safe_send_or_edit(callback, t(callback.from_user.id, "catalog_title"),
                            reply_markup=await get_catalog_keyboard(callback.from_user.id))
    await callback.answer()


# ============================================================
# CATALOG & FILES
# ============================================================

@dp.callback_query(F.data.startswith("cat:"))
async def cb_category(callback: types.CallbackQuery):
    cat_key = callback.data.split(":", 1)[1]
    cat_data = DATABASE.get("categories", {}).get(cat_key)
    if not cat_data:
        await callback.answer(t(callback.from_user.id, "section_missing"), show_alert=True)
        return
    files = cat_data.get("files", [])
    builder = []
    for f in files:
        cap = await localize(f.get("caption") or "—", callback.from_user.id)
        builder.append([InlineKeyboardButton(
            text=f"📖 {cap[:55]}",
            callback_data=f"file:view:{f.get('file_unique_id')}",
        )])
    builder.append([InlineKeyboardButton(text=t(callback.from_user.id, "back_catalog"), callback_data="menu:catalog")])
    cat_title_tr = await localize(cat_data.get('title', cat_key), callback.from_user.id)
    text = f"<b>{html.escape(cat_title_tr)}</b>\n{len(files)}"
    await safe_send_or_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("file:view:"))
async def cb_file_view(callback: types.CallbackQuery):
    uid = callback.data.split(":", 2)[2]
    if not await show_file_card(callback, uid, callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "no_file"), show_alert=True)
        return
    await callback.answer()


@dp.callback_query(F.data.startswith("file:get:"))
async def cb_file_get(callback: types.CallbackQuery):
    uid = callback.data.split(":", 2)[2]
    f = get_file_by_uid(uid)
    if not f:
        await callback.answer(t(callback.from_user.id, "no_file"), show_alert=True)
        return
    try:
        cap = await localize(f.get("caption") or "—", callback.from_user.id)
        await callback.message.answer_document(
            document=f.get("file_id"),
            caption=f"📖 <b>{html.escape(cap)}</b>",
            parse_mode=ParseMode.HTML,
        )
        await callback.answer(t(callback.from_user.id, "file_sent"))
    except Exception as e:
        logger.exception("Failed to send file %s: %s", uid, e)
        await callback.answer(t(callback.from_user.id, "file_send_fail"), show_alert=True)


@dp.callback_query(F.data.startswith("fav:toggle:"))
async def cb_fav_toggle(callback: types.CallbackQuery):
    uid = callback.data.split(":", 2)[2]
    uid_str = str(callback.from_user.id)
    user = DATABASE.get("users", {}).get(uid_str)
    if user is None:
        await track_user_activity(callback.from_user.id, callback.from_user.username or "",
                                  callback.from_user.first_name or "")
        user = DATABASE.get("users", {}).get(uid_str)
    if user is None:
        await callback.answer("Error", show_alert=True)
        return
    favs = user.setdefault("favorites", [])
    if uid in favs:
        favs.remove(uid)
        msg = t(callback.from_user.id, "fav_removed")
    else:
        favs.append(uid)
        msg = t(callback.from_user.id, "fav_added")
    await db_collection.update_one({"_id": DB_DOC_ID},
                                   {"$set": {f"data.users.{uid_str}.favorites": favs}}, upsert=True)
    if await show_file_card(callback, uid, callback.from_user.id):
        await callback.answer(msg)
    else:
        await callback.answer(t(callback.from_user.id, "no_file"), show_alert=True)


# ============================================================
# TAG SEARCH
# ============================================================

@dp.callback_query(F.data == "search:main")
async def cb_search_main(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(TagSearch.selecting)
    await state.update_data(selected_tags=[])
    markup = await get_tag_toggle_keyboard([], "search:tag", "search:go",
                                           callback.from_user.id,
                                           t(callback.from_user.id, "search_reset"), "search:reset")
    await safe_send_or_edit(callback, t(callback.from_user.id, "search_title"), reply_markup=markup)
    await callback.answer()


@dp.callback_query(StateFilter(TagSearch.selecting), F.data.startswith("search:tag:"))
async def cb_search_tag(callback: types.CallbackQuery, state: FSMContext):
    res = await toggle_tag_by_index(callback, state)
    if not res:
        return
    selected, tag, removed = res
    markup = await get_tag_toggle_keyboard(selected, "search:tag", "search:go",
                                           callback.from_user.id,
                                           t(callback.from_user.id, "search_reset"), "search:reset")
    await safe_send_or_edit(callback, t(callback.from_user.id, "search_selected_n", n=len(selected)),
                            reply_markup=markup)
    await callback.answer(t(callback.from_user.id, "search_tag_off" if removed else "search_tag_on"))


@dp.callback_query(F.data == "search:reset")
async def cb_search_reset(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(selected_tags=[])
    markup = await get_tag_toggle_keyboard([], "search:tag", "search:go",
                                           callback.from_user.id,
                                           t(callback.from_user.id, "search_reset"), "search:reset")
    await safe_send_or_edit(callback, t(callback.from_user.id, "search_reset_done"), reply_markup=markup)
    await callback.answer()


async def show_search_results(target, results, header: str, user_id: int):
    if results:
        text = f"{header}\n\n" + t(user_id, "search_found", n=len(results))
        rows = []
        for f in results[:20]:
            cap = await localize(f['caption'], user_id)
            rows.append([InlineKeyboardButton(text=f"📖 {cap[:55]}",
                                              callback_data=f"file:view:{f['uid']}")])
    else:
        text = f"{header}\n\n" + t(user_id, "search_nothing")
        rows = []
    rows.append([InlineKeyboardButton(text=t(user_id, "search_new"), callback_data="search:main")])
    rows.append([InlineKeyboardButton(text=t(user_id, "back_menu"), callback_data="menu:main")])
    await safe_send_or_edit(target, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data == "search:go")
async def cb_search_go(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_tags", [])
    if not selected:
        await callback.answer(t(callback.from_user.id, "search_pick_one"), show_alert=True)
        return
    files = get_catalog_files_list()
    sel_lower = {x.lower() for x in selected}
    scored = []
    for f in files:
        matches = len(sel_lower & {x.lower() for x in f.get("tags", [])})
        if matches:
            scored.append((matches, f))
    scored.sort(key=lambda x: -x[0])
    results = [f for _, f in scored]
    tags_tr = await localize_list(selected, callback.from_user.id)
    header = t(callback.from_user.id, "search_tagged", tags=html.escape(' '.join(tags_tr)))
    await show_search_results(callback, results, header, callback.from_user.id)
    await callback.answer()


@dp.message(StateFilter(TagSearch.selecting), F.text)
async def process_search_text(message: types.Message, state: FSMContext):
    raw_q = message.text.strip()
    q = raw_q.lower().lstrip("#")
    if not q:
        await message.answer("?")
        return
    # If user types in EN, translate the query to RU to match stored data
    translated_query = None
    if get_user_lang(message.from_user.id) == "en":
        try:
            translated_query = (await translate_text(raw_q.lstrip("#"), "ru")).lower().lstrip("#")
        except Exception:
            translated_query = None

    files = get_catalog_files_list()
    results = []
    for f in files:
        hay = (f["caption"] + " " + " ".join(f.get("tags", [])) + " " + (f.get("summary") or "")).lower()
        if q in hay or (translated_query and translated_query in hay):
            results.append(f)
    await state.clear()
    header = t(message.from_user.id, "search_query", q=html.escape(raw_q))
    await show_search_results(message, results, header, message.from_user.id)


# ============================================================
# TAG DATABASE (with rename)
# ============================================================

async def render_tag_manager(target, user_id: int):
    tags = DATABASE.get("tags", [])
    rows = []
    for i, tag in enumerate(tags):
        rows.append([InlineKeyboardButton(text=f"🗑 {tag}", callback_data=f"tagdel:{i}")])
    rows.append([InlineKeyboardButton(text=t(user_id, "tag_add_btn"), callback_data="tagadd")])
    rows.append([InlineKeyboardButton(text=t(user_id, "tag_rename_btn"), callback_data="tagrename:start")])
    rows.append([InlineKeyboardButton(text=t(user_id, "back_admin"), callback_data="admin:main")])
    text = t(user_id, "tag_db_title", n=len(tags))
    await safe_send_or_edit(target, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data == "admin:tags")
async def cb_admin_tags(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.clear()
    await render_tag_manager(callback, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data == "tagadd")
async def cb_tagadd(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.set_state(AddTag.waiting_for_text)
    await callback.message.answer(t(callback.from_user.id, "tag_ask_new"))
    await callback.answer()


@dp.message(StateFilter(AddTag.waiting_for_text), F.text)
async def process_add_tag(message: types.Message, state: FSMContext):
    tags = DATABASE.setdefault("tags", [])
    added = []
    for tag in normalize_tags_input(message.text):
        if tag.lower() not in {x.lower() for x in tags}:
            tags.append(tag)
            added.append(tag)
    await save_db(DATABASE)
    await state.clear()
    if added:
        await message.answer(t(message.from_user.id, "tag_added", tags=html.escape(' '.join(added))))
    else:
        await message.answer(t(message.from_user.id, "tag_nothing_added"))


@dp.callback_query(F.data.startswith("tagdel:"))
async def cb_tagdel(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    try:
        i = int(callback.data.split(":")[1])
    except ValueError:
        await callback.answer("Error", show_alert=True)
        return
    tags = DATABASE.get("tags", [])
    if 0 <= i < len(tags):
        removed = tags.pop(i)
        await save_db(DATABASE)
        await render_tag_manager(callback, callback.from_user.id)
        await callback.answer(t(callback.from_user.id, "tag_removed", tag=removed))
    else:
        await callback.answer(t(callback.from_user.id, "tag_missing"), show_alert=True)


@dp.callback_query(F.data == "tagrename:start")
async def cb_tagrename_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    tags = DATABASE.get("tags", [])
    if not tags:
        await callback.answer(t(callback.from_user.id, "tag_missing"), show_alert=True)
        return
    await state.set_state(RenameTag.choosing)
    rows, row = [], []
    for i, tag in enumerate(tags):
        row.append(InlineKeyboardButton(text=tag, callback_data=f"tagren:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text=t(callback.from_user.id, "back_admin"), callback_data="admin:tags")])
    await safe_send_or_edit(callback, t(callback.from_user.id, "tag_rename_pick"),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@dp.callback_query(StateFilter(RenameTag.choosing), F.data.startswith("tagren:"))
async def cb_tagrename_pick(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    try:
        i = int(callback.data.split(":")[1])
    except ValueError:
        await callback.answer("Error", show_alert=True)
        return
    tags = DATABASE.get("tags", [])
    if not (0 <= i < len(tags)):
        await callback.answer(t(callback.from_user.id, "tag_missing"), show_alert=True)
        return
    old_tag = tags[i]
    await state.update_data(rename_old=old_tag, rename_index=i)
    await state.set_state(RenameTag.waiting_for_new_name)
    await safe_send_or_edit(callback, t(callback.from_user.id, "tag_rename_ask", tag=html.escape(old_tag)))
    await callback.answer()


@dp.message(StateFilter(RenameTag.waiting_for_new_name), F.text)
async def process_tagrename(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = message.text.strip().replace("#", "").strip()
    raw = re.sub(r"\s+", "-", raw)
    if not raw:
        await message.answer(t(message.from_user.id, "tag_rename_ask", tag="?"))
        return
    new_tag = "#" + raw
    data = await state.get_data()
    old_tag = data.get("rename_old")
    if not old_tag:
        await state.clear()
        return

    existing_tags = DATABASE.get("tags", [])
    if new_tag.lower() != old_tag.lower() and any(x.lower() == new_tag.lower() for x in existing_tags):
        await message.answer(t(message.from_user.id, "tag_rename_conflict", new=new_tag))
        return

    n = rename_tag_everywhere(old_tag, new_tag)
    await save_db(DATABASE)
    await state.clear()
    if n > 0:
        await message.answer(t(message.from_user.id, "tag_rename_done", old=old_tag, new=new_tag, n=n))
    else:
        await message.answer(t(message.from_user.id, "tag_rename_no_files", old=old_tag, new=new_tag))
    await message.answer(t(message.from_user.id, "menu_title"),
                         reply_markup=get_main_menu_keyboard(message.from_user.id))


# ============================================================
# FAVORITES / RATING / MUST-READ / RANDOM
# ============================================================

@dp.callback_query(F.data == "favorites:main")
async def cb_favorites(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    uid_str = str(callback.from_user.id)
    favs = DATABASE.get("users", {}).get(uid_str, {}).get("favorites", [])
    builder = []
    for fuid in favs:
        f = get_file_by_uid(fuid)
        if f:
            cap = await localize(f.get('caption') or "—", callback.from_user.id)
            builder.append([InlineKeyboardButton(text=f"❤️ {cap[:55]}",
                                                 callback_data=f"file:view:{fuid}")])
    text = t(callback.from_user.id, "favorites_title")
    if not builder:
        text += t(callback.from_user.id, "favorites_empty")
    builder.append([InlineKeyboardButton(text=t(callback.from_user.id, "back_menu"), callback_data="menu:main")])
    await safe_send_or_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data == "rating:main")
async def cb_rating(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    users = DATABASE.get("users", {})
    ranked = [kv for kv in sorted(users.items(),
                                   key=lambda kv: (kv[1].get("score", 0), kv[1].get("streak", 0)),
                                   reverse=True) if kv[1].get("score", 0) > 0][:10]
    medals = [t(callback.from_user.id, "rating_medal_1"),
              t(callback.from_user.id, "rating_medal_2"),
              t(callback.from_user.id, "rating_medal_3")]
    lines = [t(callback.from_user.id, "rating_title")]
    if not ranked:
        lines.append(t(callback.from_user.id, "rating_empty"))
    for i, (uid_str, u) in enumerate(ranked, 1):
        medal = medals[i - 1] if i <= 3 else f"{i}."
        solved = count_solved(uid_str)
        lines.append(t(callback.from_user.id, "rating_line",
                       medal=medal, name=user_display(uid_str),
                       score=u.get('score', 0), solved=solved, streak=u.get('streak', 1)))
    me = users.get(str(callback.from_user.id), {})
    lines.append(t(callback.from_user.id, "rating_you",
                   nick=html.escape(me.get('nickname') or '—'),
                   score=me.get('score', 0),
                   solved=count_solved(str(callback.from_user.id)),
                   favs=len(me.get('favorites', []))))
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=t(callback.from_user.id, "back_menu"), callback_data="menu:main")]])
    await safe_send_or_edit(callback, "\n".join(lines), reply_markup=markup)
    await callback.answer()


@dp.callback_query(F.data == "mustread:main")
async def cb_mustread(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_mustread(callback, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data.startswith("mustread:toggle:"))
async def cb_mustread_toggle(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    uid = callback.data.split(":", 2)[2]
    new_val = None
    count = 0
    for cat_data in DATABASE.get("categories", {}).values():
        for f in cat_data.get("files", []):
            if f.get("file_unique_id") == uid:
                f["must_read"] = not f.get("must_read", False)
                new_val = f["must_read"]
                count += 1
    if not count:
        await callback.answer(t(callback.from_user.id, "no_file"), show_alert=True)
        return
    await save_db(DATABASE)
    if new_val:
        await show_file_card(callback, uid, callback.from_user.id)
        await callback.answer(t(callback.from_user.id, "mustread_added"))
    else:
        await render_mustread(callback, callback.from_user.id)
        await callback.answer(t(callback.from_user.id, "mustread_removed"))


@dp.callback_query(F.data == "challenge:main")
async def cb_challenge(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    files = get_catalog_files_list()
    if not files:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=t(callback.from_user.id, "back_menu"), callback_data="menu:main")]])
        await safe_send_or_edit(callback, "🎲", reply_markup=markup)
        await callback.answer()
        return
    chosen = random.choice(files)
    await show_file_card(callback, chosen["uid"], callback.from_user.id)
    await callback.answer("🎲")


# ============================================================
# DAILY TASKS
# ============================================================

@dp.callback_query(F.data == "task:show")
async def cb_task_show(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    daily = DATABASE.get("daily_tasks", {})
    today = get_yerevan_date()
    if today in daily and daily[today].get("tasks"):
        date_str = today
    else:
        dates = get_dates_sorted()
        date_str = dates[0] if dates else None
    if not date_str:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=t(callback.from_user.id, "back_menu"), callback_data="menu:main")]])
        await safe_send_or_edit(callback, t(callback.from_user.id, "task_no_tasks"), reply_markup=markup)
        await callback.answer()
        return
    await show_task(callback, date_str, 0, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data.startswith("task:view:"))
async def cb_task_view(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Error", show_alert=True)
        return
    try:
        idx = int(parts[3])
    except ValueError:
        await callback.answer("Error", show_alert=True)
        return
    await show_task(callback, parts[2], idx, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data == "task:archive")
async def cb_task_archive(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_archive(callback, 0, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data.startswith("arch:page:"))
async def cb_archive_page(callback: types.CallbackQuery):
    try:
        page = int(callback.data.split(":")[2])
    except ValueError:
        page = 0
    await render_archive(callback, page, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data.startswith("task:bcast:"))
async def cb_task_bcast(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Error", show_alert=True)
        return
    date_str, idx = parts[2], int(parts[3])
    await callback.answer(t(callback.from_user.id, "task_sol_bcast_running"))
    await broadcast_task(date_str, idx, report_msg=callback.message)


@dp.callback_query(F.data.startswith("task:show_sol:"))
async def cb_task_show_sol(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Error", show_alert=True)
        return
    date_str, idx = parts[2], int(parts[3])
    task = get_task(date_str, idx)
    if not task:
        await callback.answer(t(callback.from_user.id, "task_missing"), show_alert=True)
        return
    sol_text = (task.get("solution") or "").strip()
    photo_id = task.get("solution_photo_file_id")
    doc_id = task.get("solution_document_file_id")
    if not sol_text and not photo_id and not doc_id:
        await callback.answer(t(callback.from_user.id, "task_sol_not_yet"), show_alert=True)
        return
    if sol_text:
        sol_text = await localize(sol_text, callback.from_user.id)
    text = t(callback.from_user.id, "task_sol_author_header", num=idx + 1, date=date_str)
    if sol_text:
        text += "\n\n" + html.escape(sol_text)
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=t(callback.from_user.id, "back_task"), callback_data=f"task:view:{date_str}:{idx}")]])
    await safe_send_or_edit(callback, text, reply_markup=markup, photo_id=photo_id)
    if doc_id:
        try:
            await callback.message.answer_document(document=doc_id)
        except Exception:
            logger.exception("Failed to send solution document")
    await callback.answer()


@dp.callback_query(F.data.startswith("task:solve:"))
async def cb_task_solve(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Error", show_alert=True)
        return
    date_str, idx = parts[2], int(parts[3])
    if not get_task(date_str, idx):
        await callback.answer(t(callback.from_user.id, "task_missing"), show_alert=True)
        return
    await state.set_state(UserTaskSolution.waiting_for_solution)
    await state.update_data(task_date=date_str, task_idx=idx)
    await callback.message.answer(t(callback.from_user.id, "task_ask_solution"))
    await callback.answer()


@dp.message(StateFilter(UserTaskSolution.waiting_for_solution))
async def process_user_solution(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date_str, idx = data.get("task_date"), data.get("task_idx", -1)
    task = get_task(date_str, idx) if date_str else {}
    if not task:
        await state.clear()
        await message.answer("⚠️ /start")
        return
    uid_str = str(message.from_user.id)
    u = DATABASE.get("users", {}).get(uid_str, {})
    entry = {
        "text": (message.text or message.caption or "").strip(),
        "photo_file_id": message.photo[-1].file_id if message.photo else None,
        "document_file_id": message.document.file_id if message.document else None,
        "nickname": u.get("nickname") or "",
        "first_name": message.from_user.first_name or "",
        "username": message.from_user.username or "",
        "status": "pending",
        "grade": None,
        "submitted_at": datetime.now(YEREVAN_TZ).isoformat(),
    }
    if not entry["text"] and not entry["photo_file_id"] and not entry["document_file_id"]:
        await message.answer(t(message.from_user.id, "task_solution_send_any"))
        return
    task.setdefault("user_solutions", {})[uid_str] = entry
    await save_db(DATABASE)
    await state.clear()
    await message.answer(t(message.from_user.id, "task_solution_sent"))

    nick = u.get("nickname") or "—"
    tg = message.from_user.first_name or ""
    uname = message.from_user.username or ""
    context = t(message.from_user.id, "user_sol_new",
                date=date_str, num=idx + 1,
                nick=html.escape(nick),
                tg=html.escape(tg) + (f" · @{html.escape(uname)}" if uname else "")) + "\n\n"
    body = html.escape(entry["text"]) if entry["text"] else ""
    review_markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Засчитать", callback_data=f"solrev:ok:{date_str}:{idx}:{uid_str}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"solrev:no:{date_str}:{idx}:{uid_str}"),
    ]])
    for admin_id in ADMIN_IDS:
        try:
            if entry["photo_file_id"]:
                await bot.send_photo(admin_id, photo=entry["photo_file_id"],
                                     caption=(context + body)[:1024], parse_mode=ParseMode.HTML,
                                     reply_markup=review_markup)
            elif entry["document_file_id"]:
                await bot.send_document(admin_id, document=entry["document_file_id"],
                                        caption=(context + body)[:1024], parse_mode=ParseMode.HTML,
                                        reply_markup=review_markup)
            else:
                parts = _split_text(context + body, TG_TEXT_LIMIT)
                for i, part in enumerate(parts):
                    mk = review_markup if i == len(parts) - 1 else None
                    await bot.send_message(admin_id, part, parse_mode=ParseMode.HTML, reply_markup=mk)
        except Exception:
            logger.exception("Failed to notify admin %s", admin_id)
    await show_task(message, date_str, idx, message.from_user.id)


@dp.callback_query(F.data.startswith("task:sols:"))
async def cb_task_sols(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Error", show_alert=True)
        return
    date_str, idx = parts[2], int(parts[3])
    task = get_task(date_str, idx)
    if not task:
        await callback.answer(t(callback.from_user.id, "task_missing"), show_alert=True)
        return
    approved = [(u, s) for u, s in (task.get("user_solutions") or {}).items()
                if s.get("status") == "approved"]
    lines = [t(callback.from_user.id, "task_sols_header", num=idx + 1, date=date_str)]
    builder = []
    if not approved:
        lines.append(t(callback.from_user.id, "task_sols_empty"))
    else:
        approved.sort(key=lambda kv: -(kv[1].get("grade") or 0))
        for uid_str, s in approved:
            grade = s.get("grade")
            g = t(callback.from_user.id, "task_sol_grade_full", grade=grade) if grade else t(callback.from_user.id, "task_sol_ok_mark")
            snippet = (s.get("text") or "").strip()
            if snippet:
                snippet = await localize(snippet[:200], callback.from_user.id)
            if s.get("photo_file_id"):
                snippet = (snippet + " [📷]").strip()
            if s.get("document_file_id"):
                snippet = (snippet + " [📎]").strip()
            lines.append(f"⭐ <b>{sol_display(s, uid_str)}</b> — {g}\n<i>{html.escape(snippet[:150])}</i>\n")
            builder.append([InlineKeyboardButton(
                text=t(callback.from_user.id, "task_sol_view", nick=sol_button_name(s, uid_str), grade=g),
                callback_data=f"solfull:{date_str}:{idx}:{uid_str}")])
    builder.append([InlineKeyboardButton(text=t(callback.from_user.id, "back_task"),
                                         callback_data=f"task:view:{date_str}:{idx}")])
    await safe_send_or_edit(callback, "\n".join(lines),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("solfull:"))
async def cb_solfull(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Error", show_alert=True)
        return
    date_str, idx, uid_str = parts[1], int(parts[2]), parts[3]
    task = get_task(date_str, idx)
    sol = (task.get("user_solutions") or {}).get(uid_str, {})
    if not sol:
        await callback.answer(t(callback.from_user.id, "task_sol_not_found"), show_alert=True)
        return
    if sol.get("status") != "approved" and not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "task_sol_pending_user"), show_alert=True)
        return
    grade = sol.get("grade")
    header = f"🪪 <b>{sol_display(sol, uid_str)}</b>"
    header += f" — ⭐ {grade}/10" if grade else " — ✅"
    text = sol.get("text") or ""
    if text:
        text = await localize(text, callback.from_user.id)
    try:
        if sol.get("photo_file_id"):
            caption = header + (f"\n\n{html.escape(text)}" if text else "")
            await callback.message.answer_photo(photo=sol["photo_file_id"],
                                                caption=caption[:1024],
                                                parse_mode=ParseMode.HTML)
            if len(caption) > 1024:
                for part in _split_text(caption[1000:], TG_TEXT_LIMIT):
                    await bot.send_message(callback.message.chat.id, part, parse_mode=ParseMode.HTML)
        elif sol.get("document_file_id"):
            caption = header + (f"\n\n{html.escape(text)}" if text else "")
            await callback.message.answer_document(document=sol["document_file_id"],
                                                   caption=caption[:1024], parse_mode=ParseMode.HTML)
            if len(caption) > 1024:
                for part in _split_text(caption[1000:], TG_TEXT_LIMIT):
                    await bot.send_message(callback.message.chat.id, part, parse_mode=ParseMode.HTML)
        elif text:
            await safe_send_or_edit(callback, header + f"\n\n{html.escape(text)}")
        else:
            await callback.answer(t(callback.from_user.id, "task_sol_empty_content"), show_alert=True)
            return
        await callback.answer()
    except Exception:
        logger.exception("Failed to show solution")
        await callback.answer(t(callback.from_user.id, "task_sol_show_fail"), show_alert=True)


@dp.callback_query(F.data.startswith("solrev:"))
async def cb_solrev(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("Error", show_alert=True)
        return
    action, date_str, idx_s, uid_str = parts[1], parts[2], parts[3], parts[4]
    try:
        idx = int(idx_s)
    except ValueError:
        await callback.answer("Error", show_alert=True)
        return
    task = get_task(date_str, idx)
    sol = (task.get("user_solutions") or {}).get(uid_str)
    if not sol:
        await callback.answer(t(callback.from_user.id, "task_admin_sol_rev_not_found"), show_alert=True)
        return

    if action == "no":
        sol["status"] = "rejected"
        sol["grade"] = None
        sol["reviewed_at"] = datetime.now(YEREVAN_TZ).isoformat()
        await save_db(DATABASE)
        try:
            await bot.send_message(int(uid_str), t(int(uid_str), "task_rejected_notify",
                                                    date=date_str, num=idx + 1))
        except Exception:
            pass
        await callback.message.answer(t(callback.from_user.id, "task_admin_rejected"))
        await callback.answer(t(callback.from_user.id, "task_admin_sol_rejected_short"))
        return

    sol["status"] = "approved"
    sol["reviewed_at"] = datetime.now(YEREVAN_TZ).isoformat()
    await save_db(DATABASE)
    name = sol.get("nickname") or get_nickname(uid_str)
    rows = []
    for start in (1, 6):
        rows.append([InlineKeyboardButton(text=str(n), callback_data=f"grade:{n}:{date_str}:{idx}:{uid_str}")
                     for n in range(start, start + 5)])
    rows.append([InlineKeyboardButton(text=t(callback.from_user.id, "task_admin_grade_ask"),
                                      callback_data=f"grade:0:{date_str}:{idx}:{uid_str}")])
    await callback.message.answer(t(callback.from_user.id, "task_admin_approved", nick=html.escape(name)),
                                  parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer(t(callback.from_user.id, "task_admin_sol_approved_short"))


@dp.callback_query(F.data.startswith("grade:"))
async def cb_grade(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("Error", show_alert=True)
        return
    try:
        n = int(parts[1])
        idx = int(parts[3])
    except ValueError:
        await callback.answer("Error", show_alert=True)
        return
    date_str, uid_str = parts[2], parts[4]
    if not (0 <= n <= 10):
        await callback.answer("Error", show_alert=True)
        return
    task = get_task(date_str, idx)
    sol = (task.get("user_solutions") or {}).get(uid_str)
    if not sol or sol.get("status") != "approved":
        await callback.answer(t(callback.from_user.id, "task_admin_sol_rev_not_found"), show_alert=True)
        return

    prev_grade = sol.get("grade") or 0
    new_grade = n
    sol["grade"] = new_grade if new_grade > 0 else None
    await save_db(DATABASE)

    delta = new_grade - prev_grade
    if delta != 0:
        await award_points(int(uid_str), delta)

    name = sol.get("nickname") or get_nickname(uid_str)
    try:
        if new_grade > 0:
            if prev_grade:
                await bot.send_message(int(uid_str), t(int(uid_str), "task_grade_updated",
                                                        date=date_str, num=idx + 1, grade=new_grade))
            else:
                await bot.send_message(int(uid_str), t(int(uid_str), "task_approved_notify_grade",
                                                        date=date_str, num=idx + 1, grade=new_grade))
        else:
            await bot.send_message(int(uid_str), t(int(uid_str), "task_approved_notify",
                                                    date=date_str, num=idx + 1))
    except Exception:
        pass

    label = t(callback.from_user.id, "task_sol_grade_full", grade=new_grade) if new_grade > 0 else t(callback.from_user.id, "task_grade_zero")
    await callback.message.answer(t(callback.from_user.id, "task_admin_graded",
                                    nick=html.escape(name), label=label),
                                  parse_mode=ParseMode.HTML)
    await callback.answer(t(callback.from_user.id, "task_grade_saved"))


# ============================================================
# LINKS
# ============================================================

@dp.callback_query(F.data == "links:main")
async def cb_links_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_send_or_edit(callback, t(callback.from_user.id, "links_title"),
                            reply_markup=await get_links_keyboard(callback.from_user.id))
    await callback.answer()


@dp.callback_query(F.data.startswith("links:sec:"))
async def cb_links_section(callback: types.CallbackQuery):
    sec_key = callback.data.split(":", 2)[2]
    if sec_key not in DATABASE.get("links", {}):
        await callback.answer(t(callback.from_user.id, "links_section_missing"), show_alert=True)
        return
    await show_links_section(callback, sec_key, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data.startswith("links:del:"))
async def cb_links_del(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "links_only_admin"), show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Error", show_alert=True)
        return
    sec_key, idx = parts[2], int(parts[3])
    items = DATABASE.get("links", {}).get(sec_key, {}).get("items", [])
    if 0 <= idx < len(items):
        removed = items.pop(idx)
        await save_db(DATABASE)
        await show_links_section(callback, sec_key, callback.from_user.id)
        await callback.answer(t(callback.from_user.id, "links_item_removed",
                                name=(removed.get('title') or '')[:40]))
    else:
        await callback.answer(t(callback.from_user.id, "links_item_missing"), show_alert=True)


@dp.callback_query(F.data.startswith("links:add:"))
async def cb_links_add(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "links_only_admin"), show_alert=True)
        return
    sec_key = callback.data.split(":", 2)[2]
    await state.set_state(AddLink.waiting_for_text)
    await state.update_data(section=sec_key)
    await callback.message.answer(t(callback.from_user.id, "links_ask"))
    await callback.answer()


@dp.message(StateFilter(AddLink.waiting_for_text), F.text)
async def process_add_link(message: types.Message, state: FSMContext):
    text = message.text.strip()
    m = re.search(r"(https?://\S+)", text)
    if not m:
        await message.answer(t(message.from_user.id, "links_no_url"))
        return
    url = m.group(1).rstrip(".,);")
    title = text.replace(m.group(1), "").strip(" \t-—|:,")
    if not title:
        title = re.sub(r"^https?://", "", url)[:60]
    data = await state.get_data()
    sec_key = data.get("section")
    if sec_key not in DATABASE.get("links", {}):
        await state.clear()
        await message.answer(t(message.from_user.id, "links_section_missing"))
        return
    DATABASE["links"][sec_key].setdefault("items", []).append({"title": title, "url": url})
    await save_db(DATABASE)
    await state.clear()
    await message.answer(t(message.from_user.id, "links_added",
                           title=DATABASE['links'][sec_key].get('title', sec_key)))


# ============================================================
# USER FILE SUBMISSIONS
# ============================================================

@dp.callback_query(F.data == "submit:start")
async def cb_submit_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserSubmit.waiting_file)
    await state.update_data(sub_file_id=None, sub_file_name=None, sub_title="", selected_tags=[])
    await callback.message.answer(t(callback.from_user.id, "submit_start"))
    await callback.answer()


@dp.message(StateFilter(UserSubmit.waiting_file), F.document | F.photo)
async def process_submit_file(message: types.Message, state: FSMContext):
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "material"
    else:
        file_id = message.photo[-1].file_id
        file_name = "photo.jpg"
    await state.update_data(sub_file_id=file_id, sub_file_name=file_name)
    await state.set_state(UserSubmit.waiting_title)
    await message.answer(t(message.from_user.id, "submit_ask_title"))


@dp.message(StateFilter(UserSubmit.waiting_title), F.text)
async def process_submit_title(message: types.Message, state: FSMContext):
    await state.update_data(sub_title=message.text.strip()[:200])
    await state.set_state(UserSubmit.choosing_tags)
    await message.answer(t(message.from_user.id, "submit_ask_tags"),
                         reply_markup=await get_tag_toggle_keyboard([], "sub:tag", "sub:tags_done",
                                                                    message.from_user.id,
                                                                    t(message.from_user.id, "submit_skip_tags"),
                                                                    "sub:tags_skip"))


@dp.callback_query(StateFilter(UserSubmit.choosing_tags), F.data.startswith("sub:tag:"))
async def cb_sub_tag(callback: types.CallbackQuery, state: FSMContext):
    res = await toggle_tag_by_index(callback, state)
    if not res:
        return
    selected, tag, removed = res
    await safe_send_or_edit(callback, t(callback.from_user.id, "choose_tags_n", n=len(selected)),
                            reply_markup=await get_tag_toggle_keyboard(selected, "sub:tag", "sub:tags_done",
                                                                       callback.from_user.id,
                                                                       t(callback.from_user.id, "submit_skip_tags"),
                                                                       "sub:tags_skip"))
    await callback.answer(t(callback.from_user.id, "search_tag_off" if removed else "search_tag_on"))


async def render_submit_preview(target, state: FSMContext, user_id: int):
    data = await state.get_data()
    text = t(user_id, "submit_preview",
             title=html.escape(data.get('sub_title') or '—'),
             file=html.escape(data.get('sub_file_name') or '—'),
             tags=html.escape(' '.join(data.get('selected_tags', [])) or '—'))
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(user_id, "submit_send"), callback_data="submit:confirm"),
        InlineKeyboardButton(text=t(user_id, "submit_cancel"), callback_data="submit:cancel"),
    ]])
    await safe_send_or_edit(target, text, reply_markup=markup)


@dp.callback_query(F.data == "sub:tags_done", StateFilter(UserSubmit.choosing_tags))
async def cb_sub_tags_done(callback: types.CallbackQuery, state: FSMContext):
    await render_submit_preview(callback, state, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data == "sub:tags_skip", StateFilter(UserSubmit.choosing_tags))
async def cb_sub_tags_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(selected_tags=[])
    await render_submit_preview(callback, state, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data == "submit:confirm", StateFilter(UserSubmit.choosing_tags))
async def cb_submit_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("sub_file_id"):
        await callback.answer(t(callback.from_user.id, "submit_first_file"), show_alert=True)
        return
    uid_str = str(callback.from_user.id)
    u = DATABASE.get("users", {}).get(uid_str, {})
    sub_id = uuid.uuid4().hex[:12]
    payload = {
        "user_id": callback.from_user.id,
        "username": callback.from_user.username or "",
        "first_name": callback.from_user.first_name or "",
        "nickname": u.get("nickname") or "",
        "file_id": data["sub_file_id"],
        "file_name": data.get("sub_file_name") or "",
        "title": data.get("sub_title") or "",
        "tags": data.get("selected_tags", []),
        "status": "pending",
        "created_at": datetime.now(YEREVAN_TZ).isoformat(),
    }
    await save_submission(sub_id, payload)
    await state.clear()
    notify_text = (
        "📥 <b>Новая заявка на файл</b>\n\n"
        f"🪪 Ник: <b>{html.escape(payload['nickname'] or '—')}</b>\n"
        f"👤 TG: {html.escape(payload['first_name'] or '')}"
        + (f" · @{html.escape(payload['username'])}" if payload["username"] else "")
        + "\n\n"
        f"📖 {html.escape(payload['title'] or '—')}\n"
        f"📄 {html.escape(payload['file_name'] or '—')}\n"
        f"🏷 {html.escape(' '.join(payload['tags']) or '—')}"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"admin:sub_accept:{sub_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin:sub_reject:{sub_id}")],
    ])
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_document(admin_id, document=payload["file_id"], caption=notify_text[:1024],
                                    parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            logger.exception("Failed to notify admin %s", admin_id)
    await callback.message.answer(t(callback.from_user.id, "submit_sent"))
    await callback.answer()


@dp.callback_query(F.data == "submit:confirm")
async def cb_submit_confirm_stale(callback: types.CallbackQuery):
    await callback.answer(t(callback.from_user.id, "submit_stale"), show_alert=True)


@dp.callback_query(F.data == "submit:cancel")
async def cb_submit_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(t(callback.from_user.id, "submit_cancelled"))
    await callback.answer()


# ============================================================
# ADMIN: PANEL
# ============================================================

@dp.callback_query(F.data == "admin:main")
async def cb_admin_main(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.clear()
    await safe_send_or_edit(callback, t(callback.from_user.id, "admin_title"),
                            reply_markup=get_admin_menu_keyboard(callback.from_user.id))
    await callback.answer()


# ============================================================
# ADMIN: REMINDER SETTINGS
# ============================================================

def _calc_reminder_day() -> int:
    rem = get_reminder_settings()
    start_day = int(rem.get("start_day") or 1)
    sd = rem.get("start_date")
    if sd:
        try:
            start_date = datetime.strptime(sd, "%Y-%m-%d").date()
            today = datetime.now(MSK_TZ).date()
            delta = (today - start_date).days
            return start_day + max(0, delta)
        except Exception:
            pass
    return start_day


async def render_reminder_settings(target, user_id: int):
    rem = get_reminder_settings()
    day_now = _calc_reminder_day()
    text_ru = rem.get("text_ru") or TEXTS["ru"]["reminder"]
    text_en = rem.get("text_en") or TEXTS["en"]["reminder"]
    try:
        preview = text_ru.format(n=day_now)
    except Exception:
        preview = text_ru
    target_label = {
        "channel": t(user_id, "rem_target_channel"),
        "users": t(user_id, "rem_target_users"),
        "both": t(user_id, "rem_target_both"),
    }.get(rem.get("target", "channel"), rem.get("target", "channel"))
    text = t(user_id, "rem_title",
             time=rem.get("time", "19:00"),
             channel=rem.get("channel", CHANNEL_ID),
             target=target_label,
             start_day=rem.get("start_day", 1),
             start_date=rem.get("start_date") or "—",
             text_ru=html.escape(text_ru),
             text_en=html.escape(text_en),
             preview=html.escape(preview))
    await safe_send_or_edit(target, text, reply_markup=get_reminder_settings_keyboard(user_id))


@dp.callback_query(F.data == "admin:reminder")
async def cb_admin_reminder(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.clear()
    await render_reminder_settings(callback, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data == "rem:back")
async def cb_rem_back(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.clear()
    await render_reminder_settings(callback, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data.startswith("rem:edit:"))
async def cb_rem_edit(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    field = callback.data.split(":")[2]
    if field == "time":
        await state.set_state(ReminderAdmin.waiting_time)
        await callback.message.answer(t(callback.from_user.id, "rem_ask_time"))
    elif field == "text_ru":
        await state.set_state(ReminderAdmin.waiting_text_ru)
        await callback.message.answer(t(callback.from_user.id, "rem_ask_text_ru"))
    elif field == "text_en":
        await state.set_state(ReminderAdmin.waiting_text_en)
        await callback.message.answer(t(callback.from_user.id, "rem_ask_text_en"))
    elif field == "start":
        await state.set_state(ReminderAdmin.waiting_start)
        await callback.message.answer(t(callback.from_user.id, "rem_ask_start"))
    elif field == "channel":
        await state.set_state(ReminderAdmin.waiting_channel)
        await callback.message.answer(t(callback.from_user.id, "rem_ask_channel"))
    elif field == "target":
        rows = [
            [InlineKeyboardButton(text=t(callback.from_user.id, "rem_target_channel"),
                                  callback_data="rem:settarget:channel")],
            [InlineKeyboardButton(text=t(callback.from_user.id, "rem_target_users"),
                                  callback_data="rem:settarget:users")],
            [InlineKeyboardButton(text=t(callback.from_user.id, "rem_target_both"),
                                  callback_data="rem:settarget:both")],
            [InlineKeyboardButton(text=t(callback.from_user.id, "rem_back"),
                                  callback_data="rem:back")],
        ]
        await safe_send_or_edit(callback, t(callback.from_user.id, "rem_target_pick"),
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@dp.callback_query(F.data.startswith("rem:settarget:"))
async def cb_rem_settarget(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    target = callback.data.split(":")[2]
    if target not in ("channel", "users", "both"):
        await callback.answer("Error", show_alert=True)
        return
    rem = get_reminder_settings()
    rem["target"] = target
    await save_db(DATABASE)
    await callback.answer(t(callback.from_user.id, "rem_saved"))
    await render_reminder_settings(callback, callback.from_user.id)


@dp.message(StateFilter(ReminderAdmin.waiting_time), F.text)
async def process_rem_time(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", raw):
        await message.answer(t(message.from_user.id, "rem_bad_time"))
        return
    hh, mm = map(int, raw.split(":"))
    if not (0 <= hh < 24 and 0 <= mm < 60):
        await message.answer(t(message.from_user.id, "rem_bad_time"))
        return
    rem = get_reminder_settings()
    rem["time"] = f"{hh:02d}:{mm:02d}"
    await save_db(DATABASE)
    await state.clear()
    await message.answer(t(message.from_user.id, "rem_saved"))
    await render_reminder_settings(message, message.from_user.id)
    await restart_reminder_scheduler()


@dp.message(StateFilter(ReminderAdmin.waiting_text_ru), F.text)
async def process_rem_text_ru(message: types.Message, state: FSMContext):
    rem = get_reminder_settings()
    rem["text_ru"] = message.text.strip()
    await save_db(DATABASE)
    await state.clear()
    await message.answer(t(message.from_user.id, "rem_saved"))
    await render_reminder_settings(message, message.from_user.id)


@dp.message(StateFilter(ReminderAdmin.waiting_text_en), F.text)
async def process_rem_text_en(message: types.Message, state: FSMContext):
    rem = get_reminder_settings()
    rem["text_en"] = message.text.strip()
    await save_db(DATABASE)
    await state.clear()
    await message.answer(t(message.from_user.id, "rem_saved"))
    await render_reminder_settings(message, message.from_user.id)


@dp.message(StateFilter(ReminderAdmin.waiting_start), F.text)
async def process_rem_start(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    parts = raw.split()
    if not parts or not parts[0].isdigit():
        await message.answer(t(message.from_user.id, "rem_bad_start"))
        return
    start_day = int(parts[0])
    if start_day < 1 or start_day > 100000:
        await message.answer(t(message.from_user.id, "rem_bad_start"))
        return
    start_date = None
    if len(parts) >= 2:
        try:
            datetime.strptime(parts[1], "%Y-%m-%d")
            start_date = parts[1]
        except ValueError:
            await message.answer(t(message.from_user.id, "rem_bad_date"))
            return
    rem = get_reminder_settings()
    rem["start_day"] = start_day
    rem["start_date"] = start_date
    await save_db(DATABASE)
    await state.clear()
    await message.answer(t(message.from_user.id, "rem_saved"))
    await render_reminder_settings(message, message.from_user.id)


@dp.message(StateFilter(ReminderAdmin.waiting_channel), F.text)
async def process_rem_channel(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    if not (raw.startswith("@") or raw.lstrip("-").isdigit()):
        await message.answer(t(message.from_user.id, "rem_ask_channel"))
        return
    rem = get_reminder_settings()
    rem["channel"] = raw
    await save_db(DATABASE)
    await state.clear()
    await message.answer(t(message.from_user.id, "rem_saved"))
    await render_reminder_settings(message, message.from_user.id)
    await restart_reminder_scheduler()


@dp.callback_query(F.data == "rem:test")
async def cb_rem_test(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    try:
        await send_reminder_now()
        await callback.answer(t(callback.from_user.id, "rem_test_ok"), show_alert=False)
    except Exception as e:
        await callback.answer(t(callback.from_user.id, "rem_test_fail", err=str(e)), show_alert=True)


# ============================================================
# ADMIN: MANUAL UPLOAD
# ============================================================

@dp.callback_query(F.data == "admin:upload")
async def cb_admin_upload(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.set_state(AdminUpload.waiting_document)
    await state.update_data(file_id=None, file_name="", title="", description="",
                            selected_tags=[], difficulty="medium", upl_cats=[])
    await callback.message.answer(t(callback.from_user.id, "admin_upload_ask"))
    await callback.answer()


@dp.message(StateFilter(AdminUpload.waiting_document), F.document | F.photo)
async def process_upl_document(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "material"
    else:
        file_id = message.photo[-1].file_id
        file_name = "photo.jpg"
    await state.update_data(file_id=file_id, file_name=file_name)
    await state.set_state(AdminUpload.waiting_title)
    await message.answer(t(message.from_user.id, "admin_upload_title"))


@dp.message(StateFilter(AdminUpload.waiting_title), F.text)
async def process_upl_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip()[:200])
    await state.set_state(AdminUpload.waiting_description)
    await message.answer(t(message.from_user.id, "admin_upload_desc"))


@dp.message(StateFilter(AdminUpload.waiting_description), F.text)
async def process_upl_description(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    if raw.lower() in ("пропустить", "skip", "-"):
        raw = ""
    await state.update_data(description=raw)
    await state.set_state(AdminUpload.choosing_tags)
    await message.answer(t(message.from_user.id, "admin_upload_tags"),
                         reply_markup=await get_tag_toggle_keyboard([], "upl:tag", "upl:tags_done",
                                                                    message.from_user.id,
                                                                    "⏭", "upl:tags_skip"))


@dp.callback_query(StateFilter(AdminUpload.choosing_tags), F.data.startswith("upl:tag:"))
async def cb_upl_tag(callback: types.CallbackQuery, state: FSMContext):
    res = await toggle_tag_by_index(callback, state)
    if not res:
        return
    selected, tag, removed = res
    await safe_send_or_edit(callback, t(callback.from_user.id, "choose_tags_n", n=len(selected)),
                            reply_markup=await get_tag_toggle_keyboard(selected, "upl:tag", "upl:tags_done",
                                                                       callback.from_user.id,
                                                                       "⏭", "upl:tags_skip"))
    await callback.answer(t(callback.from_user.id, "search_tag_off" if removed else "search_tag_on"))


@dp.callback_query(F.data == "upl:tags_done", StateFilter(AdminUpload.choosing_tags))
async def cb_upl_tags_done(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminUpload.choosing_difficulty)
    builder = [[InlineKeyboardButton(text=t(callback.from_user.id, f"admin_diff_{lvl}"),
                                     callback_data=f"upl:diff:{lvl}")]
               for lvl in DIFF_KEYS]
    builder.append([InlineKeyboardButton(text="❌", callback_data="menu:main")])
    await safe_send_or_edit(callback, t(callback.from_user.id, "admin_upload_diff"),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data == "upl:tags_skip", StateFilter(AdminUpload.choosing_tags))
async def cb_upl_tags_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(selected_tags=[])
    await state.set_state(AdminUpload.choosing_difficulty)
    builder = [[InlineKeyboardButton(text=t(callback.from_user.id, f"admin_diff_{lvl}"),
                                     callback_data=f"upl:diff:{lvl}")]
               for lvl in DIFF_KEYS]
    builder.append([InlineKeyboardButton(text="❌", callback_data="menu:main")])
    await safe_send_or_edit(callback, t(callback.from_user.id, "admin_upload_diff"),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(StateFilter(AdminUpload.choosing_difficulty), F.data.startswith("upl:diff:"))
async def cb_upl_diff(callback: types.CallbackQuery, state: FSMContext):
    level = callback.data.split(":", 2)[2]
    if level in DIFF_KEYS:
        await state.update_data(difficulty=level)
    await state.set_state(AdminUpload.choosing_categories)
    data = await state.get_data()
    await safe_send_or_edit(callback, t(callback.from_user.id, "admin_upload_cats"),
                            reply_markup=await get_category_toggle_keyboard(data.get("upl_cats", []),
                                                                            callback.from_user.id))
    await callback.answer()


@dp.callback_query(StateFilter(AdminUpload.choosing_categories), F.data.startswith("upl:cat:"))
async def cb_upl_cat(callback: types.CallbackQuery, state: FSMContext):
    cat_key = callback.data.split(":", 2)[2]
    if cat_key not in DATABASE.get("categories", {}):
        await callback.answer(t(callback.from_user.id, "admin_upload_cat_missing"), show_alert=True)
        return
    data = await state.get_data()
    cats = list(data.get("upl_cats", []))
    if cat_key in cats:
        cats.remove(cat_key)
        selected = False
    else:
        cats.append(cat_key)
        selected = True
    await state.update_data(upl_cats=cats)
    await safe_send_or_edit(callback, t(callback.from_user.id, "admin_upload_cats"),
                            reply_markup=await get_category_toggle_keyboard(cats, callback.from_user.id))
    await callback.answer("✅" if selected else "▫️")


@dp.callback_query(F.data == "upl:publish", StateFilter(AdminUpload.choosing_categories))
async def cb_upl_publish(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    data = await state.get_data()
    if not data.get("file_id"):
        await callback.answer(t(callback.from_user.id, "submit_first_file"), show_alert=True)
        return
    cats = [c for c in data.get("upl_cats", []) if c in DATABASE.get("categories", {})]
    if not cats:
        await callback.answer(t(callback.from_user.id, "admin_upload_no_cat"), show_alert=True)
        return
    entry = {
        "file_unique_id": str(uuid.uuid4()),
        "file_id": data["file_id"],
        "file_name": data.get("file_name", ""),
        "caption": data.get("title") or "—",
        "summary": data.get("description", ""),
        "tags": data.get("selected_tags", []),
        "difficulty": data.get("difficulty", "medium"),
        "must_read": False,
        "added_at": get_yerevan_date(),
    }
    titles = []
    for cat_key in cats:
        DATABASE["categories"][cat_key].setdefault("files", []).append(copy.deepcopy(entry))
        titles.append(DATABASE["categories"][cat_key].get("title", cat_key))
    await save_db(DATABASE)
    await state.clear()
    await callback.message.answer(
        t(callback.from_user.id, "admin_upload_published",
          title=html.escape(entry['caption']),
          cats=html.escape(', '.join(titles))),
        parse_mode=ParseMode.HTML,
    )
    await announce_file_to_channel(entry, titles)
    await callback.answer(t(callback.from_user.id, "admin_upload_done_short"))


@dp.callback_query(F.data == "upl:publish")
async def cb_upl_publish_stale(callback: types.CallbackQuery):
    await callback.answer(t(callback.from_user.id, "admin_upload_stale"), show_alert=True)


# ============================================================
# ADMIN: ADD DAILY TASK
# ============================================================

@dp.callback_query(F.data == "admin:add_task")
async def cb_add_task(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.set_state(TaskOfDayAdmin.waiting_for_photo)
    await state.update_data(task_photo=None, task_text="", solution_text="",
                            solution_photo=None, solution_document=None)
    await callback.message.answer(t(callback.from_user.id, "admin_task_photo"))
    await callback.answer()


@dp.message(StateFilter(TaskOfDayAdmin.waiting_for_photo))
async def process_task_photo(message: types.Message, state: FSMContext):
    if message.photo:
        await state.update_data(task_photo=message.photo[-1].file_id)
    elif message.text and message.text.strip().lower() in ("пропустить", "skip", "-"):
        await state.update_data(task_photo=None)
    else:
        await message.answer(t(message.from_user.id, "admin_task_photo_ask"))
        return
    await state.set_state(TaskOfDayAdmin.waiting_for_task_text)
    await message.answer(t(message.from_user.id, "admin_task_text"))


@dp.message(StateFilter(TaskOfDayAdmin.waiting_for_task_text), F.text)
async def process_task_text(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    if raw.lower() in ("пропустить", "skip", "-"):
        raw = ""
    await state.update_data(task_text=raw)
    await state.set_state(TaskOfDayAdmin.waiting_for_solution)
    await message.answer(t(message.from_user.id, "admin_task_solution"))


@dp.message(StateFilter(TaskOfDayAdmin.waiting_for_solution))
async def process_task_solution(message: types.Message, state: FSMContext):
    if message.photo:
        await state.update_data(solution_photo=message.photo[-1].file_id)
        if message.caption:
            await state.update_data(solution_text=message.caption.strip())
    elif message.document:
        await state.update_data(solution_document=message.document.file_id)
    elif message.text and message.text.strip().lower() in ("пропустить", "skip", "-"):
        await state.update_data(solution_text="", solution_photo=None, solution_document=None)
    elif message.text:
        await state.update_data(solution_text=message.text.strip())
    else:
        await message.answer(t(message.from_user.id, "admin_task_sol_ask"))
        return
    await state.set_state(TaskOfDayAdmin.waiting_for_date)
    await message.answer(t(message.from_user.id, "admin_task_date"))


@dp.message(StateFilter(TaskOfDayAdmin.waiting_for_date), F.text)
async def process_task_date(message: types.Message, state: FSMContext):
    raw = message.text.strip().lower()
    if raw in ("сегодня", "today"):
        date_str = get_yerevan_date()
    elif raw in ("завтра", "tomorrow"):
        date_str = (datetime.now(YEREVAN_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        try:
            date_str = datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            await message.answer(t(message.from_user.id, "admin_task_bad_date"))
            return
    data = await state.get_data()
    group = DATABASE.setdefault("daily_tasks", {}).setdefault(date_str, {"tasks": []})
    group.setdefault("tasks", [])
    task = {
        "task_id": uuid.uuid4().hex[:10],
        "text": data.get("task_text", ""),
        "photo_file_id": data.get("task_photo"),
        "solution": data.get("solution_text", ""),
        "solution_photo_file_id": data.get("solution_photo"),
        "solution_document_file_id": data.get("solution_document"),
        "difficulty": "medium",
        "tags": [],
        "source": "admin",
        "user_solutions": {},
        "created_at": get_yerevan_date(),
        "number": len(group["tasks"]) + 1,
    }
    group["tasks"].append(task)
    await save_db(DATABASE)
    await state.clear()
    await message.answer(t(message.from_user.id, "admin_task_added",
                           date=date_str, num=task['number']),
                         parse_mode=ParseMode.HTML)
    await broadcast_task(date_str, len(group["tasks"]) - 1, report_msg=message)


# ============================================================
# ADMIN: STATS / SUBMISSIONS / PENDING / BROADCAST
# ============================================================

@dp.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.clear()
    users = DATABASE.get("users", {})
    total_files = sum(len(c.get("files", [])) for c in DATABASE.get("categories", {}).values())
    tasks_total = sum(len(g.get("tasks", [])) for g in DATABASE.get("daily_tasks", {}).values())
    pending_sols = 0
    for group in DATABASE.get("daily_tasks", {}).values():
        for task in group.get("tasks", []):
            pending_sols += sum(1 for s in (task.get("user_solutions") or {}).values()
                                if s.get("status") == "pending")
    pending_subs = await submissions_collection.count_documents({"status": "pending"})
    top = sorted(users.items(), key=lambda kv: kv[1].get("score", 0), reverse=True)[:5]
    top_lines = "\n".join(
        f"  {i}. 🪪 {html.escape(u.get('nickname') or u.get('username') or f'id{uid_str}')} — "
        f"{html.escape(u.get('first_name') or '')}"
        + (f" (@{html.escape(u.get('username'))})" if u.get("username") else "")
        + f" — {u.get('score', 0)}"
        for i, (uid_str, u) in enumerate(top, 1)
    ) or "  —"
    text = t(callback.from_user.id, "admin_stats_title",
             users=len(users), files=total_files, tags=len(DATABASE.get('tags', [])),
             tasks=tasks_total, pending=pending_sols, subs=pending_subs, top=top_lines)
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=t(callback.from_user.id, "back_admin"), callback_data="admin:main")]])
    await safe_send_or_edit(callback, text, reply_markup=markup)
    await callback.answer()


@dp.callback_query(F.data == "admin:submissions")
async def cb_admin_submissions(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.clear()
    subs = []
    async for s in submissions_collection.find({"status": "pending"}).sort("created_at", -1):
        subs.append(s)
        if len(subs) >= 10:
            break
    if not subs:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=t(callback.from_user.id, "back_admin"), callback_data="admin:main")]])
        await safe_send_or_edit(callback, t(callback.from_user.id, "admin_subs_empty"), reply_markup=markup)
        await callback.answer()
        return
    lines = [t(callback.from_user.id, "admin_subs_title")]
    builder = []
    for s in subs:
        sid = s["_id"]
        title = html.escape(s.get("title") or s.get("file_name") or "—")
        nick = html.escape(s.get("nickname") or "—")
        tg = html.escape(s.get("first_name") or "")
        uname = s.get("username") or ""
        lines.append(f"• <b>{title}</b>\n   🪪 {nick} · 👤 {tg}"
                     + (f" · @{html.escape(uname)}" if uname else ""))
        builder.append([
            InlineKeyboardButton(text=t(callback.from_user.id, "admin_subs_accept"), callback_data=f"admin:sub_accept:{sid}"),
            InlineKeyboardButton(text=t(callback.from_user.id, "admin_subs_reject"), callback_data=f"admin:sub_reject:{sid}"),
        ])
    builder.append([InlineKeyboardButton(text=t(callback.from_user.id, "back_admin"), callback_data="admin:main")])
    await safe_send_or_edit(callback, "\n".join(lines),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin:sub_accept:"))
async def cb_sub_accept(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    sub_id = callback.data.split(":", 2)[2]
    sub = await get_submission(sub_id)
    if not sub or sub.get("status") != "pending":
        await callback.answer(t(callback.from_user.id, "admin_subs_already"), show_alert=True)
        return
    await save_submission(sub_id, {"status": "accepted",
                                   "processed_at": datetime.now(YEREVAN_TZ).isoformat()})
    rows = []
    for cat_key, cat_data in DATABASE.get("categories", {}).items():
        tr_title = await localize(cat_data.get("title", cat_key), callback.from_user.id)
        rows.append([InlineKeyboardButton(text=tr_title, callback_data=f"subcat:{sub_id}:{cat_key}")])
    rows.append([InlineKeyboardButton(text=t(callback.from_user.id, "back_admin"), callback_data="admin:main")])
    await callback.message.answer(t(callback.from_user.id, "admin_subs_pick_cat"),
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@dp.callback_query(F.data.startswith("subcat:"))
async def cb_subcat(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Error", show_alert=True)
        return
    sub_id, cat_key = parts[1], parts[2]
    sub = await get_submission(sub_id)
    if not sub:
        await callback.answer(t(callback.from_user.id, "admin_subs_not_found"), show_alert=True)
        return
    if sub.get("status") == "published":
        await callback.answer(t(callback.from_user.id, "admin_subs_already_pub"), show_alert=True)
        return
    if cat_key not in DATABASE.get("categories", {}):
        await callback.answer(t(callback.from_user.id, "admin_upload_cat_missing"), show_alert=True)
        return
    entry = {
        "file_unique_id": str(uuid.uuid4()),
        "file_id": sub.get("file_id"),
        "file_name": sub.get("file_name") or "",
        "caption": sub.get("title") or "—",
        "summary": "",
        "tags": sub.get("tags", []),
        "difficulty": "medium",
        "must_read": False,
        "added_at": get_yerevan_date(),
    }
    DATABASE["categories"][cat_key].setdefault("files", []).append(entry)
    await save_db(DATABASE)
    await save_submission(sub_id, {"status": "published"})
    cat_title = DATABASE["categories"][cat_key].get("title", cat_key)
    try:
        await bot.send_message(sub.get("user_id"),
                               t(sub.get("user_id"), "admin_subs_user_notify", title=entry['caption']))
    except Exception:
        logger.warning("Failed to notify user %s", sub.get("user_id"))
    await callback.message.answer(t(callback.from_user.id, "admin_subs_published",
                                    cat=html.escape(cat_title)))
    await announce_file_to_channel(entry, [cat_title])
    await callback.answer("✅")


@dp.callback_query(F.data.startswith("admin:sub_reject:"))
async def cb_sub_reject(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    sub_id = callback.data.split(":", 2)[2]
    sub = await get_submission(sub_id)
    if not sub or sub.get("status") != "pending":
        await callback.answer(t(callback.from_user.id, "admin_subs_already"), show_alert=True)
        return
    await save_submission(sub_id, {"status": "rejected",
                                   "processed_at": datetime.now(YEREVAN_TZ).isoformat()})
    try:
        await bot.send_message(sub.get("user_id"), t(sub.get("user_id"), "admin_subs_reject_notify"))
    except Exception:
        pass
    await callback.message.answer(t(callback.from_user.id, "admin_subs_rejected"))
    await callback.answer("❌")


@dp.callback_query(F.data == "admin:pending_sols")
async def cb_pending_sols(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.clear()
    lines = [t(callback.from_user.id, "admin_pending_title")]
    builder = []
    found = 0
    stop = False
    for date_str in get_dates_sorted():
        if stop:
            break
        group = DATABASE["daily_tasks"][date_str]
        for idx, task in enumerate(group.get("tasks", [])):
            if stop:
                break
            for uid_str, s in (task.get("user_solutions") or {}).items():
                if s.get("status") != "pending":
                    continue
                found += 1
                lines.append(f"• {date_str} · №{task['number']} — 🪪 "
                             f"{html.escape(s.get('nickname') or get_nickname(uid_str))} · "
                             f"👤 {html.escape(s.get('first_name') or '')}")
                builder.append([
                    InlineKeyboardButton(text="👀", callback_data=f"solfull:{date_str}:{idx}:{uid_str}"),
                    InlineKeyboardButton(text="✅", callback_data=f"solrev:ok:{date_str}:{idx}:{uid_str}"),
                    InlineKeyboardButton(text="❌", callback_data=f"solrev:no:{date_str}:{idx}:{uid_str}"),
                ])
                if found >= 10:
                    stop = True
                    break
    if not found:
        lines.append(t(callback.from_user.id, "admin_pending_empty"))
    else:
        lines.append(t(callback.from_user.id, "admin_pending_shown", n=found))
    builder.append([InlineKeyboardButton(text=t(callback.from_user.id, "back_admin"), callback_data="admin:main")])
    await safe_send_or_edit(callback, "\n".join(lines),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await callback.answer()


@dp.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.set_state(BroadcastAdmin.waiting_for_message)
    await callback.message.answer(t(callback.from_user.id, "admin_bcast_ask"))
    await callback.answer()


@dp.message(StateFilter(BroadcastAdmin.waiting_for_message))
async def process_broadcast(message: types.Message, state: FSMContext):
    await message.answer(t(message.from_user.id, "admin_bcast_running"))
    users = DATABASE.get("users", {})
    sent, failed = 0, 0
    for uid_str in list(users.keys()):
        try:
            await message.copy_to(int(uid_str))
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await message.copy_to(int(uid_str))
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await state.clear()
    await message.answer(t(message.from_user.id, "admin_bcast_done", sent=sent, failed=failed))


# ============================================================
# ADMIN: EDIT / DELETE FILE
# ============================================================

@dp.callback_query(F.data.startswith("admin:edit_file:"))
async def cb_edit_file(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    uid = callback.data.split(":", 2)[2]
    f = get_file_by_uid(uid)
    if not f:
        await callback.answer(t(callback.from_user.id, "no_file"), show_alert=True)
        return
    await state.clear()
    await state.update_data(edit_uid=uid)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(callback.from_user.id, "admin_edit_replace"), callback_data="admin:efile:doc")],
        [InlineKeyboardButton(text=t(callback.from_user.id, "admin_edit_rename"), callback_data="admin:efile:title"),
         InlineKeyboardButton(text=t(callback.from_user.id, "admin_edit_tags"), callback_data="admin:efile:tags")],
        [InlineKeyboardButton(text=t(callback.from_user.id, "admin_edit_back"), callback_data=f"file:view:{uid}")],
    ])
    await safe_send_or_edit(callback,
                            t(callback.from_user.id, "admin_edit_title", title=html.escape(f.get('caption') or '')),
                            reply_markup=markup)
    await callback.answer()


@dp.callback_query(F.data == "admin:efile:doc")
async def cb_efile_doc(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.set_state(EditFile.waiting_for_document)
    await callback.message.answer(t(callback.from_user.id, "admin_edit_ask_doc"))
    await callback.answer()


@dp.message(StateFilter(EditFile.waiting_for_document), F.document | F.photo)
async def process_efile_doc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("edit_uid")
    if not uid:
        await state.clear()
        return
    new_id = message.document.file_id if message.document else message.photo[-1].file_id
    n = update_file_field(uid, "file_id", new_id)
    await save_db(DATABASE)
    await state.clear()
    await message.answer(t(message.from_user.id, "admin_edit_doc_done", n=n))


@dp.callback_query(F.data == "admin:efile:title")
async def cb_efile_title(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.set_state(EditFile.waiting_for_title)
    await callback.message.answer(t(callback.from_user.id, "admin_edit_ask_title"))
    await callback.answer()


@dp.message(StateFilter(EditFile.waiting_for_title), F.text)
async def process_efile_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("edit_uid")
    if not uid:
        await state.clear()
        return
    n = update_file_field(uid, "caption", message.text.strip()[:200])
    await save_db(DATABASE)
    await state.clear()
    await message.answer(t(message.from_user.id, "admin_edit_title_done", n=n))
    await show_file_card(message, uid, message.from_user.id)


@dp.callback_query(F.data == "admin:efile:tags")
async def cb_efile_tags(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    await state.set_state(EditFile.waiting_for_tags)
    await callback.message.answer(t(callback.from_user.id, "admin_edit_ask_tags"))
    await callback.answer()


@dp.message(StateFilter(EditFile.waiting_for_tags), F.text)
async def process_efile_tags(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("edit_uid")
    if not uid:
        await state.clear()
        return
    raw = message.text.strip()
    if raw.lower() in ("очистить", "clear"):
        tags = []
    else:
        tags = normalize_tags_input(raw)
        db_tags = DATABASE.setdefault("tags", [])
        for tag in tags:
            if tag.lower() not in {x.lower() for x in db_tags}:
                db_tags.append(tag)
    n = update_file_field(uid, "tags", tags)
    await save_db(DATABASE)
    await state.clear()
    await message.answer(t(message.from_user.id, "admin_edit_tags_done", n=n))
    await show_file_card(message, uid, message.from_user.id)


@dp.callback_query(F.data.startswith("admin:del_file:"))
async def cb_del_file(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    uid = callback.data.split(":", 2)[2]
    f = get_file_by_uid(uid)
    if not f:
        await callback.answer(t(callback.from_user.id, "no_file"), show_alert=True)
        return
    await state.clear()
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(callback.from_user.id, "admin_del_yes"),
                              callback_data=f"admin:del_file_yes:{uid}")],
        [InlineKeyboardButton(text=t(callback.from_user.id, "submit_cancel"),
                              callback_data=f"file:view:{uid}")],
    ])
    await safe_send_or_edit(callback,
                            t(callback.from_user.id, "admin_del_confirm",
                              title=html.escape(f.get('caption') or '')),
                            reply_markup=markup)
    await callback.answer()


@dp.callback_query(F.data.startswith("admin:del_file_yes:"))
async def cb_del_file_yes(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(t(callback.from_user.id, "only_admin"), show_alert=True)
        return
    uid = callback.data.split(":", 2)[2]
    removed = 0
    for cat_data in DATABASE.get("categories", {}).values():
        files = cat_data.get("files", [])
        new_files = [f for f in files if f.get("file_unique_id") != uid]
        removed += len(files) - len(new_files)
        cat_data["files"] = new_files
    for u in DATABASE.get("users", {}).values():
        favs = u.get("favorites", [])
        if uid in favs:
            favs.remove(uid)
    await save_db(DATABASE)
    await callback.message.answer(t(callback.from_user.id, "admin_del_done", n=removed))
    await callback.answer("🗑")


# ============================================================
# INLINE MODE
# ============================================================

@dp.inline_query()
async def inline_catalog_search(query: InlineQuery):
    q = (query.query or "").strip().lower().lstrip("#")
    files = get_catalog_files_list()
    if q:
        def matches(f):
            hay = (f["caption"] + " " + " ".join(f.get("tags", [])) + " "
                   + (f.get("summary") or "")).lower()
            return q in hay
        files = [f for f in files if matches(f)]
    results = []
    for f in files[:10]:
        try:
            results.append(InlineQueryResultCachedDocument(
                id=f["uid"],
                title=f["caption"] or "Material",
                document_file_id=f["file_id"],
                description=(f.get("summary") or f.get("category") or "MathAm")[:200],
                caption=f"📖 <b>{html.escape(f['caption'])}</b>",
                parse_mode=ParseMode.HTML,
            ))
        except Exception:
            continue
    if not results:
        results = [InlineQueryResultArticle(
            id="not_found",
            title="🔎 Nothing found",
            description="Open the bot to search by tags",
            input_message_content=InputTextMessageContent(
                message_text="🤖 MathAm: /start"
            ),
        )]
    try:
        await query.answer(results, is_personal=True, cache_time=30)
    except Exception:
        logger.exception("Inline answer failed")


# ============================================================
# DAILY REMINDER
# ============================================================

def _calc_reminder_day_for_date(target_date) -> int:
    rem = get_reminder_settings()
    start_day = int(rem.get("start_day") or 1)
    sd = rem.get("start_date")
    if sd:
        try:
            start_date = datetime.strptime(sd, "%Y-%m-%d").date()
            delta = (target_date - start_date).days
            return start_day + max(0, delta)
        except Exception:
            pass
    return start_day


async def send_reminder_now():
    """Send the reminder immediately (used by scheduler and test button)."""
    rem = get_reminder_settings()
    today = datetime.now(MSK_TZ).date()
    day_number = _calc_reminder_day_for_date(today)

    text_ru = rem.get("text_ru") or TEXTS["ru"]["reminder"]
    text_en = rem.get("text_en") or TEXTS["en"]["reminder"]
    try:
        msg_ru = text_ru.format(n=day_number)
    except Exception:
        msg_ru = text_ru
    try:
        msg_en = text_en.format(n=day_number)
    except Exception:
        msg_en = text_en

    channel = rem.get("channel") or CHANNEL_ID
    target = rem.get("target", "channel")

    if target in ("channel", "both"):
        try:
            await bot.send_message(channel, msg_ru)
        except Exception as e:
            logger.exception("Failed to send reminder to channel %s", channel)
            raise

    if target in ("users", "both"):
        for uid_str, u in list(DATABASE.get("users", {}).items()):
            lang = u.get("language", "ru")
            text = msg_en if lang == "en" else msg_ru
            try:
                await bot.send_message(int(uid_str), text)
            except Exception:
                pass
            await asyncio.sleep(0.05)

    logger.info("Reminder sent (day %s, target=%s, channel=%s)", day_number, target, channel)


async def reminder_scheduler():
    while True:
        try:
            rem = get_reminder_settings()
            time_str = rem.get("time", "19:00")
            try:
                hh, mm = map(int, time_str.split(":"))
            except Exception:
                hh, mm = 19, 0
            now = datetime.now(MSK_TZ)
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            logger.info("Next reminder in %.0f sec (at %s MSK)", wait_seconds, target)
            await asyncio.sleep(wait_seconds)
            try:
                await send_reminder_now()
            except Exception:
                logger.exception("Reminder send failed")
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder scheduler error")
            await asyncio.sleep(60)


async def restart_reminder_scheduler():
    global REMINDER_TASK
    if REMINDER_TASK and not REMINDER_TASK.done():
        REMINDER_TASK.cancel()
        try:
            await REMINDER_TASK
        except Exception:
            pass
    REMINDER_TASK = asyncio.create_task(reminder_scheduler())
    logger.info("Reminder scheduler restarted")


# ============================================================
# FALLBACK
# ============================================================

@dp.message(F.text)
async def fallback_text(message: types.Message, state: FSMContext):
    state_name = await state.get_state()
    if state_name == UserSubmit.waiting_file:
        await message.answer(t(message.from_user.id, "expect_file"))
    elif state_name == AdminUpload.waiting_document:
        await message.answer(t(message.from_user.id, "expect_doc"))
    else:
        await message.answer(t(message.from_user.id, "unknown_text"))


@dp.callback_query()
async def cb_unhandled(callback: types.CallbackQuery):
    await callback.answer()


# ============================================================
# STARTUP & ENTRY POINT
# ============================================================

async def on_startup(bot: Bot):
    global DATABASE, BOT_USERNAME, REMINDER_TASK
    DATABASE = await load_db()
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    commands = [
        BotCommand(command="start", description="🏠 Menu / Меню"),
        BotCommand(command="catalog", description="📚 Catalog / Каталог"),
        BotCommand(command="language", description="🌐 Language / Язык"),
        BotCommand(command="cancel", description="❌ Cancel / Отмена"),
    ]
    await bot.set_my_commands(commands)
    REMINDER_TASK = asyncio.create_task(reminder_scheduler())
    total_files = sum(len(c.get("files", [])) for c in DATABASE.get("categories", {}).values())
    logger.info("Startup: %s users, %s files, %s tags, channel=%s",
                len(DATABASE.get("users", {})), total_files,
                len(DATABASE.get("tags", [])), CHANNEL_ID)


def register_middlewares():
    dp.message.outer_middleware(UserActivityMiddleware())
    dp.callback_query.outer_middleware(UserActivityMiddleware())
    dp.inline_query.outer_middleware(UserActivityMiddleware())


async def run_polling():
    register_middlewares()
    dp.startup.register(on_startup)
    await bot.delete_webhook(drop_pending_updates=True)
    port = os.environ.get("PORT")
    if port:
        async def health(request: web.Request) -> web.Response:
            return web.json_response({"status": "ok", "bot": BOT_USERNAME})
        app = web.Application()
        app.router.add_get("/", health)
        app.router.add_get("/health", health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=int(port))
        await site.start()
        logger.info("Health-check server on 0.0.0.0:%s", port)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def run_webhook():
    webhook_url = os.environ.get("WEBHOOK_URL", "").strip().rstrip("/")
    webhook_path = os.environ.get("WEBHOOK_PATH", "/tgbot").strip() or "/tgbot"

    async def set_webhook(bot: Bot):
        await bot.set_webhook(webhook_url + webhook_path, drop_pending_updates=True)
        logger.info("Webhook set: %s", webhook_url + webhook_path)

    register_middlewares()
    dp.startup.register(on_startup)
    dp.startup.register(set_webhook)
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=webhook_path)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    if os.environ.get("WEBHOOK_URL"):
        run_webhook()
    else:
        asyncio.run(run_polling())