"""L3: миграционный префлайт и диагностика кредов (команда migrate-job, ADR-011).

Запускается вместо `manage.py migrate --noinput`:
1) логирует resolved target (host/db/user) до инициализации Django; отпечаток пароля —
   только за флагом MIGRATE_LOG_PWD_FINGERPRINT=1 (корреляция версий пароля при ротации;
   по умолчанию производные пароля в логи не пишутся).
2) на OperationalError печатает hint с recovery-лестницей в stderr и выходит 1.

Ключевой кейс, непокрываемый проверками равенства источников: init-only семантика
официального postgres-образа — POSTGRES_* применяется только при первом init пустого
pgdata. Ротация кредов при существующем external-томе даёт зелёные L0/L1/L2 и красный
auth; ловится только здесь.
"""
import hashlib
import os
import sys

PWD_FP_FLAG = "MIGRATE_LOG_PWD_FINGERPRINT"


def _hint_for(msg: str, user: str, db: str) -> str | None:
    if "password authentication failed" in msg:
        return (
            "password mismatch: L1/L2 зелёные -> источники согласованы; вероятный корень — init-only pgdata:\n"
            "  POSTGRES_* применяется ТОЛЬКО при первом init пустого тома.\n"
            f"  recovery: scripts/cc.sh exec postgres psql -U \"{user}\" -d postgres -c \\\n"
            f"    \"ALTER USER \\\"{user}\\\" WITH PASSWORD '<DB_PASSWORD>';\"  # значения из базового .env\n"
            "  также проверь: в .env.{APP_ENV} нет DB_NAME/DB_USER/DB_PASSWORD/POSTGRES_* (закрывает cc.sh)."
        )
    if "database" in msg and "does not exist" in msg:
        return (
            "DB_NAME vs POSTGRES_DB: расхождение источников или переименование при старом томе (init-only).\n"
            f"  recovery: scripts/cc.sh exec postgres psql -U \"{user}\" -d postgres -c "
            f"'ALTER DATABASE \"<old_db>\" RENAME TO \"{db}\";'\n"
            "  (активных коннектов быть не должно; app и так не подключается). Последний рубеж: re-init pgdata."
        )
    if "role" in msg and "does not exist" in msg:
        return (
            "DB_USER vs POSTGRES_USER: расхождение источников или переименование при старом томе (init-only).\n"
            "  recovery: scripts/cc.sh exec postgres psql -U \"<old_user>\" -d postgres -c "
            f"'ALTER USER \"<old_user>\" RENAME TO \"{user}\";'\n"
            "  Последний рубеж: re-init pgdata."
        )
    if "could not connect" in msg or "connection refused" in msg:
        return "postgres недоступен: проверь healthcheck (pg_isready) и сеть backend."
    return None


def main() -> int:
    host = os.environ.get("DB_HOST", "?")
    db = os.environ.get("DB_NAME", "?")
    user = os.environ.get("DB_USER", "?")
    line = f"migrate target: host={host} db={db} user={user}"
    if os.environ.get(PWD_FP_FLAG) == "1":
        pwd = os.environ.get("DB_PASSWORD", "")
        line += f" pwd_sha256_8={hashlib.sha256(pwd.encode()).hexdigest()[:8]}"
    print(line, file=sys.stderr)

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

    from django.core.management import call_command
    from django.db import OperationalError

    try:
        call_command("migrate", interactive=False)
    except OperationalError as exc:
        print(f"migrate failed: {exc}", file=sys.stderr)
        hint = _hint_for(str(exc).lower(), user=user, db=db)
        if hint:
            print(hint, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())