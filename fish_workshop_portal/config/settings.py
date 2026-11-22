"""
Настройки Django, инициализируемые строго из типизированного объекта AppConfig без прямых вызовов os.getenv.
"""
from config.env import BASE_DIR, get_settings

config = get_settings()

SECRET_KEY = config.django.secret_key.get_secret_value()
DEBUG = config.django.debug
_EXTRA_HOSTS = ["127.0.0.1", "localhost"] if DEBUG else ["127.0.0.1"]
ALLOWED_HOSTS = list(
    dict.fromkeys([*config.django.allowed_hosts, *_EXTRA_HOSTS])
)

# stub: remaining db.* and cli apps are registered in Stages 2-7 when their packages are created
LOCAL_APPS = [
    "db.users.apps.UsersConfig",
    "web.apps.WebConfig",
]

# runserver_nostatic must precede staticfiles so WhiteNoise serves static in dev only
THIRD_PARTY_APPS = (
    ["whitenoise.runserver_nostatic", "django.contrib.staticfiles"]
    if DEBUG
    else ["django.contrib.staticfiles"]
)

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
]

INSTALLED_APPS = LOCAL_APPS + THIRD_PARTY_APPS + DJANGO_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    *(["whitenoise.middleware.WhiteNoiseMiddleware"] if DEBUG else []),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Framing контролирует Nginx через CSP frame-ancestors (nginx/nginx.conf);
    # XFrameOptionsMiddleware отключён: X_FRAME_OPTIONS="" в Django отдаёт пустой заголовок.
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "web" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": config.db.host,
        "PORT": config.db.port,
        "NAME": config.db.name,
        "USER": config.db.user,
        "PASSWORD": config.db.password.get_secret_value(),
        "CONN_MAX_AGE": config.db.conn_max_age,
        "CONN_HEALTH_CHECKS": True,
    }
}

# Reverse proxy (Nginx TLS termination, ADR-008) & session/CSRF invariants
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# HSTS и редирект 80->443 держит Nginx; SECURE_SSL_REDIRECT сломал бы /healthz/ по HTTP
SECURE_HSTS_SECONDS = 0
SECURE_SSL_REDIRECT = False
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
# На Этапе 1 держим Lax; пересмотр под cross-site iframe (SameSite=None) — только на Этапе 10 (MAX Mini App).
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
if not DEBUG:
    CSRF_TRUSTED_ORIGINS = list(
        dict.fromkeys(
            origin
            for host in config.django.allowed_hosts
            if host not in ("127.0.0.1", "localhost", "*", ".")
            for origin in (
                (f"https://{host[1:]}", f"https://*{host}")
                if host.startswith(".")
                else (f"https://{host}",)
            )
        )
    )
 
AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "ru-RU"
TIME_ZONE = "Asia/Yekaterinburg"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

if DEBUG:
    # plain storage in dev/tests avoids requiring collectstatic manifest before pytest runs
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

PRICE_TEMPLATE_PATH = (
    BASE_DIR / "assets" / "templates_xlsx" / "price_master_template.xlsx"
)
STORAGE_CACHE_DIR = config.django.storage_cache_dir
PRICE_XLSX_FILENAME = "price.xlsx"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "loggers": {
        "django": {
            "handlers": [],
            "level": "INFO",
            "propagate": True,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}