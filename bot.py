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

# --- БАЗА ДАННЫХ: ПО 5 ФАЙЛОВ НА КАЖДУЮ ТЕМУ (ЛОКАЛЬНЫЕ ПУТИ) ---
DATABASE = {
    "combinatorics": {
        "description": "✅ Держи материалы по комбинаторике:",
        "files": [
            {"path": "files/comb1.pdf", "caption": "Конспект лекций (KIT)"},
            {"path": "files/comb2.pdf", "caption": "Инварианты и полуинварианты"},
            {"path": "files/comb3.pdf", "caption": "Графы и их приложения"},
            {"path": "files/comb4.pdf", "caption": "Принцип Дирихле и раскраски"},
            {"path": "files/comb5.pdf", "caption": "Рекуррентные соотношения"}
        ]
    },
    "algebra": {
        "description": "✅ Лови материалы по алгебре:",
        "files": [
            {"path": "files/alg1.pdf", "caption": "Базовая алгебра"},
            {"path": "files/alg2.pdf", "caption": "Функциональные уравнения"},
            {"path": "files/alg3.pdf", "caption": "Многочлены и их корни"},
            {"path": "files/alg4.pdf", "caption": "Системы уравнений"},
            {"path": "files/alg5.pdf", "caption": "Линейная алгебра для олимпиад"}
        ]
    },
    "geometry": {
        "description": "✅ Геометрия подъехала:",
        "files": [
            {"path": "files/geom1.pdf", "caption": "Планиметрия и стереометрия"},
            {"path": "files/geom2.pdf", "caption": "Комплексные числа в геометрии"},
            {"path": "files/geom3.pdf", "caption": "Вписанные и описанные окружности"},
            {"path": "files/geom4.pdf", "caption": "Векторный метод в геометрии"},
            {"path": "files/geom5.pdf", "caption": "Проективная геометрия"}
        ]
    },
    "number_theory": {
        "description": "✅ Теория чисел для прокачки мозга:",
        "files": [
            {"path": "files/nt1.pdf", "caption": "Основы теории чисел"},
            {"path": "files/nt2.pdf", "caption": "Диофантовы уравнения"},
            {"path": "files/nt3.pdf", "caption": "Lifting The Exponent (LTE)"},
            {"path": "files/nt4.pdf", "caption": "Сравнения по модулю и Малая теорема Ферма"},
            {"path": "files/nt5.pdf", "caption": "Первообразные корни и квадратичные вычеты"}
        ]
    },
    "inequalities": {
        "description": "✅ Неравенства — это сила:",
        "files": [
            {"file_path": "files/ineq1.pdf", "path": "files/ineq1.pdf", "caption": "Методы решения неравенств"},
            {"path": "files/ineq2.pdf", "caption": "Дополнительные задачи по неравенствам"},
            {"path": "files/ineq3.pdf", "caption": "Неравенство Коши-Буняковского-Шварца"},
            {"path": "files/ineq4.pdf", "caption": "Метод штурма и симметричные неравенства"},
            {"path": "files/ineq5.pdf", "caption": "Неравенство Йенсена и выпуклость"}
        ]
    },
    "olympiads": {
        "description": "✅ Олимпиадные задачи высшей пробы:",
        "files": [
            {"path": "files/olymp1.pdf", "caption": "Избранные олимпиадные задачи"},
            {"path": "files/olymp2.pdf", "caption": "Китайские олимпиадные задачи"},
            {"path": "files/olymp3.pdf", "caption": "Задачи Международной олимпиады (IMO)"},
            {"path": "files/olymp4.pdf", "caption": "Всероссийская олимпиада школьников"},
            {"path": "files/olymp5.pdf", "caption": "Шортлисты IMO прошлых лет"}
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
        
        # Проверка 1: Если файла нет на сервере, бот не падает, а просто сообщает об этом
        if not os.path.exists(file_path):
            logger.warning(f"Файл не найден: {file_path}")
            await message.answer(f"⚠️ Файл '{item['caption']}' временно недоступен.")
            continue

        # Проверка 2: Безопасная отправка
        try:
            file = FSInputFile(file_path)
            await message.answer_document(document=file, caption=f"📄 {item['caption']}")
        except Exception as e:
            logger.error(f"Ошибка при отправке файла {file_path}: {e}")
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
