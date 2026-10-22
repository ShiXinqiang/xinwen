# Новостной Telegram-бот

Собирает новости из RSS-лент, отбирает их по ключевым словам (с учётом словоформ) и публикует в канал без повторов.
Отдельно работает интерактивный агент на YandexGPT (`/search`, `/ask`, `/stats`).

## Запуск

```bash
pip install -r requirements.txt
python -m newsbot        # основной режим: агент + сбор каждые 30 минут + ежедневная копия базы
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
| `COLLECT_INTERVAL_MINUTES` | как часто собирать новости, по умолчанию 30 |
| `SCORE_MODEL` | модель для оценки новостей, по умолчанию `yandexgpt-lite/latest` (можно полный URI `gpt://…`) |
| `BACKUP_DIR` | куда класть копии базы, по умолчанию `backups/` рядом с базой |

## Сервер

Бот работает на VPS (Ubuntu 24.04) одной службой systemd `newsbot`: агент, сбор новостей по расписанию
и резервные копии базы (каждый день в 03:30 МСК на диск, хранятся 14 последних; по понедельникам — файлом
в `ADMIN_CHAT_ID`). База лежит на сервере в `/var/lib/newsbot/`, в git она больше не пишется.

**Установка** (от root):

```bash
curl -fsSL https://raw.githubusercontent.com/arthurborodin95-ctrl/xinwen/main/deploy/install.sh | bash
nano /etc/newsbot/newsbot.env      # токены и id, шаблон — deploy/newsbot.env.example
systemctl start newsbot
journalctl -u newsbot -f           # лог в реальном времени
```

Повторный запуск `install.sh` безопасен: настройки и база не перезаписываются.
Обновление вручную: `/opt/newsbot/deploy/update.sh`.

**Автодеплой после слияния в `main`** (workflow `Deploy`: тесты → обновление сервера). Один раз:

1. На сервере создать ключ, который умеет только обновлять бота:
   ```bash
   mkdir -p /root/.ssh && chmod 700 /root/.ssh
   ssh-keygen -t ed25519 -N '' -C deploy -f /root/newsbot_deploy
   echo "command=\"/opt/newsbot/deploy/update.sh\",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding $(cat /root/newsbot_deploy.pub)" >> /root/.ssh/authorized_keys
   cat /root/newsbot_deploy            # → секрет VPS_SSH_KEY
   ssh-keyscan -t ed25519 localhost 2>/dev/null | sed "s/^localhost/<IP сервера>/"   # → секрет VPS_KNOWN_HOSTS
   rm /root/newsbot_deploy             # закрытый ключ на сервере больше не нужен
   ```
2. В GitHub: Settings → Secrets and variables → Actions → секреты `VPS_HOST` (IP сервера), `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`.

Пока секретов нет, деплой просто пропускается.

## Модерация

Если задан `ADMIN_CHAT_ID`, новости после фильтров не идут в канал сразу:

1. YandexGPT оценивает каждую от 0 до 10 по редакционной политике (`editorial_policy` в таблице `config`)
   и по последним решениям владелицы — так оценки подстраиваются под неё.
2. Оценка ниже `min_score_for_moderation` (4) — в архив, владелицу не беспокоим.
3. Остальное — карточкой владелице с кнопками **✅ Опубликовать / ❌ Отклонить**; в канал уходит только одобренное.
4. Режим `publish_mode = auto` — оценка от `auto_publish_score` (8) публикуется сама, остальное на модерацию.
5. Если модель недоступна или исчерпан дневной лимит `llm_daily_token_limit` (300 000 токенов),
   карточки приходят без оценки; предупреждение владелице — не чаще раза в 6 часов.

Команда `/queue` — сколько новостей ждут решения. Проверить модель на сервере:
`set -a; . /etc/newsbot/newsbot.env; set +a; /opt/newsbot/venv/bin/python -m newsbot.llm_check`.

Без `ADMIN_CHAT_ID` модерации нет — всё, что прошло фильтры, сразу публикуется.

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
  moderation.py      кнопки ✅/❌ под карточками
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
