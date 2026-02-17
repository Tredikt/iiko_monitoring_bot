from bot.keyboards.operations import KeyboardOperations


class FoodcostKeyboards(KeyboardOperations):
    async def menu(self, period: str = "today", view_type: str = "summary", page: int = 0):
        buttons = {}
        row_num = 1
        
        buttons[row_num] = [
            ("Сегодня", f"foodcost:view:today:{view_type}:{page}"),
            ("Вчера", f"foodcost:view:yesterday:{view_type}:{page}")
        ]
        row_num += 1
        
        buttons[row_num] = [
            ("Неделя", f"foodcost:view:week:{view_type}:{page}"),
            ("Месяц", f"foodcost:view:month:{view_type}:{page}")
        ]
        row_num += 1
        
        if view_type == "summary":
            buttons[row_num] = [
                ("Топ 10 блюд", f"foodcost:view:{period}:dishes_top:0"),
                ("Топ 10 худших", f"foodcost:view:{period}:dishes_worst:0")
            ]
            row_num += 1
            
            buttons[row_num] = [
                ("По категориям", f"foodcost:view:{period}:categories:0"),
                ("По группам", f"foodcost:view:{period}:groups:0")
            ]
            row_num += 1
        else:
            if view_type in ["categories", "groups"]:
                nav_row = []
                if page > 0:
                    nav_row.append(("◀ Назад", f"foodcost:view:{period}:{view_type}:{page-1}"))
                nav_row.append(("Вперёд ▶", f"foodcost:view:{period}:{view_type}:{page+1}"))
                buttons[row_num] = nav_row
                row_num += 1
            
            buttons[row_num] = [
                ("Сводка", f"foodcost:view:{period}:summary:0")
            ]
            row_num += 1
            
            view_row = []
            if view_type not in ["dishes_top", "dishes_worst"]:
                view_row.append(("Топ 10", f"foodcost:view:{period}:dishes_top:0"))
                view_row.append(("Худшие", f"foodcost:view:{period}:dishes_worst:0"))
            elif view_type == "dishes_top":
                view_row.append(("Худшие", f"foodcost:view:{period}:dishes_worst:0"))
            elif view_type == "dishes_worst":
                view_row.append(("Топ 10", f"foodcost:view:{period}:dishes_top:0"))
            
            if view_type != "categories":
                view_row.append(("Категории", f"foodcost:view:{period}:categories:0"))
            if view_type != "groups":
                view_row.append(("Группы", f"foodcost:view:{period}:groups:0"))
            
            if view_row:
                buttons[row_num] = view_row
                row_num += 1
        
        buttons[row_num] = [("Назад", "back")]
        
        return await self.create_keyboard(buttons=buttons, architecture=True)

