import os
from dataclasses import dataclass


def _parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@dataclass(slots=True)
class Settings:
    app_name: str = "Отгрузка Status"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/fbs_tracker.db")
    bot_token: str = os.getenv("BOT_TOKEN", "")
    webapp_url: str = os.getenv("WEBAPP_URL", "http://localhost:8000")
    timezone: str = os.getenv("TIMEZONE", "Europe/Moscow")
    owner_telegram_id: int | None = _parse_optional_int(os.getenv("OWNER_TELEGRAM_ID"))


settings = Settings()

