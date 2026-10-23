"""Сбор новостей из RSS-лент."""
from concurrent.futures import ThreadPoolExecutor

import feedparser
import requests

from newsbot.pipeline.normalize import canonical_url, clean_html, entry_published

# Проверено с сервера 22.10.2026: каждая лента отвечает 200 и отдаёт записи.
RSS_FEEDS = [
    "https://ria.ru/export/rss2/index.xml",
    "https://tass.ru/rss/v2.xml",
    "https://www.interfax.ru/rss.asp",
    "https://www.kommersant.ru/RSS/news.xml",
    "https://www.vedomosti.ru/rss/news",
    "https://1prime.ru/export/rss2/index.xml",
    "https://www.forbes.ru/newrss.xml",
    "http://www.finmarket.ru/rss/mainnews.asp",
    "https://www.tks.ru/law.rss",
    "https://www.tks.ru/nearby.rss",
    "https://www.infranews.ru/feed/",
    "https://www.tourdom.ru/rss/",
    "https://seanews.ru/feed/",
    "https://www.cnews.ru/inc/rss/news.xml",
    "https://www.comnews.ru/rss",
    "http://www.cbr.ru/rss/RssNews",
    "http://www.cbr.ru/rss/RssPress",
    "https://www.eastrussia.ru/rss/",
    "https://bigasia.ru/feed/",
    # «Известия» отвечают 403 на IP сервера (Нидерланды) — берём их статьи через Google Новости
    "https://news.google.com/rss/search?q=site:iz.ru&hl=ru&gl=RU&ceid=RU:ru",
]
MAX_ARTICLES_PER_FEED = 20
# Сколько ждать одну ленту: зависший сервер не должен останавливать весь сбор
FEED_TIMEOUT_SECONDS = 20
PARALLEL_FEEDS = 8
USER_AGENT = 'Mozilla/5.0 (compatible; newsbot/1.0)'


def _aggregated_source(entry) -> str | None:
    """Издание у записи агрегатора (Google Новости кладут его в <source>), иначе None."""
    source = entry.get('source') or {}
    return source.get('title') or None


def _load_feed(feed_url: str):
    """Загружает ленту с таймаутом (feedparser сам по себе может ждать бесконечно)."""
    if not feed_url.startswith(('http://', 'https://')):
        return feedparser.parse(feed_url)  # локальный файл — в тестах
    resp = requests.get(feed_url, timeout=FEED_TIMEOUT_SECONDS, headers={'User-Agent': USER_AGENT})
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def fetch_rss_feeds(feeds=RSS_FEEDS, max_per_feed=MAX_ARTICLES_PER_FEED):
    """
    Парсит RSS-ленты. Записи без даты публикации пропускаются.
    Возвращает статьи, отсортированные от новых к старым.
    """
    def load(feed_url):
        try:
            return feed_url, _load_feed(feed_url)
        except Exception as e:
            print(f"❌ Ошибка загрузки RSS {feed_url}: {e}")
            return feed_url, None

    with ThreadPoolExecutor(max_workers=PARALLEL_FEEDS) as pool:
        loaded = list(pool.map(load, feeds))

    all_articles = []
    seen_urls = set()
    # Порядок лент сохраняется: при одинаковой ссылке побеждает лента, стоящая выше в списке
    for feed_url, feed in loaded:
        if feed is None:
            continue
        try:
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
                title = clean_html(entry.title)
                description = clean_html(entry.get('summary', '') or entry.get('description', ''))
                name = source_name
                outlet = _aggregated_source(entry)
                if outlet:
                    # «Заголовок - Известия»: отрезаем издание, чтобы заголовок совпадал с прямой лентой
                    # (дедупликация по заголовку), а описание агрегатора — это тот же заголовок со ссылкой
                    suffix = f" - {outlet}"
                    if title.endswith(suffix):
                        title = title[:-len(suffix)].rstrip()
                    name, description = outlet, ''
                all_articles.append({
                    'title': title,
                    'url': url,
                    'raw_url': entry.link.strip(),
                    'description': description,
                    'publishedAt': published.isoformat(),
                    'published': published,
                    'source': {'name': name},
                })
        except Exception as e:
            print(f"❌ Ошибка парсинга RSS {feed_url}: {e}")
    all_articles.sort(key=lambda a: a['published'], reverse=True)
    return all_articles
