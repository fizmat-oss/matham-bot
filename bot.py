import logging
import random
import os
import json
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import BotCommand, FSInputFile
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
# Укажи свой Telegram ID (узнать можно у бота @userinfobot)
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))

bot = Bot(token=TOKEN)
dp = Dispatcher()

DB_FILE = "database.json"

# Начальная база данных
DEFAULT_DATABASE = {
    "combinatorics": {"description": "✅ Материалы по комбинаторике:", "files": []},
    "algebra": {"description": "✅ Материалы по алгебре:", "files": []},
    "geometry": {"description": "✅ Материалы по геометрии:", "files": []},
    "number_theory": {"description": "✅ Материалы по теории чисел:", "files": []},
    "inequalities": {"description": "✅ Материалы по неравенствам:", "files": []},
    "olympiads": {"description": "✅ Олимпиадные задачи:", "files": []}
}

# Функция загрузки базы из JSON
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения {DB_FILE}: {e}")
    return DEFAULT_DATABASE

# Функция сохранения базы в JSON
def save_db(db_data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db_data, f, ensure_ascii=False, indent=4)

DATABASE = load_db()

# --- АВТОМАТИЧЕСКОЕ ДОБАВЛЕНИЕ ФАЙЛОВ АДМИНОМ ---
@dp.message(F.document)
async def admin_add_file_handler(message: types.Message):
    # Проверка, что пишет именно администратор
    if message.from_user.id != ADMIN_ID:
        return await message.answer("ℹ️ Отправка файлов доступна только администратору.")

    caption = message.caption
    if not caption or "|" not in caption:
        return await message.answer(
            "⚠️ **Формат добавления файла:**\n"
            "Отправь PDF и напиши в подписи:\n"
            "`категория | Название файла`\n\n"
            "**Доступные категории:** `combinatorics`, `algebra`, `geometry`, `number_theory`, `inequalities`, `olympiads`\n\n"
            "*Пример:* `algebra | Базовая алгебра лекция 1`"
        )

    category, file_name = map(str.strip, caption.split("|", 1))
    category = category.lower()

    if category not in DATABASE:
        return await message.answer(f"❌ Категории `{category}` не существует!")

    doc = message.document
    new_file = {
        "file_id": doc.file_id,
        "caption": file_name
    }

    DATABASE[category]["files"].append(new_file)
    save_db(DATABASE)

    await message.answer(
        f"✅ **Файл успешно добавлен!**\n\n"
        f"📁 **Категория:** `{category}`\n"
        f"📄 **Название:** {file_name}\n"
        f"🔑 **file_id:** `{doc.file_id}`"
    )

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Здарова! ✌️\nЯ бот канала matham.\n"
        "Доступные разделы: `combinatorics`, `algebra`, `geometry`, `number_theory`, `inequalities`, `olympiads`.\n\n"
        "Просто напиши ключевое слово или жми **«Удиви меня»**! 🎲"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("Отправь ключевое слово (например, `algebra`), чтобы получить файлы.")

async def send_task_files(message: types.Message, task):
    if not task["files"]:
        return await message.answer("📁 В этом разделе пока нет файлов.")

    await message.answer(task["description"])
    for item in task["files"]:
        try:
            await message.answer_document(document=item["file_id"], caption=f"📄 {item['caption']}")
        except Exception as e:
            logger.error(f"Ошибка отправки file_id: {e}")

@dp.message(Command("surprise"))
async def cmd_surprise(message: types.Message):
    random_key = random.choice(list(DATABASE.keys()))
    await message.answer(f"🎲 Тема: **{random_key.upper()}**!")
    await send_task_files(message, DATABASE[random_key])

@dp.message(F.text & ~F.text.startswith("/"))
async def find_file(message: types.Message):
    query = message.text.strip().lower()
    if query in ["удиви меня", "surprise", "рандом"]:
        return await cmd_surprise(message)
    
    task = DATABASE.get(query)
    if task:
        await send_task_files(message, task)
    else:
        await message.answer("❌ Такого слова не нашлось. Попробуй /help")

async def set_main_menu(bot: Bot):
    main_menu_commands = [
        BotCommand(command="start", description="Запустить бота 🚀"),
        BotCommand(command="help", description="Как пользоваться? ℹ️"),
        BotCommand(command="surprise", description="Удиви меня 🎲")
    ]
    await bot.set_my_commands(main_menu_commands)

async def run_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await run_web_server()
    await set_main_menu(bot)
    logger.info("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
