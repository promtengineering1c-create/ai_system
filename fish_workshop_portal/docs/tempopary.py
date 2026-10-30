"""
Composition Root: сборка инфраструктурных зависимостей.

Этап 1 — единственный провайдер: IStorage для runtime-кэша прайса.
Провайдеры последующих этапов (IXlsxRenderer, IRateLimiter, ICaptchaProvider,
IMailer, IExchangeGateway) добавляются сюда по мере создания их адаптеров.

Сброс кэша в тестах: `get_storage.cache_clear()` после monkeypatch
`config.settings.STORAGE_CACHE_DIR`.
"""

from functools import lru_cache

from config import settings as project_settings
from core.interfaces import IStorage
from integrations.storage.local_fs import LocalFileSystemStorage


@lru_cache(maxsize=1)
def get_storage() -> IStorage:
    """Возвращает синглтон файлового хранилища runtime-кэша прайса."""
    return LocalFileSystemStorage(project_settings.STORAGE_CACHE_DIR)