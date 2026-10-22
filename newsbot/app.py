"""
Единый процесс для VPS: агент (polling) + сбор новостей по расписанию + резервные копии базы.
Запуск: python -m newsbot
"""
import datetime
import logging

from telegram.ext import Application, ContextTypes

from newsbot import collector
from newsbot.agent.bot import build_application
from newsbot.backup import backup_db
from newsbot.config import Settings, load_settings
from newsbot.publisher import notify_admin

logger = logging.getLogger(__name__)

MSK = datetime.timezone(datetime.timedelta(hours=3))
BACKUP_TIME = datetime.time(3, 30, tzinfo=MSK)
# Еженедельная копия администратору: понедельник (0 — воскресенье в нумерации JobQueue)
WEEKLY_BACKUP_DAY = 1


async def collect_job(context: ContextTypes.DEFAULT_TYPE):
    settings: Settings = context.bot_data['settings']
    try:
        await collector.run(settings, bot=context.bot)
    except Exception as e:
        logger.exception("Сбор новостей упал")
        await notify_admin(context.bot, settings.admin_chat_id, f"❌ Сбор новостей упал: {e}")


async def backup_job(context: ContextTypes.DEFAULT_TYPE):
    settings: Settings = context.bot_data['settings']
    try:
        path = backup_db()
        logger.info(f"Резервная копия базы: {path}")
        is_weekly = datetime.datetime.now(MSK).isoweekday() % 7 == WEEKLY_BACKUP_DAY
        if is_weekly and settings.admin_chat_id:
            with open(path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=settings.admin_chat_id, document=f, filename=path.name,
                    caption="🗄 Еженедельная копия базы новостей"
                )
    except Exception as e:
        logger.exception("Резервная копия не создана")
        await notify_admin(context.bot, settings.admin_chat_id, f"❌ Резервная копия базы не создана: {e}")


def build(settings: Settings | None = None) -> Application:
    settings = settings or load_settings()
    if not settings.telegram_chat_id:
        raise ValueError("TELEGRAM_CHAT_ID не задан")
    app = build_application(settings)
    app.bot_data['settings'] = settings
    # max_instances=1: если сбор затянулся дольше интервала, следующий не стартует поверх
    app.job_queue.run_repeating(
        collect_job, interval=settings.collect_interval_minutes * 60, first=10,
        name='collect', job_kwargs={'max_instances': 1, 'coalesce': True},
    )
    app.job_queue.run_daily(backup_job, time=BACKUP_TIME, name='backup')
    return app


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)  # не писать в лог каждый запрос polling
    app = build()
    logger.info("🚀 Бот запущен: агент + сбор новостей по расписанию")
    app.run_polling()
