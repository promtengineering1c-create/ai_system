"""Self-test L2 чекера (ADR-011): фиксирует семантику на текущей версии рендера.

Compose пиннен >= 2.24; тесты защищают логику чекера от регрессий при апгрейде CLI.
"""
import json
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "render_check.py"


def _render(pg_db, pg_user, pg_pwd, app_db, app_user, app_pwd) -> str:
    app_env = {
        "DB_NAME": app_db,
        "DB_USER": app_user,
        "DB_PASSWORD": app_pwd,
    }
    cfg = {
        "services": {
            "postgres": {
                "environment": {
                    "POSTGRES_DB": pg_db,
                    "POSTGRES_USER": pg_user,
                    "POSTGRES_PASSWORD": pg_pwd,
                }
            },
            "web": {"environment": dict(app_env)},
            "worker": {"environment": dict(app_env)},
            "migrate-job": {"environment": dict(app_env)},
        }
    }
    return json.dumps(cfg)


def test_matching_render_passes():
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=_render("db", "user", "pwd", "db", "user", "pwd"),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr


def test_diverged_password_fails():
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=_render("db", "user", "pwd", "db", "user", "OTHER"),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1
    assert "mapping diverged in compose: postgres.POSTGRES_PASSWORD != web.DB_PASSWORD" in r.stderr
    assert "mapping diverged in compose: postgres.POSTGRES_PASSWORD != worker.DB_PASSWORD" in r.stderr
    assert "mapping diverged in compose: postgres.POSTGRES_PASSWORD != migrate-job.DB_PASSWORD" in r.stderr


def test_missing_mapping_fails():
    # регрессия compose-файла: у сервиса удалена строка маппинга
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps({"services": {"postgres": {"environment": {"POSTGRES_DB": "d"}}}}),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1


def test_broken_render_exit_2():
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="not json",
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2