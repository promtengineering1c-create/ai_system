"""
Корневой роутер URL: монтирование публичной витрины и контура авторизации/подписки (web), эндпоинта Django Ninja (/api/v1/exchange/) и административной панели.
"""

from django.contrib import admin
from django.urls import include, path

# stub: /api/v1/exchange/ router is mounted in Stage 4 when api package is created
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("web.urls")),
]

