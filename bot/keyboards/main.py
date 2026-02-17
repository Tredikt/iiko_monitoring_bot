from bot.keyboards.operations import KeyboardOperations


class MainKeyboards(KeyboardOperations):
    async def menu(self):
        buttons = {
            1: [
                ("Сегодня", "period:today"),
                ("Вчера", "period:yesterday")
            ],
            2: [
                ("Неделя", "period:week"),
                ("Месяц", "period:month")
            ],
            3: [
                ("Фудкост", "foodcost:view:today:summary:0"),
            ],
            4: [
                ("Организации", "orgs:info"),
                ("Терминалы", "terminals:list")
            ],
            5: [
                ("Настройки", "settings")
            ]
        }
        return await self.create_keyboard(buttons=buttons, architecture=True)

