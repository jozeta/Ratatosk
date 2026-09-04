import secrets
from contextlib import contextmanager

from app.services.storage_backends.base import StorageBackend


class S3Backend(StorageBackend):
    """S3-compatible object storage (AWS S3, MinIO, Backblaze B2, etc).

    boto3 is only imported here, on first actual use - installing it is only
    required when SECUREDROP_STORAGE_BACKEND=s3 is set; the default local
    backend never touches this module. See requirements-s3.txt.
    """

    def __init__(self):
        try:
            import boto3
        except ImportError as e:
            raise RuntimeError(
                "storage_backend=s3 requires boto3 - install it with: pip install -r requirements-s3.txt"
            ) from e

        from app.core.config import settings

        self._bucket = settings.s3_bucket
        self._prefix = settings.s3_prefix.strip("/")
        if not self._bucket:
            raise RuntimeError("SECUREDROP_S3_BUCKET must be set when storage_backend=s3")

        kwargs = {"region_name": settings.s3_region or None}
        if settings.s3_endpoint_url:
            kwargs["endpoint_url"] = settings.s3_endpoint_url
        if settings.s3_access_key_id and settings.s3_secret_access_key:
            kwargs["aws_access_key_id"] = settings.s3_access_key_id
            kwargs["aws_secret_access_key"] = settings.s3_secret_access_key
        self._client = boto3.client("s3", **kwargs)

    def _key(self, filename: str) -> str:
        return f"{self._prefix}/{filename}" if self._prefix else filename

    def save(self, tmp_path: str) -> tuple[str, int]:
        import os

        filename = secrets.token_hex(32)
        size = os.path.getsize(tmp_path)
        self._client.upload_file(tmp_path, self._bucket, self._key(filename))
        os.remove(tmp_path)
        return filename, size

    @contextmanager
    def open_read(self, storage_filename: str):
        body = self._client.get_object(Bucket=self._bucket, Key=self._key(storage_filename))["Body"]
        try:
            yield body
        finally:
            body.close()

    def delete(self, storage_filename: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._key(storage_filename))

    def usage_bytes(self) -> int:
        total = 0
        paginator = self._client.get_paginator("list_objects_v2")
        kwargs = {"Bucket": self._bucket}
        if self._prefix:
            kwargs["Prefix"] = self._prefix + "/"
        for page in paginator.paginate(**kwargs):
            for obj in page.get("Contents", []):
                total += obj["Size"]
        return total
