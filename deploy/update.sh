#!/usr/bin/env bash
# Обновление кода и перезапуск. Вызывается деплоем из GitHub Actions (ключ ограничен только этим скриптом)
# или вручную от root: /opt/newsbot/deploy/update.sh
set -euo pipefail
APP_DIR=/opt/newsbot
BRANCH="${BRANCH:-main}"

git -C "$APP_DIR" fetch -q origin "$BRANCH"
git -C "$APP_DIR" reset -q --hard "origin/$BRANCH"
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
cp "$APP_DIR/deploy/newsbot.service" /etc/systemd/system/newsbot.service
systemctl daemon-reload
systemctl restart newsbot
sleep 5
if systemctl is-active -q newsbot; then
  echo "✅ newsbot работает, версия $(git -C "$APP_DIR" log --oneline -1)"
else
  echo "❌ newsbot не запустился:"
  journalctl -u newsbot --no-pager -n 30
  exit 1
fi
