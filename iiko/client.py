import httpx
import hashlib
import json
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from config import settings
import logging

logger = logging.getLogger(__name__)


class IikoClient:
    def __init__(self):
        self.base_url = settings.IIKO_BASE_URL
        self.api_login = settings.IIKO_API_LOGIN
        self.api_password = settings.IIKO_API_PASSWORD
        self._token: Optional[str] = None
        # Увеличиваем timeout для OLAP запросов - они могут быть долгими
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self):
        await self._client.aclose()

    async def get_token(self) -> str:
        """
        Получение токена доступа для локального iiko API.
        Использует логин и пароль (пароль хешируется через SHA1).
        """
        if self._token:
            return self._token

        password_hash = hashlib.sha1(self.api_password.encode()).hexdigest()
        auth_data = {
            "login": self.api_login,
            "pass": password_hash
        }

        for attempt in range(3):
            try:
                response = await self._client.post(
                    f"{self.base_url}/auth",
                    data=auth_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                # Локальный iiko API возвращает токен напрямую в ответе как текст
                data = response.text.strip()
                if data:
                    self._token = data
                    return self._token
            except Exception as e:
                logger.error(f"Failed to get token (attempt {attempt + 1}/3): {e}")
                if attempt == 2:
                    raise

        raise Exception("Failed to get token after 3 attempts")

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        token = await self.get_token()
        headers = kwargs.pop("headers", {})
        headers["Content-Type"] = "application/json"

        # Токен передаётся через query параметр key
        url = f"{self.base_url}{endpoint}?key={token}"

        response = None
        for attempt in range(3):
            try:
                response = await self._client.request(
                    method,
                    url,
                    headers=headers,
                    **kwargs
                )
                
                # Обработка специфичных кодов ошибок iiko API
                if response.status_code == 401:
                    # Токен истёк, обновляем
                    logger.warning(f"Token expired (401), refreshing token for {endpoint}")
                    self._token = None
                    token = await self.get_token()
                    url = f"{self.base_url}{endpoint}?key={token}"
                    continue
                elif response.status_code == 400:
                    # Неверный запрос
                    error_text = response.text[:200] if hasattr(response, 'text') else "Bad Request"
                    logger.error(f"Bad request (400) for {endpoint}: {error_text}")
                    raise Exception(f"Bad request: {error_text}")
                elif response.status_code == 409:
                    # Конфликт - endpoint может быть недоступен
                    logger.debug(f"Conflict (409) for {endpoint} - endpoint may not be available")
                    return {}
                elif response.status_code >= 500:
                    # Ошибка сервера
                    logger.error(f"Server error ({response.status_code}) for {endpoint}")
                    if attempt < 2:  # Повторяем только первые 2 попытки
                        continue
                
                response.raise_for_status()
                
                # Проверяем, что ответ не пустой и является JSON
                content = response.text.strip()
                if not content:
                    logger.debug(f"Empty response from {endpoint}")
                    return {}
                
                try:
                    return response.json()
                except Exception as json_error:
                    logger.debug(f"Response is not JSON from {endpoint}: {content[:100] if content else 'empty'}")
                    # Если это не JSON, возвращаем пустой словарь
                    return {}
            except Exception as e:
                logger.error(f"Request failed (attempt {attempt + 1}/3): {e}")
                if attempt == 2:
                    raise
                if response is not None and response.status_code == 401:
                    self._token = None
                    token = await self.get_token()
                    url = f"{self.base_url}{endpoint}?key={token}"

    async def get_organizations(self) -> List[Dict[str, Any]]:
        """
        Получение списка организаций из локального iiko API.
        Использует endpoint /corporation/departments с параметром revisionFrom=-1 (по умолчанию).
        Если не удаётся получить - возвращает пустой список (бот работает со всеми организациями).
        Список организаций не критичен для работы бота - он работает со всеми организациями по умолчанию.
        """
        try:
            # Используем правильный endpoint с параметром revisionFrom согласно документации
            endpoint = "/corporation/departments"
            
            # Добавляем параметр revisionFrom=-1 (по умолчанию, неревизионный запрос)
            # Согласно документации: "По умолчанию (неревизионный запрос) revisionFrom = -1"
            try:
                # Используем прямой запрос с параметрами
                token = await self.get_token()
                headers = {"Content-Type": "application/json"}
                # Правильное формирование URL: сначала revisionFrom, потом key через &
                full_url = f"{self.base_url}{endpoint}?revisionFrom=-1&key={token}"
                
                response = None
                for attempt in range(3):
                    try:
                        response = await self._client.get(
                            full_url,
                            headers=headers
                        )
                        
                        if response.status_code == 401:
                            self._token = None
                            token = await self.get_token()
                            full_url = f"{self.base_url}{endpoint}?revisionFrom=-1&key={token}"
                            continue
                        
                        response.raise_for_status()
                        
                        # Проверяем, что ответ не пустой
                        content = response.text.strip()
                        if not content:
                            logger.warning(f"Endpoint {endpoint} returned empty response (status 200)")
                            logger.debug(f"Response headers: {dict(response.headers)}")
                            return []
                        
                        # Определяем Content-Type
                        content_type = response.headers.get('content-type', '').lower()
                        logger.debug(f"Response Content-Type: {content_type}")
                        
                        data = None
                        
                        # Парсим в зависимости от Content-Type
                        if 'xml' in content_type or content.strip().startswith('<?xml'):
                            # Парсим XML
                            try:
                                logger.debug(f"Parsing XML response from {endpoint}")
                                root = ET.fromstring(content)
                                
                                # Ищем corporateItemDtoes/corporateItemDto
                                items = root.findall('.//corporateItemDto')
                                if not items:
                                    # Пробуем другие возможные корневые элементы
                                    items = root.findall('.//department') or root.findall('.//item')
                                
                                data = []
                                for item in items:
                                    item_dict = {}
                                    for child in item:
                                        tag = child.tag
                                        text = child.text.strip() if child.text else None
                                        item_dict[tag] = text
                                    if item_dict:
                                        data.append(item_dict)
                                
                                logger.debug(f"Parsed {len(data)} organizations from XML response")
                                if len(data) > 0:
                                    first_item = data[0]
                                    possible_id_fields = [k for k in first_item.keys() if 'id' in k.lower() or 'guid' in k.lower() or 'uuid' in k.lower()]
                                    if 'id' not in first_item:
                                        logger.warning(f"No 'id' field found! Available fields: {list(first_item.keys())}")
                                        for field in ['departmentId', 'entityId', 'guid', 'uuid', 'corporateItemId']:
                                            if field in first_item:
                                                # Добавляем 'id' как алиас для удобства
                                                for org in data:
                                                    if field in org:
                                                        org['id'] = org[field]
                                                break
                                    
                            except ET.ParseError as e:
                                logger.error(f"❌ Failed to parse XML from {endpoint}: {e}")
                                logger.error(f"Response text (first 500 chars): {content[:500]}")
                                return []
                            except Exception as e:
                                logger.error(f"❌ Error processing XML from {endpoint}: {e}")
                                return []
                                
                        elif 'json' in content_type or content.strip().startswith('{') or content.strip().startswith('['):
                            # Парсим JSON
                            try:
                                data = response.json()
                                logger.debug(f"Parsed JSON response from {endpoint}: type={type(data).__name__}")
                            except Exception as e:
                                logger.error(f"❌ Failed to parse JSON from {endpoint}: {e}")
                                logger.error(f"Response text (first 500 chars): {content[:500]}")
                                return []
                        else:
                            logger.warning(f"Unknown Content-Type {content_type}, trying to parse as JSON")
                            try:
                                data = response.json()
                            except Exception as e:
                                logger.error(f"❌ Failed to parse response from {endpoint}: {e}")
                                logger.error(f"Content-Type: {content_type}")
                                logger.error(f"Response text (first 500 chars): {content[:500]}")
                                return []
                        
                        # Обрабатываем ответ
                        if isinstance(data, list):
                            if len(data) > 0:
                                return data
                            logger.warning(f"Empty list returned from {endpoint}")
                            return []
                        
                        if isinstance(data, dict):
                            for key in ["departments", "organizations", "entities", "data"]:
                                if key in data and isinstance(data[key], list) and len(data[key]) > 0:
                                    return data[key]
                            if data:
                                return [data]
                            logger.warning(f"Empty dict returned from {endpoint}")
                            return []
                        
                        return []
                    except Exception as e:
                        logger.error(f"Request failed (attempt {attempt + 1}/3): {e}")
                        if attempt == 2:
                            raise
                        if response is not None and response.status_code == 401:
                            self._token = None
                            token = await self.get_token()
                            full_url = f"{self.base_url}{endpoint}?revisionFrom=-1&key={token}"
                
            except Exception as e:
                # 409 Conflict - это нормально, endpoint может быть недоступен
                if "409" in str(e) or "Conflict" in str(e):
                    logger.debug(f"Endpoint {endpoint} returned 409 Conflict (endpoint may not be available)")
                elif "404" in str(e) or "Not Found" in str(e):
                    logger.debug(f"Endpoint {endpoint} returned 404 Not Found")
                else:
                    logger.debug(f"Endpoint {endpoint} failed: {e}")
            
            logger.debug("Organization list not available, bot will work with all organizations")
            return []
        except Exception as e:
            logger.debug(f"Could not get organizations list: {e}. Bot will work with all organizations.")
            return []

    async def get_terminals(self) -> List[Dict[str, Any]]:
        """
        Получение списка терминалов из локального iiko API.
        Использует endpoint /corporation/terminals с параметром revisionFrom=-1.
        """
        try:
            endpoint = "/corporation/terminals"
            token = await self.get_token()
            headers = {"Content-Type": "application/json"}
            full_url = f"{self.base_url}{endpoint}?revisionFrom=-1&key={token}"
            
            response = None
            for attempt in range(3):
                try:
                    response = await self._client.get(
                        full_url,
                        headers=headers
                    )
                    
                    if response.status_code == 401:
                        self._token = None
                        token = await self.get_token()
                        full_url = f"{self.base_url}{endpoint}?revisionFrom=-1&key={token}"
                        continue
                    
                    response.raise_for_status()
                    
                    content = response.text.strip()
                    if not content:
                        logger.warning(f"Endpoint {endpoint} returned empty response (status 200)")
                        return []
                    
                    content_type = response.headers.get('content-type', '').lower()
                    
                    data = None
                    
                    if 'xml' in content_type or content.strip().startswith('<?xml'):
                        try:
                            root = ET.fromstring(content)
                            # Пробуем разные варианты поиска элементов терминалов
                            items = root.findall('.//terminal')
                            if not items:
                                items = root.findall('.//item')
                            if not items:
                                items = root.findall('.//terminalDto')
                            if not items:
                                items = root.findall('.//corporateItemDto')
                            
                            # Логируем структуру XML для отладки
                            if not items:
                                logger.warning(f"No terminal elements found in XML. Root tag: {root.tag}")
                                logger.debug(f"XML structure (first 500 chars): {content[:500]}")
                                # Пробуем найти все элементы
                                all_elements = root.findall('.//*')
                                if all_elements:
                                    unique_tags = set(elem.tag for elem in all_elements)
                                    logger.debug(f"Available XML tags: {list(unique_tags)[:20]}")
                            
                            data = []
                            for item in items:
                                item_dict = {}
                                for child in item:
                                    tag = child.tag
                                    text = child.text.strip() if child.text else None
                                    item_dict[tag] = text
                                if item_dict:
                                    data.append(item_dict)
                            
                            logger.debug(f"Parsed {len(data)} terminals from XML response")
                        except ET.ParseError as e:
                            logger.error(f"❌ Failed to parse XML from {endpoint}: {e}")
                            return []
                    elif 'json' in content_type or content.strip().startswith('{') or content.strip().startswith('['):
                        try:
                            data = response.json()
                            if isinstance(data, dict):
                                # Пробуем разные ключи
                                for key in ["terminals", "data", "items"]:
                                    if key in data and isinstance(data[key], list):
                                        data = data[key]
                                        break
                        except Exception as e:
                            logger.error(f"❌ Failed to parse JSON from {endpoint}: {e}")
                            return []
                    
                    if isinstance(data, list):
                        logger.debug(f"Got {len(data)} terminals from {endpoint}")
                        return data
                    
                    return []
                except httpx.HTTPStatusError as e:
                    logger.error(f"Request failed with status {e.response.status_code} (attempt {attempt + 1}/3): {e}")
                    if attempt == 2:
                        raise
                except httpx.RequestError as e:
                    logger.error(f"Request failed (attempt {attempt + 1}/3): {e}")
                    if attempt == 2:
                        raise
            
            return []
        except Exception as e:
            logger.error(f"Could not get terminals list: {e}")
            return []

    async def get_sales_metrics(
        self,
        org_ids: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получение метрик продаж через OLAP отчеты локального iiko API.
        Использует endpoint /v2/reports/olap
        Формат запроса основан на рабочем примере.
        
        Для получения себестоимости пробует использовать отчёт по контролю хранения,
        так как поля себестоимости (ProductCostBase.ProductCost, ProductCostBase.OneItem)
        доступны только в этом типе отчёта, а не в SALES.
        """
        try:
            # Базовые поля для отчёта по продажам
            base_aggregate_fields = [
                "UniqOrderId.OrdersCount",
                "DishDiscountSumInt",
                "DishSumInt"
            ]
            
            # Поля себестоимости из отчёта по контролю хранения
            cost_aggregate_fields = [
                "ProductCostBase.ProductCost",  # Себестоимость из отчёта по контролю хранения
                "ProductCostBase.OneItem"       # Себестоимость единицы из отчёта по контролю хранения
            ]
            
            # OLAP запрос для агрегации метрик продаж
            olap_payload_sales = {
                "reportType": "SALES",
                "groupByRowFields": [
                    "CloseTime",
                    "OpenTime"
                ],
                "groupByColFields": [],
                "aggregateFields": base_aggregate_fields,
                "filters": {
                    "OpenDate.Typed": {
                        "filterType": "DateRange",
                        "from": date_from,
                        "to": date_to,
                        "includeLow": True,
                        "includeHigh": True
                    }
                }
            }
            
            # OLAP запрос для получения себестоимости из отчёта по контролю хранения
            # Согласно ошибке API, доступные типы отчётов: [STOCK, SALES, TRANSACTIONS, DELIVERIES]
            # STOCK - это отчёт по складу/остаткам (контроль хранения), где должны быть поля себестоимости
            storage_report_type = "STOCK"
            
            # Пробуем разные варианты полей для STOCK отчёта
            # Согласно документации, в STOCK отчёте есть поле EventDate (не OpenDate)
            olap_payload_storage = {
                "reportType": storage_report_type,
                "groupByRowFields": [
                    "ProductName"  # Название блюда/продукта
                ],
                "groupByColFields": [],
                "aggregateFields": cost_aggregate_fields,
                "filters": {
                    "EventDate": {  # Для STOCK отчёта используем EventDate (без .Typed)
                        "filterType": "DateRange",
                        "from": date_from,
                        "to": date_to,
                        "includeLow": True,
                        "includeHigh": True
                    }
                }
            }
            logger.debug(f"Will try storage report type: {storage_report_type}")
            
            if org_ids:
                logger.debug(f"Filtering by organizations (client-side): {org_ids[:3]}..." if len(org_ids) > 3 else f"Filtering by organizations (client-side): {org_ids}")
            
            sales_response = None
            used_version = None
            # v1 API использует GET, а не POST, поэтому пробуем только v2 для POST запросов
            for version in ["v2"]:
                endpoint = f"/{version}/reports/olap"
                try:
                    sales_response = await self._make_request(
                        "POST",
                        endpoint,
                        json=olap_payload_sales
                    )
                    if sales_response:
                        used_version = version
                        break
                except Exception as e:
                    logger.debug(f"OLAP API {version} failed for SALES: {e}")
            
            if not sales_response:
                logger.error("Failed to get sales data from OLAP API")
                raise Exception("Failed to get sales data from OLAP response")
            
            cost_data = None
            sales_cost_response = None
            try:
                # Пробуем добавить поля себестоимости в запрос SALES
                olap_payload_sales_with_cost = {
                    "reportType": "SALES",
                    "groupByRowFields": [
                        "DishName",  # Группируем по блюдам для получения себестоимости
                        "OpenTime",
                        "CloseTime"
                    ],
                    "groupByColFields": [],
                    "aggregateFields": base_aggregate_fields + cost_aggregate_fields,  # Добавляем поля себестоимости
                    "filters": {
                        "OpenDate.Typed": {
                            "filterType": "DateRange",
                            "from": date_from,
                            "to": date_to,
                            "includeLow": True,
                            "includeHigh": True
                        }
                    }
                }
                
                if used_version == "v2":
                    sales_cost_response = await self._make_request(
                        "POST",
                        f"/{used_version}/reports/olap",
                        json=olap_payload_sales_with_cost
                    )
                else:
                    sales_cost_response = None
                
                if sales_cost_response and isinstance(sales_cost_response, dict) and 'data' in sales_cost_response:
                    sales_cost_data = sales_cost_response.get('data', [])
                    if sales_cost_data and len(sales_cost_data) > 0:
                        first_item_keys = list(sales_cost_data[0].keys())
                        cost_fields = [k for k in first_item_keys if 'cost' in k.lower() or 'ProductCostBase' in k or 'Cost' in k]
                        if cost_fields:
                            cost_data = sales_cost_data
                        else:
                            logger.debug(f"SALES report with cost fields returned data but no cost fields found")
            except Exception as e:
                error_msg = str(e)
                if "Unknown OLAP field" not in error_msg:
                    logger.debug(f"Failed to get cost from SALES report: {e}")
            
            if not cost_data or len(cost_data) == 0:
                cost_response = None
            
            # Сначала пробуем v1 API с GET запросом (формат: report=STOCK&from=DD.MM.YYYY&to=DD.MM.YYYY&groupRow=ProductName&agr=ProductCostBase.ProductCost)
            try:
                # Преобразуем даты в формат DD.MM.YYYY для v1 API
                if date_from:
                    date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
                else:
                    date_from_obj = datetime.now()
                if date_to:
                    date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
                else:
                    date_to_obj = datetime.now()
                date_from_v1 = date_from_obj.strftime("%d.%m.%Y")
                date_to_v1 = date_to_obj.strftime("%d.%m.%Y")
                
                token = await self.get_token()
                endpoint_v1 = "/reports/olap"
                
                # Пробуем разные варианты параметров для v1 GET запроса
                v1_variants = [
                    ("EventDate+ProductName", f"groupRow=EventDate&groupRow=ProductName"),
                    ("ProductName only", f"groupRow=ProductName"),
                    ("EventCookingDate+ProductName", f"groupRow=EventCookingDate&groupRow=ProductName"),
                ]
                
                for variant_name, group_row_params in v1_variants:
                    if cost_data and len(cost_data) > 0:
                        break  # Уже получили данные
                    
                    url = f"{self.base_url}{endpoint_v1}?key={token}&report={storage_report_type}&from={date_from_v1}&to={date_to_v1}&{group_row_params}&agr=ProductCostBase.ProductCost&agr=ProductCostBase.OneItem"
                    
                    logger.debug(f"Trying OLAP API v1 GET endpoint: {endpoint_v1} (report={storage_report_type}, variant={variant_name})")
                    
                    response = None
                    for attempt in range(3):
                        try:
                            response = await self._client.get(url)
                            if response.status_code == 401:
                                self._token = None
                                token = await self.get_token()
                                url = f"{self.base_url}{endpoint_v1}?key={token}&report={storage_report_type}&from={date_from_v1}&to={date_to_v1}&{group_row_params}&agr=ProductCostBase.ProductCost&agr=ProductCostBase.OneItem"
                                continue
                            response.raise_for_status()
                            
                            content = response.text.strip()
                            if not content:
                                logger.debug(f"STOCK v1 report (variant={variant_name}) returned empty response")
                                break
                            
                            if content.strip().startswith('<?xml') or content.strip().startswith('<'):
                                try:
                                    root = ET.fromstring(content)
                                    logger.debug(f"STOCK v1 XML response root tag: {root.tag} (variant={variant_name})")
                                    
                                    rows = root.findall('.//row') or root.findall('.//item') or root.findall('.//r')
                                    if not rows:
                                        all_elements = root.findall('.//*')
                                    
                                    if rows and len(rows) > 0:
                                        # Преобразуем XML в список словарей
                                        cost_data = []
                                        for row in rows:
                                            row_dict = {}
                                            # Получаем атрибуты
                                            row_dict.update(row.attrib)
                                            # Получаем дочерние элементы
                                            for child in row:
                                                tag = child.tag
                                                text = child.text.strip() if child.text else None
                                                # Если есть атрибуты, объединяем их
                                                if child.attrib:
                                                    row_dict[tag] = {**child.attrib, 'value': text} if text else child.attrib
                                                else:
                                                    row_dict[tag] = text
                                            
                                            if row_dict:
                                                cost_data.append(row_dict)
                                        
                                        if cost_data and len(cost_data) > 0:
                                            first_item_keys = list(cost_data[0].keys())
                                            cost_fields = [k for k in first_item_keys if 'cost' in k.lower() or 'ProductCostBase' in k or 'Cost' in k]
                                            if cost_fields:
                                                break
                                            else:
                                                logger.debug(f"STOCK v1 report (variant={variant_name}) returned data but no cost fields")
                                                cost_data = None
                                        else:
                                            logger.debug(f"STOCK v1 XML report (variant={variant_name}) has rows but couldn't parse them")
                                    else:
                                        # Пустой отчёт или нет данных
                                        logger.debug(f"STOCK v1 XML report (variant={variant_name}) is empty or has no rows")
                                        # Логируем полную структуру XML для отладки
                                        try:
                                            xml_str = ET.tostring(root, encoding='unicode')
                                            logger.debug(f"   Full XML structure: {xml_str[:500]}")
                                            # Проверяем, может быть данные в другом формате
                                            if root.tag == 'report' and len(root) == 0:
                                                logger.debug(f"   Empty <report/> tag - no data for period {date_from_v1} - {date_to_v1} (variant={variant_name})")
                                        except Exception:
                                            pass
                                except ET.ParseError as xml_error:
                                    logger.debug(f"Failed to parse STOCK v1 XML (variant={variant_name}): {xml_error}")
                            else:
                                # Пробуем JSON
                                try:
                                    cost_response = response.json()
                                    if cost_response and isinstance(cost_response, dict) and 'data' in cost_response:
                                        cost_data = cost_response.get('data', [])
                                        if cost_data and len(cost_data) > 0:
                                            first_item_keys = list(cost_data[0].keys())
                                            cost_fields = [k for k in first_item_keys if 'cost' in k.lower() or 'ProductCostBase' in k or 'Cost' in k]
                                            if cost_fields:
                                                break
                                except Exception as json_error:
                                    logger.debug(f"STOCK v1 report (variant={variant_name}) response is not JSON or XML")
                        except Exception as e:
                            logger.debug(f"STOCK v1 GET request failed (variant={variant_name}, attempt {attempt + 1}/3): {e}")
                            if attempt == 2:
                                break  # Переходим к следующему варианту
                            if response is not None and response.status_code == 401:
                                self._token = None
                                token = await self.get_token()
                                url = f"{self.base_url}{endpoint_v1}?key={token}&report={storage_report_type}&from={date_from_v1}&to={date_to_v1}&{group_row_params}&agr=ProductCostBase.ProductCost&agr=ProductCostBase.OneItem"
            except Exception as e:
                logger.debug(f"Failed to try STOCK v1 GET request: {e}")
            
            # Если v1 не сработал, пробуем v2
            # Согласно ответу API, для STOCK отчёта ОБЯЗАТЕЛЕН фильтр EventDate
            # Пробуем разные варианты группировки с обязательным фильтром EventDate
            if not cost_data or len(cost_data) == 0:
                endpoint = "/v2/reports/olap"
                
                # Пробуем разные варианты группировки для STOCK отчёта (с обязательным фильтром EventDate)
                grouping_variants = [
                    (["ProductName"], "ProductName only"),
                    (["EventDate", "ProductName"], "EventDate+ProductName"),
                    (["ProductName", "EventDate"], "ProductName+EventDate"),
                ]
                
                for group_fields, variant_name in grouping_variants:
                    if cost_data and len(cost_data) > 0:
                        break  # Уже получили данные
                    
                    try:
                        # Формируем payload с обязательным фильтром EventDate
                        payload = {
                            "reportType": storage_report_type,
                            "groupByRowFields": group_fields,
                            "groupByColFields": [],
                            "aggregateFields": cost_aggregate_fields,
                            "filters": {
                                "EventDate": {  # ОБЯЗАТЕЛЬНЫЙ фильтр для STOCK отчёта
                                    "filterType": "DateRange",
                                    "from": date_from,
                                    "to": date_to,
                                    "includeLow": True,
                                    "includeHigh": True
                                }
                            }
                        }
                        
                        logger.debug(f"Trying OLAP API v2 endpoint: {endpoint} (reportType={storage_report_type}, grouping={variant_name})")
                        
                        try:
                            token = await self.get_token()
                            url = f"{self.base_url}{endpoint}?key={token}"
                            response = await self._client.post(
                                url,
                                headers={"Content-Type": "application/json"},
                                json=payload
                            )
                            
                            if response.status_code == 409:
                                # 409 Conflict - логируем содержимое ответа
                                response_text = response.text[:1000] if response.text else "No response text"
                                logger.debug(f"STOCK report (grouping={variant_name}) returned 409 Conflict")
                                continue
                            
                            response.raise_for_status()
                            cost_response = response.json() if response.text else {}
                        except httpx.HTTPStatusError as e:
                            if e.response.status_code == 400:
                                error_text = e.response.text[:500] if hasattr(e.response, 'text') else str(e)
                                logger.error(f"Bad request (400) for {endpoint}: {error_text}")
                                # Продолжаем пробовать следующий вариант
                                continue
                            raise
                        
                        if cost_response and isinstance(cost_response, dict):
                            if 'data' in cost_response:
                                cost_data = cost_response.get('data', [])
                                if cost_data and len(cost_data) > 0:
                                    first_item_keys = list(cost_data[0].keys())
                                    cost_fields = [k for k in first_item_keys if 'cost' in k.lower() or 'ProductCostBase' in k or 'Cost' in k]
                                    if cost_fields:
                                        break
                                    else:
                                        logger.debug(f"STOCK report (grouping={variant_name}) returned data but no cost fields found")
                                        cost_data = None
                                else:
                                    logger.debug(f"STOCK report (grouping={variant_name}) returned empty data list")
                            else:
                                # Ответ есть, но нет ключа 'data' - логируем структуру ответа
                                logger.debug(f"STOCK report (grouping={variant_name}) response doesn't have 'data' key")
                        else:
                            logger.debug(f"STOCK report (grouping={variant_name}) response structure is invalid: {type(cost_response)}")
                    except Exception as e:
                        error_msg = str(e)
                        if "Unknown OLAP field" in error_msg:
                            logger.debug(f"STOCK report (grouping={variant_name}) has unknown fields")
                            # Продолжаем пробовать следующий вариант
                            continue
                        elif "reportType" in error_msg.lower():
                            logger.debug(f"Report type '{storage_report_type}' not supported")
                            break  # Не имеет смысла пробовать другие варианты
                        else:
                            logger.debug(f"OLAP API v2 failed for STOCK report (grouping={variant_name})")
                            # Продолжаем пробовать следующий вариант
                            continue
            
            if not cost_data or len(cost_data) == 0:
                logger.debug("Could not get cost data from STOCK report")
            
            # Используем sales_response как основной ответ
            response = sales_response
            
            # Логируем запрос и ответ для отладки
            if org_ids:
                logger.debug(f"OLAP request with org filter: {org_ids[:3]}..." if len(org_ids) > 3 else f"OLAP request with org filter: {org_ids}")
                logger.debug(f"OLAP payload filters: {json.dumps(olap_payload_sales.get('filters', {}), indent=2, ensure_ascii=False)}")
            
            # --- Шаг 3: Обработка данных о продажах ---
            revenue = 0
            orders = 0
            total_cost = 0  # Общая себестоимость для фудкоста
            
            if isinstance(response, dict) and 'data' in response:
                data = response['data']
                if isinstance(data, list) and len(data) > 0:
                    # Логируем структуру первого элемента
                    first_item_keys = list(data[0].keys())
                    logger.debug(f"Sales OLAP response item keys: {first_item_keys}")
                    
                    cost_fields_in_sales = [k for k in first_item_keys if 'cost' in k.lower() or 'ProductCostBase' in k or 'Cost' in k]
                    if cost_fields_in_sales and not cost_data:
                        logger.debug(f"Found cost fields in main SALES report: {cost_fields_in_sales}")
                        # Используем данные из основного ответа для расчёта себестоимости
                        cost_data = data
                    
                    if org_ids:
                        logger.debug(f"Client-side filtering by org_ids is not possible - DepartmentId not available in OLAP response")
                    
                    # Агрегируем заказы по аналогии с _aggregate_take_stats из рабочего примера
                    orders_dict = {}  # order_key -> сумма заказа
                    
                    for item in data:
                        # Формируем ключ заказа по OpenTime + CloseTime
                        open_time = str(item.get('OpenTime', ''))
                        close_time = str(item.get('CloseTime', ''))
                        order_key = f"{open_time}_{close_time}"
                        
                        # Берём сумму со скидкой, если есть, иначе без скидки
                        dish_sum = item.get('DishDiscountSumInt')
                        if dish_sum is None:
                            dish_sum = item.get('DishSumInt') or 0
                        
                        try:
                            value = float(dish_sum or 0)
                        except (TypeError, ValueError):
                            value = 0.0
                        
                        # Суммируем по ключу заказа
                        orders_dict[order_key] = orders_dict.get(order_key, 0.0) + value
                    
                    # Количество уникальных заказов
                    orders = len(orders_dict)
                    # Общая выручка
                    revenue = sum(orders_dict.values())
            
            # --- Шаг 4: Обработка данных о себестоимости из отчёта по контролю хранения ---
            if cost_data and len(cost_data) > 0:
                logger.info(f"Processing cost data from storage report ({len(cost_data)} items)")
                first_cost_item_keys = list(cost_data[0].keys())
                logger.info(f"Storage report item keys: {first_cost_item_keys}")
                
                # Ищем поля себестоимости
                cost_field = None
                for field in ['ProductCostBase.ProductCost', 'ProductCostBase.OneItem', 'ProductCost', 'Cost']:
                    if field in first_cost_item_keys:
                        cost_field = field
                        logger.info(f"Using cost field: {field}")
                        break
                
                if cost_field:
                    # Агрегируем себестоимость
                    for item in cost_data:
                        cost_value = item.get(cost_field)
                        if cost_value is not None:
                            try:
                                cost_float = float(cost_value)
                                total_cost += cost_float
                            except (TypeError, ValueError):
                                pass
                    
                    logger.debug(f"Total cost from storage report: {total_cost:,.0f}")
                else:
                    logger.debug(f"No cost fields found in storage report")
            else:
                logger.debug(f"No cost data available from STOCK report")
            
            avg_check = revenue / orders if orders > 0 else 0
            
            # Рассчитываем фудкост (себестоимость / выручка * 100%)
            food_cost_pct = (total_cost / revenue * 100) if revenue > 0 else 0
            
            # Логируем для отладки
            logger.debug(f"Food cost calculation: revenue={revenue:,.0f}, cost={total_cost:,.0f}, food_cost_pct={food_cost_pct:.1f}%")
            if total_cost == 0 and revenue > 0:
                logger.warning(f"Food cost is 0 but revenue > 0!")
            
            return {
                "revenue": revenue,
                "orders": orders,
                "average_check": avg_check,
                "food_cost": total_cost,
                "food_cost_pct": food_cost_pct
            }
        except Exception as e:
            logger.error(f"Failed to get sales metrics: {e}")
            # Return mock data structure for development
            return {
                "revenue": 0,
                "orders": 0,
                "average_check": 0,
                "food_cost": 0,
                "food_cost_pct": 0
            }
    
    async def get_detailed_foodcost(
        self,
        org_ids: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получение детализированного фудкоста по блюдам и категориям.
        Возвращает данные сгруппированные по:
        - Блюдам (DishName)
        - Категориям (DishCategory)
        - Группам блюд (DishGroup)
        """
        try:
            # Поля для детализированного отчёта
            aggregate_fields = [
                "UniqOrderId.OrdersCount",
                "DishDiscountSumInt",
                "DishSumInt",
                "ProductCostBase.ProductCost",  # Пробуем получить себестоимость
                "ProductCostBase.OneItem"
            ]
            
            # OLAP запрос для детализированного фудкоста
            olap_payload = {
                "reportType": "SALES",
                "groupByRowFields": [
                    "DishName",      # Название блюда
                    "DishCategory",  # Категория блюда
                    "DishGroup"      # Группа блюда
                ],
                "groupByColFields": [],
                "aggregateFields": aggregate_fields,
                "filters": {
                    "OpenDate.Typed": {
                        "filterType": "DateRange",
                        "from": date_from,
                        "to": date_to,
                        "includeLow": True,
                        "includeHigh": True
                    }
                }
            }
            
            logger.info("📊 Getting detailed foodcost data (by dishes and categories)")
            
            # Пробуем получить данные через v2 API (v1 использует GET, а не POST)
            response = None
            for version in ["v2"]:
                endpoint = f"/{version}/reports/olap"
                try:
                    logger.info(f"Trying OLAP API {version} for detailed foodcost")
                    response = await self._make_request(
                        "POST",
                        endpoint,
                        json=olap_payload
                    )
                    if response:
                        logger.info(f"Successfully got detailed foodcost data from OLAP API {version}")
                        break
                except Exception as e:
                    error_msg = str(e)
                    if "Unknown OLAP field" in error_msg:
                        # Если поля себестоимости не поддерживаются, убираем их
                        logger.warning(f"Cost fields not supported in {version}, trying without them")
                        olap_payload["aggregateFields"] = [
                            "UniqOrderId.OrdersCount",
                            "DishDiscountSumInt",
                            "DishSumInt"
                        ]
                        try:
                            response = await self._make_request(
                                "POST",
                                endpoint,
                                json=olap_payload
                            )
                            if response:
                                logger.info(f"Got detailed foodcost data without cost fields from {version}")
                                break
                        except Exception as e2:
                            logger.warning(f"OLAP API {version} failed: {e2}")
                            continue
                    else:
                        logger.warning(f"OLAP API {version} failed: {e}")
                        continue
            
            if not response or not isinstance(response, dict) or 'data' not in response:
                logger.error("❌ Failed to get detailed foodcost data")
                return {
                    "by_dishes": [],
                    "by_categories": [],
                    "by_groups": [],
                    "total_revenue": 0,
                    "total_cost": 0,
                    "avg_foodcost_pct": 0
                }
            
            data = response.get('data', [])
            if not data or len(data) == 0:
                logger.warning("No data in detailed foodcost response")
                return {
                    "by_dishes": [],
                    "by_categories": [],
                    "by_groups": [],
                    "total_revenue": 0,
                    "total_cost": 0,
                    "avg_foodcost_pct": 0
                }
            
            # Логируем структуру первого элемента
            first_item_keys = list(data[0].keys())
            logger.debug(f"Detailed foodcost response item keys: {first_item_keys}")
            
            # Обрабатываем данные
            dishes_dict = {}  # dish_name -> {revenue, cost, orders, foodcost_pct}
            categories_dict = {}  # category -> {revenue, cost, orders, foodcost_pct}
            groups_dict = {}  # group -> {revenue, cost, orders, foodcost_pct}
            
            total_revenue = 0
            total_cost = 0
            
            for item in data:
                dish_name = item.get('DishName', 'Без названия')
                dish_category = item.get('DishCategory', 'Без категории')
                dish_group = item.get('DishGroup', 'Без группы')
                
                # Получаем выручку
                dish_sum = item.get('DishDiscountSumInt')
                if dish_sum is None:
                    dish_sum = item.get('DishSumInt') or 0
                try:
                    revenue = float(dish_sum or 0)
                except (TypeError, ValueError):
                    revenue = 0.0
                
                # Получаем себестоимость
                cost = 0.0
                cost_field = None
                for field in ['ProductCostBase.ProductCost', 'ProductCostBase.OneItem', 'ProductCost', 'Cost']:
                    if field in item:
                        cost_value = item.get(field)
                        if cost_value is not None:
                            try:
                                cost = float(cost_value)
                                cost_field = field
                                break
                            except (TypeError, ValueError):
                                pass
                
                # Получаем количество заказов
                orders = item.get('UniqOrderId.OrdersCount', 0)
                try:
                    orders = float(orders or 0)
                except (TypeError, ValueError):
                    orders = 0.0
                
                # Рассчитываем фудкост для этого блюда
                foodcost_pct = (cost / revenue * 100) if revenue > 0 else 0.0
                
                # Агрегируем по блюдам
                if dish_name not in dishes_dict:
                    dishes_dict[dish_name] = {
                        "name": dish_name,
                        "category": dish_category,
                        "group": dish_group,
                        "revenue": 0.0,
                        "cost": 0.0,
                        "orders": 0.0,
                        "foodcost_pct": 0.0
                    }
                dishes_dict[dish_name]["revenue"] += revenue
                dishes_dict[dish_name]["cost"] += cost
                dishes_dict[dish_name]["orders"] += orders
                
                # Агрегируем по категориям
                if dish_category not in categories_dict:
                    categories_dict[dish_category] = {
                        "name": dish_category,
                        "revenue": 0.0,
                        "cost": 0.0,
                        "orders": 0.0,
                        "foodcost_pct": 0.0
                    }
                categories_dict[dish_category]["revenue"] += revenue
                categories_dict[dish_category]["cost"] += cost
                categories_dict[dish_category]["orders"] += orders
                
                # Агрегируем по группам
                if dish_group not in groups_dict:
                    groups_dict[dish_group] = {
                        "name": dish_group,
                        "revenue": 0.0,
                        "cost": 0.0,
                        "orders": 0.0,
                        "foodcost_pct": 0.0
                    }
                groups_dict[dish_group]["revenue"] += revenue
                groups_dict[dish_group]["cost"] += cost
                groups_dict[dish_group]["orders"] += orders
                
                total_revenue += revenue
                total_cost += cost
            
            # Пересчитываем фудкост для каждого блюда, категории и группы
            for dish_name, dish_data in dishes_dict.items():
                if dish_data["revenue"] > 0:
                    dish_data["foodcost_pct"] = (dish_data["cost"] / dish_data["revenue"] * 100)
            
            for category_name, category_data in categories_dict.items():
                if category_data["revenue"] > 0:
                    category_data["foodcost_pct"] = (category_data["cost"] / category_data["revenue"] * 100)
            
            for group_name, group_data in groups_dict.items():
                if group_data["revenue"] > 0:
                    group_data["foodcost_pct"] = (group_data["cost"] / group_data["revenue"] * 100)
            
            # Сортируем по выручке (по убыванию)
            by_dishes = sorted(dishes_dict.values(), key=lambda x: x["revenue"], reverse=True)
            by_categories = sorted(categories_dict.values(), key=lambda x: x["revenue"], reverse=True)
            by_groups = sorted(groups_dict.values(), key=lambda x: x["revenue"], reverse=True)
            
            # Рассчитываем средний фудкост
            avg_foodcost_pct = (total_cost / total_revenue * 100) if total_revenue > 0 else 0.0
            
            logger.debug(f"Detailed foodcost: {len(by_dishes)} dishes, {len(by_categories)} categories, {len(by_groups)} groups")
            logger.info(f"   Total revenue: {total_revenue:,.0f}, Total cost: {total_cost:,.0f}, Avg foodcost: {avg_foodcost_pct:.1f}%")
            
            return {
                "by_dishes": by_dishes,
                "by_categories": by_categories,
                "by_groups": by_groups,
                "total_revenue": total_revenue,
                "total_cost": total_cost,
                "avg_foodcost_pct": avg_foodcost_pct
            }
            
        except Exception as e:
            logger.error(f"Failed to get detailed foodcost: {e}")
            import traceback
            traceback.print_exc()
            return {
                "by_dishes": [],
                "by_categories": [],
                "by_groups": [],
                "total_revenue": 0,
                "total_cost": 0,
                "avg_foodcost_pct": 0
            }
