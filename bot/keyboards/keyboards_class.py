from bot.keyboards.main import MainKeyboards
from bot.keyboards.orgs import OrgsKeyboards
from bot.keyboards.foodcost import FoodcostKeyboards


class KeyboardsClass:
    def __init__(self):
        self.main = MainKeyboards()
        self.orgs = OrgsKeyboards()
        self.foodcost = FoodcostKeyboards()

