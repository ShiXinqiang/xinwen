import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from newsbot import moderation, storage
from newsbot.config import Settings
from newsbot.pipeline.scoring import parse_assessment
from conftest import FakeBot, make_article

SETTINGS = Settings(
    telegram_bot_token='123:abc', telegram_chat_id='-100', admin_chat_id='42',
    allowed_user_ids=frozenset(), yandex_folder_id=None, yandex_api_key=None, gnews_api_key=None,
)


class Query:
    def __init__(self, data, text='карточка'):
        self.data = data
        self.message = SimpleNamespace(text=text)
        self.answers, self.edits, self.markup_removed = [], [], False

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(text)

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markup_removed = True


def press(data, user_id=42, bot=None):
    query = Query(data)
    bot = bot or FakeBot()
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=user_id))
    context = SimpleNamespace(bot=bot, bot_data={'settings': SETTINGS, 'allowed_user_ids': frozenset()})
    asyncio.run(moderation.moderation_callback(update, context))
    return query, bot


def candidate(title='Китай и ЕАЭС договорились', url='https://ex.ru/1'):
    a = make_article(title, url=url, description='Подробности')
    a['_hash'] = 'h-' + url
    return storage.add_candidate(a, 'pending', {'score': 9, 'topic': 'ВЭД', 'summary': 'Суть', 'reason': 'по теме'})


def test_approve_publishes_to_channel_once():
    cid = candidate()
    query, bot = press(f'mod:approve:{cid}')
    assert [m['chat_id'] for m in bot.sent] == ['-100']
    assert bot.sent[0]['text'].startswith('Китай и ЕАЭС договорились\n\nПодробности')
    assert query.edits == ['карточка\n\n✅ Опубликовано']
    assert storage.get_candidate(cid)['status'] == 'approved'
    assert storage.is_url_sent('https://ex.ru/1')
    # повторное нажатие — без второй публикации
    query2, bot2 = press(f'mod:approve:{cid}')
    assert bot2.sent == [] and query2.answers == ['Уже решено раньше'] and query2.markup_removed


def test_reject_does_not_publish():
    cid = candidate()
    query, bot = press(f'mod:reject:{cid}')
    assert bot.sent == [] and query.edits == ['карточка\n\n❌ Отклонено']
    assert storage.get_candidate(cid)['status'] == 'rejected'
    assert not storage.is_url_sent('https://ex.ru/1')


def test_failed_publication_returns_candidate_to_queue():
    cid = candidate()

    class BrokenBot(FakeBot):
        async def send_message(self, **kwargs):
            raise RuntimeError('канал недоступен')

    query, _ = press(f'mod:approve:{cid}', bot=BrokenBot())
    assert storage.get_candidate(cid)['status'] == 'pending'
    assert query.edits == [] and 'Не удалось опубликовать' in query.answers[0]


def test_only_moderator_can_press():
    cid = candidate()
    query, bot = press(f'mod:approve:{cid}', user_id=7)
    assert query.answers == ['Доступ ограничен'] and bot.sent == []
    assert storage.get_candidate(cid)['status'] == 'pending'


@pytest.mark.parametrize('text, score', [
    ('{"score": 7, "topic": "ВЭД", "summary": "Суть", "reason": "по теме"}', 7),
    ('```json\n{"score": "12", "topic": "ВЭД"}\n```', 10),
    ('Вот оценка: {"score": 3.6, "reason": "спорт"} — готово', 4),
])
def test_parse_assessment(text, score):
    assert parse_assessment(text)['score'] == score


def test_parse_assessment_rejects_garbage():
    with pytest.raises(ValueError):
        parse_assessment('не могу оценить')
