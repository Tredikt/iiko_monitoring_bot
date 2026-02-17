from aiogram import Bot
from functools import cached_property

from bot.keyboards import KeyboardsClass
from services.analytics import AnalyticsService
from bot.deps import get_analytics_service


class Variables:
    def __init__(self, bot: Bot, keyboards: KeyboardsClass):
        self.bot = bot
        self.keyboards = keyboards

    @cached_property
    def analytics(self) -> AnalyticsService:
        return get_analytics_service()

