"""
Инфраструктурный пакет конфигурации Django и параметров среды (config).
Инициализирует каскадную загрузку переменных окружения через pydantic-settings
и экспортирует единый синглтон-агрегатор конфигурации AppConfig.
"""

from .env import AppConfig, get_settings

__all__ = ["AppConfig", "get_settings"]