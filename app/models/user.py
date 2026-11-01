import datetime
import uuid

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )

    # Account-login brute-force protection (separate from FileObject's
    # secondary-password lockout).
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    login_locked_until: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # TOTP-based MFA. mfa_secret is written as soon as setup starts but
    # mfa_enabled only flips to True once the user proves they captured it
    # correctly (see /api/auth/mfa/confirm), so a botched setup can't lock
    # anyone out. Backup codes are stored as a JSON array of salted hashes.
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_backup_codes: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Last accepted TOTP time step - a code is single-use (SEC-014).
    mfa_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- End-to-end encryption keypair (FEAT-001/FEAT-002) ---
    # ECDH P-256. The private key is wrapped in the browser with a key derived
    # (PBKDF2) from a separate *encryption passphrase* that never leaves the
    # browser - not the login password, which the server sees at login.
    enc_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # SPKI, base64url
    enc_wrapped_private_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # iv||AES-GCM(PKCS8), base64url
    enc_kdf_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enc_kdf_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enc_key_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)  # sha256(SPKI) hex

    # --- Single sign-on (FEAT-010) --- the IdP's stable identity for this
    # account. SSO-only accounts get an unusable random password hash.
    oidc_issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oidc_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    password_login: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Listed in the user-to-user sharing directory only if the user opts in
    # (SEC-020); otherwise others must know the exact username.
    discoverable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Bumped to invalidate every outstanding JWT for this account at once (password
    # change, admin-forced reset, or an explicit "log out everywhere") - see the "tv"
    # claim check in get_current_user().
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
