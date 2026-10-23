"""Интерактивный агент: /search, /ask, /stats и оценка ответов."""
import asyncio
import html
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from newsbot import storage
from newsbot.agent.access import restricted
from newsbot.config import load_settings
from newsbot.moderation import moderation_callback
from newsbot.pipeline.filters import ArticleFilter
from newsbot.sources.gnews import fetch_gnews
from newsbot.sources.rss import fetch_rss_feeds
from newsbot.yandex import call_yandex_gpt

logger = logging.getLogger(__name__)
user_context = {}

FEEDBACK_KEYBOARD = InlineKeyboardMarkup([[
    InlineKeyboardButton("👍 Полезно", callback_data='feedback_like'),
    InlineKeyboardButton("👎 Бесполезно", callback_data='feedback_dislike'),
]])


def format_news_summary(articles, max_items=5):
    """Список ссылок в HTML (все поля экранированы)."""
    if not articles:
        return "Новостей не найдено."
    lines = []
    for i, a in enumerate(articles[:max_items], 1):
        title = a.get('title', 'Без заголовка')
        url = a.get('url', '#')
        source = a.get('source', {}).get('name', 'Неизвестный источник')
        lines.append(f'{i}. <a href="{html.escape(url, quote=True)}">{html.escape(title)}</a> — {html.escape(source)}')
    return "\n".join(lines)

def search_news(query: str) -> str:
    articles = fetch_gnews(query, max_articles=10)
    if not articles:
        # Те же правила словоформ, что и в фильтре канала: любое слово запроса
        query_filter = ArticleFilter(query.split(), [])
        articles = [a for a in fetch_rss_feeds() if query_filter.accepts(a['title'] + ' ' + a['description'])]
    return format_news_summary(articles)

async def ask_agent(question: str, user_id: int) -> str:
    history = user_context.get(user_id, [])
    context_text = "\n".join(history[-10:]) if history else ""
    prompt = f"""
Ты — интеллектуальный помощник. Отвечай на вопросы пользователя на основе своих знаний.

История диалога:
{context_text}

Вопрос: {question}
Ответ:
"""
    response = await asyncio.to_thread(call_yandex_gpt, prompt, max_tokens=600, temperature=0.7)
    if not response:
        return "Извините, не удалось обработать запрос."
    history.append(f"Пользователь: {question}")
    history.append(f"Бот: {response}")
    user_context[user_id] = history[-20:]
    return response


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Привет! Я — ваш новостной агент.\n"
        "Команды:\n"
        "/search <запрос> — поиск новостей\n"
        "/ask <вопрос> — задать вопрос\n"
        "/stats — статистика\n"
        "/queue — сколько новостей ждут вашей оценки\n"
        "/help — помощь\n"
        "Под ответами есть кнопки 👍/👎 для оценки."
    )

@restricted
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("Укажите запрос: /search <текст>")
        return
    await update.message.reply_text("🔍 Ищу...")
    result = await asyncio.to_thread(search_news, query)
    await update.message.reply_text(result, parse_mode='HTML', disable_web_page_preview=True)

async def _answer(update: Update, question: str, status: str):
    await update.message.reply_text(status)
    answer = await ask_agent(question, update.effective_user.id)
    await update.message.reply_text(answer, reply_markup=FEEDBACK_KEYBOARD)

@restricted
async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = ' '.join(context.args)
    if not question:
        await update.message.reply_text("Задайте вопрос: /ask <текст>")
        return
    await _answer(update, question, "🤔 Думаю...")

@restricted
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _answer(update, update.message.text, "🤔 Анализирую...")

@restricted
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = storage.get_total_sent()
    await update.message.reply_text(f"📊 Всего отправлено новостей: {total}")

@restricted
async def queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = storage.count_pending_candidates()
    mode = storage.get_publish_mode()
    if mode == 'feed':
        await update.message.reply_text(f"🗂 Новостей без вашей оценки 👍/👎: {pending}")
    else:
        label = 'модерация' if mode == 'moderation' else 'автопубликация'
        await update.message.reply_text(f"🗂 Ждут решения: {pending}\nРежим: {label}")

@restricted
async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rating = 1 if query.data == 'feedback_like' else -1
    storage.save_feedback(update.effective_user.id, query.message.text[:500], rating)
    # Ответ оставляем, убираем только кнопки, чтобы не оценивали дважды
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("✅ Спасибо за оценку!" if rating == 1 else "😕 Спасибо, я постараюсь улучшиться!")


def build_application(settings=None) -> Application:
    settings = settings or load_settings()
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN не задан")
    if not settings.allowed_user_ids:
        logger.warning("ALLOWED_USER_IDS не задан — агентом (и квотой YandexGPT) может пользоваться любой.")
    storage.init_db()
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data['allowed_user_ids'] = settings.allowed_user_ids
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("queue", queue))
    app.add_handler(CallbackQueryHandler(moderation_callback, pattern='^(mod|fb):'))
    app.add_handler(CallbackQueryHandler(feedback_callback, pattern='^feedback_'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    return app

def main():
    logging.basicConfig(level=logging.INFO)
    app = build_application()
    print("🚀 Интерактивный агент запущен...")
    app.run_polling()
