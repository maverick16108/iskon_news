# Развёртывание на patita (news.prema.su)

Раскладка подогнана под конкретный сервер: одно ядро, ~1.7 ГБ свободной памяти
и мало места на диске. Поэтому:

- **база — системный PostgreSQL 17**, который на сервере уже есть, а не контейнер;
- **фронтенд собирается на рабочей машине**, на сервер уезжает только `dist/` —
  так на сервере не нужен Node и не появляется `node_modules` на сотни мегабайт;
- **бэкенд под systemd** в обычном venv, без сборки Docker-образа.

Сервер боевой, на нём уже девять сайтов. Все команды ниже трогают только
`news.prema.su`, отдельную базу и отдельный юнит.

## 1. База данных

Внимание: **системный PostgreSQL слушает порт 5433, а не 5432**. На 5432 висит
контейнер `laravel-postgres` чужого проекта — подключаться туда нельзя.

```bash
ssh patita
sudo -u postgres psql <<'SQL'
CREATE USER iskcon_news WITH PASSWORD 'ЗАМЕНИТЬ_НА_СВОЙ_ПАРОЛЬ';
CREATE DATABASE iskcon_news OWNER iskcon_news;
SQL
```

## 2. Код и окружение

```bash
ssh patita
mkdir -p /opt/iskcon-news
cd /opt/iskcon-news
git clone https://github.com/maverick16108/iskon_news.git .

python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

Файл `/opt/iskcon-news/.env` (в git его нет, создаётся руками):

```ini
DATABASE_URL=postgresql+asyncpg://iskcon_news:ПАРОЛЬ@localhost:5433/iskcon_news
SECRET_KEY=<python3 -c "import secrets; print(secrets.token_hex(32))">
FRONTEND_ORIGIN=https://news.prema.su
COOKIE_SECURE=true
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
```

Права: `chown -R www-data:www-data /opt/iskcon-news` и `chmod 600 /opt/iskcon-news/.env`.

## 3. Схема и первый администратор

```bash
cd /opt/iskcon-news/backend
sudo -u www-data ../backend/.venv/bin/alembic upgrade head
sudo -u www-data ../backend/.venv/bin/python cli.py createsuperuser
sudo -u www-data ../backend/.venv/bin/python cli.py seed-sources
```

## 4. Бэкенд

```bash
cp /opt/iskcon-news/deploy/iskcon-news.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now iskcon-news
systemctl status iskcon-news
```

Порт 8101 выбран свободным — 8000 и соседние на сервере уже заняты.

## 5. Фронтенд

На рабочей машине:

```bash
cd frontend
npm run build
rsync -avz --delete dist/ patita:/var/www/news.prema.su/
```

На сервере:

```bash
chown -R www-data:www-data /var/www/news.prema.su
```

## 6. nginx и сертификат

```bash
cp /opt/iskcon-news/deploy/nginx-news.prema.su.conf /etc/nginx/sites-available/news.prema.su
ln -s /etc/nginx/sites-available/news.prema.su /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

certbot --nginx -d news.prema.su --redirect
```

Флаг `secure` у сессионной куки берётся из `COOKIE_SECURE` в `.env` — под HTTPS
он должен быть `true`, иначе кука поедет и по незащищённому соединению.

## 7. Регулярный сбор новостей

`/etc/cron.d/iskcon-news`:

```cron
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin

17 * * * * www-data cd /opt/iskcon-news/backend && ../backend/.venv/bin/python cli.py fetch >> /var/log/iskcon-news-fetch.log 2>&1
```

Ротация лога настроена в `/etc/logrotate.d/iskcon-news`.

## Обновление

Прод развёрнут как git-чекаут `/opt/iskcon-news`, обновляется одной командой:

```bash
ssh patita /opt/iskcon-news/deploy/update.sh
```

Скрипт забирает свежий `main`, доставляет зависимости бэкенда, накатывает
миграции, пересобирает фронтенд на сервере (там стоит Node 20.19), раскладывает
статику, чинит права и перезапускает сервис. В конце проверяет `/api/health`
и ответ сайта снаружи.

Порядок работы: коммит и `git push` с рабочей машины → `update.sh` на сервере.

Откатиться на предыдущий коммит:

```bash
ssh patita 'cd /opt/iskcon-news && git reset --hard HEAD~1 && systemctl restart iskcon-news'
```

Файл `.env` в git не входит и обновлением не затрагивается; резервная копия
боевого лежит в `/root/iskcon-news.env.backup`.

Каталог принадлежит `www-data`, поэтому для git от root прописано исключение:
`git config --global --add safe.directory /opt/iskcon-news`.

## Что проверить перед выкладкой

- На диске свободно около 5 ГБ — venv и статика займут ~400 МБ, но запас
  небольшой, стоит заранее почистить старые логи и образы Docker.
- Сессионная кука: `secure=True` обязательно после включения HTTPS.
- Ключ OpenAI в `.env` с правами `600`, в репозиторий он не попадает.
