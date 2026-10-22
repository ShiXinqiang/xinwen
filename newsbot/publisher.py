"""Оформление и отправка сообщений в Telegram."""
import asyncio
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import RetryAfter

from newsbot.pipeline.normalize import normalize_text

MSK = timezone(timedelta(hours=3))
MAX_DESCRIPTION_LEN = 500


def format_pub_date(published: datetime) -> str:
    """Дата публикации по Москве (день.месяц.год час:минута)."""
    return published.astimezone(MSK).strftime('%d.%m.%Y %H:%M')

def format_article(a: dict) -> str:
    """Plain text: заголовок, описание (если не повторяет заголовок), дата, ссылка."""
    description = a['description']
    if len(description) > MAX_DESCRIPTION_LEN:
        description = description[:MAX_DESCRIPTION_LEN].rstrip() + '...'
    parts = [a['title']]
    if description and normalize_text(description) != normalize_text(a['title']):
        parts.append(description)
    parts.append(f"📅 {format_pub_date(a['published'])}\n🔗 {a['url']}")
    return '\n\n'.join(parts)

def score_badge(assessment: dict | None) -> str:
    if not assessment:
        return '⚪ без оценки'
    score = assessment['score']
    mark = '🟢' if score >= 8 else '🟡' if score >= 5 else '🔴'
    topic = f" · {assessment['topic']}" if assessment.get('topic') else ''
    return f"{mark} {score}/10{topic}"

def format_card(a: dict, assessment: dict | None) -> str:
    """Карточка для владелицы: оценка модели, заголовок, суть, причина, источник, ссылка."""
    gist = (assessment or {}).get('summary') or a['description'][:300]
    parts = [score_badge(assessment), a['title']]
    if gist and normalize_text(gist) != normalize_text(a['title']):
        parts.append(gist)
    meta = []
    if (assessment or {}).get('reason'):
        meta.append(f"💬 {assessment['reason']}")
    meta.append(f"📰 {a['source'].get('name') or 'источник не указан'} · 📅 {format_pub_date(a['published'])}")
    meta.append(f"🔗 {a['url']}")
    parts.append('\n'.join(meta))
    return '\n\n'.join(parts)

def moderation_keyboard(candidate_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"mod:approve:{candidate_id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"mod:reject:{candidate_id}"),
    ]])

def feedback_keyboard(candidate_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👍 Нравится", callback_data=f"fb:like:{candidate_id}"),
        InlineKeyboardButton("👎 Не нравится", callback_data=f"fb:dislike:{candidate_id}"),
    ]])

def article_from_candidate(c: dict) -> dict:
    return {
        'title': c['title'], 'url': c['url'], 'raw_url': c['raw_url'], 'description': c['description'] or '',
        'published': datetime.fromisoformat(c['published_at']), 'publishedAt': c['published_at'],
        'source': {'name': c['source'] or ''}, '_hash': c['hash'],
    }

async def send_with_retry(bot, **kwargs):
    """send_message с одним повтором, если Telegram попросил подождать."""
    try:
        return await bot.send_message(**kwargs)
    except RetryAfter as e:
        wait = e.retry_after.total_seconds() if isinstance(e.retry_after, timedelta) else e.retry_after
        print(f"   ⏳ Лимит Telegram, жду {wait} с")
        await asyncio.sleep(wait + 1)
        return await bot.send_message(**kwargs)

async def notify_admin(bot, admin_chat_id: str | None, text: str):
    if not admin_chat_id:
        print(f"ℹ️ {text}")
        return
    try:
        await bot.send_message(chat_id=admin_chat_id, text=text)
    except Exception as e:
        print(f"⚠️ Уведомление администратору не отправлено: {e}")
