from typing import List, Dict, Any
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards.operations import KeyboardOperations


class OrgsKeyboards(KeyboardOperations):
    async def menu(self, orgs: List[Dict[str, Any]], page: int = 0, per_page: int = 10):
        departments = [org for org in orgs if org.get("type") == "DEPARTMENT"]
        
        start_idx = page * per_page
        end_idx = start_idx + per_page
        page_orgs = departments[start_idx:end_idx]
        
        if not page_orgs:
            buttons = {"Назад": "back"}
            return await self.create_keyboard(buttons=buttons)
        
        buttons_dict = {}
        for org in page_orgs:
            org_name = org.get("name", "Unknown")[:20]
            buttons_dict[org_name] = "orgs:info"
        
        nav_buttons = {}
        if page > 0:
            nav_buttons["◀ Назад"] = f"orgs:page:{page-1}"
        if end_idx < len(departments):
            nav_buttons["Вперёд ▶"] = f"orgs:page:{page+1}"
        
        buttons_dict["Назад"] = "back"
        
        keyboard = InlineKeyboardBuilder()
        
        org_buttons = list(buttons_dict.items())[:-1]
        for i in range(0, len(org_buttons), 2):
            row_orgs = org_buttons[i:i+2]
            row = [InlineKeyboardButton(text=text, callback_data=callback) for text, callback in row_orgs]
            keyboard.row(*row)
        
        if nav_buttons:
            nav_row = [InlineKeyboardButton(text=text, callback_data=callback) for text, callback in nav_buttons.items()]
            keyboard.row(*nav_row)
        
        keyboard.row(InlineKeyboardButton(text="Назад", callback_data="back"))
        
        return keyboard.as_markup()

