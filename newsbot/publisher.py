"""Оформление и отправка сообщений в Telegram."""
import asyncio
from datetime import datetime, timedelta, timezone

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
