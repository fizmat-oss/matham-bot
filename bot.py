import logging
import random
import os
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, BotCommand
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()

DATABASE = {
    "combinatorics": {
        "description": "✅ Держи материалы по комбинаторике",
        "files": [
            {"path": "files/combStefanWalzer.pdf", "caption": "Конспект лекций (KIT)"},
            {"path": "files/invariants.pdf", "caption": "Инварианты и полуинварианты"}
        ]
    },
    "algebra": {
        "description": "✅ Лови материалы по алгебре!",
        "files": [
            {"path": "files/algebra.pdf", "caption": "Базовая алгебра"},
            {"path": "files/functional.pdf", "caption": "Функциональные уравнения"}
        ]
    },
    "geometry": {
        "description": "✅ Геометрия подъехала!",
        "files": [
            {"path": "files/geometry_555.pdf", "caption": "Планиметрия и стереометрия"},
            {"path": "files/complexnumbergeometry.pdf", "caption": "Комплексные числа в геометрии"}
        ]
    },
    "number_theory": {
        "description": "✅ Теория чисел для прокачки мозга!",
        "files": [
            {"path": "files/number_theory.pdf", "caption": "Основы теории чисел"},
            {"path": "files/diofantequation.pdf", "caption": "Диофантовы уравнения"},
            {"path": "files/LTELemma.pdf", "caption": "Lifting The Exponent (LTE)"}
        ]
    },
    "inequalities": {
        "description": "✅ Неравенства — это сила!",
        "files": [
            {"path": "files/inequality.pdf", "caption": "Методы решения неравенств"},
            {"path": "files/inequality1.pdf", "caption": "Дополнительные задачи по неравенствам"}
        ]
    },
    "olympiads": {
        "description": "✅ Олимпиадные задачи высшей пробы!",
        "files": [
            {"path": "files/olympiad.tasks.pdf", "caption": "Избранные олимпиадные задачи"},
            {"path": "files/chinaolimpiadproblems.pdf", "caption": "Китайские олимпиадные задачи"}
        ]
    }
}

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
        file_path = item["path"]
        
        if not os.path.exists(file_path):
            logger.error(f"Файл не найден на сервере: {file_path}")
            await message.answer(f"⚠️ Файл '{item['caption']}' отсутствует на сервере!")
            continue

        try:
            file = FSInputFile(file_path)
            await message.answer_document(document=file, caption=f"📄 {item['caption']}")
        except Exception as e:
            logger.error(f"Ошибка при отправке {file_path}: {e}")
            await message.answer(f"⚠️ Ошибка при отправке файла '{item['caption']}'.")

@dp.message(Command("surprise"))
async def cmd_surprise(message: types.Message):
    random_key = random.choice(list(DATABASE.keys()))
    await message.answer(f"🎲 Тема: **{random_key.upper()}**!")
    await send_task_files(message, DATABASE[random_key])

# Обрабатываем только обычный текст, пропуская команды бота (начинающиеся с /)
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
    logger.info(f"🌐 Веб-сервер слушает порт {port}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await run_web_server()
    await set_main_menu(bot)
    logger.info("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
