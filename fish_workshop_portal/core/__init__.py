"""
Пакет ядра системы (core).
Содержит базовые переиспользуемые абстракции, иерархию доменных исключений,
протоколы/ABC-интерфейсы для внешних зависимостей и примитивы безопасности.
Слой полностью изолирован от бизнес-логики и инфраструктуры фреймворка.
"""

from .exceptions import FishWorkshopError, PriceNotAvailableError
from .interfaces import IStorage

__all__ = [
    "FishWorkshopError",
    "PriceNotAvailableError",
    "IStorage",
]