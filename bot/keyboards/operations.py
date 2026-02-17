from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


class KeyboardOperations:
    @staticmethod
    async def get_empty_keyboard():
        return InlineKeyboardBuilder().as_markup()

    async def create_keyboard(
            self,
            buttons: list | dict | None = None,
            interval: int = 1,
            count: int = 0,
            is_builder: bool = None,
            architecture: bool = False
    ):
        if architecture:
            return await self.__architect_keyboard(buttons=buttons)
        elif isinstance(buttons, dict):
            return await self.__inline_keyboard(buttons=buttons, interval=interval, count=count)
        elif isinstance(buttons, list):
            return await self.__inline_keyboard_list(buttons=buttons, interval=interval, count=count)
        else:
            return InlineKeyboardBuilder().as_markup()

    @staticmethod
    async def __architect_keyboard(buttons: dict):
        buttons_list = list()
        button = InlineKeyboardButton
        keyboard = InlineKeyboardBuilder()
        for number, row in buttons.items():
            for text, callback_data in row:
                buttons_list.append(button(text=text, callback_data=callback_data))
            keyboard.row(*buttons_list)
            buttons_list.clear()
        return keyboard.as_markup()

    @staticmethod
    async def __inline_keyboard(buttons: dict, interval: int, count: int):
        buttons_list = list()
        interval_count = 0

        keyboard = InlineKeyboardBuilder()
        button = InlineKeyboardButton
        for text, callback_data in buttons.items():
            if isinstance(callback_data, list) and callback_data[0] == "url":
                buttons_list.append(button(text=text, url=callback_data[1]))
            else:
                buttons_list.append(button(text=text, callback_data=callback_data))
            if len(buttons_list) == interval:
                keyboard.row(*buttons_list)
                buttons_list.clear()

                interval_count += 1
                if count > 0 and interval_count == count:
                    interval = 1

        if buttons_list:
            keyboard.row(*buttons_list)

        return keyboard.as_markup()

    @staticmethod
    async def __inline_keyboard_list(buttons: list, interval: int, count: int):
        buttons_list = list()
        interval_count = 0

        keyboard = InlineKeyboardBuilder()
        button = InlineKeyboardButton

        for item in buttons:
            if isinstance(item, dict):
                text = item.get("text", "")
                callback_data = item.get("callback_data", "")
                buttons_list.append(button(text=text, callback_data=callback_data))
            elif isinstance(item, InlineKeyboardButton):
                buttons_list.append(item)

            if len(buttons_list) == interval:
                keyboard.row(*buttons_list)
                buttons_list.clear()
                interval_count += 1

                if count > 0 and interval_count == count:
                    interval = 1

        if buttons_list:
            keyboard.row(*buttons_list)

        return keyboard.as_markup()

