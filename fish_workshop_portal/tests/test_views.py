"""Интеграционные тесты главной страницы витрины и эндпоинта скачивания прайса (/price/download/)."""

from pathlib import Path
from unittest.mock import patch

from django.test import Client
import pytest

from config import settings
from integrations.storage.local_fs import LocalFileSystemStorage


@pytest.fixture
def client() -> Client:
    return Client()


def test_index_view_renders_download_button_when_price_exists(
    client: Client,
    tmp_path: Path,
) -> None:
    storage = LocalFileSystemStorage(base_path=tmp_path)
    storage.save(settings.PRICE_XLSX_FILENAME, b"price content")

    with patch("config.container.get_storage", return_value=storage):
        response = client.get("/")

    assert response.status_code == 200
    assert response.context["price_available"] is True
    assert "/price/download/" in response.content.decode("utf-8")


def test_index_view_hides_download_button_when_price_missing(
    client: Client,
    tmp_path: Path,
) -> None:
    storage = LocalFileSystemStorage(base_path=tmp_path)

    with patch("config.container.get_storage", return_value=storage):
        response = client.get("/")

    assert response.status_code == 200
    assert response.context["price_available"] is False


def test_price_download_view_success(
    client: Client,
    tmp_path: Path,
) -> None:
    storage = LocalFileSystemStorage(base_path=tmp_path)
    content = b"fake binary xlsx content"
    storage.save(settings.PRICE_XLSX_FILENAME, content)

    with patch("config.container.get_storage", return_value=storage):
        response = client.get("/price/download/")

    assert response.status_code == 200
    assert (
        response["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert (
        response["Content-Disposition"]
        == f'attachment; filename="{settings.PRICE_XLSX_FILENAME}"'
    )
    assert b"".join(response.streaming_content) == content


def test_price_download_view_returns_404_when_missing(
    client: Client,
    tmp_path: Path,
) -> None:
    storage = LocalFileSystemStorage(base_path=tmp_path)

    with patch("config.container.get_storage", return_value=storage):
        response = client.get("/price/download/")

    assert response.status_code == 404