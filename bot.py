import logging
import random
import os

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, BotCommand
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# --- Конфиг: токен и URL берём из переменных окружения Render ---
TOKEN = os.environ[8913891668:AAHvrcI511gul51lmt3mfI19W7jYy1CxJoE]
BASE_WEBHOOK_URL = os.environ[https://matham-bot.onrender.com]  # например https://matham-bot.onrender.com (без / на конце)
WEBHOOK_PATH = "/webhook"
PORT = int(os.environ.get("PORT", 10000))

bot = Bot(token=TOKEN)
dp = Dispatcher()

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


async def set_main_menu(bot: Bot):
    main_menu_commands = [
        BotCommand(command="start", description="Запустить бота 🚀"),
        BotCommand(command="help", description="Как пользоваться? ℹ️"),
        BotCommand(command="surprise", description="Удиви меня 🎲")
    ]
    await bot.set_my_commands(main_menu_commands)


async def on_startup(app: web.Application):
    await set_main_menu(bot)
    await bot.set_webhook(f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}")
    print(f"🚀 Webhook установлен: {BASE_WEBHOOK_URL}{WEBHOOK_PATH}")


async def on_shutdown(app: web.Application):
    await bot.delete_webhook()


async def handle_root(request):
    return web.Response(text="Bot is running!")


def main():
    logging.basicConfig(level=logging.INFO)

    app = web.Application()
    app.router.add_get("/", handle_root)

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
