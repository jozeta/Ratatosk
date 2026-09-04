import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApiKey(Base):
    """A long-lived programmatic credential (CLI/scripted upload access).

    Only a SHA-256 hash of the raw key is ever stored - unlike account
    passwords, API keys are high-entropy random tokens, so a fast hash is
    both sufficient (brute force is infeasible) and necessary (must support
    an indexed equality lookup per-request, which bcrypt can't).
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)  # shown in the UI to identify the key
    # "full" behaves exactly like before; "upload" is rejected by
    # _resolve_api_key_user() outside /api/uploads/*, so a leaked upload-only
    # key can't list, download, or delete anything.
    scope: Mapped[str] = mapped_column(String(16), default="full", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
