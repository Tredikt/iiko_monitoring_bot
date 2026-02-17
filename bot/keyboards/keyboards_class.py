from bot.keyboards.main import MainKeyboards
from bot.keyboards.settings import SettingsKeyboards
from bot.keyboards.orgs import OrgsKeyboards
from bot.keyboards.foodcost import FoodcostKeyboards


class KeyboardsClass:
    def __init__(self):
        self.main = MainKeyboards()
        self.settings = SettingsKeyboards()
        self.orgs = OrgsKeyboards()
        self.foodcost = FoodcostKeyboards()

