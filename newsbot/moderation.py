"""
Кнопки под карточками новостей:
- 👍/👎 (режим feed) — оценка владелицы, ничего не публикует; отметки — примеры для модели;
- ✅/❌ (режим moderation) — опубликовать в канал / отклонить.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from newsbot import storage
from newsbot.config import load_settings
from newsbot.publisher import article_from_candidate, format_article, send_with_retry

logger = logging.getLogger(__name__)


FEEDBACK_LABELS = {'approved': "👍 Учту: такие новости нужны", 'rejected': "👎 Учту: такие больше не присылать"}


def _is_moderator(user_id: int, settings, allowed: frozenset) -> bool:
    # TELEGRAM_CHAT_ID с положительным id — личка владелицы: её id совпадает с id чата
    return (str(user_id) in (str(settings.admin_chat_id), str(settings.telegram_chat_id))
            or user_id in allowed)


async def moderation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    settings = context.bot_data.get('settings') or load_settings()
    if not _is_moderator(update.effective_user.id, settings, context.bot_data.get('allowed_user_ids') or frozenset()):
        await query.answer("Доступ ограничен", show_alert=True)
        return

    try:
        kind, action, raw_id = query.data.split(':')
        candidate_id = int(raw_id)
    except ValueError:
        await query.answer("Неизвестная кнопка")
        return

    candidate = storage.get_candidate(candidate_id)
    if candidate is None:
        await query.answer("Новость не найдена")
        return

    new_status = 'approved' if action in ('approve', 'like') else 'rejected'
    # Атомарно pending → решение: двойное нажатие не опубликует новость дважды
    if not storage.decide_candidate(candidate_id, new_status):
        await query.answer("Уже решено раньше")
        await query.edit_message_reply_markup(reply_markup=None)
        return

    if kind == 'fb':
        label = FEEDBACK_LABELS[new_status]
    elif new_status == 'approved':
        article = article_from_candidate(candidate)
        try:
            await send_with_retry(context.bot, chat_id=settings.telegram_chat_id,
                                  text=format_article(article), disable_web_page_preview=True)
        except Exception as e:
            storage.reopen_candidate(candidate_id)
            logger.exception("Публикация одобренной новости не удалась")
            await query.answer(f"Не удалось опубликовать: {e}", show_alert=True)
            return
        storage.mark_article_sent(article['url'], article['title'], article['source']['name'], article['_hash'])
        label = "✅ Опубликовано"
    else:
        label = "❌ Отклонено"

    await query.answer(label)
    # Кнопки убираем, решение дописываем в карточку — видно, что уже обработано
    await query.edit_message_text(f"{query.message.text}\n\n{label}", disable_web_page_preview=True)
