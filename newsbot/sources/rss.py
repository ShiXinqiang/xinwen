"""Сбор новостей из RSS-лент."""
import feedparser

from newsbot.pipeline.normalize import canonical_url, clean_html, entry_published

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
