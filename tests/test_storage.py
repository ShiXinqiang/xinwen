import json
import sqlite3

from newsbot import storage
from newsbot.pipeline.dedup import select_new
from newsbot.pipeline.normalize import title_hash
from conftest import make_article


def test_url_sent_ever(db):
    storage.mark_article_sent('https://ex.ru/1', 'T', 'S', 'h')
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE sent_articles SET sent_at = datetime('now', '-30 days')")
    assert storage.is_url_sent('https://ex.ru/1')
    assert storage.is_url_sent('https://other', 'https://ex.ru/1')
    assert not storage.is_url_sent('https://ex.ru/2', None)


def test_hash_window(db):
    storage.mark_article_sent('https://ex.ru/1', 'T', 'S', 'h')
    assert storage.is_hash_sent_recently('h', 48)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE sent_articles SET sent_at = datetime('now', '-49 hours')")
    assert not storage.is_hash_sent_recently('h', 48)


def test_regression_resend_after_midnight(db):
    """Раньше статья, отправленная «вчера» по UTC, уходила повторно при каждом запуске."""
    a = make_article('Китай и ЕАЭС', url='https://ex.ru/a')
    storage.mark_article_sent(a['url'], a['title'], 'S', title_hash(a['title']))
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE sent_articles SET sent_at = datetime('now', '-1 day')")
    assert select_new([make_article('Китай и ЕАЭС', url='https://ex.ru/a')]) == []


def test_select_new_dedups_batch_and_titles():
    storage.mark_article_sent('https://old.ru/x', 'Старая новость', 'S', title_hash('Старая новость'))
    articles = [
        make_article('Новость А', url='https://a.ru/1'),
        make_article('Новость «А»', url='https://b.ru/2'),     # тот же заголовок с другого сайта
        make_article('Старая новость', url='https://c.ru/3'),  # заголовок уже отправлялся
        make_article('Новость Б', url='https://a.ru/4'),
    ]
    new = select_new(articles)
    assert [a['url'] for a in new] == ['https://a.ru/1', 'https://a.ru/4']
    assert all('_hash' in a for a in new)


def test_migration_adds_gas_exclusions_once():
    excluded = storage.get_excluded_keywords()
    assert {'Газпром', 'газовый', 'газопровод'} <= set(excluded)
    storage.set_excluded_keywords(['нефть'])  # пользователь сам убрал — повторно не добавляем
    storage.init_db()
    assert storage.get_excluded_keywords() == ['нефть']
    assert storage.get_config('config_version') == '4'


def test_migration_keeps_user_list_without_gas(db):
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM config WHERE key = 'config_version'")
        conn.execute("UPDATE config SET value = ? WHERE key = 'excluded_keywords'", (json.dumps(['уголь']),))
    storage.init_db()
    assert storage.get_excluded_keywords() == ['уголь']


def test_migration_v3_adds_knr_once(db):
    # База в состоянии версии 2, как рабочая news.db до этого изменения
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE config SET value = '2' WHERE key = 'config_version'")
        conn.execute("UPDATE config SET value = ? WHERE key = 'keywords'", (json.dumps(['Китай', 'ВЭД'], ensure_ascii=False),))
    storage.init_db()
    assert storage.get_keywords() == ['Китай', 'ВЭД', 'КНР']
    storage.set_keywords(['Китай'])  # пользователь сам убрал — повторно не добавляем
    storage.init_db()
    assert storage.get_keywords() == ['Китай']


def test_fresh_db_has_knr_without_duplicates():
    assert storage.get_keywords().count('КНР') == 1


def test_migration_v4_switches_moderation_to_feed(db):
    for before, after in (('moderation', 'feed'), ('auto', 'auto')):
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE config SET value = '3' WHERE key = 'config_version'")
            conn.execute("UPDATE config SET value = ? WHERE key = 'publish_mode'", (before,))
        storage.init_db()
        assert storage.get_publish_mode() == after   # ручной выбор режима не трогаем


def test_fresh_db_is_feed_mode():
    assert storage.get_publish_mode() == 'feed'
