import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# -------------------------------------------------------------------
# НАСТРОЙКИ (Замените на свои данные)
# -------------------------------------------------------------------
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"
ADMIN_ID = 123456789  # Ваш Telegram ID (число)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# -------------------------------------------------------------------
# СОСТОЯНИЯ (FSM)
# -------------------------------------------------------------------
class AdminStates(StatesGroup):
    waiting_for_file = State()


# -------------------------------------------------------------------
# КЛАВИАТУРЫ
# -------------------------------------------------------------------
def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для админ-панели."""
    buttons = [
        [InlineKeyboardButton(text="📁 Изменить файл", callback_data="change_file")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# -------------------------------------------------------------------
# ПОЛЬЗОВАТЕЛЬСКАЯ ЧАСТЬ
# -------------------------------------------------------------------
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Приветствие для обычных пользователей."""
    await message.answer(
        "Привет! Я бот.\n\n"
        "Если вы администратор, отправьте команду /admin для доступа к панели управления."
    )


# -------------------------------------------------------------------
# АДМИН-ПАНЕЛЬ
# -------------------------------------------------------------------
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def cmd_admin(message: types.Message):
    """Панель управления — только для ADMIN_ID."""
    await message.answer(
        "⚙️ **Панель администратора**\n\nВыберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode="Markdown"
    )


@dp.message(Command("admin"))
async def cmd_admin_denied(message: types.Message):
    """Ответ для тех, кто пытается вызвать /admin без прав."""
    await message.answer("⛔ У вас нет доступа к этой команде.")


# -------------------------------------------------------------------
# ОБРАБОТКА КНОПКИ И ЗАГРУЗКА ФАЙЛА
# -------------------------------------------------------------------
@dp.callback_query(F.data == "change_file", F.from_user.id == ADMIN_ID)
async def process_change_file_button(callback: types.CallbackQuery, state: FSMContext):
    """Нажатие на кнопку 'Изменить файл'."""
    await callback.message.answer("📥 Отправьте новый файл (документ) для замены.")
    await state.set_state(AdminStates.waiting_for_file)
    await callback.answer()


@dp.message(AdminStates.waiting_for_file, F.document, F.from_user.id == ADMIN_ID)
async def save_new_file(message: types.Message, state: FSMContext):
    """Прием и сохранение документа от админа."""
    file_id = message.document.file_id
    file_name = message.document.file_name

    # Создаем папку, если ее нет, и сохраняем файл
    save_dir = "./downloads"
    os.makedirs(save_dir, exist_ok=True)
    destination_path = os.path.join(save_dir, file_name)

    file_info = await bot.get_file(file_id)
    await bot.download_file(file_info.file_path, destination_path)

    await message.answer(
        f"✅ Файл **{file_name}** успешно получен и сохранен в папку `{save_dir}`!",
        parse_mode="Markdown"
    )
    await state.clear()


@dp.message(AdminStates.waiting_for_file, F.from_user.id == ADMIN_ID)
async def process_invalid_file_type(message: types.Message):
    """Если админ отправил текст или фото вместо документа."""
    await message.answer("⚠️ Пожалуйста, отправьте именно **документ** (файл без сжатия).")


# -------------------------------------------------------------------
# ЗАПУСК БОТА
# -------------------------------------------------------------------
async def main():
    # Удаляем старые необработанные сообщения
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
