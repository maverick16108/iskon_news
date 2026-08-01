#!/usr/bin/env bash
# Обновление прода из git. Запускать на сервере от root:
#   /opt/iskcon-news/deploy/update.sh
#
# Забирает свежий main, доставляет зависимости, накатывает миграции,
# пересобирает фронтенд и перезапускает сервис.

set -euo pipefail

APP_DIR=/opt/iskcon-news
WWW_DIR=/var/www/news.prema.su
SERVICE=iskcon-news

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

cd "$APP_DIR"

say "Забираем изменения из git"
BEFORE=$(git rev-parse --short HEAD)
git fetch --depth 1 origin main
git reset --hard origin/main
AFTER=$(git rev-parse --short HEAD)

if [ "$BEFORE" = "$AFTER" ]; then
    echo "Изменений нет, остаёмся на $AFTER"
else
    echo "$BEFORE -> $AFTER"
fi
git log --oneline -1

say "Зависимости бэкенда"
backend/.venv/bin/pip install -q --disable-pip-version-check -r backend/requirements.txt
echo "готово"

say "Миграции базы"
(cd backend && ../backend/.venv/bin/alembic upgrade head)

say "Сборка фронтенда"
# npm ci воспроизводит package-lock.json один в один; сборке нужны и devDependencies
(cd frontend && npm ci --no-audit --no-fund --silent && npm run build)

say "Выкладка статики"
rsync -a --delete frontend/dist/ "$WWW_DIR/"
chown -R www-data:www-data "$WWW_DIR"

say "Права"
chown -R www-data:www-data "$APP_DIR"
chmod 600 "$APP_DIR/.env"

say "Перезапуск сервиса"
systemctl restart "$SERVICE"
sleep 6
systemctl is-active "$SERVICE"

say "Проверка"

# systemctl возвращает управление раньше, чем uvicorn успевает занять порт,
# поэтому ждём, а не спрашиваем один раз сразу после перезапуска
for attempt in $(seq 1 20); do
    if curl -fsS --max-time 5 http://127.0.0.1:8101/api/health; then
        echo
        break
    fi
    if [ "$attempt" = 20 ]; then
        echo "Бэкенд не ответил за 20 секунд — смотрите journalctl -u iskcon-news" >&2
        exit 1
    fi
    sleep 1
done

curl -fsS -o /dev/null -w 'https://news.prema.su -> HTTP %{http_code}\n' --max-time 20 https://news.prema.su/api/health

say "Обновление завершено"
