import os
from contextlib import AbstractContextManager
from typing import BinaryIO

from app.services.storage_backends.base import StorageBackend


class LocalDiskBackend(StorageBackend):
    """Default backend - behavior-identical to the app's original,
    filesystem-only storage_service. Storage directory is the *dynamic*
    (DB-backed, admin-editable) `storage_path` setting."""

    def _dir(self) -> str:
        from app.core.dynamic_settings import get_settings

        path = get_settings()["storage_path"]
        os.makedirs(path, exist_ok=True)
        return path

    def save(self, tmp_path: str) -> tuple[str, int]:
        import secrets

        filename = secrets.token_hex(32)
        dest = os.path.join(self._dir(), filename)
        os.replace(tmp_path, dest)
        return filename, os.path.getsize(dest)

    def open_read(self, storage_filename: str) -> AbstractContextManager[BinaryIO]:
        return open(os.path.join(self._dir(), storage_filename), "rb")

    def delete(self, storage_filename: str) -> None:
        path = os.path.join(self._dir(), storage_filename)
        if os.path.exists(path):
            os.remove(path)

    def usage_bytes(self) -> int:
        total = 0
        for entry in os.scandir(self._dir()):
            if entry.is_file():
                total += entry.stat().st_size
        return total
