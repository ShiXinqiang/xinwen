"""Отбор статей, которые ещё не отправлялись."""
from newsbot import storage
from newsbot.pipeline.normalize import title_hash

# Окно, в течение которого одинаковый заголовок считается повтором
DUPLICATE_TITLE_HOURS = 48


def select_new(articles: list[dict], duplicate_hours: int = DUPLICATE_TITLE_HOURS) -> list[dict]:
    """
    Убирает статьи, чья ссылка уже отправлялась (когда угодно), и статьи с заголовком,
    отправленным за последние duplicate_hours часов или уже встретившимся в этой пачке.
    Каждой оставшейся статье проставляет '_hash'.
    """
    new_articles = []
    batch_hashes = set()
    for a in articles:
        h = title_hash(a['title'])
        if h in batch_hashes:
            continue
        if storage.is_url_sent(a['url'], a.get('raw_url')) or storage.is_hash_sent_recently(h, duplicate_hours):
            continue
        batch_hashes.add(h)
        a['_hash'] = h
        new_articles.append(a)
    return new_articles
