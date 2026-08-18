import logging
import random
import os
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import BotCommand
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ C FILE_ID ВМЕСТО ПУТЕЙ К ФАЙЛАМ ---
DATABASE = {
    "combinatorics": {
        "description": "✅ Держи материалы по комбинаторике",
        "files": [
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_1", "caption": "Конспект лекций (KIT)"},
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_2", "caption": "Инварианты и полуинварианты"}
        ]
    },
    "algebra": {
        "description": "✅ Лови материалы по алгебре!",
        "files": [
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_3", "caption": "Базовая алгебра"},
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_4", "caption": "Функциональные уравнения"}
        ]
    },
    "geometry": {
        "description": "✅ Геометрия подъехала!",
        "files": [
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_5", "caption": "Планиметрия и стереометрия"},
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_6", "caption": "Комплексные числа в геометрии"}
        ]
    },
    "number_theory": {
        "description": "✅ Теория чисел для прокачки мозга!",
        "files": [
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_7", "caption": "Основы теории чисел"},
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_8", "caption": "Диофантовы уравнения"},
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_9", "caption": "Lifting The Exponent (LTE)"}
        ]
    },
    "inequalities": {
        "description": "✅ Неравенства — это сила!",
        "files": [
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_10", "caption": "Методы решения неравенств"},
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_11", "caption": "Дополнительные задачи по неравенствам"}
        ]
    },
    "olympiads": {
        "description": "✅ Олимпиадные задачи высшей пробы!",
        "files": [
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_12", "caption": "Избранные олимпиадные задачи"},
            {"file_id": "СУДА_ВСТАВЛЯЙ_FILE_ID_13", "caption": "Китайские олимпиадные задачи"}
        ]
    }
}

# --- ПОМОЩНИК: Выдает file_id при отправке любого файла боту ---
@dp.message(F.document)
async def get_file_id_handler(message: types.Message):
    doc = message.document
    await message.answer(
        f"📄 **Файл:** `{doc.file_name}`\n"
        f"🔑 **file_id:** (нажми, чтобы скопировать)\n`{doc.file_id}`"
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
    await message.answer(task["description"])
    for item in task["files"]:
        file_id = item["file_id"]
        
        # Защита от заглушек
        if "СУДА_ВСТАВЛЯЙ" in file_id:
            await message.answer(f"⚠️ Файл '{item['caption']}' ещё не настроен администратором.")
            continue

        try:
            # Отправка файла напрямую по file_id из серверов Telegram
            await message.answer_document(document=file_id, caption=f"📄 {item['caption']}")
        except Exception as e:
            logger.error(f"Ошибка отправки file_id {file_id}: {e}")
            await message.answer(f"⚠️ Ошибка при отправке файла '{item['caption']}'.")

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
