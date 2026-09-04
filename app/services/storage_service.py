import os
from contextlib import AbstractContextManager
from typing import BinaryIO

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
    safe_id = upload_id.replace("/", "").replace("\\", "").replace("..", "")
    return os.path.join(tmp_dir(), f"{safe_id}.part")


def get_storage_usage_bytes() -> int:
    return get_backend().usage_bytes()


def has_capacity(additional_bytes: int) -> bool:
    cfg = get_settings()
    cap_bytes = int(cfg["total_storage_cap_gb"]) * 1024 * 1024 * 1024
    used = get_storage_usage_bytes()
    return (used + additional_bytes) <= cap_bytes * 0.95


def finalize_blob(tmp_path: str) -> tuple[str, int]:
    return get_backend().save(tmp_path)


def delete_blob(storage_filename: str) -> None:
    get_backend().delete(storage_filename)


def open_blob(storage_filename: str) -> AbstractContextManager[BinaryIO]:
    return get_backend().open_read(storage_filename)


def clear_all_blobs() -> None:
    """Deletes every stored file (encrypted blobs and in-progress upload
    chunks) - used by the admin "reset everything" flow. Irreversible."""
    backend = get_backend()
    from app.services.storage_backends.local import LocalDiskBackend

    if isinstance(backend, LocalDiskBackend):
        for entry in os.scandir(backend._dir()):
            if entry.is_file():
                os.remove(entry.path)
    else:
        # Non-local backends only expose usage_bytes()/delete-by-name, so a
        # full wipe has to enumerate first. LocalDiskBackend is special-cased
        # above purely because it already had a cheaper os.scandir path.
        _clear_via_listing(backend)

    for entry in os.scandir(tmp_dir()):
        if entry.is_file():
            os.remove(entry.path)


def _clear_via_listing(backend) -> None:
    from app.services.storage_backends.s3 import S3Backend

    if isinstance(backend, S3Backend):
        paginator = backend._client.get_paginator("list_objects_v2")
        kwargs = {"Bucket": backend._bucket}
        if backend._prefix:
            kwargs["Prefix"] = backend._prefix + "/"
        for page in paginator.paginate(**kwargs):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                backend._client.delete_objects(Bucket=backend._bucket, Delete={"Objects": keys})
