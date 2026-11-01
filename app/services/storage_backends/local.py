import os
from contextlib import AbstractContextManager
from typing import BinaryIO

from app.services.storage_backends.base import StorageBackend

LEGACY_DEFAULT_STORAGE_PATH = "./storage/encrypted"


class LocalDiskBackend(StorageBackend):
    """Default backend: blobs on local disk.

    The directory comes from RATATOSK_STORAGE_ROOT (env-only, SEC-010). For
    installs that changed the old admin-panel `storage_path` setting before it
    became read-only, that saved value is still honoured unless the env var is
    set explicitly - so upgrading never orphans existing files."""

    def _dir(self) -> str:
        from app.core.config import settings, storage_root_explicit

        path = settings.storage_root
        if not storage_root_explicit:
            from app.core.dynamic_settings import get_settings

            legacy = get_settings().get("storage_path")
            if legacy and legacy != LEGACY_DEFAULT_STORAGE_PATH:
                path = legacy
        os.makedirs(path, exist_ok=True)
        return path

    def _path(self, storage_filename: str) -> str:
        # Blob names are always 64 hex chars we generated; refuse anything
        # else so a corrupted row can never address a path outside the dir.
        if len(storage_filename) != 64 or any(c not in "0123456789abcdef" for c in storage_filename):
            raise ValueError("invalid storage filename")
        return os.path.join(self._dir(), storage_filename)

    def save(self, tmp_path: str) -> tuple[str, int]:
        import secrets

        filename = secrets.token_hex(32)
        dest = os.path.join(self._dir(), filename)
        os.replace(tmp_path, dest)
        return filename, os.path.getsize(dest)

    def open_read(self, storage_filename: str) -> AbstractContextManager[BinaryIO]:
        return open(self._path(storage_filename), "rb")

    def delete(self, storage_filename: str) -> None:
        path = self._path(storage_filename)
        if os.path.exists(path):
            os.remove(path)

    def usage_bytes(self) -> int:
        total = 0
        for entry in os.scandir(self._dir()):
            if entry.is_file():
                total += entry.stat().st_size
        return total
