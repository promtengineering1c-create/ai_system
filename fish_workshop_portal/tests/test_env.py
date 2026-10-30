from pathlib import Path

import pytest
from pydantic import ValidationError

from config.env import (
    AppConfig,
    CaptchaSettings,
    DatabaseSettings,
    DjangoSettings,
    ExchangeSettings,
    RedisSettings,
    SecuritySettings,
    SmtpSettings,
    _env_files,
)


def test_env_files_cascade_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_env = tmp_path / ".env"
    dev_env = tmp_path / ".env.development"
    base_env.write_text("DJANGO__DEBUG=False\n", encoding="utf-8")
    dev_env.write_text("DJANGO__DEBUG=True\n", encoding="utf-8")

    monkeypatch.setenv("APP_ENV", "development")
    files = _env_files(base_dir=tmp_path)

    assert files == (base_env, dev_env)


def test_env_files_path_traversal_protection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "../etc/passwd")

    with pytest.raises(ValueError, match="APP_ENV must contain only ASCII letters"):
        _env_files()


def test_django_settings_whitespace_secret_rejected(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DJANGO__SECRET_KEY=   \n", encoding="utf-8")

    with pytest.raises(ValidationError):
        DjangoSettings(_env_file=(env_file,))


def test_database_settings_invalid_port(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DB_HOST=localhost\nDB_PORT=70000\nDB_NAME=test\nDB_USER=test\nDB_PASSWORD=secret\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        DatabaseSettings(_env_file=(env_file,))


def test_redis_settings_valid_and_invalid_urls(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("REDIS_URL=http://localhost:6379\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        RedisSettings(_env_file=(env_file,))

    valid_settings = RedisSettings(url="redis://localhost:6379/0", _env_file=())
    assert valid_settings.url == "redis://localhost:6379/0"


def test_exchange_settings_rejects_identical_nodes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EXCHANGE_NODE_1C=SYNC\nEXCHANGE_NODE_WEB=sync\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="Exchange nodes must have different identifiers"):
        ExchangeSettings(_env_file=(env_file,))


def test_captcha_settings_yandex_validation() -> None:
    with pytest.raises(
        ValidationError,
        match="Yandex captcha requires CAPTCHA_SECRET_KEY and CAPTCHA_CLIENT_KEY",
    ):
        CaptchaSettings(provider="yandex", _env_file=())


def test_smtp_settings_encryption_conflict() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        SmtpSettings(
            host="smtp.example.com",
            port=465,
            user="user",
            password="pwd",
            use_tls=True,
            use_ssl=True,
            default_from="test@example.com",
            _env_file=(),
        )

    with pytest.raises(ValidationError, match="conflicts with selected encryption mode"):
        SmtpSettings(
            host="smtp.example.com",
            port=587,
            user="user",
            password="pwd",
            use_tls=False,
            use_ssl=True,
            default_from="test@example.com",
            _env_file=(),
        )


def test_app_config_immutability(test_app_config: AppConfig) -> None:
    with pytest.raises(AttributeError, match="AppConfig is immutable"):
        test_app_config.django = None