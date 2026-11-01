"""Small operational tables: login throttling, token revocation, retryable
blob deletion, single-runner leases, and upload chunk bookkeeping."""
import datetime
import uuid

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime, utcnow


class LoginThrottle(Base):
    """Failed-login bookkeeping per (account, client network) - SEC-012.

    Locking the *account* outright let anyone on the internet keep the admin
    locked out. Keying by network means an attacker only locks themselves out.
    `net_key` is an HMAC of the masked client network under the server secret,
    never the IP itself; rows are deleted once their lockout window passes.
    """

    __tablename__ = "login_throttles"
    __table_args__ = (UniqueConstraint("user_id", "net_key", name="uq_throttle_user_net"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    net_key: Mapped[str] = mapped_column(String(64), nullable=False)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class RevokedToken(Base):
    """JWT ids invalidated by an explicit logout (SEC-017). Rows are purged
    once the token would have expired anyway."""

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False, index=True)


class PendingBlobDeletion(Base):
    """Blob deletions queued in the same transaction that removes the file
    row, then performed (and retried on failure) by the cleanup worker - so a
    storage outage can't leave orphaned ciphertext behind (ARCH-007)."""

    __tablename__ = "pending_blob_deletions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    storage_filename: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Lease(Base):
    """A named, expiring lock so periodic jobs run in one process at a time
    even with several workers or hosts (ARCH-001)."""

    __tablename__ = "leases"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    holder: Mapped[str] = mapped_column(String(64), nullable=False)
    until: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False)


class UploadChunk(Base):
    """One received byte range of an in-progress upload (BUG-008/PERF-008).

    Chunks are written at their declared offset, so a retried PUT is a no-op
    instead of appending a duplicate, and several chunks can be in flight at
    once. /complete verifies the chunks tile the whole declared size exactly.
    """

    __tablename__ = "upload_chunks"
    __table_args__ = (UniqueConstraint("upload_id", "offset", name="uq_chunk_offset"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    upload_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    offset: Mapped[int] = mapped_column(Integer, nullable=False)
    length: Mapped[int] = mapped_column(Integer, nullable=False)
