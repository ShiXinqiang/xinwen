"""
Оценка новостей моделью: насколько новость подходит каналу (0–10), тема, суть и причина оценки.
Модель видит редакционную политику и последние решения владелицы — так оценки подстраиваются под неё.
"""
import json
import logging

from newsbot import storage
from newsbot.yandex import LLMError, complete

logger = logging.getLogger(__name__)

MAX_TEXT_LEN = 1000

SYSTEM_PROMPT = """Ты — редактор Telegram-канала. Оцени, подходит ли новость каналу.

Редакционная политика:
{policy}
{examples}
Ответь строго одним JSON-объектом, без пояснений и без markdown:
{{"score": целое от 0 до 10, "topic": "тема в 2–4 словах", "summary": "суть новости одной фразой до 20 слов", "reason": "почему такая оценка, до 15 слов"}}
10 — точно для канала, 0 — точно не для канала. Оценивай по сути новости, а не по отдельным словам."""


def build_system_prompt(policy: str, approved: list[str], rejected: list[str]) -> str:
    examples = ''
    if approved:
        examples += '\nВладелица канала одобряла такие новости:\n' + '\n'.join(f'- {t}' for t in approved) + '\n'
    if rejected:
        examples += '\nИ отклоняла такие:\n' + '\n'.join(f'- {t}' for t in rejected) + '\n'
    return SYSTEM_PROMPT.format(policy=policy, examples=examples)

def article_prompt(article: dict) -> str:
    text = (article.get('description') or '')[:MAX_TEXT_LEN]
    return f"Источник: {article['source'].get('name', '')}\nЗаголовок: {article['title']}\nТекст: {text or '(нет)'}"

def parse_assessment(text: str) -> dict:
    """Достаёт JSON из ответа модели (бывает обёрнут в ``` или с текстом вокруг). ValueError, если не вышло."""
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        raise ValueError(f"в ответе нет JSON: {text[:100]!r}")
    data = json.loads(text[start:end + 1])
    score = max(0, min(10, int(round(float(data['score'])))))
    clean = lambda key, limit: str(data.get(key) or '').strip()[:limit]
    return {'score': score, 'topic': clean('topic', 60), 'summary': clean('summary', 300), 'reason': clean('reason', 200)}


def score_articles(articles: list[dict], model: str) -> dict:
    """
    Проставляет каждой статье '_assessment' (dict или None, если оценить не удалось).
    Синхронная — вызывать из потока. Возвращает статистику.
    """
    stats = {'scored': 0, 'failed': 0, 'over_budget': 0, 'tokens': 0, 'error': None}
    if not articles:
        return stats
    limit = storage.get_int_config('llm_daily_token_limit')
    approved, rejected = storage.get_moderation_examples()
    system = build_system_prompt(storage.get_config('editorial_policy', storage.DEFAULT_CONFIG['editorial_policy']),
                                 approved, rejected)
    stop = False
    for a in articles:
        a['_assessment'] = None
        if stop:
            continue
        if storage.get_llm_tokens_today() >= limit:
            stats['over_budget'] += 1
            continue
        try:
            text, tokens = complete(
                [{"role": "system", "text": system}, {"role": "user", "text": article_prompt(a)}],
                model=model, max_tokens=300, temperature=0.1,
            )
            storage.add_llm_tokens(tokens)
            stats['tokens'] += tokens
            a['_assessment'] = parse_assessment(text)
            stats['scored'] += 1
        except LLMError as e:
            stats['failed'] += 1
            stats['error'] = str(e)
            logger.warning(f"Оценка не получена: {e}")
            # Ключей нет или доступ запрещён — дальше пробовать бессмысленно
            if 'не настроен' in str(e) or ' 401' in str(e) or ' 403' in str(e):
                stop = True
        except (ValueError, KeyError, TypeError) as e:
            stats['failed'] += 1
            stats['error'] = f"не разобран ответ модели: {e}"
            logger.warning(stats['error'])
    return stats
