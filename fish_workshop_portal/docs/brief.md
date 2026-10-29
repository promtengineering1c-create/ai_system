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