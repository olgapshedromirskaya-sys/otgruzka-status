import os
from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    app_name: str = "FBS Tracker Bot"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/fbs_tracker.db")
    bot_token: str = os.getenv("BOT_TOKEN", "")
    webapp_url: str = os.getenv("WEBAPP_URL", "http://localhost:8000")
    timezone: str = os.getenv("TIMEZONE", "Europe/Moscow")


settings = Settings()

