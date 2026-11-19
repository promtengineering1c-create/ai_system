"""
Фикстуры pytest: тестовый контейнер зависимостей со StubCaptchaProvider, временным хранилищем и тестовой БД.
"""

from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import SecretStr

from config.container import get_storage
from config.env import (
    AppConfig,
    CaptchaSettings,
    DatabaseSettings,
    DjangoSettings,
    ExchangeSettings,
    RedisSettings,
    SecuritySettings,
    SmtpSettings,
)
from core.interfaces import IStorage
from integrations.storage.local_fs import LocalFileSystemStorage


@pytest.fixture(autouse=True)
def reset_container_cache() -> Generator[None, None, None]:
    get_storage.cache_clear()
    yield
    get_storage.cache_clear()


@pytest.fixture
def isolated_storage_dir(tmp_path: Path) -> Path:
    storage_path = tmp_path / "storage"
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path


@pytest.fixture
def test_storage(isolated_storage_dir: Path) -> IStorage:
    return LocalFileSystemStorage(base_path=isolated_storage_dir)


@pytest.fixture
def test_app_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        base_dir=tmp_path,
        django=DjangoSettings(
            secret_key=SecretStr("test-secret-key-for-testing-only-12345"),
            debug=True,
            allowed_hosts=["testserver", "localhost"],
            _env_file=(),
        ),
        db=DatabaseSettings(
            host="localhost",
            port=5432,
            name="test_db",
            user="test_user",
            password=SecretStr("test_password"),
            _env_file=(),
        ),
        redis=RedisSettings(
            url="redis://localhost:6379/0",
            _env_file=(),
        ),
        security=SecuritySettings(
            api_token=SecretStr("test-bearer-token-12345"),
            rate_limit_per_minute=100,
            _env_file=(),
        ),
        exchange=ExchangeSettings(
            base_dir=tmp_path / "exchange",
            node_1c="1C",
            node_web="WEB",
            poll_interval=1,
            _env_file=(),
        ),
        captcha=CaptchaSettings(
            provider="stub",
            _env_file=(),
        ),
        smtp=SmtpSettings(
            host="localhost",
            port=1025,
            user="test_mailer",
            password=SecretStr("test_smtp_password"),
            use_tls=False,
            use_ssl=False,
            default_from="noreply@test.local",
            _env_file=(),
        ),
    )

