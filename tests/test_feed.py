import asyncio
import json
from types import SimpleNamespace

from newsbot import collector, moderation, storage
from newsbot.config import Settings
from newsbot.pipeline import scoring
from conftest import FakeBot, make_article

# Владелица получает новости в личку: TELEGRAM_CHAT_ID = её id, ADMIN_CHAT_ID не обязателен
OWNER = Settings(
    telegram_bot_token='123:abc', telegram_chat_id='4954401', admin_chat_id=None,
    allowed_user_ids=frozenset(), yandex_folder_id=None, yandex_api_key=None, gnews_api_key=None,
)


def articles():
    return [
        make_article('Китай снизил пошлины на импорт', url='https://ex.ru/1', description='Подробности'),
        make_article('Логистика в Китай подорожала', url='https://ex.ru/2', description='Детали'),
    ]


def fake_model(monkeypatch, scores):
    def complete(messages, model, max_tokens, temperature):
        title = messages[1]['text'].split('Заголовок: ')[1].split('\n')[0]
        return json.dumps({'score': scores[title], 'topic': 'ВЭД', 'summary': 'Суть', 'reason': 'по теме'},
                          ensure_ascii=False), 50
    monkeypatch.setattr(scoring, 'complete', complete)


def run(bot):
    return asyncio.run(collector.run(OWNER, bot=bot, fetch=articles, send_delay=0))


def test_feed_sends_cards_with_like_buttons_to_owner(monkeypatch):
    fake_model(monkeypatch, {'Китай снизил пошлины на импорт': 9, 'Логистика в Китай подорожала': 2})
    bot = FakeBot()
    result = run(bot)
    assert result['sent'] == 1 and result['archived'] == 1 and result['queued'] == 0
    [card] = bot.sent
    assert card['chat_id'] == '4954401'
    assert card['text'].startswith('🟢 9/10 · ВЭД\n\nКитай снизил пошлины на импорт')
    buttons = card['reply_markup'].inline_keyboard[0]
    assert [b.text for b in buttons] == ['👍 Нравится', '👎 Не нравится']
    assert buttons[0].callback_data.startswith('fb:like:')
    assert storage.is_url_sent('https://ex.ru/1')
    # повторно не присылает
    bot2 = FakeBot()
    assert run(bot2)['sent'] == 0 and bot2.sent == []


class Query:
    def __init__(self, data):
        self.data = data
        self.message = SimpleNamespace(text='карточка')
        self.answers, self.edits = [], []

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(text)

    async def edit_message_reply_markup(self, reply_markup=None):
        pass


def press(data, user_id=4954401):
    query, bot = Query(data), FakeBot()
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=user_id))
    asyncio.run(moderation.moderation_callback(update, SimpleNamespace(
        bot=bot, bot_data={'settings': OWNER, 'allowed_user_ids': frozenset()})))
    return query, bot


def test_like_and_dislike_only_record_feedback():
    liked = storage.add_candidate(make_article('Нужная новость', url='https://ex.ru/a'), 'pending')
    disliked = storage.add_candidate(make_article('Ненужная новость', url='https://ex.ru/b'), 'pending')
    q1, b1 = press(f'fb:like:{liked}')
    q2, b2 = press(f'fb:dislike:{disliked}')
    assert b1.sent == [] and b2.sent == []                       # ничего не публикуется
    assert q1.edits == ['карточка\n\n👍 Учту: такие новости нужны']
    assert q2.edits == ['карточка\n\n👎 Учту: такие больше не присылать']
    assert storage.get_moderation_examples() == (['Нужная новость'], ['Ненужная новость'])


def test_feedback_reaches_next_scoring(monkeypatch):
    seen = []

    def complete(messages, model, max_tokens, temperature):
        seen.append(messages[0]['text'])
        return '{"score": 7}', 10
    monkeypatch.setattr(scoring, 'complete', complete)
    cid = storage.add_candidate(make_article('Новость про таможенные пошлины', url='https://ex.ru/z'), 'pending')
    press(f'fb:like:{cid}')
    run(FakeBot())
    assert 'понравились такие новости:\n- Новость про таможенные пошлины' in seen[0]


def test_stranger_cannot_rate():
    cid = storage.add_candidate(make_article('Новость', url='https://ex.ru/c'), 'pending')
    query, _ = press(f'fb:like:{cid}', user_id=7)
    assert query.answers == ['Доступ ограничен']
    assert storage.get_candidate(cid)['status'] == 'pending'
