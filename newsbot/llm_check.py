"""
Проверка модели оценки на сервере (базу не трогает):
    set -a; . /etc/newsbot/newsbot.env; set +a; /opt/newsbot/venv/bin/python -m newsbot.llm_check
"""
import sys

from newsbot.config import load_settings
from newsbot.pipeline.scoring import article_prompt, build_system_prompt, parse_assessment
from newsbot.storage import DEFAULT_CONFIG
from newsbot.yandex import LLMError, complete

SAMPLES = [
    ('Товарооборот России и Китая в сентябре превысил $29 млрд',
     'Объём торговли вырос на 8% за счёт поставок машин и оборудования, расчёты в юанях достигли 95%.'),
    ('Блогер рассказала о прогрессировании болезни', 'Популярный блогер поделилась новостями о здоровье.'),
]


def main():
    settings = load_settings()
    print(f"Модель: {settings.score_model}")
    system = build_system_prompt(DEFAULT_CONFIG['editorial_policy'], [], [])
    ok = True
    for title, text in SAMPLES:
        article = {'title': title, 'description': text, 'source': {'name': 'Проверка'}}
        try:
            answer, tokens = complete([{"role": "system", "text": system},
                                       {"role": "user", "text": article_prompt(article)}],
                                      model=settings.score_model, max_tokens=300, temperature=0.1)
            a = parse_assessment(answer)
            print(f"✅ {a['score']}/10 · {a['topic']} · {a['reason']}  ({tokens} токенов)\n   {title}")
        except (LLMError, ValueError) as e:
            ok = False
            print(f"❌ {title}\n   {e}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
