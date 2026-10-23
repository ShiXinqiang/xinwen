"""Поиск новостей через GNews API."""
import requests
from datetime import datetime, timedelta, timezone

from newsbot.config import load_settings


def fetch_gnews(query='', max_articles=20):
    """Получает новости из GNews по запросу за последние сутки."""
    api_key = load_settings().gnews_api_key
    if not api_key:
        return []
    from_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    params = {'q': query, 'from': from_date, 'max': max_articles, 'lang': 'ru', 'apikey': api_key}
    try:
        resp = requests.get("https://gnews.io/api/v4/search", params=params, timeout=15)
        if resp.status_code != 200:
            print(f"GNews ошибка: {resp.status_code}")
            return []
        return resp.json().get('articles', [])
    except Exception as e:
        print(f"❌ Ошибка GNews: {e}")
        return []
