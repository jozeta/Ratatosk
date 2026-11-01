import datetime
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime


class FileObject(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    storage_filename: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    # No longer populated (SEC-003): storing the uploader's account/cookie id
    # permanently linked every anonymous upload from one browser. Kept only so
    # pre-existing NOT NULL columns on old databases still accept inserts ("").
    uploader_token: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # --- Download authorization (SEC-001 / SEC-006) ---
    # SHA-256 of a token the client derives from the file's secret (the URL
    # key, or the passphrase via PBKDF2) with HKDF, using a label independent
    # of the encryption key. Downloads must present the token, so knowing only
    # a file id is no longer enough to consume, burn, or lock a file - and the
    # server never receives the passphrase or anything that yields the key.
    # NULL for files uploaded before this scheme ("legacy" - see auth_scheme).
    download_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Passphrase-mode only: PBKDF2 parameters, which aren't secret, so the
    # downloader can derive the token before fetching the ciphertext.
    kdf_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kdf_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passphrase_protected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Legacy (pre-token) passphrase files only: bcrypt of the passphrase that
    # old clients sent to the server. Never written for new uploads.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Wrong-passphrase brute-force protection. Time-limited, not permanent: a
    # permanent lock let anyone holding the file id destroy access for the
    # real recipient (SEC-006).
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime, nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # legacy permanent flag; migrated on read

    burn_after_download: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_downloads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0 = unlimited
    download_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False, index=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # Owner switched the link off without deleting it (FEAT-007).
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Extension the client declared at upload time (used for policy checks) - kept
    # only for admin statistics, not treated as sensitive since it never included
    # the actual filename.
    extension: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Populated only when the owner explicitly shares this file with specific
    # accounts (see FileShare) - the client-side random key for the upload,
    # stored so recipients can decrypt without a separate link/passphrase.
    # Cleared as soon as no share needs it (SEC-018).
    shared_decryption_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Opt-in, set at upload time by a logged-in owner only.
    notify_on_download: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Multi-file bundles (FEAT-003): the bundle itself is an encrypted manifest
    # file (is_bundle); each member file points at it so the owner sees one
    # entry and deleting the bundle deletes its members.
    is_bundle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    bundle_parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # Files submitted through an upload request link (FEAT-001): the file
    # secret is wrapped to the request owner's public key, so only they can
    # open it. owner_id is the request owner.
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    wrapped_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ephemeral_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def auth_scheme(self) -> str:
        """How a downloader proves they may fetch this file."""
        if self.download_token_hash:
            return "token"
        if self.password_hash:
            return "legacy_password"
        return "none"
