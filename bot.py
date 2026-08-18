import asyncio
import logging
import random
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, BotCommand
from aiohttp import web

TOKEN = "8913891668:AAGhjDC6HjBpDeJdzKFpGkU6Pgq08_Blljs"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- 1. Простейший веб-сервер для бесплатного Web Service на Render ---
async def handle(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Веб-сервер мгновенно открыл порт {port}!")

async def set_main_menu(bot: Bot):
    main_menu_commands = [
        BotCommand(command="start", description="Запустить бота 🚀"),
        BotCommand(command="help", description="Как пользоваться? ℹ️"),
        BotCommand(command="surprise", description="Удиви меня 🎲")
    ]
    await bot.set_my_commands(main_menu_commands)

DATABASE = {
    "combinatorics": {
        "description": "✅ Держи материалы по комбинаторике",
        "files": [{"path": "files/combStefanWalzer.pdf", "caption": "Конспект лекций (KIT)"}]
    },
    "algebra": {
        "description": "✅ Лови материалы по алгебре!",
        "files": [{"path": "files/algebra.pdf", "caption": "Базовая алгебра"}]
    },
    "geometry": {
        "description": "✅ Геометрия подъехала!",
        "files": [{"path": "files/geometry_555.pdf", "caption": "Планиметрия и стереометрия"}]
    },
    "number_theory": {
        "description": "✅ Теория чисел для прокачки мозга!",
        "files": [{"path": "files/number_theory.pdf", "caption": "Основы теории чисел"}]
    },
    "inequalities": {
        "description": "✅ Неравенства — это сила!",
        "files": [{"path": "files/inequality.pdf", "caption": "Методы решения неравенств"}]
    },
    "olympiads": {
        "description": "✅ Олимпиадные задачи высшей пробы!",
        "files": [{"path": "files/olympiad.tasks.pdf", "caption": "Избранные олимпиадные задачи"}]
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
        try:
            file = FSInputFile(item["path"])
            await message.answer_document(document=file, caption=f"📄 {item['caption']}")
        except Exception:
            await message.answer(f"⚠️ Файл '{item['caption']}' не найден на сервере!")

@dp.message(Command("surprise"))
async def cmd_surprise(message: types.Message):
    random_key = random.choice(list(DATABASE.keys()))
    await message.answer(f"🎲 Тема: **{random_key.upper()}**!")
    await send_task_files(message, DATABASE[random_key])

@dp.message(F.text)
async def find_file(message: types.Message):
    query = message.text.strip().lower()
    if query in ["удиви меня", "surprise", "рандом"]:
        return await cmd_surprise(message)
    
    task = DATABASE.get(query)
    if task:
        await send_task_files(message, task)
    else:
        await message.answer("❌ Такого слова не нашлось. Попробуй /help")

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # 1. Сначала мгновенно поднимаем веб-сервер, чтобы Render сразу поймал порт
    await start_web_server()
    
    # 2. Настраиваем меню и запускаем бота
    await set_main_menu(bot)
    print("Бот и веб-сервер успешно запущены на бесплатном Web Service! 🚀")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
