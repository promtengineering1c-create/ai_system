"""Модульные тесты LocalFileSystemStorage: атомарная запись, чтение, удаление и защита от Path Traversal."""

from pathlib import Path

import pytest

from core.interfaces import IStorage
from integrations.storage.local_fs import LocalFileSystemStorage


def test_storage_save_and_load(isolated_storage_dir: Path) -> None:
    storage: IStorage = LocalFileSystemStorage(base_path=isolated_storage_dir)
    test_key = "test_file.bin"
    test_data = b"binary payload content"

    storage.save(test_key, test_data)

    assert storage.exists(test_key) is True
    assert storage.load(test_key) == test_data


def test_storage_delete_existing_file(isolated_storage_dir: Path) -> None:
    storage: IStorage = LocalFileSystemStorage(base_path=isolated_storage_dir)
    test_key = "to_delete.bin"
    storage.save(test_key, b"temp data")

    storage.delete(test_key)

    assert storage.exists(test_key) is False


def test_storage_delete_non_existent_file_does_not_raise(
    isolated_storage_dir: Path,
) -> None:
    storage: IStorage = LocalFileSystemStorage(base_path=isolated_storage_dir)

    storage.delete("missing_file.bin")


def test_storage_load_missing_file_raises_error(
    isolated_storage_dir: Path,
) -> None:
    storage: IStorage = LocalFileSystemStorage(base_path=isolated_storage_dir)

    with pytest.raises(FileNotFoundError):
        storage.load("non_existent.bin")


def test_storage_nested_directories_creation(
    isolated_storage_dir: Path,
) -> None:
    storage: IStorage = LocalFileSystemStorage(base_path=isolated_storage_dir)
    nested_key = "sub_dir/level_2/nested_file.txt"
    test_data = b"nested data"

    storage.save(nested_key, test_data)

    assert storage.exists(nested_key) is True
    assert storage.load(nested_key) == test_data


def test_storage_prevents_path_traversal(isolated_storage_dir: Path) -> None:
    storage: IStorage = LocalFileSystemStorage(base_path=isolated_storage_dir)
    malicious_key = "../outside.txt"

    with pytest.raises(ValueError, match="Key escapes storage root"):
        storage.save(malicious_key, b"exploit")

    with pytest.raises(ValueError, match="Key escapes storage root"):
        storage.load(malicious_key)

    with pytest.raises(ValueError, match="Key escapes storage root"):
        storage.exists(malicious_key)

    with pytest.raises(ValueError, match="Key escapes storage root"):
        storage.delete(malicious_key)


def test_storage_atomic_overwrite(isolated_storage_dir: Path) -> None:
    storage: IStorage = LocalFileSystemStorage(base_path=isolated_storage_dir)
    key = "state.bin"

    storage.save(key, b"version 1")
    storage.save(key, b"version 2")

    assert storage.load(key) == b"version 2"