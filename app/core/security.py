import datetime
import hashlib
import secrets

import bcrypt
import pyotp
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

API_KEY_PREFIX = "sdk_"
MFA_TOKEN_EXPIRE_MINUTES = 5
BACKUP_CODE_COUNT = 10


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


# A fixed, valid bcrypt hash with no matching password, used to give a
# nonexistent-username login attempt the same bcrypt-verify cost as a real
# one - otherwise the response time itself would reveal which usernames exist.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"no-such-account", bcrypt.gensalt()).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8")[:72], hashed.encode("ascii"))
    except ValueError:
        return False


def generate_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, key_hash, display_prefix). Only the hash is stored."""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    key_hash = hash_api_key(raw)
    display_prefix = raw[: len(API_KEY_PREFIX) + 6]
    return raw, key_hash, display_prefix


def hash_api_key(raw: str) -> str:
    # API keys are high-entropy random tokens, not human-chosen passwords, so
    # a fast hash is correct here: brute force is infeasible regardless, and
    # a per-request lookup needs to be an indexed equality match (bcrypt
    # can't do that - it's deliberately slow and salted per-hash).
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)


def hash_reset_token(raw: str) -> str:
    # Same reasoning as API keys: a high-entropy random value needing an
    # indexed equality lookup, not a human-chosen secret needing bcrypt.
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_access_token(subject: str, is_admin: bool = False, token_version: int = 0) -> str:
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload = {"sub": subject, "is_admin": is_admin, "tv": token_version, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_mfa_token(subject: str) -> str:
    """A short-lived, deliberately-limited token proving the password step
    passed, issued while an MFA code is still owed. It carries no `is_admin`
    claim and a `purpose` marker that get_current_user() rejects outright, so
    it can never be used in place of a real access token even if replayed
    against a protected endpoint."""
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=MFA_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "purpose": "mfa", "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_mfa_token(token: str) -> str:
    """Returns the user id if `token` is a valid, unexpired MFA-pending token."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login attempt")
    if payload.get("purpose") != "mfa":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login attempt")
    return payload["sub"]


def create_mfa_setup_token(subject: str) -> str:
    """Same idea as create_mfa_token, but for the "MFA is mandatory and you
    haven't set it up yet" path: proves the password step passed, and is only
    ever accepted by the two enforce-setup endpoints - get_current_user()
    rejects it just like the mfa-pending token, so it can't be used to reach
    the rest of the app without actually completing setup."""
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=MFA_TOKEN_EXPIRE_MINUTES * 2)
    payload = {"sub": subject, "purpose": "mfa_setup", "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_mfa_setup_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login attempt")
    if payload.get("purpose") != "mfa_setup":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login attempt")
    return payload["sub"]


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, username: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def verify_totp_code(secret: str, code: str) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code:
        return False
    try:
        # valid_window=1 tolerates ~30s of clock drift on either side.
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False


def generate_backup_codes(count: int = BACKUP_CODE_COUNT) -> list[str]:
    return ["".join(secrets.choice("23456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(10)) for _ in range(count)]


def hash_backup_code(code: str) -> str:
    # High-entropy, randomly generated, single-use - same reasoning as API
    # keys and reset tokens: a fast hash is correct and necessary here.
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def _resolve_api_key_user(token: str, db: Session, request: Request) -> User | None:
    if not token.startswith(API_KEY_PREFIX):
        return None

    from app.core.dynamic_settings import get_settings
    from app.models.api_key import ApiKey

    if not get_settings().get("enable_api_keys", True):
        return None

    api_key = db.query(ApiKey).filter(ApiKey.key_hash == hash_api_key(token)).first()
    if api_key is None:
        return None
    if api_key.scope == "upload" and not request.url.path.startswith("/api/uploads/"):
        # An upload-only key simply doesn't resolve to anyone outside the
        # upload endpoints - no separate scope-check dependency needed on
        # every other router.
        return None
    user = db.get(User, api_key.user_id)
    if user is None or not user.is_active:
        return None
    api_key.last_used_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return user


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if creds is None:
        return None
    token = creds.credentials

    if token.startswith(API_KEY_PREFIX):
        return _resolve_api_key_user(token, db, request)

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if payload.get("purpose") in ("mfa", "mfa_setup"):
        # These prove the password step only - neither must ever grant
        # access on its own, or MFA (including mandatory setup) would just
        # be decorative.
        return None
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        return None
    if payload.get("tv", 0) != user.token_version:
        # Password change / admin reset / "log out everywhere" bumped this
        # account's token_version - every token minted before that moment
        # (this one included) is now dead, no matter how long until it'd
        # otherwise expire.
        return None
    return user


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def require_admin(user: User | None = Depends(get_current_user)) -> User:
    if user is None or not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user
