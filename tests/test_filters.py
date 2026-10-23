import pytest

from newsbot.pipeline.filters import ArticleFilter
from newsbot.storage import DEFAULT_CONFIG
import json

KEYWORDS = json.loads(DEFAULT_CONFIG['keywords'])
EXCLUDED = json.loads(DEFAULT_CONFIG['excluded_keywords']) + ["Газпром", "газовый", "газопровод"]


@pytest.fixture(scope='module')
def f():
    return ArticleFilter(KEYWORDS, EXCLUDED)


@pytest.mark.parametrize('text, keyword', [
    ('Поставки в Китая выросли', 'Китай'),            # словоформа
    ('Китаю предложили новый маршрут', 'Китай'),
    ('Китайский рынок растёт', 'Китай'),               # длинный ключ — по началу слова, как раньше
    ('Новые пошлинами облагаются товары', 'Пошлины'),
    ('Объём параллельного импорта вырос', 'Импорт'),
    ('Импортозамещение в логистике', 'Импорт'),
    ('Газета сообщила о санкциях', 'Санкции'),         # «газ» больше не режет «газету»
    ('Встреча БРИКС в Казани', 'БРИКС'),
])
def test_accepts(f, text, keyword):
    assert f.check(text) == (True, keyword)


@pytest.mark.parametrize('text, blocker', [
    ('Экспорт газа в Китай', 'газ'),
    ('Металлургия и таможня', 'металл'),
    ('Сырье для Китая', 'сырьё'),                      # ё/е
    ('Газпром и Китай подписали договор', 'Газпром'),
    ('Газового контракта с Китаем нет', 'газовый'),
    ('Угольный экспорт в Китай', 'уголь'),
])
def test_excluded(f, text, blocker):
    assert f.check(text) == (False, blocker)


def test_no_keyword(f):
    assert f.check('Погода в Москве') == (False, None)


def test_short_keyword_matches_only_by_lemma():
    f = ArticleFilter(['ВЭД'], [])
    assert f.accepts('Новости ВЭД')
    assert not f.accepts('Ведомости пишут')


def test_explicit_prefix():
    f = ArticleFilter(['Китай'], ['нефт*'])
    assert not f.accepts('Нефтяной экспорт в Китай')
    assert f.accepts('Экспорт в Китай')


def test_phrase_must_be_consecutive():
    f = ArticleFilter(['Параллельный импорт'], [])
    assert f.accepts('Схемы параллельного импорта')
    assert not f.accepts('Параллельный рынок и импорт')
