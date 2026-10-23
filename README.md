# Новостной Telegram-бот

Собирает новости из RSS-лент, отбирает их по ключевым словам (с учётом словоформ) и публикует в канал без повторов.
Отдельно работает интерактивный агент на YandexGPT (`/search`, `/ask`, `/stats`).

## Запуск

```bash
pip install -r requirements.txt
python -m newsbot        # основной режим: агент + сбор каждые 2 часа + ежедневная копия базы
python main.py           # один проход сбора (для отладки)
python adjust_filters.py # отчёт по оценкам
```

Тесты: `pip install -r requirements-dev.txt && python -m pytest`.

## Переменные окружения (`.env` или секреты GitHub)

| Переменная | Назначение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | токен бота |
| `TELEGRAM_CHAT_ID` | канал для новостей |
| `ADMIN_CHAT_ID` | необязательно: сюда приходят итоги каждого сбора (в канал служебные сообщения не идут) |
| `ALLOWED_USER_IDS` | необязательно: id пользователей агента через запятую; пусто — доступ у всех |
| `YANDEX_FOLDER_ID`, `YANDEX_API_KEY` | YandexGPT для агента |
| `GNEWS_API_KEY` | необязательно: GNews для `/search` |
| `NEWS_DB_PATH` | путь к базе, по умолчанию `news.db` (на сервере `/var/lib/newsbot/news.db`) |
| `COLLECT_INTERVAL_MINUTES` | как часто собирать новости, в минутах; по умолчанию 120 (раз в 2 часа) |
| `SCORE_MODEL` | модель для оценки новостей, по умолчанию `yandexgpt-lite/latest` (можно полный URI `gpt://…`) |
| `BACKUP_DIR` | куда класть копии базы, по умолчанию `backups/` рядом с базой |

## Сервер

Бот работает на VPS (Ubuntu 24.04) одной службой systemd `newsbot`: агент, сбор новостей по расписанию
и резервные копии базы (каждый день в 03:30 МСК на диск, хранятся 14 последних; по понедельникам — файлом
в `ADMIN_CHAT_ID`). База лежит только на сервере, в `/var/lib/newsbot/news.db`; в репозитории её нет.

**Установка** (от root):

```bash
curl -fsSL https://raw.githubusercontent.com/arthurborodin95-ctrl/xinwen/main/deploy/install.sh | bash
nano /etc/newsbot/newsbot.env      # токены и id, шаблон — deploy/newsbot.env.example
systemctl start newsbot
journalctl -u newsbot -f           # лог в реальном времени
```

Повторный запуск `install.sh` безопасен: настройки и база не перезаписываются.
Восстановить базу из копии:
`systemctl stop newsbot && cp /var/lib/newsbot/backups/news-<дата>.db /var/lib/newsbot/news.db && chown newsbot:newsbot /var/lib/newsbot/news.db && systemctl start newsbot`.
Обновление вручную: `/opt/newsbot/deploy/update.sh`.

**Автодеплой после слияния в `main`** (workflow `Deploy`: тесты → обновление сервера). Один раз:

1. На сервере создать ключ, который умеет только обновлять бота:
   ```bash
   mkdir -p /root/.ssh && chmod 700 /root/.ssh
   ssh-keygen -t ed25519 -N '' -C newsbot-deploy -f /root/newsbot_deploy -q
   echo "command=\"/opt/newsbot/deploy/update.sh\",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding $(cat /root/newsbot_deploy.pub)" >> /root/.ssh/authorized_keys
   chmod 600 /root/.ssh/authorized_keys
   cat /root/newsbot_deploy            # → секрет VPS_SSH_KEY
   ssh-keyscan -t ed25519 localhost 2>/dev/null | sed "s/^localhost/<IP сервера>/"   # → секрет VPS_KNOWN_HOSTS
   ```
   После добавления секретов в GitHub закрытый ключ на сервере больше не нужен: `rm /root/newsbot_deploy`.
2. В GitHub: Settings → Secrets and variables → Actions → секреты `VPS_HOST` (IP сервера), `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`.

Пока секретов нет, деплой просто пропускается.

## Отбор новостей и оценки владелицы

Режим задаётся `publish_mode` в таблице `config`:

- **`feed` (по умолчанию)** — новости приходят владелице в `TELEGRAM_CHAT_ID` с кнопками **👍 Нравится / 👎 Не нравится**.
  Кнопки ничего не публикуют: отметки — примеры для модели, по ним она решает, что присылать дальше.
- `moderation` — карточки в `ADMIN_CHAT_ID` с **✅ Опубликовать / ❌ Отклонить**, одобренное уходит в канал `TELEGRAM_CHAT_ID`.
- `auto` — как `moderation`, но оценка от `auto_publish_score` (8) публикуется сама.

Во всех режимах YandexGPT оценивает новость от 0 до 10 по редакционной политике (`editorial_policy`) и последним
отметкам владелицы; оценка ниже `min_score_for_moderation` (4) — в архив, владелице не приходит.
Если модель недоступна или исчерпан дневной лимит `llm_daily_token_limit` (300 000 токенов), новости приходят
без оценки; предупреждение в `ADMIN_CHAT_ID` — не чаще раза в 6 часов.

Команда `/queue` — сколько новостей без оценки владелицы. Проверить модель на сервере:
`cd /opt/newsbot && set -a && . /etc/newsbot/newsbot.env && set +a && venv/bin/python -m newsbot.llm_check`.

## Ключевые слова и исключения

Хранятся в таблице `config` базы (`keywords`, `excluded_keywords` — JSON-списки). Правила совпадения:

- по лемме: «Китай» находит «Китая», «Китаю»; «газ» находит «газа», но не «газету»;
- слова ключа от 5 букв ещё и по началу слова: «Китай» → «китайский», «металл» → «металлургия»;
- `*` в конце — по началу слова явно: `нефт*` → «нефтяной», «нефти»;
- фраза из нескольких слов («Параллельный импорт») ищется как подряд идущие слова.

## Устройство

```
main.py, agent_bot.py, adjust_filters.py   точки входа для отладки
deploy/              установка на сервер: служба systemd, install.sh, update.sh
newsbot/
  app.py             основной процесс: агент + сбор по расписанию + копии базы (python -m newsbot)
  backup.py          резервные копии базы
  config.py          переменные окружения
  storage.py         SQLite: отправленные статьи, настройки, статистика, оценки
  collector.py       один проход сбора: ленты → свежесть → слова → новизна → оценка → модерация
  moderation.py      кнопки под карточками: 👍/👎 (оценка) и ✅/❌ (публикация в канал)
  llm_check.py       проверка модели оценки на сервере
  publisher.py       оформление сообщения, отправка с учётом лимитов Telegram
  yandex.py          YandexGPT: генерация и эмбеддинги
  sources/rss.py     RSS-ленты (записи без даты отбрасываются)
  sources/gnews.py   GNews API
  pipeline/normalize.py  очистка HTML, канонические ссылки, даты
  pipeline/filters.py    ключевые слова и исключения по леммам
  pipeline/dedup.py      новизна: ссылка — навсегда, заголовок — 48 часов (и отправленные, и предложенные)
  pipeline/scoring.py    оценка новостей моделью, дневной лимит токенов
  pipeline/semantic.py   семантический отбор (выключен до обучения на оценках)
  agent/bot.py       интерактивный агент
  learning.py        обучение на оценках (пока только отчёт)
tests/
```
