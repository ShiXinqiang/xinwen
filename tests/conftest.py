import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from newsbot import storage


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    """Каждый тест — со своей пустой базой; переменные окружения не протекают из .env."""
    monkeypatch.setenv("NEWS_DB_PATH", str(tmp_path / "news.db"))
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ADMIN_CHAT_ID", "ALLOWED_USER_IDS",
                 "YANDEX_FOLDER_ID", "YANDEX_API_KEY", "GNEWS_API_KEY",
                 "COLLECT_INTERVAL_MINUTES", "BACKUP_DIR", "SCORE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    storage.init_db()
    return tmp_path / "news.db"


def make_article(title, url=None, description='', hours_ago=1, source='Тест'):
    published = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    url = url or f"https://example.ru/{abs(hash(title))}"
    return {
        'title': title,
        'url': url,
        'raw_url': url,
        'description': description,
        'publishedAt': published.isoformat(),
        'published': published,
        'source': {'name': source},
    }


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
