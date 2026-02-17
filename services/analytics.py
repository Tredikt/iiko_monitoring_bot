from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from iiko.client import IikoClient
from db.repo import SettingsRepo
import logging

logger = logging.getLogger(__name__)


class AnalyticsService:
    def __init__(self, iiko_client: IikoClient):
        self.iiko_client = iiko_client
        self._cache: Dict[str, tuple] = {}
        self._cache_ttl = 300

    async def get_all_organizations(self) -> List[Dict[str, Any]]:
        """Получение списка всех организаций"""
        orgs = await self.iiko_client.get_organizations()
        return orgs if orgs else []

    async def get_terminals(self) -> List[Dict[str, Any]]:
        """Получение списка всех терминалов"""
        terminals = await self.iiko_client.get_terminals()
        return terminals if terminals else []

    def _get_cache_key(self, date_from: str, date_to: str) -> str:
        """Генерирует ключ кэша для периода"""
        return f"{date_from}_{date_to}"

    def _is_cache_valid(self, cache_time: datetime) -> bool:
        """Проверяет, действителен ли кэш"""
        return (datetime.now() - cache_time).total_seconds() < self._cache_ttl

    async def get_metrics(self, date_from: str, date_to: str, org_ids: Optional[List[str]] = None, use_cache: bool = True) -> Dict[str, Any]:
        """
        Получение метрик по организациям.
        Если org_ids=None - агрегирует данные по всем организациям.
        Если org_ids указан - получает метрики только по указанным организациям.
        Использует кэширование для ускорения повторных запросов.
        """
        cache_key = f"{date_from}_{date_to}_{str(org_ids) if org_ids else 'all'}"
        
        if use_cache and cache_key in self._cache:
            cached_data, cache_time = self._cache[cache_key]
            if self._is_cache_valid(cache_time):
                logger.debug(f"Using cached metrics for {date_from} - {date_to} (orgs: {len(org_ids) if org_ids else 'all'})")
                return cached_data
            else:
                del self._cache[cache_key]
        
        metrics = await self.iiko_client.get_sales_metrics(
            org_ids=org_ids,
            date_from=date_from,
            date_to=date_to
        )
        
        revenue = metrics.get("revenue", 0) or metrics.get("totalRevenue", 0) or 0
        orders = metrics.get("orders", 0) or metrics.get("orderCount", 0) or 0
        avg_check = revenue / orders if orders > 0 else 0
        food_cost = metrics.get("food_cost", 0) or 0
        food_cost_pct = metrics.get("food_cost_pct", 0) or 0

        result = {
            "revenue": revenue,
            "orders": orders,
            "average_check": avg_check,
            "food_cost": food_cost,
            "food_cost_pct": food_cost_pct
        }
        
        if use_cache:
            self._cache[cache_key] = (result, datetime.now())
            logger.debug(f"Cached metrics for {date_from} - {date_to} (orgs: {len(org_ids) if org_ids else 'all'})")
        
        return result

    async def get_org_names(self) -> str:
        """Получение названий всех организаций для отображения"""
        orgs = await self.get_all_organizations()
        if len(orgs) == 1:
            return orgs[0].get("name", "Все организации")
        elif len(orgs) > 1:
            departments = [org for org in orgs if org.get("type") == "DEPARTMENT"]
            if departments:
                names = [dept.get("name", "Unknown") for dept in departments if dept.get("name")]
                if names:
                    return f"Все организации ({len(departments)})"
            return f"Все организации ({len(orgs)})"
        return "Все организации"

    async def get_period_metrics(self, date_from: datetime, date_to: datetime, org_ids: Optional[List[str]] = None, use_cache: bool = True) -> Dict[str, Any]:
        date_from_str = date_from.strftime("%Y-%m-%d")
        date_to_str = date_to.strftime("%Y-%m-%d")
        
        metrics = await self.get_metrics(date_from_str, date_to_str, org_ids=org_ids, use_cache=use_cache)
        
        if org_ids and len(org_ids) == 1:
            orgs = await self.get_all_organizations()
            org = next((o for o in orgs if o.get("id") == org_ids[0]), None)
            org_name = org.get("name", "Организация") if org else "Организация"
        elif org_ids and len(org_ids) > 1:
            org_name = f"Выбранные организации ({len(org_ids)})"
        else:
            org_name = await self.get_org_names()
        
        return {
            "org_name": org_name,
            "date_from": date_from_str,
            "date_to": date_to_str,
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            **metrics
        }

    async def compare_with_yesterday(self, today_metrics: Dict[str, Any], org_ids: Optional[List[str]] = None) -> Optional[float]:
        """Сравнение с вчерашним днём"""
        try:
            today = datetime.now()
            yesterday = today - timedelta(days=1)
            
            yesterday_metrics = await self.get_period_metrics(yesterday, yesterday, org_ids=org_ids)
            
            if yesterday_metrics["revenue"] == 0:
                return None
            
            change_pct = ((today_metrics["revenue"] - yesterday_metrics["revenue"]) / yesterday_metrics["revenue"]) * 100
            return change_pct
        except Exception as e:
            logger.error(f"Failed to compare with yesterday: {e}")
            return None

    async def compare_periods(
        self, 
        current_from: datetime, 
        current_to: datetime,
        previous_from: datetime,
        previous_to: datetime,
        org_ids: Optional[List[str]] = None
    ) -> Dict[str, Optional[float]]:
        """
        Сравнение двух периодов.
        Возвращает процент изменения для выручки, заказов и среднего чека.
        Использует кэш для ускорения (прошлые периоды можно кэшировать).
        """
        try:
            current_metrics = await self.get_period_metrics(current_from, current_to, org_ids=org_ids, use_cache=True)
            previous_metrics = await self.get_period_metrics(previous_from, previous_to, org_ids=org_ids, use_cache=True)
            
            result = {
                "revenue_change": None,
                "orders_change": None,
                "avg_check_change": None
            }
            
            if previous_metrics["revenue"] > 0:
                result["revenue_change"] = (
                    (current_metrics["revenue"] - previous_metrics["revenue"]) / 
                    previous_metrics["revenue"] * 100
                )
            
            if previous_metrics["orders"] > 0:
                result["orders_change"] = (
                    (current_metrics["orders"] - previous_metrics["orders"]) / 
                    previous_metrics["orders"] * 100
                )
            
            if previous_metrics["average_check"] > 0:
                result["avg_check_change"] = (
                    (current_metrics["average_check"] - previous_metrics["average_check"]) / 
                    previous_metrics["average_check"] * 100
                )
            
            return result
        except Exception as e:
            logger.error(f"Failed to compare periods: {e}")
            return {"revenue_change": None, "orders_change": None, "avg_check_change": None}

    async def get_rolling_average(self, days: int) -> float:
        today = datetime.now()
        date_from = today - timedelta(days=days)
        
        metrics = await self.get_period_metrics(date_from, today)
        return metrics["revenue"] / days if days > 0 else 0
    
    async def get_detailed_foodcost(
        self,
        date_from: datetime,
        date_to: datetime,
        org_ids: Optional[List[str]] = None,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Получение детализированного фудкоста по блюдам и категориям.
        Возвращает данные сгруппированные по блюдам, категориям и группам.
        """
        date_from_str = date_from.strftime("%Y-%m-%d")
        date_to_str = date_to.strftime("%Y-%m-%d")
        
        cache_key = f"detailed_foodcost_{date_from_str}_{date_to_str}_{str(org_ids) if org_ids else 'all'}"
        
        if use_cache and cache_key in self._cache:
            cached_data, cache_time = self._cache[cache_key]
            if self._is_cache_valid(cache_time):
                logger.debug(f"Using cached detailed foodcost for {date_from_str} - {date_to_str}")
                return cached_data
            else:
                del self._cache[cache_key]
        
        detailed_data = await self.iiko_client.get_detailed_foodcost(
            org_ids=org_ids,
            date_from=date_from_str,
            date_to=date_to_str
        )
        
        result = {
            "date_from": date_from_str,
            "date_to": date_to_str,
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            **detailed_data
        }
        
        if use_cache:
            self._cache[cache_key] = (result, datetime.now())
            logger.debug(f"Cached detailed foodcost for {date_from_str} - {date_to_str}")
        
        return result

