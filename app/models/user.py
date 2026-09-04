import datetime
import uuid

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    # Account-login brute-force protection (separate from FileObject's
    # secondary-password lockout).
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    login_locked_until: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    # TOTP-based MFA. mfa_secret is written as soon as setup starts but
    # mfa_enabled only flips to True once the user proves they captured it
    # correctly (see /api/auth/mfa/confirm), so a botched setup can't lock
    # anyone out. Backup codes are stored as a JSON array of salted hashes.
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_backup_codes: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Bumped to invalidate every outstanding JWT for this account at once (password
    # change, admin-forced reset, or an explicit "log out everywhere") - see the "tv"
    # claim check in get_current_user().
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
