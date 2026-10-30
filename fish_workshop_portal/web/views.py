"""
Тонкие контроллеры витрины и клиентского контура: рендеринг каталога, обработка HTMX-шагов регистрации/подписки, подтверждение Email, сброс пароля и отдача .xlsx.
"""

import io
from typing import Any

from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest
from django.views.generic import TemplateView

from config.container import get_storage


class IndexView(TemplateView):
    template_name = "web/index.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        storage = get_storage()
        # Условное отображение кнопки скачивания на главной
        context["has_price"] = storage.exists(settings.PRICE_XLSX_FILENAME)
        
        # TBD(depends: stage 2-3): Каталог товаров, штамп CatalogSyncMeta 
        # и график MobileTradeSchedule будут добавлены в контекст позже.
        return context


def price_download_view(request: HttpRequest) -> FileResponse:
    """
    Тонкий контроллер прямой отдачи актуального кэша прайса.
    """
    storage = get_storage()
    if not storage.exists(settings.PRICE_XLSX_FILENAME):
        raise Http404("Прайс-лист временно недоступен или находится в процессе сборки.")

    data = storage.load(settings.PRICE_XLSX_FILENAME)
    
    return FileResponse(
        io.BytesIO(data),
        as_attachment=True,
        filename="price_list.xlsx",
    )

# TBD(depends: stages 7-8): Контроллеры разовой отправки прайса на Email (HTMX),
# 3-шагового онбординга подписки, регистрации, входа и сброса пароля будут 
# реализованы по мере внедрения account_service и subscription_service.

