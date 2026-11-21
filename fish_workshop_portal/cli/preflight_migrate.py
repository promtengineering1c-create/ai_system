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

_CONN_MARKERS = (
    "could not connect",
    "connection refused",
    "could not translate host name",
    "failed to resolve host",
    "name or service not known",
    "timeout expired",
)

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
    if any(marker in msg for marker in _CONN_MARKERS):
        return "postgres недоступен: проверь healthcheck (pg_isready), DNS и сеть backend."
    return None

def _resolve_target(want_fp: bool) -> tuple[str, str, str, str | None]:
    host = os.environ.get("DB_HOST")
    db = os.environ.get("DB_NAME")
    user = os.environ.get("DB_USER")
    pwd = os.environ.get("DB_PASSWORD") if want_fp else None

    if None in (host, db, user) or (want_fp and pwd is None):
        try:
            from config.env import DatabaseSettings

            cfg = DatabaseSettings()
            host = host or cfg.host
            db = db or cfg.name
            user = user or cfg.user
            if want_fp and pwd is None:
                pwd = cfg.password.get_secret_value()
        except Exception:
            pass

    return host or "?", db or "?", user or "?", pwd

def main() -> int:
    want_fp = os.environ.get(PWD_FP_FLAG) == "1"
    host, db, user, pwd = _resolve_target(want_fp)
    line = f"migrate target: host={host} db={db} user={user}"
    
    if want_fp:
        fp = (
            hashlib.sha256(pwd.encode()).hexdigest()[:8]
            if pwd is not None
            else "<unset>"
        )
        line += f" pwd_sha256_8={fp}"

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