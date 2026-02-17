from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_TG_ID: int
    IIKO_API_LOGIN: str  # Логин для локального iiko API
    IIKO_API_PASSWORD: str  # Пароль для локального iiko API
    IIKO_BASE_URL: str
    DEFAULT_REPORT_TIME: str = "23:00"
    DEFAULT_ALERT_THRESHOLD_PCT: int = 15
    DEFAULT_ROLLING_DAYS: int = 7
    TZ: str = "Europe/Moscow"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Игнорировать дополнительные поля из .env


settings = Settings()

