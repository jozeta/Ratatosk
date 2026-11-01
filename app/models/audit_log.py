import datetime
import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    file_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_token: Mapped[str | None] = mapped_column(String(64), nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(512), nullable=True)

    timestamp: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.datetime.now(datetime.UTC), index=True
    )
