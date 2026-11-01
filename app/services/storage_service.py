import os
from contextlib import AbstractContextManager
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dynamic_settings import get_settings
from app.services.storage_backends import get_backend


def tmp_dir() -> str:
    from app.core.config import settings as static_settings

    os.makedirs(static_settings.tmp_root, exist_ok=True)
    return static_settings.tmp_root


def tmp_path_for(upload_id: str) -> str:
    # Chunked-upload staging always happens on local disk regardless of the
    # configured storage backend - only the finished object is handed to the
    # backend, in finalize_blob() below.
    safe_id = "".join(c for c in upload_id if c.isalnum() or c == "-")
    return os.path.join(tmp_dir(), f"{safe_id}.part")


def used_bytes(db: Session) -> int:
    """Bytes stored plus bytes reserved by uploads still in progress.

    Computed from the database (indexed aggregate) instead of listing every
    blob on disk or every object in the S3 bucket on each upload (PERF-001).
    In-progress reservations are included so parallel uploads can't each
    pass the capacity check and overcommit storage together (SEC-011)."""
    from app.models.file import FileObject
    from app.models.upload_session import UploadSession

    stored = db.execute(
        select(func.coalesce(func.sum(FileObject.size_bytes), 0)).where(FileObject.is_deleted == False)  # noqa: E712
    ).scalar_one()
    reserved = db.execute(select(func.coalesce(func.sum(UploadSession.declared_size), 0))).scalar_one()
    return int(stored) + int(reserved)


def has_capacity(db: Session, additional_bytes: int) -> bool:
    cfg = get_settings()
    cap_bytes = int(cfg["total_storage_cap_gb"]) * 1024 * 1024 * 1024
    return (used_bytes(db) + additional_bytes) <= cap_bytes * 0.95


def get_storage_usage_bytes() -> int:
    """Actual backend usage (slow: lists storage). For reconciliation only."""
    return get_backend().usage_bytes()


def finalize_blob(tmp_path: str) -> tuple[str, int]:
    return get_backend().save(tmp_path)


def delete_blob(storage_filename: str) -> None:
    get_backend().delete(storage_filename)


def open_blob(storage_filename: str) -> AbstractContextManager[BinaryIO]:
    return get_backend().open_read(storage_filename)


def clear_blobs(storage_filenames: list[str]) -> None:
    """Deletes the given blobs plus every staged upload part - used by the
    admin factory reset. Only blobs the database knows about are touched, so
    a reset can never delete unrelated files (SEC-010: it used to remove
    *everything* in the storage directory, which was admin-editable)."""
    backend = get_backend()
    for name in storage_filenames:
        try:
            backend.delete(name)
        except Exception:  # noqa: S110  # nosec B110 - a reset must finish even if one blob is already gone
            pass
    for entry in os.scandir(tmp_dir()):
        if entry.is_file() and entry.name.endswith(".part"):
            os.remove(entry.path)
