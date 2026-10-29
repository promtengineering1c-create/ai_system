"""
Протоколы и ABC-интерфейсы для внешних зависимостей: IStorage (save/load/delete), ICaptchaProvider, IMailer, IExchangeGateway, IChannelAdapter (задел под бот MAX в Релизе 1.2).
"""

from abc import ABC, abstractmethod


class IStorage(ABC):
    """
    Интерфейс абстрактного хранилища (ключ-значение).
    Изолирует бизнес-логику от конкретной реализации (локальная ФС, S3).
    """

    @abstractmethod
    def save(self, key: str, data: bytes) -> None:
        """Сохраняет бинарные данные по указанному ключу (атомарно)."""

    @abstractmethod
    def load(self, key: str) -> bytes:
        """Читает и возвращает бинарные данные по ключу."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Удаляет данные по ключу (без ошибок, если ключа нет)."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Проверяет физическое наличие данных по ключу."""
