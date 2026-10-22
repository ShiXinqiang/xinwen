"""Один проход сбора: ленты -> свежесть -> ключевые слова -> новизна -> (семантика) -> отправка в канал."""
import asyncio
from datetime import datetime, timedelta, timezone

import telegram

from newsbot import storage
from newsbot.config import Settings, load_settings
from newsbot.pipeline.dedup import select_new
from newsbot.pipeline.filters import ArticleFilter
from newsbot.pipeline.semantic import semantic_filter
from newsbot.publisher import format_article, notify_admin, send_with_retry
from newsbot.sources.rss import fetch_rss_feeds
from newsbot.yandex import get_embedding

# Семантический фильтр выключен до этапа 3 (эмбеддинги документов + обучение на оценках новостей)
USE_SEMANTIC = False
# Пауза между сообщениями: лимит Telegram для канала ~20 сообщений в минуту
SEND_DELAY_SECONDS = 3


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

    sent_count = 0
    errors = 0
    # Сначала более старые, чтобы в канале лента шла по порядку
    for a in reversed(new_articles[:max_articles_to_send]):
        print(f"📤 Отправляю: {a['title'][:50]}...")
        try:
            await send_with_retry(
                bot,
                chat_id=settings.telegram_chat_id,
                text=format_article(a),
                disable_web_page_preview=True
            )
            storage.mark_article_sent(a['url'], a['title'], a['source'].get('name', ''), a['_hash'])
            sent_count += 1
        except Exception as e:
            errors += 1
            print(f"   ❌ Ошибка отправки: {e}")
        await asyncio.sleep(send_delay)

    storage.save_session_stats(
        total_found=total_found,
        total_filtered=len(filtered),
        total_sent=sent_count,
        semantic_passed=semantic_stats['passed'],
        semantic_failed=semantic_stats['failed'],
        avg_similarity=semantic_stats['avg_similarity'],
        threshold=semantic_threshold
    )
    summary = (f"Сбор новостей: найдено {total_found}, по ключевым словам {len(filtered)}, "
               f"новых {len(new_articles)}, отправлено {sent_count}")
    if errors:
        summary += f", ошибок отправки {errors}"
    await notify_admin(bot, settings.admin_chat_id, summary)
    return {'found': total_found, 'filtered': len(filtered), 'new': len(new_articles), 'sent': sent_count, 'errors': errors}
