from app.services.storage_backends.base import StorageBackend

__all__ = ["StorageBackend", "get_backend"]

_backend: StorageBackend | None = None


def get_backend() -> StorageBackend:
    """Returns the process-wide storage backend, built once from the static
    (env-var) `storage_backend` setting on first use."""
    global _backend
    if _backend is None:
        from app.core.config import settings

        if settings.storage_backend == "s3":
            from app.services.storage_backends.s3 import S3Backend

            _backend = S3Backend()
        else:
            from app.services.storage_backends.local import LocalDiskBackend

            _backend = LocalDiskBackend()
    return _backend
