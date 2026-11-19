"""
Каскадная загрузка окружения (.env.development / .env) и изолированные классы BaseSettings с env_prefix (DatabaseSettings, RedisSettings, SecuritySettings, ExchangeSettings, CaptchaSettings, SmtpSettings), объединенные в агрегатор AppConfig.
"""

from functools import lru_cache
import os
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BeforeValidator,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
_ALLOWED_ENV_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)

NonEmptyStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
NonEmptySecretStr = Annotated[
    SecretStr,
    # strip before SecretStr wraps value so Field(min_length=1) catches whitespace-only secrets
    BeforeValidator(
        lambda v: v.get_secret_value().strip()
        if isinstance(v, SecretStr)
        else (v.strip() if isinstance(v, str) else v)
    ),
    Field(min_length=1),
]
Port = Annotated[int, Field(ge=1, le=65535)]


class _BaseDomainSettings(BaseSettings):
    """Базовый неизменяемый класс доменных настроек с динамическим подключением .env."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
        frozen=True,
    )

    def __init__(self, **values: Any) -> None:
        if "_env_file" not in values:
            values["_env_file"] = _env_files()
        super().__init__(**values)


class DjangoSettings(_BaseDomainSettings):
    model_config = SettingsConfigDict(env_prefix="DJANGO__")

    secret_key: NonEmptySecretStr
    debug: bool = False
    allowed_hosts: list[NonEmptyStr] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"]
    )


class DatabaseSettings(_BaseDomainSettings):
    model_config = SettingsConfigDict(env_prefix="DB_")

    host: NonEmptyStr
    port: Port = 5432
    name: NonEmptyStr
    user: NonEmptyStr
    password: NonEmptySecretStr
    conn_max_age: Annotated[int, Field(ge=0)] | None = 60


class RedisSettings(_BaseDomainSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: NonEmptyStr = Field(repr=False)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = parsed.port
            if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
                raise ValueError
            if port is not None and not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            raise ValueError(
                "REDIS_URL must be a redis:// or rediss:// URL with a valid host and port"
            ) from None
        return value


class SecuritySettings(_BaseDomainSettings):
    model_config = SettingsConfigDict(env_prefix="SECURITY_")

    api_token: NonEmptySecretStr
    rate_limit_per_minute: Annotated[int, Field(gt=0)] = 60


class ExchangeSettings(_BaseDomainSettings):
    model_config = SettingsConfigDict(env_prefix="EXCHANGE_")

    base_dir: Path = BASE_DIR / "exchange"
    node_1c: NonEmptyStr = "1C"
    node_web: NonEmptyStr = "WEB"
    poll_interval: Annotated[int, Field(gt=0)] = 5

    @model_validator(mode="after")
    def validate_nodes(self) -> "ExchangeSettings":
        # casefold prevents collisions on case-insensitive filesystems in /exchange/
        if self.node_1c.casefold() == self.node_web.casefold():
            raise ValueError("Exchange nodes must have different identifiers")
        return self


class CaptchaSettings(_BaseDomainSettings):
    model_config = SettingsConfigDict(env_prefix="CAPTCHA_")

    provider: Literal["stub", "yandex"] = "stub"
    secret_key: SecretStr = SecretStr("")
    client_key: str = ""
    verify_url: str = "https://smartcaptcha.yandexcloud.net/validate"

    @model_validator(mode="after")
    def validate_yandex(self) -> "CaptchaSettings":
        if self.provider == "yandex":
            if (
                not self.secret_key.get_secret_value().strip()
                or not self.client_key.strip()
            ):
                raise ValueError(
                    "Yandex captcha requires CAPTCHA_SECRET_KEY and CAPTCHA_CLIENT_KEY"
                )
            try:
                parsed = urlsplit(self.verify_url)
                if parsed.scheme != "https" or not parsed.hostname:
                    raise ValueError
                _ = parsed.port
            except ValueError:
                raise ValueError("CAPTCHA_VERIFY_URL must be a valid HTTPS URL") from None
        return self


class SmtpSettings(_BaseDomainSettings):
    model_config = SettingsConfigDict(env_prefix="SMTP_")

    host: NonEmptyStr
    port: Port = 465
    user: NonEmptyStr
    password: NonEmptySecretStr
    use_tls: bool = False
    use_ssl: bool = True
    default_from: NonEmptyStr
    timeout: Annotated[float, Field(gt=0)] = 10.0

    @model_validator(mode="after")
    def validate_encryption(self) -> "SmtpSettings":
        if self.use_tls and self.use_ssl:
            raise ValueError("SMTP_USE_TLS and SMTP_USE_SSL are mutually exclusive")
        # guard only swapped standard ports; allow custom ports (e.g. 1025/2525)
        if (self.use_ssl and self.port == 587) or (self.use_tls and self.port == 465):
            raise ValueError(
                f"Port {self.port} conflicts with selected encryption mode (SSL/TLS)"
            )
        return self


class AppConfig:
    """Неизменяемый агрегатор доменных конфигураций с однократным разрешением каскада .env."""

    __slots__ = (
        "django",
        "db",
        "redis",
        "security",
        "exchange",
        "captcha",
        "smtp",
    )

    def __init__(
        self,
        *,
        base_dir: Path = BASE_DIR,
        django: DjangoSettings | None = None,
        db: DatabaseSettings | None = None,
        redis: RedisSettings | None = None,
        security: SecuritySettings | None = None,
        exchange: ExchangeSettings | None = None,
        captcha: CaptchaSettings | None = None,
        smtp: SmtpSettings | None = None,
    ) -> None:
        env_files = _env_files(base_dir)
        object.__setattr__(
            self,
            "django",
            django if django is not None else DjangoSettings(_env_file=env_files),
        )
        object.__setattr__(
            self,
            "db",
            db if db is not None else DatabaseSettings(_env_file=env_files),
        )
        object.__setattr__(
            self,
            "redis",
            redis if redis is not None else RedisSettings(_env_file=env_files),
        )
        object.__setattr__(
            self,
            "security",
            security if security is not None else SecuritySettings(_env_file=env_files),
        )
        object.__setattr__(
            self,
            "exchange",
            exchange if exchange is not None else ExchangeSettings(_env_file=env_files),
        )
        object.__setattr__(
            self,
            "captcha",
            captcha if captcha is not None else CaptchaSettings(_env_file=env_files),
        )
        object.__setattr__(
            self,
            "smtp",
            smtp if smtp is not None else SmtpSettings(_env_file=env_files),
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("AppConfig is immutable")


def _env_files(base_dir: Path = BASE_DIR) -> tuple[Path, ...]:
    """Возвращает существующие файлы каскада (.env, .env.{APP_ENV}) с защитой от Path Traversal."""
    app_env = os.getenv("APP_ENV", "development")
    if not app_env or any(c not in _ALLOWED_ENV_CHARS for c in app_env):
        raise ValueError("APP_ENV must contain only ASCII letters, digits, '_' or '-'")
    return tuple(
        path
        for path in (base_dir / ".env", base_dir / f".env.{app_env}")
        if path.is_file()
    )


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    """Возвращает кэшированный синглтон конфигурации процесса."""
    return AppConfig()