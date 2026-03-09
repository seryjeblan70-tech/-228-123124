import asyncio
import logging
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# -------------------- Конфигурация --------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан")

ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
if not ADMIN_ID:
    logging.warning("ADMIN_ID не задан, админские команды будут недоступны")

MINI_APP_URL = "https://mybarochekapitg.bothost.ru"  # твой домен с приложением
API_BASE_URL = "https://mybarochekapitg.bothost.ru/api"  # базовый URL API

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# -------------------- Команда /start --------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    args = message.text.split()
    referral_code = None
    if len(args) > 1 and args[1].startswith('ref_'):
        referral_code = args[1][4:]  # извлекаем код после ref_
        logger.info(f"Реферальный код: {referral_code}")
        # Отправляем код на сервер
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(f"{API_BASE_URL}/register_referral", json={
                    "referral_code": referral_code,
                    "new_user_id": message.from_user.id
                })
        except Exception as e:
            logger.error(f"Ошибка при регистрации реферала: {e}")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🚀 Играть", web_app=WebAppInfo(url=MINI_APP_URL))
        ]]
    )
    await message.answer("Привет! Нажми кнопку, чтобы начать игру.", reply_markup=keyboard)

# -------------------- Проверка на админа --------------------
def is_admin(message: types.Message) -> bool:
    return message.from_user.id == ADMIN_ID

# -------------------- Админские команды --------------------
@dp.message(Command("add_event"))
async def cmd_add_event(message: types.Message):
    if not is_admin(message):
        await message.reply("⛔ Доступ запрещён.")
        return

    args = message.text.split(maxsplit=4)
    if len(args) < 5:
        await message.reply(
            "Использование:\n"
            "/add_event <тип> <множитель> <часы> <описание>\n"
            "Пример: /add_event double_gems 2 6 Удвоенные алмазы!"
        )
        return

    _, event_type, multiplier, duration_hours, description = args
    try:
        multiplier = float(multiplier)
        duration_hours = int(duration_hours)
    except ValueError:
        await message.reply("❌ Множитель должен быть числом, часы – целым числом.")
        return

    payload = {
        "type": event_type,
        "multiplier": multiplier,
        "duration_hours": duration_hours,
        "description": description
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{API_BASE_URL}/admin/event", json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    await message.reply(f"✅ Ивент создан! ID: {data['id']}, истекает: {data['expires_at']}")
                else:
                    error = await resp.text()
                    await message.reply(f"❌ Ошибка: {resp.status} – {error}")
        except Exception as e:
            await message.reply(f"❌ Ошибка соединения: {e}")

@dp.message(Command("events"))
async def cmd_events(message: types.Message):
    if not is_admin(message):
        await message.reply("⛔ Доступ запрещён.")
        return

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{API_BASE_URL}/admin/events") as resp:
                if resp.status == 200:
                    events = await resp.json()
                    if not events:
                        await message.reply("📭 Активных ивентов нет.")
                        return
                    text = "📋 **Активные ивенты:**\n\n"
                    for e in events:
                        text += (
                            f"🆔 {e['id']} | {e['type']} x{e['multiplier']}\n"
                            f"📝 {e['description']}\n"
                            f"⏳ до {e['expires_at']}\n\n"
                        )
                    await message.reply(text)
                else:
                    error = await resp.text()
                    await message.reply(f"❌ Ошибка: {resp.status} – {error}")
        except Exception as e:
            await message.reply(f"❌ Ошибка соединения: {e}")

@dp.message(Command("delete_event"))
async def cmd_delete_event(message: types.Message):
    if not is_admin(message):
        await message.reply("⛔ Доступ запрещён.")
        return

    args = message.text.split()
    if len(args) != 2:
        await message.reply("Использование: /delete_event <ID ивента>")
        return

    event_id = args[1]
    async with aiohttp.ClientSession() as session:
        try:
            async with session.delete(f"{API_BASE_URL}/admin/event") as resp:
                if resp.status == 200:
                    await message.reply("✅ Ивент удалён.")
                else:
                    error = await resp.text()
                    await message.reply(f"❌ Ошибка: {resp.status} – {error}")
        except Exception as e:
            await message.reply(f"❌ Ошибка соединения: {e}")


@dp.message(Command("add_gems"))
async def cmd_add_gems(message: types.Message):
    if not is_admin(message):
        await message.reply("⛔ Доступ запрещён.")
        return

    args = message.text.split()
    if len(args) != 3:
        await message.reply("Использование: /add_gems <telegram_id> <количество>")
        return

    try:
        telegram_id = int(args[1])
        amount = int(args[2])
        if amount <= 0:
            await message.reply("❌ Количество должно быть положительным числом.")
            return
    except ValueError:
        await message.reply("❌ Неверный формат. Ожидаются числа.")
        return

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{API_BASE_URL}/admin/add_gems", json={
                "telegram_id": telegram_id,
                "amount": amount
            }) as resp:
                if resp.status == 200:
                    await message.reply(f"✅ Пользователю {telegram_id} добавлено {amount} 💎.")
                elif resp.status == 404:
                    await message.reply("❌ Пользователь с таким ID не найден.")
                else:
                    error = await resp.text()
                    await message.reply(f"❌ Ошибка сервера: {resp.status} – {error}")
        except Exception as e:
            await message.reply(f"❌ Ошибка соединения: {e}")


@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if not is_admin(message):
        await message.reply("⛔ Доступ запрещён.")
        return

    # Получаем текст сообщения
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Использование: /broadcast <текст сообщения>")
        return

    broadcast_text = parts[1].strip()
    if not broadcast_text:
        await message.reply("❌ Текст не может быть пустым.")
        return

    # Запрашиваем подтверждение
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data="broadcast_yes"),
                InlineKeyboardButton(text="❌ Нет", callback_data="broadcast_no")
            ]
        ]
    )
    await message.reply(
        f"Вы собираетесь отправить сообщение всем пользователям:\n\n{broadcast_text}\n\nЭто займёт некоторое время. Подтвердите действие.",
        reply_markup=keyboard
    )
    # Сохраняем текст в памяти (можно через FSM, но проще через глобальный словарь)
    broadcast_data[message.from_user.id] = broadcast_text

# Словарь для временного хранения текста рассылки
broadcast_data = {}

@dp.callback_query(lambda c: c.data.startswith('broadcast_'))
async def broadcast_callback(callback: types.CallbackQuery):
    action = callback.data.split('_')[1]
    admin_id = callback.from_user.id
    if action == 'no':
        await callback.message.edit_text("❌ Рассылка отменена.")
        broadcast_data.pop(admin_id, None)
        return

    # action == 'yes'
    text = broadcast_data.pop(admin_id, None)
    if not text:
        await callback.message.edit_text("❌ Ошибка: данные утеряны. Попробуйте снова.")
        return

    await callback.message.edit_text("⏳ Начинаю рассылку... Это может занять несколько минут.")

    # Получаем список всех пользователей с сервера
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{API_BASE_URL}/admin/users") as resp:
                if resp.status != 200:
                    await callback.message.edit_text(f"❌ Ошибка получения списка пользователей: {resp.status}")
                    return
                data = await resp.json()
                user_ids = data.get('ids', [])
        except Exception as e:
            await callback.message.edit_text(f"❌ Ошибка соединения с сервером: {e}")
            return

    if not user_ids:
        await callback.message.edit_text("📭 Нет пользователей для рассылки.")
        return

    # Рассылка с задержкой и обработкой ошибок
    sent = 0
    failed = 0
    status_msg = await callback.message.answer(f"✅ Отправлено: {sent}, ❌ Ошибок: {failed}")

    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
            # Обновляем статус каждые 10 сообщений
            if sent % 10 == 0:
                await status_msg.edit_text(f"✅ Отправлено: {sent}, ❌ Ошибок: {failed}")
        except TelegramForbiddenError:
            # Пользователь заблокировал бота – пропускаем
            failed += 1
        except TelegramRetryAfter as e:
            # Слишком много запросов – ждём
            await asyncio.sleep(e.retry_after)
            # Повторная отправка этому же пользователю
            try:
                await bot.send_message(uid, text)
                sent += 1
            except:
                failed += 1
        except Exception:
            failed += 1

        # Небольшая задержка, чтобы не превысить лимиты
        await asyncio.sleep(0.05)  # примерно 20 сообщений в секунду

    await status_msg.edit_text(f"✅ Рассылка завершена.\n✅ Успешно: {sent}\n❌ Ошибок: {failed}")



# -------------------- Запуск бота --------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())