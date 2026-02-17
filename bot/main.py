import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import settings
from bot.handlers import router
from bot.scheduler import ReportScheduler
from bot.keyboards import keyboards
from bot.middlewares.basic_middleware import BasicMiddleware
from iiko.client import IikoClient
from services.analytics import AnalyticsService
from bot.deps import set_analytics_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    iiko_client = IikoClient()
    analytics_service = AnalyticsService(iiko_client)
    set_analytics_service(analytics_service)

    scheduler = ReportScheduler(bot, analytics_service)

    dp.message.middleware(BasicMiddleware(bot=bot, keyboards=keyboards))
    dp.callback_query.middleware(BasicMiddleware(bot=bot, keyboards=keyboards))

    dp.include_router(router)

    scheduler.start()

    try:
        logger.info("Bot started")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await iiko_client.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

