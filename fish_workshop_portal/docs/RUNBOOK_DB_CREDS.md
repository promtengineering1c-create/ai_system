# Runbook: DB-креды, единый источник, recovery (ADR-011)

## Инвариант
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` — только в базовом `.env`.
  В `.env.${APP_ENV}` креды БД и `POSTGRES_*` запрещены (проверяется `scripts/cc.sh`,
  включая `export`-префикс; не-кредовые параметры `DB_*` в `.env.${APP_ENV}` допустимы).
  В базовом `.env` запрещены `POSTGRES_*` (compose маппит `POSTGRES_*` из `DB_*`).
- Единственный вход к compose — `scripts/cc.sh` (переход в корень репозитория,
  unset shell-override, preflight env-файлов и bind-маунтов, L2 render-check с пробросом
  глобальных флагов compose, затем `exec docker compose "$@"`).
  Прямые вызовы `docker compose` вне cc.sh запрещены — не проходят unset/preflight.
- deploy.sh / rollback.sh / backup_db.sh вызывают compose только через cc.sh.
- Условие применимости: один APP_ENV на хост (один compose-проект = один postgres).
  Второе окружение на том же хосте ломает инвариант — отдельный ADR до появления.
- compose пиннен >= 2.24: long-form env_file + корректный срез `export`-префикса в .env.
- Пароли генерируются из `[A-Za-z0-9]` (требование к генератору: `$`/спецсимволы в
  интерполяции — отдельный класс багов). Существующий спецсимвольный пароль
  меняется лестницей ниже, не сменой политики генерации.

## Порядок деплоя
1. `scripts/cc.sh pull`
2. `scripts/cc.sh up -d` — migrate-job стартует `cli.preflight_migrate` (L3):
   лог target + hint на OperationalError; при ошибке web не стартует (fail-fast).

## Диагностика auth-fail
`scripts/cc.sh logs migrate-job`. Маппинг hint'ов:
- password authentication failed -> лестница ниже (частый корень: init-only pgdata);
- database "X" does not exist -> DB_NAME vs POSTGRES_DB или переименование при старом томе;
- role "X" does not exist -> DB_USER vs POSTGRES_USER или переименование;
- could not connect -> postgres unhealthy / сеть backend.

## Recovery-лестница
Unix-socket trust: у официального postgres-образа pg_hba содержит `local all all trust`,
ALTER выполняется без пароля изнутри контейнера postgres. Суперпользователь кластера,
созданный при `initdb`, имеет имя из `POSTGRES_USER` (`<user>`, при переименовании — `<old_user>`),
подключение выполняется к служебной БД `postgres` (`-d postgres`):
1. Пароль:   `scripts/cc.sh exec postgres psql -U "<user>" -d postgres -c "ALTER USER \"<user>\" WITH PASSWORD '<pwd>';"`
2. Имя роли: `scripts/cc.sh exec postgres psql -U "<old_user>" -d postgres -c "ALTER USER \"<old_user>\" RENAME TO \"<new_user>\";"`
3. Имя БД:   `scripts/cc.sh exec postgres psql -U "<user>" -d postgres -c "ALTER DATABASE \"<old_db>\" RENAME TO \"<new_db>\";"`
   (нет активных коннектов; при auth-fail их и нет)
4. Re-init pgdata — последний рубеж (потеря данных; pgdata external, `down -v` не удаляет).

Важно: после первого init фактического тома значения `POSTGRES_*` в `.env` — описание init,
не действующий конфиг; их изменение валидируется только лестницей выше.
Отпечаток пароля в логах migrate-job — только при `MIGRATE_LOG_PWD_FINGERPRINT=1`.