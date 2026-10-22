from datetime import datetime, timedelta, timezone

from newsbot.sources.rss import fetch_rss_feeds


def rfc(d):
    return d.strftime('%a, %d %b %Y %H:%M:%S +0000')


def test_fetch_rss_feeds(tmp_path):
    now = datetime.now(timezone.utc)
    feed = tmp_path / 'feed.xml'
    feed.write_text(f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Тест</title>
<item><title>Первая &amp;quot;новость&amp;quot;</title><link>https://ex.ru/a/1/?utm_source=rss</link>
<description>&lt;p&gt;Текст &lt;b&gt;жирный&lt;/b&gt;&lt;/p&gt;</description><pubDate>{rfc(now - timedelta(hours=2))}</pubDate></item>
<item><title>Без даты</title><link>https://ex.ru/a/2</link></item>
<item><title>Дубль ссылки</title><link>https://ex.ru/a/1</link><pubDate>{rfc(now)}</pubDate></item>
<item><title>Свежая</title><link>https://ex.ru/a/3</link><pubDate>{rfc(now)}</pubDate></item>
</channel></rss>""", encoding='utf-8')
    articles = fetch_rss_feeds([str(feed)])
    assert [a['title'] for a in articles] == ['Свежая', 'Первая "новость"']
    first = articles[1]
    assert first['url'] == 'https://ex.ru/a/1'
    assert first['raw_url'] == 'https://ex.ru/a/1/?utm_source=rss'
    assert first['description'] == 'Текст жирный'
    assert first['source'] == {'name': 'Тест'}


def test_broken_feed_does_not_crash(tmp_path):
    assert fetch_rss_feeds([str(tmp_path / 'missing.xml')]) == []


def test_http_feed_uses_timeout_and_survives_errors(monkeypatch):
    import requests
    from newsbot.sources import rss
    now = datetime.now(timezone.utc)
    calls = []

    class Resp:
        content = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Сеть</title>
<item><title>Из сети</title><link>https://net.ru/1</link><pubDate>{rfc(now)}</pubDate></item>
</channel></rss>""".encode()

        def raise_for_status(self):
            pass

    def fake_get(url, timeout, headers):
        calls.append((url, timeout))
        if 'dead' in url:
            raise requests.ConnectionError('Remote end closed connection without response')
        return Resp()

    monkeypatch.setattr(rss.requests, 'get', fake_get)
    articles = rss.fetch_rss_feeds(['https://dead.example/rss', 'https://ok.example/rss'])
    assert [a['title'] for a in articles] == ['Из сети']
    assert all(t == rss.FEED_TIMEOUT_SECONDS for _, t in calls) and len(calls) == 2


def test_google_news_entries_take_outlet_name(tmp_path):
    now = datetime.now(timezone.utc)
    feed = tmp_path / 'gn.xml'
    feed.write_text(f"""<?xml version="1.0"?><rss version="2.0"><channel><title>"site:iz.ru" - Google Новости</title>
<item><title>Китай и ЕАЭС договорились - Известия</title><link>https://news.google.com/rss/articles/CBMiAbc?oc=5</link>
<description>&lt;a href="https://news.google.com/rss/articles/CBMiAbc?oc=5"&gt;Китай и ЕАЭС договорились&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;Известия&lt;/font&gt;</description>
<pubDate>{rfc(now)}</pubDate><source url="https://iz.ru">Известия</source></item>
</channel></rss>""", encoding='utf-8')
    [a] = fetch_rss_feeds([str(feed)])
    assert a['title'] == 'Китай и ЕАЭС договорились'   # совпадёт с заголовком из прямой ленты iz.ru
    assert a['source'] == {'name': 'Известия'}
    assert a['description'] == ''
    assert a['url'] == 'https://news.google.com/rss/articles/CBMiAbc?oc=5'


def test_feed_list_has_no_duplicates():
    from newsbot.sources.rss import RSS_FEEDS
    assert len(RSS_FEEDS) == len(set(RSS_FEEDS)) == 20
