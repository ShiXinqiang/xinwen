import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from telegram.error import RetryAfter

from newsbot import collector, storage
from newsbot.config import Settings
from newsbot.pipeline import scoring
from conftest import FakeBot, make_article

# Без ADMIN_CHAT_ID — публикация сразу в канал (как до модерации)
DIRECT = Settings(
    telegram_bot_token='123:abc', telegram_chat_id='-100', admin_chat_id=None,
    allowed_user_ids=frozenset(), yandex_folder_id=None, yandex_api_key=None, gnews_api_key=None,
)
MODERATED = replace(DIRECT, admin_chat_id='42')


def articles():
    return [
        make_article('Китай и ЕАЭС договорились', url='https://ex.ru/1', description='Подробности соглашения', hours_ago=1),
        make_article('Китай и ЕАЭС договорились!', url='https://copy.ru/1', hours_ago=2),
        make_article('Пошлины на импорт газа', url='https://ex.ru/2', hours_ago=1),
        make_article('Санкции против Китая', url='https://ex.ru/3', hours_ago=48),
        make_article('Погода в Москве', url='https://ex.ru/4', hours_ago=1),
        make_article('Логистика в Китай', url='https://ex.ru/5', description='Логистика в Китай', hours_ago=3),
    ]


def run(bot, settings=DIRECT):
    return asyncio.run(collector.run(settings, bot=bot, fetch=articles, send_delay=0))


def fake_model(monkeypatch, scores: dict, tokens=100):
    """Подменяет вызов YandexGPT: оценка по заголовку из словаря."""
    calls = []

    def complete(messages, model, max_tokens, temperature):
        calls.append(messages)
        title = messages[1]['text'].split('Заголовок: ')[1].split('\n')[0]
        return json.dumps({'score': scores[title], 'topic': 'Торговля с Китаем',
                           'summary': f'Суть: {title}', 'reason': 'по теме ВЭД'}, ensure_ascii=False), tokens
    monkeypatch.setattr(scoring, 'complete', complete)
    return calls


# ---------- без модерации ----------

def test_direct_sends_once():
    bot = FakeBot()
    result = run(bot)
    assert result['found'] == 6 and result['filtered'] == 3 and result['new'] == 2 and result['sent'] == 2
    # старые первыми; описание, повторяющее заголовок, не дублируется
    assert bot.sent[0]['text'].startswith('Логистика в Китай\n\n📅 ')
    assert bot.sent[1]['text'].startswith('Китай и ЕАЭС договорились\n\nПодробности соглашения\n\n📅 ')
    assert bot.sent[1]['text'].endswith('🔗 https://ex.ru/1')
    assert all(m['chat_id'] == '-100' for m in bot.sent)

    bot2 = FakeBot()
    assert run(bot2)['sent'] == 0 and bot2.sent == []


def test_retry_after():
    class FloodBot(FakeBot):
        calls = 0

        async def send_message(self, **kwargs):
            FloodBot.calls += 1
            if FloodBot.calls == 1:
                raise RetryAfter(timedelta(seconds=0))
            await super().send_message(**kwargs)

    assert run(FloodBot())['sent'] == 2
    assert storage.get_total_sent() == 2


def test_failed_send_is_not_marked_sent():
    class BrokenBot(FakeBot):
        async def send_message(self, **kwargs):
            raise RuntimeError('boom')

    result = run(BrokenBot())
    assert result['sent'] == 0 and result['errors'] == 2
    assert storage.get_total_sent() == 0


def test_requires_token():
    with pytest.raises(RuntimeError):
        asyncio.run(collector.run(Settings(None, None, None, frozenset(), None, None, None), bot=FakeBot(), fetch=list))


# ---------- модерация ----------

def test_moderation_sends_cards_not_to_channel(monkeypatch):
    fake_model(monkeypatch, {'Китай и ЕАЭС договорились': 9, 'Логистика в Китай': 6})
    bot = FakeBot()
    result = run(bot, MODERATED)
    assert result['sent'] == 0 and result['queued'] == 2 and result['archived'] == 0
    assert all(m['chat_id'] == '42' for m in bot.sent)          # в канал — ничего
    first, second = bot.sent
    assert first['text'].startswith('🟢 9/10 · Торговля с Китаем\n\nКитай и ЕАЭС договорились')  # лучшие первыми
    assert second['text'].startswith('🟡 6/10')
    assert '💬 по теме ВЭД' in first['text']
    assert first['reply_markup'].inline_keyboard[0][0].callback_data.startswith('mod:approve:')
    assert storage.count_pending_candidates() == 2
    assert storage.get_llm_tokens_today() == 200
    # повторный сбор не предлагает те же новости
    bot2 = FakeBot()
    assert run(bot2, MODERATED)['queued'] == 0 and bot2.sent == []


def test_low_score_goes_to_archive(monkeypatch):
    fake_model(monkeypatch, {'Китай и ЕАЭС договорились': 9, 'Логистика в Китай': 2})
    bot = FakeBot()
    result = run(bot, MODERATED)
    assert result['queued'] == 1 and result['archived'] == 1 and len(bot.sent) == 1


def test_auto_mode_publishes_high_scores(monkeypatch):
    fake_model(monkeypatch, {'Китай и ЕАЭС договорились': 9, 'Логистика в Китай': 6})
    storage.set_config('publish_mode', 'auto')
    bot = FakeBot()
    result = run(bot, MODERATED)
    assert result['sent'] == 1 and result['queued'] == 1
    assert [m['chat_id'] for m in bot.sent] == ['-100', '42']
    assert storage.is_url_sent('https://ex.ru/1')


def test_model_unavailable_still_sends_cards_and_warns_once():
    bot = FakeBot()                                              # ключей YandexGPT нет
    result = run(bot, MODERATED)
    cards = [m for m in bot.sent if 'reply_markup' in m]
    warnings = [m for m in bot.sent if m['text'].startswith('⚠️')]
    assert result['queued'] == 2 and len(cards) == 2
    assert all(c['text'].startswith('⚪ без оценки') for c in cards)
    assert len(warnings) == 1 and 'не оценила' in warnings[0]['text']
    # следующее предупреждение — не раньше чем через LLM_ALERT_EVERY_HOURS
    storage.set_config('publish_mode', 'moderation')
    bot2 = FakeBot()
    asyncio.run(collector.run(MODERATED, bot=bot2, send_delay=0, fetch=lambda: [
        make_article('Новая новость про Китай', url='https://ex.ru/9')]))
    assert not [m for m in bot2.sent if m['text'].startswith('⚠️')]


def test_daily_token_limit(monkeypatch):
    fake_model(monkeypatch, {'Китай и ЕАЭС договорились': 9, 'Логистика в Китай': 6}, tokens=500)
    storage.set_config('llm_daily_token_limit', '400')
    result = run(FakeBot(), MODERATED)
    assert result['scoring']['scored'] == 1 and result['scoring']['over_budget'] == 1
    assert result['queued'] == 2                                  # новости не потерялись


def test_card_send_failure_retries_next_run(monkeypatch):
    fake_model(monkeypatch, {'Китай и ЕАЭС договорились': 9, 'Логистика в Китай': 6})

    class BrokenBot(FakeBot):
        async def send_message(self, **kwargs):
            if 'reply_markup' in kwargs:
                raise RuntimeError('boom')
            await super().send_message(**kwargs)

    assert run(BrokenBot(), MODERATED)['errors'] == 2
    assert storage.count_pending_candidates() == 0
    assert run(FakeBot(), MODERATED)['queued'] == 2


def test_examples_from_decisions_reach_the_prompt(monkeypatch):
    calls = fake_model(monkeypatch, {'Китай и ЕАЭС договорились': 9, 'Логистика в Китай': 6})
    approved = storage.add_candidate(make_article('Одобренная новость о таможне'), 'pending')
    rejected = storage.add_candidate(make_article('Отклонённая новость о футболе'), 'pending')
    storage.decide_candidate(approved, 'approved')
    storage.decide_candidate(rejected, 'rejected')
    run(FakeBot(), MODERATED)
    system = calls[0][0]['text']
    assert 'одобряла такие новости:\n- Одобренная новость о таможне' in system
    assert 'отклоняла такие:\n- Отклонённая новость о футболе' in system
