import time

from newsbot.pipeline.normalize import canonical_url, clean_html, entry_published, title_hash


def test_clean_html_removes_all_tags_and_entities():
    assert clean_html('<p>Текст <b>про</b>&nbsp;Китай &quot;сегодня&quot;</p>') == 'Текст про Китай "сегодня"'
    assert clean_html('') == ''
    assert clean_html(None) == ''


def test_canonical_url_drops_tracking_fragment_and_slash():
    assert canonical_url('HTTPS://Ex.RU/a/1/?utm_source=rss&id=5&from=main#top') == 'https://ex.ru/a/1?id=5'
    assert canonical_url('https://ex.ru/') == 'https://ex.ru/'


def test_canonical_url_keeps_meaningful_params():
    assert canonical_url('https://ex.ru/news?reference=7&page=2') == 'https://ex.ru/news?reference=7&page=2'


def test_title_hash_ignores_case_and_punctuation():
    assert title_hash('Китай и ЕАЭС: "новый транзит"') == title_hash('китай и ЕАЭС — «новый   транзит»')
    assert title_hash('Китай') != title_hash('Индия')


def test_entry_published():
    t = time.strptime('2026-10-22 07:00:00', '%Y-%m-%d %H:%M:%S')
    assert entry_published({'published_parsed': t}).isoformat() == '2026-10-22T07:00:00+00:00'
    assert entry_published({'updated_parsed': t}).hour == 7
    assert entry_published({}) is None
