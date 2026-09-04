import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FileObject(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    storage_filename: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    uploader_token: Mapped[str] = mapped_column(String(36), nullable=False)

    # Optional secondary passphrase gate (server-side check, independent of the
    # client-side AES key which the server never sees).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    burn_after_download: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_downloads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0 = unlimited
    download_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Extension the client declared at upload time (used for policy checks) - kept
    # only for admin statistics, not treated as sensitive since it never included
    # the actual filename.
    extension: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Populated only when the owner explicitly shares this file with specific
    # accounts (see FileShare) - the client-side random key for the upload,
    # stored so recipients can decrypt without a separate link/passphrase. Only
    # ever set for random-key-mode uploads; passphrase-mode files can't be
    # shared this way since the server never has that key.
    shared_decryption_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Opt-in, set at upload time by a logged-in owner only (anonymous uploads have
    # no email to notify). Actually honored only if enable_download_notifications
    # and smtp_enabled are also both on - see files.py::download_blob.
    notify_on_download: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
