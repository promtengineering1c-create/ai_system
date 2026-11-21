"""
Кастомная модель User (email как USERNAME_FIELD, хэш пароля, опциональные phone, max_user_id, флаг is_verified_b2b по ADR-005, статус подписки, штамп согласия по 152-ФЗ/ФЗ-38 и JSONField анкеты по ADR-003).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.db.models.functions import Lower

from core.models import TimeStampedModel


class UserManager(BaseUserManager):
    """Менеджер пользователей с регистронезависимой нормализацией Email."""

    @classmethod
    def normalize_email(cls, email: str | None) -> str:
        return (email or "").strip().lower()

    def get_by_natural_key(self, username: str | None) -> User:
        return self.get(
            **{self.model.USERNAME_FIELD: self.normalize_email(username)}
        )

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            raise ValueError("Email обязателен.")
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self.model(email=normalized_email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Суперпользователь должен иметь is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Суперпользователь должен иметь is_superuser=True.")
        if not password:
            raise ValueError("Пароль обязателен для суперпользователя.")

        return self.create_user(email=email, password=password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Минимальный каркас учетной записи; бизнес-атрибуты добавляются на Этапах 2-8."""

    email = models.EmailField("Email", unique=True)
    is_active = models.BooleanField("Активен", default=True)
    is_staff = models.BooleanField("Доступ в админку", default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="users_user_email_ci_uniq",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.email = UserManager.normalize_email(self.email)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.email:
            self.email = UserManager.normalize_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email

