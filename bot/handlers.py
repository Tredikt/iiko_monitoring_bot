from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from db.repo import SettingsRepo
import logging

logger = logging.getLogger(__name__)

router = Router()


class AnalyticsState(StatesGroup):
    """Состояния для выбора организации"""
    selected_org_id = State()


@router.message(Command("start"))
async def cmd_start(message: Message, variables):
    await message.answer(
        "Выберите период для просмотра аналитики:",
        reply_markup=await variables.keyboards.main.menu()
    )


@router.callback_query(F.data == "refresh")
async def callback_refresh(callback: CallbackQuery, variables):
    await callback.answer("Обновление данных...")
    
    variables.analytics._cache.clear()
    logger.info("Cache cleared for refresh")
    
    await callback.message.edit_text(
        "Выберите период для просмотра аналитики:",
        reply_markup=await variables.keyboards.main.menu()
    )


@router.callback_query(F.data == "back")
async def callback_back(callback: CallbackQuery, state: FSMContext, variables):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "Выберите период для просмотра аналитики:",
        reply_markup=await variables.keyboards.main.menu()
    )


@router.callback_query(F.data == "settings")
async def callback_settings(callback: CallbackQuery, variables):
    settings_obj = await SettingsRepo.get_settings()
    text = (
        f"⚙️ Настройки\n\n"
        f"Порог алерта: {settings_obj.alert_threshold_pct}%\n"
        f"Rolling days: {settings_obj.rolling_days}\n"
        f"Время отчёта: {settings_obj.report_time}"
    )
    await callback.message.edit_text(text, reply_markup=await variables.keyboards.settings.menu())


@router.callback_query(F.data.startswith("setting:"))
async def callback_setting(callback: CallbackQuery, variables):
    parts = callback.data.split(":")
    setting_type = parts[1]
    value = int(parts[2])

    settings_obj = await SettingsRepo.get_settings()

    if setting_type == "threshold":
        new_value = settings_obj.alert_threshold_pct + value
        await SettingsRepo.update_settings(alert_threshold_pct=new_value)
        await callback.answer(f"Порог алерта: {new_value}%")
    elif setting_type == "rolling":
        new_value = max(1, settings_obj.rolling_days + value)
        await SettingsRepo.update_settings(rolling_days=new_value)
        await callback.answer(f"Rolling days: {new_value}")
    elif setting_type == "time":
        hour, minute = map(int, settings_obj.report_time.split(":"))
        total_minutes = hour * 60 + minute + value
        total_minutes = total_minutes % (24 * 60)
        new_hour = total_minutes // 60
        new_minute = total_minutes % 60
        new_time = f"{new_hour:02d}:{new_minute:02d}"
        await SettingsRepo.update_settings(report_time=new_time)
        await callback.answer(f"Время отчёта: {new_time}")

    settings_obj = await SettingsRepo.get_settings()
    text = (
        f"⚙️ Настройки\n\n"
        f"Порог алерта: {settings_obj.alert_threshold_pct}%\n"
        f"Rolling days: {settings_obj.rolling_days}\n"
        f"Время отчёта: {settings_obj.report_time}"
    )
    await callback.message.edit_text(text, reply_markup=await variables.keyboards.settings.menu())


@router.callback_query(F.data.startswith("orgs:"))
async def callback_orgs_list(callback: CallbackQuery, variables):
    """Обработчик для списка организаций"""
    parts = callback.data.split(":")
    action = parts[1]
    
    try:
        orgs = await variables.analytics.get_all_organizations()
        
        if action == "info":
            await callback.answer()
            if not orgs:
                await callback.message.edit_text(
                    "Не удалось загрузить список организаций",
                    reply_markup=await variables.keyboards.main.menu()
                )
                return
            await callback.message.edit_text(
                "Выберите организацию:",
                reply_markup=await variables.keyboards.orgs.menu(orgs, page=0)
            )
        elif action == "page":
            page = int(parts[2]) if len(parts) > 2 else 0
            await callback.answer()
            if not orgs:
                await callback.message.edit_text(
                    "Не удалось загрузить список организаций",
                    reply_markup=await variables.keyboards.main.menu()
                )
                return
            await callback.message.edit_text(
                "Выберите организацию:",
                reply_markup=await variables.keyboards.orgs.menu(orgs, page=page)
            )
    except Exception as e:
        logger.error(f"Error getting organizations list: {e}")
        await callback.answer("Ошибка при получении списка организаций", show_alert=True)


@router.callback_query(F.data.startswith("period:"))
async def callback_period(callback: CallbackQuery, state: FSMContext, variables):
    period = callback.data.split(":")[1]
    today = datetime.now()
    
    selected_org_id = None

    try:
        if period == "today":
            date_from = today.replace(hour=0, minute=0, second=0, microsecond=0)
            date_to = today
            period_text = date_from.strftime("%Y-%m-%d")
        elif period == "yesterday":
            yesterday = today - timedelta(days=1)
            date_from = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            date_to = yesterday.replace(hour=23, minute=59, second=59)
            period_text = date_from.strftime("%Y-%m-%d")
        elif period == "week":
            date_from = today - timedelta(days=7)
            date_to = today
            period_text = f"{date_from.strftime('%Y-%m-%d')} - {date_to.strftime('%Y-%m-%d')}"
        elif period == "month":
            date_from = today - timedelta(days=30)
            date_to = today
            period_text = f"{date_from.strftime('%Y-%m-%d')} - {date_to.strftime('%Y-%m-%d')}"
        else:
            await callback.answer("Неизвестный период", show_alert=True)
            return

        await callback.answer("Загрузка данных...")

        org_ids = None
        metrics = await variables.analytics.get_period_metrics(date_from, date_to, org_ids=org_ids)
        
        comparison = None
        comparison_label = ""
        
        if period == "today":
            change_pct = await variables.analytics.compare_with_yesterday(metrics, org_ids=org_ids)
            if change_pct is not None:
                comparison = {"revenue_change": change_pct}
                comparison_label = "к вчера"
        elif period == "yesterday":
            day_before = today - timedelta(days=2)
            comparison = await variables.analytics.compare_periods(
                date_from, date_to,
                day_before.replace(hour=0, minute=0, second=0, microsecond=0),
                day_before.replace(hour=23, minute=59, second=59),
                org_ids=org_ids
            )
            comparison_label = "к позавчера"
        elif period == "week":
            prev_week_from = date_from - timedelta(days=7)
            prev_week_to = date_to - timedelta(days=7)
            comparison = await variables.analytics.compare_periods(
                date_from, date_to, prev_week_from, prev_week_to,
                org_ids=org_ids
            )
            comparison_label = "к прошлой неделе"
        elif period == "month":
            prev_month_from = date_from - timedelta(days=30)
            prev_month_to = date_to - timedelta(days=30)
            comparison = await variables.analytics.compare_periods(
                date_from, date_to, prev_month_from, prev_month_to,
                org_ids=org_ids
            )
            comparison_label = "к прошлому месяцу"

        revenue = metrics["revenue"]
        orders = metrics["orders"]
        avg_check = metrics["average_check"]

        settings_obj = await SettingsRepo.get_settings()
        threshold = settings_obj.alert_threshold_pct

        revenue_emoji = "🟢"
        orders_emoji = "🟢"
        avg_check_emoji = "🟢"
        
        if comparison:
            if comparison.get("revenue_change") is not None:
                revenue_emoji = "🟢" if comparison["revenue_change"] >= -threshold else "🔴"
            if comparison.get("orders_change") is not None:
                orders_emoji = "🟢" if comparison.get("orders_change", 0) >= -threshold else "🔴"
            if comparison.get("avg_check_change") is not None:
                avg_check_emoji = "🟢" if comparison.get("avg_check_change", 0) >= 0 else "🔴"

        change_text = ""
        if comparison:
            changes = []
            if comparison.get("revenue_change") is not None:
                emoji = "🟢" if comparison["revenue_change"] >= -threshold else "🔴"
                changes.append(f"{emoji} Выручка: {comparison['revenue_change']:+.1f}%")
            if comparison.get("orders_change") is not None:
                emoji = "🟢" if comparison.get("orders_change", 0) >= -threshold else "🔴"
                changes.append(f"{emoji} Заказов: {comparison['orders_change']:+.1f}%")
            if comparison.get("avg_check_change") is not None:
                emoji = "🟢" if comparison.get("avg_check_change", 0) >= 0 else "🔴"
                changes.append(f"{emoji} Средний чек: {comparison['avg_check_change']:+.1f}%")
            
            if changes:
                change_text = f"\n\nΔ {comparison_label}:\n" + "\n".join(changes)

        updated_at = metrics.get("updated_at", datetime.now().strftime("%H:%M:%S"))
        warning_text = ""
        food_cost = metrics.get("food_cost", 0)
        food_cost_pct = metrics.get("food_cost_pct", 0)
        food_cost_text = ""
        if food_cost > 0:
            food_cost_emoji = "🟢" if food_cost_pct <= 30 else "🟡" if food_cost_pct <= 40 else "🔴"
            food_cost_text = f"\n{food_cost_emoji} Фудкост: {food_cost:,.0f} ₽ ({food_cost_pct:.1f}%)"
        
        text = (
            f"{metrics['org_name']}\n\n"
            f"Период: {period_text}\n"
            f"🕐 Обновлено: {updated_at}\n\n"
            f"{revenue_emoji} Выручка: {revenue:,.0f} ₽\n"
            f"{orders_emoji} Заказов: {orders:,.0f}\n"
            f"{avg_check_emoji} Средний чек: {avg_check:,.0f} ₽"
            f"{food_cost_text}"
            f"{change_text}"
            f"{warning_text}"
        )

        try:
            await callback.message.edit_text(text, reply_markup=await variables.keyboards.main.menu())
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                await callback.answer()
            else:
                raise

    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        await callback.answer("Ошибка при получении данных", show_alert=True)
        try:
            await callback.message.edit_text(
                "Выберите период для просмотра аналитики:",
                reply_markup=await variables.keyboards.main.menu()
            )
        except TelegramBadRequest:
            pass


@router.callback_query(F.data.startswith("terminals:"))
async def callback_terminals(callback: CallbackQuery, variables):
    """Обработчик для списка терминалов"""
    action = callback.data.split(":")[1]
    
    try:
        if action == "list":
            await callback.answer("Загрузка списка терминалов...")
            terminals = await variables.analytics.get_terminals()
            
            if not terminals:
                await callback.message.edit_text(
                    "Не удалось загрузить список терминалов или терминалы не найдены",
                    reply_markup=await variables.keyboards.main.menu()
                )
                return
            
            text_parts = [f"Список терминалов ({len(terminals)}):\n"]
            
            for i, terminal in enumerate(terminals[:50], 1):
                name = terminal.get("name") or terminal.get("terminalName") or "Без названия"
                terminal_id = terminal.get("id") or terminal.get("terminalId") or "N/A"
                address = terminal.get("address") or terminal.get("addressStr") or ""
                department_id = terminal.get("departmentId") or terminal.get("department") or ""
                
                text_parts.append(f"\n{i}. {name}")
                text_parts.append(f"   ID: {terminal_id[:20]}..." if len(str(terminal_id)) > 20 else f"   ID: {terminal_id}")
                if address:
                    text_parts.append(f"   Адрес: {address[:50]}")
                if department_id:
                    text_parts.append(f"   Департамент: {department_id[:20]}...")
            
            if len(terminals) > 50:
                text_parts.append(f"\n... и ещё {len(terminals) - 50} терминалов")
            
            text = "\n".join(text_parts)
            if len(text) > 4000:
                text = text[:4000] + "\n\n... (сообщение обрезано)"
            
            await callback.message.edit_text(
                text,
                reply_markup=await variables.keyboards.main.menu()
            )
    except Exception as e:
        logger.error(f"Error getting terminals list: {e}")
        await callback.answer("Ошибка при получении списка терминалов", show_alert=True)


@router.callback_query(F.data.startswith("foodcost:"))
async def callback_foodcost(callback: CallbackQuery, variables):
    """Обработчик для просмотра фудкоста"""
    parts = callback.data.split(":")
    action = parts[1]
    
    if len(parts) == 2:
        period = "today"
        view_type = "summary"
        page = 0
    else:
        period = parts[2] if len(parts) > 2 else "today"
        view_type = parts[3] if len(parts) > 3 else "summary"
        page = int(parts[4]) if len(parts) > 4 else 0
    
    try:
        if action == "view":
            await callback.answer("Загрузка данных о фудкосте...")
            
            today = datetime.now()
            if period == "today":
                date_from = today.replace(hour=0, minute=0, second=0, microsecond=0)
                date_to = today
                period_text = date_from.strftime("%Y-%m-%d")
            elif period == "yesterday":
                yesterday = today - timedelta(days=1)
                date_from = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
                date_to = yesterday.replace(hour=23, minute=59, second=59)
                period_text = date_from.strftime("%Y-%m-%d")
            elif period == "week":
                date_from = today - timedelta(days=7)
                date_to = today
                period_text = f"{date_from.strftime('%Y-%m-%d')} - {date_to.strftime('%Y-%m-%d')}"
            elif period == "month":
                date_from = today - timedelta(days=30)
                date_to = today
                period_text = f"{date_from.strftime('%Y-%m-%d')} - {date_to.strftime('%Y-%m-%d')}"
            else:
                date_from = today.replace(hour=0, minute=0, second=0, microsecond=0)
                date_to = today
                period_text = date_from.strftime("%Y-%m-%d")
            
            detailed_data = await variables.analytics.get_detailed_foodcost(date_from, date_to)
            
            total_revenue = detailed_data.get("total_revenue", 0)
            total_cost = detailed_data.get("total_cost", 0)
            avg_foodcost_pct = detailed_data.get("avg_foodcost_pct", 0)
            
            change_text = ""
            if period == "today":
                yesterday = today - timedelta(days=1)
                yesterday_data = await variables.analytics.get_detailed_foodcost(
                    yesterday.replace(hour=0, minute=0, second=0, microsecond=0),
                    yesterday.replace(hour=23, minute=59, second=59)
                )
                yesterday_foodcost_pct = yesterday_data.get("avg_foodcost_pct", 0)
                change_pct = avg_foodcost_pct - yesterday_foodcost_pct if yesterday_foodcost_pct > 0 else 0
                change_emoji = "🟢" if change_pct <= 0 else "🔴"
                change_text = f"\n\n{change_emoji} Изменение к вчера: {change_pct:+.1f}%"
            elif period == "yesterday":
                day_before = today - timedelta(days=2)
                day_before_data = await variables.analytics.get_detailed_foodcost(
                    day_before.replace(hour=0, minute=0, second=0, microsecond=0),
                    day_before.replace(hour=23, minute=59, second=59)
                )
                day_before_foodcost_pct = day_before_data.get("avg_foodcost_pct", 0)
                change_pct = avg_foodcost_pct - day_before_foodcost_pct if day_before_foodcost_pct > 0 else 0
                change_emoji = "🟢" if change_pct <= 0 else "🔴"
                change_text = f"\n\n{change_emoji} Изменение к позавчера: {change_pct:+.1f}%"
            elif period == "week":
                prev_week_from = date_from - timedelta(days=7)
                prev_week_to = date_to - timedelta(days=7)
                prev_week_data = await variables.analytics.get_detailed_foodcost(prev_week_from, prev_week_to)
                prev_week_foodcost_pct = prev_week_data.get("avg_foodcost_pct", 0)
                change_pct = avg_foodcost_pct - prev_week_foodcost_pct if prev_week_foodcost_pct > 0 else 0
                change_emoji = "🟢" if change_pct <= 0 else "🔴"
                change_text = f"\n\n{change_emoji} Изменение к прошлой неделе: {change_pct:+.1f}%"
            elif period == "month":
                prev_month_from = date_from - timedelta(days=30)
                prev_month_to = date_to - timedelta(days=30)
                prev_month_data = await variables.analytics.get_detailed_foodcost(prev_month_from, prev_month_to)
                prev_month_foodcost_pct = prev_month_data.get("avg_foodcost_pct", 0)
                change_pct = avg_foodcost_pct - prev_month_foodcost_pct if prev_month_foodcost_pct > 0 else 0
                change_emoji = "🟢" if change_pct <= 0 else "🔴"
                change_text = f"\n\n{change_emoji} Изменение к прошлому месяцу: {change_pct:+.1f}%"
            
            if avg_foodcost_pct <= 30:
                status = "🟢 Отлично"
            elif avg_foodcost_pct <= 35:
                status = "🟡 Нормально"
            elif avg_foodcost_pct <= 40:
                status = "🟠 Выше нормы"
            else:
                status = "🔴 Критично"
            
            if view_type == "summary":
                text = (
                    f"Фудкост\n\n"
                    f"Период: {period_text}\n"
                    f"Обновлено: {detailed_data.get('updated_at', datetime.now().strftime('%H:%M:%S'))}\n"
                    f"Статус: {status}\n\n"
                    f"Выручка: {total_revenue:,.0f} ₽\n"
                    f"Себестоимость: {total_cost:,.0f} ₽\n"
                    f"Фудкост: {avg_foodcost_pct:.1f}%"
                    f"{change_text}"
                )
            elif view_type in ["dishes", "dishes_top"]:
                dishes = detailed_data.get("by_dishes", [])
                top_dishes = dishes[:10]
                
                text_parts = [
                    f"🍽️ Топ 10 блюд (по выручке)\n",
                    f"Период: {period_text}\n",
                    f"🕐 Обновлено: {detailed_data.get('updated_at', datetime.now().strftime('%H:%M:%S'))}\n\n"
                ]
                
                if top_dishes:
                    text_parts.append("Топ блюд:\n")
                    for i, dish in enumerate(top_dishes, start=1):
                        name = dish.get("name", "Без названия")[:40]
                        revenue = dish.get("revenue", 0)
                        cost = dish.get("cost", 0)
                        foodcost_pct = dish.get("foodcost_pct", 0)
                        orders = dish.get("orders", 0)
                        
                        emoji = "🟢" if foodcost_pct <= 30 else "🟡" if foodcost_pct <= 40 else "🔴"
                        text_parts.append(
                            f"{i}. {emoji} {name}\n"
                            f"   Выручка: {revenue:,.0f} ₽ | Себестоимость: {cost:,.0f} ₽\n"
                            f"   Фудкост: {foodcost_pct:.1f}% | Заказов: {orders:.0f}\n"
                        )
                else:
                    text_parts.append("Нет данных о блюдах")
                
                text = "\n".join(text_parts)
            elif view_type == "dishes_worst":
                dishes = detailed_data.get("by_dishes", [])
                
                valid_dishes = []
                excluded_count = 0
                for dish in dishes:
                    revenue = dish.get("revenue", 0)
                    cost = dish.get("cost", 0)
                    foodcost_pct = dish.get("foodcost_pct", 0)
                    
                    if revenue > 0:
                        if cost > revenue * 10 or foodcost_pct > 200:
                            excluded_count += 1
                            continue
                        if revenue < 1000 and cost > 5000:
                            excluded_count += 1
                            continue
                    
                    valid_dishes.append(dish)
                
                red_zone_dishes = [d for d in valid_dishes if 40 < d.get("foodcost_pct", 0) <= 200]
                
                if red_zone_dishes:
                    red_zone_dishes.sort(key=lambda x: x.get("foodcost_pct", 0), reverse=True)
                    worst_dishes = red_zone_dishes[:10]
                    title_suffix = " (красная зона)"
                else:
                    dishes_sorted_by_foodcost = sorted(
                        [d for d in valid_dishes if d.get("foodcost_pct", 0) <= 200],
                        key=lambda x: x.get("foodcost_pct", 0),
                        reverse=True
                    )
                    worst_dishes = dishes_sorted_by_foodcost[:10]
                    title_suffix = " (самый высокий фудкост)"
                
                text_parts = [
                    f"Топ 10 худших блюд{title_suffix}\n",
                    f"Период: {period_text}\n",
                    f"🕐 Обновлено: {detailed_data.get('updated_at', datetime.now().strftime('%H:%M:%S'))}\n"
                ]
                
                if excluded_count > 0:
                    text_parts.append(f"\n⚠️ Исключено {excluded_count} блюд с некорректными данными (фудкост > 200% или явные ошибки)\n")
                
                text_parts.append("\n")
                
                if worst_dishes:
                    text_parts.append("Топ худших блюд:\n")
                    for i, dish in enumerate(worst_dishes, start=1):
                        name = dish.get("name", "Без названия")[:40]
                        revenue = dish.get("revenue", 0)
                        cost = dish.get("cost", 0)
                        foodcost_pct = dish.get("foodcost_pct", 0)
                        orders = dish.get("orders", 0)
                        
                        emoji = "🟢" if foodcost_pct <= 30 else "🟡" if foodcost_pct <= 40 else "🔴"
                        text_parts.append(
                            f"{i}. {emoji} {name}\n"
                            f"   Выручка: {revenue:,.0f} ₽ | Себестоимость: {cost:,.0f} ₽\n"
                            f"   Фудкост: {foodcost_pct:.1f}% | Заказов: {orders:.0f}\n"
                        )
                else:
                    text_parts.append("Нет данных о блюдах")
                
                text = "\n".join(text_parts)
            elif view_type == "categories":
                categories = detailed_data.get("by_categories", [])
                per_page = 10
                start_idx = page * per_page
                end_idx = start_idx + per_page
                page_categories = categories[start_idx:end_idx]
                
                text_parts = [
                    f"📁 Фудкост по категориям\n",
                    f"Период: {period_text}\n",
                    f"🕐 Обновлено: {detailed_data.get('updated_at', datetime.now().strftime('%H:%M:%S'))}\n\n"
                ]
                
                if page_categories:
                    text_parts.append("Топ категорий:\n")
                    for i, category in enumerate(page_categories, start=start_idx + 1):
                        name = category.get("name", "Без категории")[:40]
                        revenue = category.get("revenue", 0)
                        cost = category.get("cost", 0)
                        foodcost_pct = category.get("foodcost_pct", 0)
                        orders = category.get("orders", 0)
                        
                        emoji = "🟢" if foodcost_pct <= 30 else "🟡" if foodcost_pct <= 40 else "🔴"
                        text_parts.append(
                            f"{i}. {emoji} {name}\n"
                            f"   Выручка: {revenue:,.0f} ₽ | Себестоимость: {cost:,.0f} ₽\n"
                            f"   Фудкост: {foodcost_pct:.1f}% | Заказов: {orders:.0f}\n"
                        )
                    
                    if len(categories) > end_idx:
                        text_parts.append(f"\n... и ещё {len(categories) - end_idx} категорий")
                else:
                    text_parts.append("Нет данных о категориях")
                
                text = "\n".join(text_parts)
            elif view_type == "groups":
                groups = detailed_data.get("by_groups", [])
                per_page = 10
                start_idx = page * per_page
                end_idx = start_idx + per_page
                page_groups = groups[start_idx:end_idx]
                
                text_parts = [
                    f"📦 Фудкост по группам\n",
                    f"Период: {period_text}\n",
                    f"🕐 Обновлено: {detailed_data.get('updated_at', datetime.now().strftime('%H:%M:%S'))}\n\n"
                ]
                
                if page_groups:
                    text_parts.append("Топ групп:\n")
                    for i, group in enumerate(page_groups, start=start_idx + 1):
                        name = group.get("name", "Без группы")[:40]
                        revenue = group.get("revenue", 0)
                        cost = group.get("cost", 0)
                        foodcost_pct = group.get("foodcost_pct", 0)
                        orders = group.get("orders", 0)
                        
                        emoji = "🟢" if foodcost_pct <= 30 else "🟡" if foodcost_pct <= 40 else "🔴"
                        text_parts.append(
                            f"{i}. {emoji} {name}\n"
                            f"   Выручка: {revenue:,.0f} ₽ | Себестоимость: {cost:,.0f} ₽\n"
                            f"   Фудкост: {foodcost_pct:.1f}% | Заказов: {orders:.0f}\n"
                        )
                    
                    if len(groups) > end_idx:
                        text_parts.append(f"\n... и ещё {len(groups) - end_idx} групп")
                else:
                    text_parts.append("Нет данных о группах")
                
                text = "\n".join(text_parts)
            else:
                text = "Неизвестный тип просмотра"
            
            if len(text) > 4000:
                text = text[:4000] + "\n\n... (сообщение обрезано)"
            
            try:
                await callback.message.edit_text(
                    text,
                    reply_markup=await variables.keyboards.foodcost.menu(period, view_type, page)
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    await callback.answer()
                else:
                    raise
    except Exception as e:
        logger.error(f"Error getting food cost: {e}")
        import traceback
        traceback.print_exc()
        await callback.answer("Ошибка при получении данных о фудкосте", show_alert=True)


@router.message()
async def handle_other_messages(message: Message, variables):
    await message.answer(
        "Используйте кнопки для навигации:",
        reply_markup=await variables.keyboards.main.menu()
    )

