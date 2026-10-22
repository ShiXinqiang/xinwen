"""Настройки из переменных окружения (.env). Динамические настройки фильтров — в таблице config (storage)."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _parse_ids(value: str) -> frozenset:
    return frozenset(int(x) for x in value.replace(' ', '').split(',') if x)


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    # Служебные сообщения (итоги сбора) — только сюда, не в канал
    admin_chat_id: str | None
    # Кто может пользоваться агентом; пусто — все
    allowed_user_ids: frozenset
    yandex_folder_id: str | None
    yandex_api_key: str | None
    gnews_api_key: str | None
    # Как часто собирать новости в постоянно работающем процессе (VPS)
    collect_interval_minutes: int = 30
    # Модель для оценки новостей: короткое имя (yandexgpt-lite/latest) или полный URI
    score_model: str = "yandexgpt-lite/latest"


def load_settings() -> Settings:
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        admin_chat_id=os.getenv("ADMIN_CHAT_ID") or None,
        allowed_user_ids=_parse_ids(os.getenv("ALLOWED_USER_IDS", "")),
        yandex_folder_id=os.getenv("YANDEX_FOLDER_ID") or None,
        yandex_api_key=os.getenv("YANDEX_API_KEY") or None,
        gnews_api_key=os.getenv("GNEWS_API_KEY") or None,
        collect_interval_minutes=int(os.getenv("COLLECT_INTERVAL_MINUTES") or 30),
        score_model=os.getenv("SCORE_MODEL") or "yandexgpt-lite/latest",
    )


def db_path() -> str:
    return os.getenv("NEWS_DB_PATH", "news.db")


def backup_dir() -> str:
    return os.getenv("BACKUP_DIR") or os.path.join(os.path.dirname(os.path.abspath(db_path())), "backups")
