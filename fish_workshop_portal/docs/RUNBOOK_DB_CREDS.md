# Runbook: Реакция на рассинхронизацию учётных данных PostgreSQL

## 1. Назначение и контекст

Данный документ содержит операционные инструкции по восстановлению работоспособности системы при расхождении учётных данных PostgreSQL между файлом конфигурации `.env` на хосте и реальным состоянием существующей базы данных (`pgdata`).

### Архитектурный контекст (ADR-011)
* **Инициализация PostgreSQL:** Переменные `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` в official Docker-образе PostgreSQL применяются **только при первичной инициализации** нового пустого тома (`pgdata`).
* **Повторные запуски:** При наличии существующего тома (`external: true`) PostgreSQL игнорирует изменения `POSTGRES_*` в `.env`. 
* **Последствия:** Изменение `DB_USER`, `DB_PASSWORD` или `DB_NAME` в `.env` без применения DDL-команд к базе данных приводит к падению контейнера `migrate-job` с `OperationalError` (ошибка аутентификации или отсутствия базы).
* **Связанные документы:** 
  * `architecture_overview_8.md` — ADR-011 (Инварианты источников и деплоя).
  * `migration.example.md` — Плановый регламент развёртывания и отката.

---

## 2. Предварительные требования и переменные окружения

Для выполнения любых команд через скрипт `scripts/cc.sh` необходимо задавать обязательные контекстные переменные `APP_ENV` и `APP_IMAGE_TAG`.

Перед началом работы экпортируйте их в вашей текущей сессии SSH:

```bash
export APP_ENV=prod              # Или staging/dev в зависимости от окружения
export APP_IMAGE_TAG=current     # Используется текущая версия или конкретный хэш/тег
```

---

## 3. Диагностика инцидента

При сбое контейнера `migrate-job` во время деплоя (`scripts/deploy.sh`) выполните последовательную диагностику:

### Шаг 3.1. Проверка логов `migrate-job`
```bash
scripts/cc.sh logs migrate-job
```

### Типовые ошибки и причины:
1. `password authentication failed for user "<user>"` — В `.env` изменён `DB_PASSWORD`, но в PostgreSQL остался старый пароль.
2. `role "<user>" does not exist` — В `.env` изменён `DB_USER`, но роль в PostgreSQL не переименована.
3. `database "<name>" does not exist` — В `.env` изменён `DB_NAME`, но база данных в PostgreSQL не переименована.

### Шаг 3.2. Безопасная отладка отпечатка пароля (при необходимости)
Если есть сомнения, какой именно пароль пытался использовать `migrate-job`, включите временный отпечаток (fingerprint):

```bash
MIGRATE_LOG_PWD_FINGERPRINT=1 scripts/cc.sh run --rm migrate-job
```
*Примечание: Выводится только MD5-хэш/длина пароля для верификации совпадения без раскрытия секретов в логах.*

---

## 4. Процедуры восстановления (Recovery Matrix)

Подключение для выполнения восстановительных команд производится к контейнеру `postgres` от имени системного суперпользователя `postgres` через локальный Unix-сокет (`trust` авторизация внутри контейнера).

### Сценарий A: Изменился только `DB_PASSWORD`

В `.env` обновлён пароль, но роль в БД содержит старый.

1. Безопасно задайте новый пароль для роли (считывается без сохранения в истории bash):
```bash
echo -n "Введите новый DB_PASSWORD из .env: " && read -rs NEW_DB_PASSWORD && echo ""

scripts/cc.sh exec -T postgres psql -U postgres -d postgres -c \
  "ALTER USER \"${DB_USER:-app_user}\" WITH PASSWORD '${NEW_DB_PASSWORD}';"
```

---

### Сценарий B: Изменился `DB_USER`

В `.env` изменено имя пользователя (роли). 

*Важно: Попытка выполнить `ALTER USER` от имени самого пользователя вызовет ошибку `session user cannot be renamed`. Переименование выполняется строго из-под суперпользователя `postgres`.*

1. Выполните переименование роли и обновление её пароля:
```bash
echo -n "Введите старое имя пользователя (OLD_USER): " && read -r OLD_USER
echo -n "Введите новое имя пользователя (NEW_USER из .env): " && read -r NEW_USER
echo -n "Введите DB_PASSWORD из .env: " && read -rs DB_PASSWORD && echo ""

scripts/cc.sh exec -T postgres psql -U postgres -d postgres -c \
  "ALTER ROLE \"${OLD_USER}\" RENAME TO \"${NEW_USER}\";"

scripts/cc.sh exec -T postgres psql -U postgres -d postgres -c \
  "ALTER ROLE \"${NEW_USER}\" WITH PASSWORD '${DB_PASSWORD}';"
```

---

### Сценарий C: Изменилось имя базы данных `DB_NAME`

В `.env` изменено `DB_NAME`.

*Важно: PostgreSQL не позволит переименовать базу данных (`ALTER DATABASE ... RENAME TO`), если к ней есть активные подключения (`database is being accessed by other users`).*

1. Выполните принудительный разрыв активных соединений и переименование базы:
```bash
echo -n "Введите старое имя базы (OLD_DB): " && read -r OLD_DB
echo -n "Введите новое имя базы (NEW_DB из .env): " && read -r NEW_DB

# 1. Принудительное завершение всех сессий к старой БД
scripts/cc.sh exec -T postgres psql -U postgres -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${OLD_DB}' AND pid <> pg_backend_pid();"

# 2. Переименование базы данных
scripts/cc.sh exec -T postgres psql -U postgres -d postgres -c \
  "ALTER DATABASE \"${OLD_DB}\" RENAME TO \"${NEW_DB}\";"
```

---

### Сценарий D: Полный сброс и повторная инициализация тома `pgdata`

Применяется **только на staging/dev** или при первичном развёртывании, если данные в БД не представляют ценности и требуется пересоздать схему с нуля.

1. Остановите зависимые сервисы:
```bash
scripts/cc.sh stop web worker postgres
```

2. Удалите существующий Docker volume:
```bash
docker volume rm app_pgdata || docker volume rm $(docker volume ls -q | grep pgdata)
```

3. Запустите PostgreSQL для чистой инициализации с новыми значениями `POSTGRES_*` из `.env`:
```bash
scripts/cc.sh up -d postgres
```

4. Дождитесь готовности PostgreSQL (статус `healthy`):
```bash
scripts/cc.sh ps postgres
```

---

## 5. Проверка и возврат системы в строй

После применения необходимых изменений в PostgreSQL (Сценарии A, B, C или D) выполните финальную валидацию:

1. Запустите миграцию повторно вручную:
```bash
scripts/cc.sh run --rm migrate-job
```
*Убедитесь, что миграции завершились с кодом 0 (`OK`).*

2. Убедитесь, что отладочные флаги отключены в окружении:
```bash
unset MIGRATE_LOG_PWD_FINGERPRINT
```

3. Возобновите стандартный сценарий деплоя согласно `migration.example.md` (Шаг 6.1):
```bash
scripts/deploy.sh
```

4. Проверьте статус всех сервисов приложения:
```bash
scripts/cc.sh ps
```