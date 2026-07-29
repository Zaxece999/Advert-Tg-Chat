import asyncio
import logging
import configparser
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from database.database import db
from handlers.user_handlers import router as user_router
from handlers.account_handlers import router as account_router
from services.background_tasks import start_background_tasks, stop_background_tasks

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

config = configparser.ConfigParser()
config.read('config.ini')

bot = Bot(
    token=config.get('TELEGRAM', 'bot_token'),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

async def on_startup():
    logger.info("🚀 Запуск бота...")

    try:
        db.create_tables()
        logger.info("💾 Таблицы базы данных успешно созданы")
    except Exception as e:
        logger.error(f"❌ Ошибка при создании таблиц базы данных: {e}")
        return

    dp.include_router(account_router)
    dp.include_router(user_router)
    logger.info("🔀 Роутеры успешно зарегистрированы")

    await start_background_tasks()

    logger.info("✅ Бот успешно запущен!")

async def on_shutdown():
    logger.info("🛑 Остановка бота...")

    await stop_background_tasks()

    await bot.session.close()
    logger.info("✅ Завершение работы бота")

async def main():
    try:
        dp.startup.register(on_startup)
        dp.shutdown.register(on_shutdown)

        await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())
