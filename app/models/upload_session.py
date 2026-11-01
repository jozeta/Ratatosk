import datetime
import uuid

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime


class UploadSession(Base):
    """An in-progress chunked upload (between /init and /complete).

    Kept in the database rather than in process memory so that uploads
    survive a server restart and work across multiple uvicorn workers, and so
    the concurrent-upload limit is enforced globally rather than per-process.
    """

    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Who started this upload ("user:<id>" or "anon:<cookie>") - every chunk
    # and the final /complete must come from the same actor.
    actor: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bytes_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    declared_size: Mapped[int] = mapped_column(Integer, nullable=False)
    extension: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Set when uploading into an upload request link (FEAT-001).
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=lambda: datetime.datetime.now(datetime.UTC)
    )
    last_activity_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=lambda: datetime.datetime.now(datetime.UTC)
    )
