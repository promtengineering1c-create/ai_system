# GitHub


sudo apt update
sudo apt install git -y
sudo apt install gh -y

git config --global user.name ""
git config --global user.email ""

curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null

sudo apt install gh -y

gh auth login

gh repo create ai_system --public --source=. --remote=origin --push

# Создание сетевой папки 
sudo apt update && sudo apt install samba -y
sudo mkdir -p /srv/samba/share
sudo chmod -R 0777 /srv/samba/share
Конфигурация (/etc/samba/smb.conf):
Добавить в конец файла: sudo nano /etc/samba/smb.conf
ls -la /srv/samba/share  
```` code
[share]
   path = /srv/samba/share
   browsable = yes
   writable = yes
   read only = no
   guest ok = yes
   create mask = 0777
   directory mask = 0777
   change notify = yes
   stat cache = no
````
sudo systemctl restart smbd

sudo systemctl enable smbd добавить в автозагрузку

# Установка uv
which uv или uv --version
curl -LsSf https://astral.sh/uv/install.sh | sh

files: 
pyproject.toml: 
```` code
[project]
name = "name"
version = "0.1.0"
description = ""
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "pyyaml>=6.0.0,<7.0.0",
]
````
.python-version:
```` code
3.12
````
uv sync

source .venv/bin/activate

uv add "django~=5.2" "pydantic-settings~=2.16" "whitenoise~=6.12"

uv add "psycopg[binary]~=3.3"

uv add --dev pytest pytest-django pytest-cov ruff




python manage.py runserver 0.0.0.0:8000

ln -sf .env.development .env семилинк?

docker compose up --build
docker compose down

# первый запуск

Проверка установки
docker --version && docker compose version && ls -la && ls -la scripts/ nginx/ 2>/dev/null

docker volume inspect pgdata >/dev/null 2>&1 && echo "pgdata: OK" || echo "pgdata: MISSING"
если MISSING
    docker volume create pgdata

# Для первого локального запуска использована тестовая пара admin:admin и прямое перенаправление >
python3 -c 'import crypt; print("admin:" + crypt.crypt("admin", crypt.mksalt(crypt.METHOD_SHA512)))' > data/nginx-dynamic/.htpasswd


# ПРОВЕРКИ
python3 -m py_compile config/settings.py && echo "settings.py syntax: OK"
/scripts/cc.sh config --quiet && echo "cc.sh config: OK"

chmod +x scripts/deploy.sh
bash -n scripts/deploy.sh && echo "syntax OK"      # синтаксис sh
shellcheck -x scripts/*.sh  


APP_ENV=development .venv/bin/python manage.py makemigrations users
ls -la db/users/migrations/

# ВОТ ПЕРВЫЙ ЗАПУСК 
export APP_ENV=development
./scripts/cc.sh build

export APP_ENV=development

# 1. Запуск БД и Redis с ожиданием прохождения healthcheck
./scripts/cc.sh up -d --wait postgres redis

# 2. Выполнение одноразовых задач (миграции БД, публикация статики, генерация TLS-заглушки)
./scripts/cc.sh run --rm migrate-job
./scripts/cc.sh run --rm static-publish-job
./scripts/cc.sh run --rm cert-init

# 3. Запуск web и nginx с ожиданием healthcheck
./scripts/cc.sh up -d --wait web nginx

# 4. Проверка состояния всех контейнеров стека
./scripts/cc.sh ps -a

# 1. Проверка системного резолвинга и доступности витрины по имени домена
getent hosts uralsfish.ru
curl -Iks https://uralsfish.ru/ | head -n 1

# 2. Создание суперпользователя для входа в https://uralsfish.ru/admin/
cd ~/ai-system/fish_workshop_portal && \
APP_ENV=development ./scripts/cc.sh exec web python manage.py createsuperuser