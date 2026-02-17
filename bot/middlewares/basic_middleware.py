import logging
from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, CallbackQuery, Message

from bot.keyboards import KeyboardsClass
from bot.variables import Variables
from config import settings

logger = logging.getLogger(__name__)

USERS = [settings.ADMIN_TG_ID]


class BasicMiddleware(BaseMiddleware):
    def __init__(self, bot: Bot, keyboards: KeyboardsClass):
        self.bot = bot
        self.keyboards = keyboards

    async def __call__(self, handler, event: TelegramObject, data):
        # В aiogram 3.x event уже является CallbackQuery или Message
        if isinstance(event, CallbackQuery):
            source = event
            if source.from_user.id not in USERS:
                await event.answer("⛔️ Доступ запрещён", show_alert=True)
                return
        elif isinstance(event, Message):
            source = event
            if source.from_user.id not in USERS:
                await event.answer("⛔️ Доступ запрещён")
                return
        else:
            # Для других типов событий пропускаем проверку
            source = None
        
        data["variables"] = Variables(
            bot=self.bot,
            keyboards=self.keyboards
        )
        
        try:
            result = await handler(event, data)
            return result
        except Exception as e:
            logger.error(f"Error in handler: {e}", exc_info=True)
            raise

