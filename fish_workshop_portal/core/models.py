"""
Абстрактные базовые модели Django с автоматическими штампами времени created_at и updated_at.
"""

from django.db import models


class TimeStampedModel(models.Model):
    """Абстрактная модель с временными метками создания и обновления записи."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


