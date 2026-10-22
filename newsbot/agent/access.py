"""Доступ к командам и кнопкам бота: только пользователи из ALLOWED_USER_IDS (если список задан)."""
import functools

from telegram import Update
from telegram.ext import ContextTypes


def restricted(handler):
    """Пускает только пользователей из ALLOWED_USER_IDS (если список задан)."""
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        allowed = context.bot_data.get('allowed_user_ids')
        user = update.effective_user
        if allowed and (user is None or user.id not in allowed):
            if update.callback_query:
                await update.callback_query.answer("Доступ ограничен", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(f"⛔ Доступ ограничен. Ваш id: {user.id if user else '?'}")
            return
        return await handler(update, context)
    return wrapper
