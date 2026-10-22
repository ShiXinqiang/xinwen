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
