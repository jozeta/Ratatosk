import datetime
import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime


class FileShare(Base):
    __tablename__ = "file_shares"
    __table_args__ = (UniqueConstraint("file_id", "recipient_id", name="uq_file_recipient"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    file_id: Mapped[str] = mapped_column(String(36), ForeignKey("files.id"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    recipient_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    # End-to-end shares (FEAT-002): the file secret wrapped to the recipient's
    # public key with ECDH-ES. NULL for legacy shares, which rely on the
    # server-held FileObject.shared_decryption_key instead.
    wrapped_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ephemeral_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )
