"""
Простое хранилище настроек в памяти (без БД).
Для продакшена можно будет переключиться на SQLAlchemy.
"""
from typing import Dict, Any, Optional
from config import settings as app_settings


class InMemorySettings:
    """Класс для хранения настроек в памяти"""
    def __init__(self):
        self._data: Dict[str, Any] = {
            "alert_threshold_pct": app_settings.DEFAULT_ALERT_THRESHOLD_PCT,
            "report_time": app_settings.DEFAULT_REPORT_TIME,
            "rolling_days": app_settings.DEFAULT_ROLLING_DAYS,
            "org_id": None
        }
    
    def get(self, key: str, default=None):
        return self._data.get(key, default)
    
    def set(self, key: str, value: Any):
        self._data[key] = value
    
    @property
    def alert_threshold_pct(self) -> int:
        return self._data["alert_threshold_pct"]
    
    @property
    def report_time(self) -> str:
        return self._data["report_time"]
    
    @property
    def rolling_days(self) -> int:
        return self._data["rolling_days"]
    
    @property
    def org_id(self) -> Optional[str]:
        return self._data["org_id"]


# Глобальный экземпляр настроек в памяти
_memory_settings = InMemorySettings()


class SettingsRepo:
    """Репозиторий для работы с настройками (в памяти)"""
    
    @staticmethod
    async def get_settings() -> InMemorySettings:
        """Получить настройки"""
        return _memory_settings

    @staticmethod
    async def update_settings(**kwargs) -> InMemorySettings:
        """Обновить настройки"""
        for key, value in kwargs.items():
            if key in _memory_settings._data:
                _memory_settings.set(key, value)
        return _memory_settings
