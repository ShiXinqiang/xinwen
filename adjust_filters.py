#!/usr/bin/env python3
"""
Скрипт для адаптивной настройки фильтров бота на основе обратной связи пользователей.
Запускается по cron (например, раз в сутки).
"""
import logging
from dotenv import load_dotenv
load_dotenv()

from db import init_db, get_recent_feedback_stats

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def adjust_filters():
    """
    Пока только отчёт по оценкам: настройки не меняются.

    Прежняя логика была ошибочной: оценки хранятся как +1/-1, а сравнивались с 3.0/4.0
    (порог понижался всегда), плохие оценки ослабляли фильтр вместо ужесточения,
    а в ключевые слова попадали любые частые слова из ответов GPT, включая «это», «который».
    К тому же оцениваются ответы агента, а не новости канала. Новое обучение — этап 3.
    """
    init_db()
    avg_rating, count = get_recent_feedback_stats(days=7)
    logger.info(f"Оценок за 7 дней: {count}, средняя (от -1 до 1): {avg_rating:.2f}")
    logger.info("Автоматическая корректировка фильтров отключена до этапа 3.")

if __name__ == '__main__':
    adjust_filters()
