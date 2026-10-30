"""
Легковесный DI-контейнер для сборки сервисов с внедрением конкретных реализаций репозиториев, хранилища, капчи и шлюзов из настроек AppConfig.
"""

from functools import lru_cache

from django.conf import settings

from core.interfaces import IStorage
from integrations.storage.local_fs import LocalFileSystemStorage


@lru_cache(maxsize=1)
def get_storage() -> IStorage:
    return LocalFileSystemStorage(base_path=settings.STORAGE_CACHE_DIR)


# TBD(depends: stages 4-7 adapters): factory functions for IXlsxRenderer, IRateLimiter, ICaptchaProvider, IMailer, IExchangeGateway