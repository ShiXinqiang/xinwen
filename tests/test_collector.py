import asyncio
from datetime import timedelta

import pytest
from telegram.error import RetryAfter

from newsbot import collector, storage
from newsbot.config import Settings
from conftest import FakeBot, make_article

SETTINGS = Settings(
    telegram_bot_token='123:abc', telegram_chat_id='-100', admin_chat_id='42',
    allowed_user_ids=frozenset(), yandex_folder_id=None, yandex_api_key=None, gnews_api_key=None,
)


def articles():
    return [
        make_article('Китай и ЕАЭС договорились', url='https://ex.ru/1', description='Подробности соглашения', hours_ago=1),
        make_article('Китай и ЕАЭС договорились!', url='https://copy.ru/1', hours_ago=2),
        make_article('Пошлины на импорт газа', url='https://ex.ru/2', hours_ago=1),
        make_article('Санкции против Китая', url='https://ex.ru/3', hours_ago=48),
        make_article('Погода в Москве', url='https://ex.ru/4', hours_ago=1),
        make_article('Логистика в Китай', url='https://ex.ru/5', description='Логистика в Китай', hours_ago=3),
    ]


def run(bot):
    return asyncio.run(collector.run(SETTINGS, bot=bot, fetch=articles, send_delay=0))


def test_sends_once_and_reports_to_admin_only():
    bot = FakeBot()
    result = run(bot)
    channel = [m for m in bot.sent if m['chat_id'] == '-100']
    admin = [m for m in bot.sent if m['chat_id'] == '42']
    assert result == {'found': 6, 'filtered': 3, 'new': 2, 'sent': 2, 'errors': 0}
    # старые первыми; описание, повторяющее заголовок, не дублируется
    assert channel[0]['text'].startswith('Логистика в Китай\n\n📅 ')
    assert channel[1]['text'].startswith('Китай и ЕАЭС договорились\n\nПодробности соглашения\n\n📅 ')
    assert channel[1]['text'].endswith('🔗 https://ex.ru/1')
    assert len(admin) == 1 and 'отправлено 2' in admin[0]['text']

    bot2 = FakeBot()
    assert run(bot2)['sent'] == 0
    assert all(m['chat_id'] == '42' for m in bot2.sent)


def test_retry_after(monkeypatch):
    class FloodBot(FakeBot):
        calls = 0

        async def send_message(self, **kwargs):
            FloodBot.calls += 1
            if FloodBot.calls == 1:
                raise RetryAfter(timedelta(seconds=0))
            await super().send_message(**kwargs)

    bot = FloodBot()
    assert run(bot)['sent'] == 2
    assert storage.get_total_sent() == 2


def test_failed_send_is_not_marked_sent():
    class BrokenBot(FakeBot):
        async def send_message(self, **kwargs):
            if kwargs['chat_id'] == '-100':
                raise RuntimeError('boom')
            await super().send_message(**kwargs)

    result = run(BrokenBot())
    assert result['sent'] == 0 and result['errors'] == 2
    assert storage.get_total_sent() == 0


def test_requires_token():
    with pytest.raises(RuntimeError):
        asyncio.run(collector.run(Settings(None, None, None, frozenset(), None, None, None), bot=FakeBot(), fetch=list))
