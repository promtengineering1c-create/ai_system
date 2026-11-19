"""
Маршруты публичной витрины, скачивания/отправки прайса, 3-шаговой регистрации-подписки, входа, сброса пароля по Email и отписки.
"""

from django.urls import path

from web import views

app_name = "web"

urlpatterns = [
    path("", views.IndexView.as_view(), name="index"),
    path("price/download/", views.price_download_view, name="price_download"),
    
    # TBD(depends: stages 7-8): Маршруты 3-шаговой регистрации, подписки, входа, 
    # сброса пароля и отписки будут добавлены при реализации account_service 
    # и subscription_service.
]

