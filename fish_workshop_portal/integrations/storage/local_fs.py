"""
Реализация интерфейса IStorage (save/load/delete/exists) поверх локальной
файловой системы с атомарной перезаписью через временный файл.
"""

import os
import tempfile
from pathlib import Path

from core.interfaces import IStorage


class LocalFileSystemStorage(IStorage):
    """
    Изолированное файловое хранилище внутри корневой директории base_path.
    Обеспечивает защиту от Path Traversal и атомарную запись через os.replace.
    """

    def __init__(self, base_path: str | Path, file_mode: int = 0o644) -> None:
        self._base_path = Path(base_path).resolve()
        self._base_path.mkdir(parents=True, exist_ok=True)
        self._file_mode = file_mode

    def _resolve(self, key: str) -> Path:
        resolved = (self._base_path / key).resolve()
        if not resolved.is_relative_to(self._base_path):
            raise ValueError(f"Key escapes storage root: {key!r}")
        return resolved

    def save(self, key: str, data: bytes) -> None:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
        fd_closed = False
        try:
            with os.fdopen(fd, "wb") as fh:
                fd_closed = True
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp_name, self._file_mode)
            os.replace(tmp_name, target)
        except BaseException:
            if not fd_closed:
                os.close(fd)
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def load(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()