#!/usr/bin/env bash
# Первичная установка бота на сервер (Ubuntu 24.04). Запускать от root:
#   curl -fsSL https://raw.githubusercontent.com/arthurborodin95-ctrl/xinwen/main/deploy/install.sh | bash
# Повторный запуск безопасен: настройки и база не перезаписываются.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/arthurborodin95-ctrl/xinwen.git}"
BRANCH="${BRANCH:-main}"
APP_DIR=/opt/newsbot
DATA_DIR=/var/lib/newsbot
ENV_FILE=/etc/newsbot/newsbot.env

[ "$(id -u)" -eq 0 ] || { echo "Запустите от root"; exit 1; }

echo "==> Пакеты"
apt-get update -qq
apt-get install -y -qq git python3-venv sqlite3 >/dev/null

echo "==> Пользователь newsbot"
id newsbot >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin newsbot

echo "==> Код в $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch -q origin "$BRANCH"
  git -C "$APP_DIR" reset -q --hard "origin/$BRANCH"
else
  git clone -q --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

echo "==> Python-окружение"
[ -d "$APP_DIR/venv" ] || python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> База в $DATA_DIR"
# Существующая база не трогается; новая создаётся ботом при первом запуске.
# Перенос на другой сервер: положить сюда news.db из резервной копии до запуска.
mkdir -p "$DATA_DIR/backups"
chown -R newsbot:newsbot "$DATA_DIR"
chmod 750 "$DATA_DIR"

echo "==> Настройки $ENV_FILE"
mkdir -p /etc/newsbot
if [ ! -f "$ENV_FILE" ]; then
  cp "$APP_DIR/deploy/newsbot.env.example" "$ENV_FILE"
  echo "    создан шаблон — заполните его"
fi
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "==> Служба systemd"
cp "$APP_DIR/deploy/newsbot.service" /etc/systemd/system/newsbot.service
systemctl daemon-reload
systemctl enable -q newsbot

if grep -qE '^TELEGRAM_BOT_TOKEN=$' "$ENV_FILE"; then
  echo
  echo "Осталось: заполнить $ENV_FILE (nano $ENV_FILE) и запустить: systemctl start newsbot"
else
  systemctl restart newsbot
  sleep 3
  systemctl --no-pager --lines=15 status newsbot || true
fi

OTHER=$(pgrep -af 'python.*(agent_bot|main\.py|gnews_bot)' | grep -v "$APP_DIR/venv" || true)
if [ -n "$OTHER" ]; then
  echo
  echo "⚠️  Найдены другие процессы бота — их нужно остановить, иначе Telegram выдаст Conflict:"
  echo "$OTHER"
fi
