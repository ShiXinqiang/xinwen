"""
Один проход сбора: ленты -> свежесть -> ключевые слова -> новизна -> оценка моделью -> модерация владелицей.
Без ADMIN_CHAT_ID модерации нет — новости публикуются в канал сразу, как раньше.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import telegram

from newsbot import storage
from newsbot.config import Settings, load_settings
from newsbot.pipeline.dedup import select_new
from newsbot.pipeline.filters import ArticleFilter
from newsbot.pipeline.scoring import score_articles
from newsbot.pipeline.semantic import semantic_filter
from newsbot.publisher import format_article, format_card, moderation_keyboard, notify_admin, send_with_retry
from newsbot.sources.rss import fetch_rss_feeds
from newsbot.yandex import get_embedding

# Семантический фильтр выключен до этапа 3 (эмбеддинги документов + обучение на оценках новостей)
USE_SEMANTIC = False
# Пауза между сообщениями: лимит Telegram для канала ~20 сообщений в минуту
SEND_DELAY_SECONDS = 3
# Предупреждения о сбоях модели — не чаще, чем раз в столько часов
LLM_ALERT_EVERY_HOURS = 6

logger = logging.getLogger(__name__)


async def _publish(bot, settings, a: dict) -> None:
    await send_with_retry(bot, chat_id=settings.telegram_chat_id, text=format_article(a), disable_web_page_preview=True)
    storage.mark_article_sent(a['url'], a['title'], a['source'].get('name', ''), a['_hash'])


async def _publish_direct(batch, settings, bot, send_delay) -> dict:
    """Без модерации: всё, что прошло фильтры, — в канал (старые первыми, чтобы лента шла по порядку)."""
    result = {'sent': 0, 'queued': 0, 'archived': 0, 'errors': 0}
    for a in reversed(batch):
        print(f"📤 Отправляю: {a['title'][:50]}...")
        try:
            await _publish(bot, settings, a)
            result['sent'] += 1
        except Exception as e:
            result['errors'] += 1
            print(f"   ❌ Ошибка отправки: {e}")
        await asyncio.sleep(send_delay)
    return result


async def _moderate(batch, settings, bot, send_delay) -> dict:
    """Оценка моделью → архив (низкая оценка) / сразу в канал (режим auto, высокая) / карточка владелице."""
    result = {'sent': 0, 'queued': 0, 'archived': 0, 'errors': 0}
    result['scoring'] = await asyncio.to_thread(score_articles, batch, settings.score_model)
    mode = storage.get_publish_mode()
    min_score = storage.get_int_config('min_score_for_moderation')
    auto_score = storage.get_int_config('auto_publish_score')

    # Лучшие первыми; без оценки — в конце
    batch = sorted(batch, key=lambda a: -a['_assessment']['score'] if a['_assessment'] else 1)
    for a in batch:
        assessment = a['_assessment']
        score = assessment['score'] if assessment else None
        if score is not None and score < min_score:
            storage.add_candidate(a, 'auto_rejected', assessment)
            result['archived'] += 1
            continue
        if mode == 'auto' and score is not None and score >= auto_score:
            try:
                await _publish(bot, settings, a)
                storage.add_candidate(a, 'auto_published', assessment)
                result['sent'] += 1
            except Exception as e:
                result['errors'] += 1
                logger.warning(f"Ошибка публикации: {e}")
            await asyncio.sleep(send_delay)
            continue
        candidate_id = storage.add_candidate(a, 'pending', assessment)
        try:
            message = await send_with_retry(
                bot, chat_id=settings.admin_chat_id, text=format_card(a, assessment),
                reply_markup=moderation_keyboard(candidate_id), disable_web_page_preview=True,
            )
            if message is not None:
                storage.set_candidate_message(candidate_id, message.message_id)
            result['queued'] += 1
        except Exception as e:
            # Не показали — убираем, чтобы новость пришла в следующий сбор
            storage.delete_candidate(candidate_id)
            result['errors'] += 1
            logger.warning(f"Карточка не отправлена: {e}")
        await asyncio.sleep(send_delay)
    return result


def _llm_alert_due() -> bool:
    last = storage.get_config('last_llm_alert')
    if last and datetime.now(timezone.utc) - datetime.fromisoformat(last) < timedelta(hours=LLM_ALERT_EVERY_HOURS):
        return False
    storage.set_config('last_llm_alert', datetime.now(timezone.utc).isoformat())
    return True


async def run(settings: Settings | None = None, bot=None, fetch=fetch_rss_feeds, send_delay=SEND_DELAY_SECONDS) -> dict:
    settings = settings or load_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы")
    bot = bot or telegram.Bot(token=settings.telegram_bot_token)

    storage.init_db()
    article_filter = ArticleFilter(storage.get_keywords(), storage.get_excluded_keywords())
    semantic_threshold = storage.get_semantic_threshold()
    max_articles_to_send = storage.get_max_articles_to_send()
    max_hours_old = storage.get_max_hours_old()

    # Загрузка лент — сетевая и долгая: в отдельном потоке, чтобы агент в том же процессе отвечал
    all_news = await asyncio.to_thread(fetch)
    total_found = len(all_news)
    print(f"Найдено статей с датой публикации: {total_found}")

    time_limit = datetime.now(timezone.utc) - timedelta(hours=max_hours_old)
    fresh = [a for a in all_news if a['published'] >= time_limit]
    print(f"После фильтрации времени ({max_hours_old} ч) осталось {len(fresh)} статей.")

    filtered = [a for a in fresh if article_filter.accepts(a['title'] + ' ' + a['description'])]
    print(f"После фильтрации слов осталось {len(filtered)} статей.")

    new_articles = select_new(filtered)
    print(f"Новых статей: {len(new_articles)}")

    semantic_stats = {'passed': 0, 'failed': 0, 'avg_similarity': 0.0}
    topic_embeddings = storage.get_all_topic_embeddings() if USE_SEMANTIC else {}
    if topic_embeddings and new_articles:
        new_articles, semantic_stats = semantic_filter(new_articles, topic_embeddings, semantic_threshold, get_embedding)
        print(f"Семантика: принято {semantic_stats['passed']}, отклонено {semantic_stats['failed']}")

    batch = new_articles[:max_articles_to_send]
    if settings.admin_chat_id:
        result = await _moderate(batch, settings, bot, send_delay)
    else:
        result = await _publish_direct(batch, settings, bot, send_delay)
    sent_count, errors = result['sent'], result['errors']

    storage.save_session_stats(
        total_found=total_found,
        total_filtered=len(filtered),
        total_sent=sent_count,
        semantic_passed=semantic_stats['passed'],
        semantic_failed=semantic_stats['failed'],
        avg_similarity=semantic_stats['avg_similarity'],
        threshold=semantic_threshold
    )
    scoring = result.get('scoring') or {}
    summary = (f"Сбор новостей: найдено {total_found}, по ключевым словам {len(filtered)}, "
               f"новых {len(new_articles)}, в канал {sent_count}, на модерацию {result['queued']}, "
               f"в архив {result['archived']}")
    if scoring:
        summary += f", оценено {scoring['scored']} ({scoring['tokens']} токенов)"
    print(summary)

    # Владелице — только о проблемах (итог каждого сбора — в лог, иначе 48 сообщений в сутки)
    problems = []
    if errors:
        problems.append(f"ошибок отправки: {errors}")
    if scoring.get('failed'):
        problems.append(f"модель не оценила {scoring['failed']} новостей ({scoring['error']})")
    if scoring.get('over_budget'):
        problems.append(f"дневной лимит токенов исчерпан, без оценки: {scoring['over_budget']}")
    if problems and (errors or _llm_alert_due()):
        await notify_admin(bot, settings.admin_chat_id, "⚠️ " + "; ".join(problems) + ". Новости при этом не теряются.")

    return {'found': total_found, 'filtered': len(filtered), 'new': len(new_articles), **result}
