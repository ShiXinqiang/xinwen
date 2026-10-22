import os
import re
import html
import calendar
import hashlib
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup

GNEWS_API_KEY = os.getenv('GNEWS_API_KEY')

# ---- RSS ЛЕНТЫ ----
RSS_FEEDS = [
    "https://ria.ru/export/rss2/index.xml",
    "https://tass.ru/rss/v2.xml",
    "https://www.interfax.ru/rss.asp",
    "https://www.finmarket.ru/export/rss.asp",
    "https://www.kommersant.ru/RSS/news.xml",
    "https://www.vedomosti.ru/rss",
    "https://1prime.ru/export/rss.xml",
    "https://www.forbes.ru/rss/all",
    "https://iz.ru/xml/rss/all.xml",
    "https://www.tks.ru/law.rss",
    "https://www.tks.ru/nearby.rss",
    "https://trans.ru/rss/news",
    "https://www.infranews.ru/feed/",
    "https://www.tourdom.ru/rss/",
    "https://www.autostat.ru/export/rss/",
    "https://morvesti.ru/rss/",
    "https://portnews.ru/rss/",
    "https://seanews.ru/feed/",
    "https://primpress.ru/rss/",
    "https://www.cnews.ru/news/rss",
    "https://www.comnews.ru/rss",
    "http://www.cbr.ru/rss/RssNews",
    "http://www.cbr.ru/rss/RssPress",
    "https://biang.ru/rss/",
    "http://russian.news.cn/rss/news.xml",
    "https://www.eastrussia.ru/feed/",
    "https://bigasia.ru/feed/",
    "http://russian.china.org.cn/rss/feed.xml",
    "http://russian.people.com.cn/rss/feed.xml",
    "https://rsshub.app/cnbc/rss/",
    "https://www.scmp.com/rss/",
    "https://tvbrics.com/feed/"
]
MAX_ARTICLES_PER_FEED = 20

# Параметры ссылок, которые не меняют саму статью (метки рекламных кампаний и т.п.)
TRACKING_PARAMS = {'yclid', 'gclid', 'fbclid', 'from', 'ref'}


# ---- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----

def normalize_text(text: str) -> str:
    text = re.sub(r'[^\w\s]', '', text).lower()
    return re.sub(r'\s+', ' ', text).strip()

def clean_html(text: str) -> str:
    """Убирает все HTML-теги и раскодирует сущности (&quot;, &nbsp; ...) — для plain text."""
    if not text:
        return ''
    text = BeautifulSoup(text, 'html.parser').get_text(' ')
    text = html.unescape(text).replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', text).strip()

def canonical_url(url: str) -> str:
    """Приводит ссылку к единому виду: без меток, якоря и завершающего слэша."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not (k.lower().startswith('utm_') or k.lower() in TRACKING_PARAMS)]
    path = parts.path.rstrip('/') or '/'
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ''))

def title_hash(title: str) -> str:
    """Хеш нормализованного заголовка. Описание не учитываем: редакции его часто правят."""
    return hashlib.md5(normalize_text(title).encode('utf-8')).hexdigest()

def entry_published(entry):
    """Дата публикации записи RSS в UTC или None, если даты нет."""
    parsed = entry.get('published_parsed') or entry.get('updated_parsed')
    if not parsed:
        return None
    # feedparser отдаёт struct_time в UTC
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)


# ---- ПОЛУЧЕНИЕ НОВОСТЕЙ ----

def fetch_gnews(query='', max_articles=20):
    """Получает новости из GNews по ключевым словам."""
    if not GNEWS_API_KEY:
        return []
    from_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    params = {'q': query, 'from': from_date, 'max': max_articles, 'lang': 'ru', 'apikey': GNEWS_API_KEY}
    try:
        resp = requests.get("https://gnews.io/api/v4/search", params=params, timeout=15)
        if resp.status_code != 200:
            print(f"GNews ошибка: {resp.status_code}")
            return []
        data = resp.json()
        return data.get('articles', [])
    except Exception as e:
        print(f"❌ Ошибка GNews: {e}")
        return []

def fetch_rss_feeds(feeds=RSS_FEEDS, max_per_feed=MAX_ARTICLES_PER_FEED):
    """
    Парсит RSS-ленты. Записи без даты публикации пропускаются.
    Возвращает статьи, отсортированные от новых к старым.
    """
    all_articles = []
    seen_urls = set()
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            source_name = feed.feed.get('title', 'Неизвестный источник')
            for entry in feed.entries[:max_per_feed]:
                if not entry.get('link') or not entry.get('title'):
                    continue
                url = canonical_url(entry.link)
                if url in seen_urls:
                    continue
                published = entry_published(entry)
                if published is None:
                    continue
                seen_urls.add(url)
                all_articles.append({
                    'title': clean_html(entry.title),
                    'url': url,
                    'raw_url': entry.link.strip(),
                    'description': clean_html(entry.get('summary', '') or entry.get('description', '')),
                    'publishedAt': published.isoformat(),
                    'published': published,
                    'source': {'name': source_name},
                })
        except Exception as e:
            print(f"❌ Ошибка парсинга RSS {feed_url}: {e}")
    all_articles.sort(key=lambda a: a['published'], reverse=True)
    return all_articles
