"""
Конфигурация Django-приложения db.users.
"""

from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "db.users"
    label = "users"
    verbose_name = "Пользователи"

