import asyncio
import html
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from dotenv import load_dotenv

from db import init_db, save_feedback, get_total_sent, get_keywords
from yandex_ai import call_yandex_gpt
from news_fetcher import fetch_gnews, fetch_rss_feeds, normalize_text

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не задан")

logging.basicConfig(level=logging.INFO)
user_context = {}
init_db()

def format_news_summary(articles, max_items=5):
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
        all_news = fetch_rss_feeds()
        keywords = query.split()
        articles = [a for a in all_news if any(kw.lower() in normalize_text(a['title'] + ' ' + a['description']) for kw in keywords)]
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Привет! Я — ваш новостной агент.\n"
        "Команды:\n"
        "/search <запрос> — поиск новостей\n"
        "/ask <вопрос> — задать вопрос\n"
        "/stats — статистика\n"
        "/feedback like|dislike — оценка\n"
        "/help — помощь"
    )

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("Укажите запрос: /search <текст>")
        return
    await update.message.reply_text("🔍 Ищу...")
    result = await asyncio.to_thread(search_news, query)
    await update.message.reply_text(result, parse_mode='HTML', disable_web_page_preview=True)

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = ' '.join(context.args)
    if not question:
        await update.message.reply_text("Задайте вопрос: /ask <текст>")
        return
    user_id = update.effective_user.id
    await update.message.reply_text("🤔 Думаю...")
    answer = await ask_agent(question, user_id)
    keyboard = [[InlineKeyboardButton("👍 Полезно", callback_data='feedback_like'),
                 InlineKeyboardButton("👎 Бесполезно", callback_data='feedback_dislike')]]
    await update.message.reply_text(answer, reply_markup=InlineKeyboardMarkup(keyboard))

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = get_total_sent()
    await update.message.reply_text(f"📊 Всего отправлено новостей: {total}")

async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    rating = 1 if query.data == 'feedback_like' else -1
    save_feedback(user_id, query.message.text[:500], rating)
    # Ответ оставляем, убираем только кнопки, чтобы не оценивали дважды
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("✅ Спасибо за оценку!" if rating == 1 else "😕 Спасибо, я постараюсь улучшиться!")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("🤔 Анализирую...")
    answer = await ask_agent(update.message.text, user_id)
    keyboard = [[InlineKeyboardButton("👍 Полезно", callback_data='feedback_like'),
                 InlineKeyboardButton("👎 Бесполезно", callback_data='feedback_dislike')]]
    await update.message.reply_text(answer, reply_markup=InlineKeyboardMarkup(keyboard))

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(feedback_callback, pattern='feedback_'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    print("🚀 Интерактивный агент запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
