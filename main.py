import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import telegram
from telegram.error import RetryAfter

load_dotenv()

# ---- ИМПОРТЫ ИЗ СОБСТВЕННЫХ МОДУЛЕЙ ----
from db import (
    init_db,
    is_url_sent,
    is_hash_sent_recently,
    mark_article_sent,
    save_session_stats,
    get_keywords,
    get_excluded_keywords,
    get_semantic_threshold,
    get_max_articles_to_send,
    get_max_hours_old,
    get_embedding,
    save_embedding,
    get_all_topic_embeddings,
)
from yandex_ai import get_embedding as get_embedding_yandex
from news_fetcher import fetch_rss_feeds, normalize_text, title_hash

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# Служебные сообщения (старт, «ничего не найдено», итоги) — только администратору, не в канал
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Семантический фильтр выключен до этапа 3 (эмбеддинги документов + обучение на оценках новостей)
USE_SEMANTIC = False
# Окно, в течение которого одинаковый заголовок считается повтором
DUPLICATE_TITLE_HOURS = 48
# Пауза между сообщениями: лимит Telegram для канала ~20 сообщений в минуту
SEND_DELAY_SECONDS = 3

# ---- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----

def cosine_similarity(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x*y for x,y in zip(a,b))
    norm_a = sum(x*x for x in a)**0.5
    norm_b = sum(y*y for y in b)**0.5
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

def format_pub_date(published: datetime) -> str:
    """Дата публикации по Москве (день.месяц.год час:минута)."""
    msk_tz = timezone(timedelta(hours=3))
    return published.astimezone(msk_tz).strftime('%d.%m.%Y %H:%M')

async def notify_admin(bot, text: str):
    if not ADMIN_CHAT_ID:
        print(f"ℹ️ {text}")
        return
    try:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)
    except Exception as e:
        print(f"⚠️ Уведомление администратору не отправлено: {e}")

async def send_with_retry(bot, **kwargs):
    try:
        await bot.send_message(**kwargs)
    except RetryAfter as e:
        wait = e.retry_after.total_seconds() if isinstance(e.retry_after, timedelta) else e.retry_after
        print(f"   ⏳ Лимит Telegram, жду {wait} с")
        await asyncio.sleep(wait + 1)
        await bot.send_message(**kwargs)

# ---- ОСНОВНАЯ ФУНКЦИЯ ----
async def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы")
        sys.exit(1)

    init_db()
    keywords = get_keywords()
    excluded_keywords = get_excluded_keywords()
    semantic_threshold = get_semantic_threshold()
    max_articles_to_send = get_max_articles_to_send()
    max_hours_old = get_max_hours_old()

    topic_embeddings = get_all_topic_embeddings()
    use_semantic = USE_SEMANTIC and bool(topic_embeddings)
    if use_semantic:
        print(f"✅ Загружено {len(topic_embeddings)} эталонных векторов.")
    else:
        print("⚠️ Семантический фильтр отключён.")

    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)

    all_news = fetch_rss_feeds()
    total_found = len(all_news)
    print(f"Найдено статей с датой публикации: {total_found}")

    time_limit = datetime.now(timezone.utc) - timedelta(hours=max_hours_old)
    all_news = [a for a in all_news if a['published'] >= time_limit]
    print(f"После фильтрации времени ({max_hours_old} ч) осталось {len(all_news)} статей.")

    filtered = []
    for a in all_news:
        text = normalize_text(a['title'] + ' ' + a['description'])
        if any(kw.lower() in text for kw in keywords):
            if not any(excl.lower() in text for excl in excluded_keywords):
                filtered.append(a)
    print(f"После фильтрации слов осталось {len(filtered)} статей.")

    new_articles = []
    batch_hashes = set()
    for a in filtered:
        h = title_hash(a['title'])
        if h in batch_hashes:
            continue
        if is_url_sent(a['url'], a['raw_url']) or is_hash_sent_recently(h, DUPLICATE_TITLE_HOURS):
            continue
        batch_hashes.add(h)
        a['_hash'] = h
        new_articles.append(a)
    print(f"Новых статей: {len(new_articles)}")

    semantic_passed = 0
    semantic_failed = 0
    similarities = []
    if use_semantic and new_articles:
        final_articles = []
        for a in new_articles[:30]:
            text = normalize_text(a['title'] + ' ' + a['description'])[:500]
            h = a['_hash']
            emb = get_embedding(h)
            if emb is None:
                emb = get_embedding_yandex(text)
                if emb:
                    save_embedding(h, emb)
                else:
                    semantic_failed += 1
                    continue
            max_sim = max(cosine_similarity(emb, vec) for vec in topic_embeddings.values())
            similarities.append(max_sim)
            if max_sim >= semantic_threshold:
                final_articles.append(a)
                semantic_passed += 1
            else:
                semantic_failed += 1
        new_articles = final_articles
        print(f"Семантика: принято {semantic_passed}, отклонено {semantic_failed}")

    # ---- ОТПРАВКА НОВОСТЕЙ (PLAIN TEXT, ТЕГИ УЖЕ ВЫРЕЗАНЫ) ----
    sent_count = 0
    errors = 0
    # Сначала более старые, чтобы в канале лента шла по порядку
    for a in reversed(new_articles[:max_articles_to_send]):
        description = a['description']
        if len(description) > 500:
            description = description[:500].rstrip() + '...'

        parts = [a['title']]
        if description and normalize_text(description) != normalize_text(a['title']):
            parts.append(description)
        parts.append(f"📅 {format_pub_date(a['published'])}\n🔗 {a['url']}")
        text = '\n\n'.join(parts)

        print(f"📤 Отправляю: {a['title'][:50]}...")
        try:
            await send_with_retry(
                bot,
                chat_id=TELEGRAM_CHAT_ID,
                text=text,
                disable_web_page_preview=True
            )
            mark_article_sent(a['url'], a['title'], a['source'].get('name', ''), a['_hash'])
            sent_count += 1
            print(f"   ✅ Отправлено ({sent_count})")
        except Exception as e:
            errors += 1
            print(f"   ❌ Ошибка отправки: {e}")
        await asyncio.sleep(SEND_DELAY_SECONDS)

    avg_sim = sum(similarities) / len(similarities) if similarities else 0.0
    save_session_stats(
        total_found=total_found,
        total_filtered=len(filtered),
        total_sent=sent_count,
        semantic_passed=semantic_passed,
        semantic_failed=semantic_failed,
        avg_similarity=avg_sim,
        threshold=semantic_threshold
    )
    summary = (f"Сбор новостей: найдено {total_found}, по ключевым словам {len(filtered)}, "
               f"новых {len(new_articles)}, отправлено {sent_count}")
    if errors:
        summary += f", ошибок отправки {errors}"
    await notify_admin(bot, summary)

if __name__ == '__main__':
    asyncio.run(main())
