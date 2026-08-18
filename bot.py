import asyncio
import logging
import random
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, BotCommand

# Твой токен
TOKEN = "8913891668:AAGhjDC6HjBpDeJdzKFpGkU6Pgq08_Blljs"

bot = Bot(token=TOKEN)
dp = Dispatcher()

async def set_main_menu(bot: Bot):
    main_menu_commands = [
        BotCommand(command="start", description="Запустить бота 🚀"),
        BotCommand(command="help", description="Как пользоваться? ℹ️"),
        BotCommand(command="surprise", description="Удиви меня 🎲")
    ]
    await bot.set_my_commands(main_menu_commands)

# РАСШИРЕННАЯ БАЗА ДАННЫХ
DATABASE = {
    "combinatorics": {
        "description": "✅ Держи материалы по комбинаторике",
        "files": [
            {"path": "files/combStefanWalzer.pdf", "caption": "Конспект лекций (KIT)"}
        ]
    },
    "algebra": {
        "description": "✅ Лови материалы по алгебре!",
        "files": [
            {"path": "files/algebra.pdf", "caption": "Базовая алгебра"}
        ]
    },
    "geometry": {
        "description": "✅ Геометрия подъехала!",
        "files": [
            {"path": "files/geometry_555.pdf", "caption": "Планиметрия и стереометрия"}
        ]
    },
    "number_theory": {
        "description": "✅ Теория чисел для прокачки мозга!",
        "files": [
            {"path": "files/number_theory.pdf", "caption": "Основы теории чисел"}
        ]
    },
    "inequalities": {
        "description": "✅ Неравенства — это сила!",
        "files": [
            {"path": "files/inequality.pdf", "caption": "Методы решения неравенств"}
        ]
    },
    "olympiads": {
        "description": "✅ Олимпиадные задачи высшей пробы!",
        "files": [
            {"path": "files/olympiad.tasks.pdf", "caption": "Избранные олимпиадные задачи"}
        ]
    }
}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Здарова! ✌️\n"
        "Я бот канала matham.\n"
        "Доступные разделы:\n"
        "• `combinatorics` — Комбинаторика\n"
        "• `algebra` — Алгебра\n"
        "• `geometry` — Геометрия\n"
        "• `number_theory` — Теория чисел\n"
        "• `inequalities` — Неравенства\n"
        "• `olympiads` — Олимпиады\n\n"
        "Просто напиши ключевое слово или жми кнопку **«Удиви меня»** в меню! 🎲"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "Отправь мне одно из ключевых слов (например, `algebra` или `geometry`), чтобы получить файлы по этой теме.\n"
        "А команда /surprise пришлет тебе случайный файл из базы!"
    )

# Функция отправки файлов по конкретной теме
async def send_task_files(message: types.Message, task):
    await message.answer(task["description"])
    for item in task["files"]:
        try:
            file = FSInputFile(item["path"])
            await message.answer_document(
                document=file,
                caption=f"📄 {item['caption']}"
            )
        except Exception:
            await message.answer(f"⚠️ Файл '{item['caption']}' не найден на сервере, сорян!")

# Команда /surprise и обработка кнопки "Удиви меня"
@dp.message(Command("surprise"))
async def cmd_surprise(message: types.Message):
    # Выбираем случайную тему из базы данных
    random_key = random.choice(list(DATABASE.keys()))
    task = DATABASE[random_key]
    
    await message.answer(f"🎲 Судьба выбрала для тебя тему: **{random_key.upper()}**!")
    await send_task_files(message, task)

@dp.message(F.text)
async def find_file(message: types.Message):
    query = message.text.strip().lower()
    
    # Если пользователь написал "удиви меня" текстом
    if query in ["удиви меня", "surprise", "рандом"]:
        await cmd_surprise(message)
        return

    task = DATABASE.get(query)
    
    if task:
        await send_task_files(message, task)
    else:
        await message.answer("❌ Такого ключевого слова не нашлось. Попробуй /help или нажми «Удиви меня»!")

async def main():
    logging.basicConfig(level=logging.INFO)
    await set_main_menu(bot)
    print("Бот запущен и готов к работе, братишка! 🚀")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
