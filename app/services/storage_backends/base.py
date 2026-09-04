from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import BinaryIO


class StorageBackend(ABC):
    """Where finished (encrypted) blobs live once an upload completes.

    Chunked-upload staging always happens on local disk first regardless of
    backend (see storage_service.tmp_path_for) - a backend only ever receives
    one already-assembled file via save(), and is never involved in the
    chunk-by-chunk part of an upload.
    """

    @abstractmethod
    def save(self, tmp_path: str) -> tuple[str, int]:
        """Takes ownership of the finished file at tmp_path, returns (storage_filename, size_bytes)."""

    @abstractmethod
    def open_read(self, storage_filename: str) -> AbstractContextManager[BinaryIO]:
        """A context manager yielding a readable, binary, chunk-iterable file-like object."""

    @abstractmethod
    def delete(self, storage_filename: str) -> None:
        """Removing an already-deleted file must be a no-op, not an error."""

    @abstractmethod
    def usage_bytes(self) -> int:
        """Total bytes currently stored, for the admin capacity check and stats page."""
