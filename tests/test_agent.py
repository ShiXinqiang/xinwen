import asyncio
from types import SimpleNamespace

from newsbot.agent import bot as agent


def test_format_news_summary_escapes_html():
    text = agent.format_news_summary([{'title': 'A_b *c* <e> & f', 'url': 'https://x.ru/?a=1&b="2"', 'source': {'name': 'S&P'}}])
    assert text == '1. <a href="https://x.ru/?a=1&amp;b=&quot;2&quot;">A_b *c* &lt;e&gt; &amp; f</a> — S&amp;P'
    assert agent.format_news_summary([]) == "Новостей не найдено."


class Message:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


def make_update(user_id):
    message = Message()
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id), effective_message=message,
                           message=message, callback_query=None), message


def call(handler, user_id, allowed):
    update, message = make_update(user_id)
    context = SimpleNamespace(bot_data={'allowed_user_ids': allowed}, args=[])
    asyncio.run(handler(update, context))
    return message.replies


def test_access_restricted():
    assert call(agent.stats, 7, frozenset({1}))[0].startswith('⛔ Доступ ограничен. Ваш id: 7')
    assert call(agent.stats, 1, frozenset({1})) == ['📊 Всего отправлено новостей: 0']


def test_access_open_when_list_empty():
    assert call(agent.stats, 7, frozenset()) == ['📊 Всего отправлено новостей: 0']


def test_feedback_dislike_is_negative(monkeypatch):
    saved = []
    monkeypatch.setattr(agent.storage, 'save_feedback', lambda uid, text, rating: saved.append(rating))

    class Query:
        def __init__(self, data):
            self.data = data
            self.message = Message()
            self.message.text = 'ответ'

        async def answer(self, *a, **k):
            pass

        async def edit_message_reply_markup(self, reply_markup=None):
            pass

    for data in ('feedback_like', 'feedback_dislike'):
        update = SimpleNamespace(effective_user=SimpleNamespace(id=1), callback_query=Query(data), effective_message=None)
        asyncio.run(agent.feedback_callback(update, SimpleNamespace(bot_data={})))
    assert saved == [1, -1]
