from bot.keyboards.operations import KeyboardOperations


class SettingsKeyboards(KeyboardOperations):
    async def menu(self):
        buttons = {
            1: [
                ("Порог алерта: -5%", "setting:threshold:-5"),
                ("Порог алерта: +5%", "setting:threshold:+5")
            ],
            2: [
                ("Rolling days: -1", "setting:rolling:-1"),
                ("Rolling days: +1", "setting:rolling:+1")
            ],
            3: [
                ("Время: -30 мин", "setting:time:-30"),
                ("Время: +30 мин", "setting:time:+30")
            ],
            4: [
                ("Назад", "back")
            ]
        }
        return await self.create_keyboard(buttons=buttons, architecture=True)

