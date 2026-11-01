import datetime
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime, utcnow


class UploadRequest(Base):
    """An encrypted "send me a file" link (FEAT-001).

    Anyone with the link - no account needed - can upload files that are
    encrypted in their browser to the owner's public key, so only the owner
    can open them. The link carries the key's fingerprint in its #fragment;
    the uploader's browser refuses to encrypt if the public key the server
    hands out doesn't match, so the server can't substitute its own key.
    """

    __tablename__ = "upload_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    # Shown to uploaders. Chosen by the owner, who decides what it reveals.
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    public_key: Mapped[str] = mapped_column(Text, nullable=False)  # owner's SPKI at creation
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    max_uploads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 = unlimited
    upload_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_file_size_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    file_ttl: Mapped[str] = mapped_column(String(16), nullable=False)  # how long submissions are kept
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
