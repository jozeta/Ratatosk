import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dynamic_settings import get_settings
from app.core.password_policy import validate_password
from app.core.security import (
    _DUMMY_PASSWORD_HASH,
    create_access_token,
    create_mfa_setup_token,
    create_mfa_token,
    decode_mfa_setup_token,
    decode_mfa_token,
    generate_backup_codes,
    generate_reset_token,
    generate_totp_secret,
    hash_backup_code,
    hash_password,
    hash_reset_token,
    require_user,
    totp_provisioning_uri,
    verify_password,
    verify_totp_code,
)
from app.models.file import FileObject
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MfaConfirmRequest,
    MfaConfirmResponse,
    MfaDisableRequest,
    MfaEnforceConfirmRequest,
    MfaEnforceConfirmResponse,
    MfaEnforceSetupRequest,
    MfaLoginRequired,
    MfaSetupRequired,
    MfaSetupResponse,
    MfaVerifyRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UpdateEmailRequest,
)
from app.services.audit_service import log_event
from app.services.email_service import send_password_reset_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

RESET_TOKEN_RESEND_COOLDOWN_SECONDS = 60
GENERIC_RESET_MESSAGE = "If an account matches, a password reset email has been sent."


def _register_login_failure(db: Session, user: User, cfg: dict, request: Request, event: str) -> None:
    """Shared brute-force bookkeeping for both wrong passwords and wrong MFA
    codes - both are guesses against the same account, so they share one
    lockout counter."""
    if not cfg["enable_login_rate_limit"]:
        log_event(db, event, request=request, user_id=user.id)
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    user.failed_login_attempts += 1
    locked_now = user.failed_login_attempts >= cfg["max_login_attempts"]
    if locked_now:
        user.login_locked_until = now + datetime.timedelta(minutes=cfg["login_lockout_minutes"])
    db.commit()
    if locked_now:
        log_event(db, "BRUTE_FORCE_BLOCK", request=request, user_id=user.id, detail="lockout triggered")
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Too many failed attempts. Try again in {cfg['login_lockout_minutes']} minute(s).",
        )
    log_event(db, event, request=request, user_id=user.id)


def _normalize_email(email: str | None) -> str | None:
    email = (email or "").strip().lower()
    return email or None


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    cfg = get_settings()
    if not cfg["allow_user_registration"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registration is disabled")

    errors = validate_password(payload.password, cfg)
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=" ".join(errors))

    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    email = _normalize_email(payload.email)
    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

    user = User(username=payload.username, password_hash=hash_password(payload.password), email=email)
    db.add(user)
    db.commit()
    db.refresh(user)

    log_event(db, "USER_REGISTERED", request=request, user_id=user.id)
    token = create_access_token(user.id, user.is_admin, user.token_version)
    return TokenResponse(access_token=token, is_admin=user.is_admin, username=user.username, id=user.id)


@router.post("/login", response_model=TokenResponse | MfaLoginRequired | MfaSetupRequired)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    cfg = get_settings()
    rate_limited = cfg["enable_login_rate_limit"]
    now = datetime.datetime.now(datetime.timezone.utc)
    user = db.query(User).filter(User.username == payload.username).first()

    # Locked accounts are rejected before even checking the password, so a
    # locked-out attacker can't keep guessing "for free" while locked.
    if user is not None and rate_limited and user.login_locked_until:
        locked_until = user.login_locked_until.replace(tzinfo=datetime.timezone.utc)
        if locked_until > now:
            remaining = max(1, int((locked_until - now).total_seconds() // 60) + 1)
            log_event(db, "BRUTE_FORCE_BLOCK", request=request, user_id=user.id, detail="account login locked")
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Too many failed attempts. Try again in {remaining} minute(s).",
            )

    # Always run a bcrypt verify, even for an unknown username, so the two
    # cases take the same amount of time - otherwise the response latency
    # itself would reveal which usernames have accounts.
    password_ok = verify_password(payload.password, user.password_hash if user else _DUMMY_PASSWORD_HASH)
    if user is None or not password_ok:
        if user is not None and rate_limited:
            user.failed_login_attempts += 1
            locked_now = user.failed_login_attempts >= cfg["max_login_attempts"]
            if locked_now:
                user.login_locked_until = now + datetime.timedelta(minutes=cfg["login_lockout_minutes"])
            db.commit()
            if locked_now:
                log_event(db, "BRUTE_FORCE_BLOCK", request=request, user_id=user.id, detail="lockout triggered")
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail=f"Too many failed attempts. Try again in {cfg['login_lockout_minutes']} minute(s).",
                )
        log_event(db, "LOGIN_FAILED", request=request, detail=f"username={payload.username}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    # Admins can always log in; regular users can be locked out via policy.
    if not user.is_admin and not cfg["allow_user_login"]:
        log_event(db, "LOGIN_FAILED", request=request, user_id=user.id, detail="login disabled by policy")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User login is currently disabled")

    if user.failed_login_attempts or user.login_locked_until:
        user.failed_login_attempts = 0
        user.login_locked_until = None
        db.commit()

    if user.mfa_enabled and cfg["enable_mfa"]:
        return MfaLoginRequired(mfa_token=create_mfa_token(user.id))

    mfa_enforced = cfg["enforce_mfa_admins"] if user.is_admin else cfg["enforce_mfa_users"]
    if cfg["enable_mfa"] and mfa_enforced and not user.mfa_enabled:
        return MfaSetupRequired(setup_token=create_mfa_setup_token(user.id))

    log_event(db, "LOGIN_SUCCESS", request=request, user_id=user.id)
    token = create_access_token(user.id, user.is_admin, user.token_version)
    return TokenResponse(access_token=token, is_admin=user.is_admin, username=user.username, id=user.id)


@router.post("/mfa/verify", response_model=TokenResponse)
def mfa_verify(payload: MfaVerifyRequest, request: Request, db: Session = Depends(get_db)):
    cfg = get_settings()
    user_id = decode_mfa_token(payload.mfa_token)
    user = db.get(User, user_id)
    if user is None or not user.is_active or not user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login attempt")

    now = datetime.datetime.now(datetime.timezone.utc)
    if cfg["enable_login_rate_limit"] and user.login_locked_until:
        locked_until = user.login_locked_until.replace(tzinfo=datetime.timezone.utc)
        if locked_until > now:
            remaining = max(1, int((locked_until - now).total_seconds() // 60) + 1)
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Too many failed attempts. Try again in {remaining} minute(s).",
            )

    ok = verify_totp_code(user.mfa_secret, payload.code)
    used_backup_code = False
    if not ok and user.mfa_backup_codes:
        codes = json.loads(user.mfa_backup_codes)
        code_hash = hash_backup_code(payload.code)
        if code_hash in codes:
            ok = True
            used_backup_code = True
            codes.remove(code_hash)
            user.mfa_backup_codes = json.dumps(codes)

    if not ok:
        _register_login_failure(db, user, cfg, request, "MFA_FAILED")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")

    if user.failed_login_attempts or user.login_locked_until:
        user.failed_login_attempts = 0
        user.login_locked_until = None
    db.commit()

    if used_backup_code:
        log_event(db, "MFA_BACKUP_CODE_USED", request=request, user_id=user.id)
    log_event(db, "LOGIN_SUCCESS", request=request, user_id=user.id)
    token = create_access_token(user.id, user.is_admin, user.token_version)
    return TokenResponse(access_token=token, is_admin=user.is_admin, username=user.username, id=user.id)


def _start_mfa_setup(user: User, cfg: dict, db: Session, request: Request) -> MfaSetupResponse:
    if not cfg["enable_mfa"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Two-factor authentication is disabled on this site")
    if user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is already enabled")

    secret = generate_totp_secret()
    user.mfa_secret = secret
    db.commit()
    log_event(db, "MFA_SETUP_STARTED", request=request, user_id=user.id)
    return MfaSetupResponse(secret=secret, otpauth_url=totp_provisioning_uri(secret, user.username, "SecureDrop"))


def _finish_mfa_setup(user: User, code: str, cfg: dict, db: Session, request: Request) -> list[str]:
    if not cfg["enable_mfa"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Two-factor authentication is disabled on this site")
    if user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is already enabled")
    if not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start MFA setup first")
    if not verify_totp_code(user.mfa_secret, code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

    raw_codes = generate_backup_codes()
    user.mfa_backup_codes = json.dumps([hash_backup_code(c) for c in raw_codes])
    user.mfa_enabled = True
    db.commit()
    log_event(db, "MFA_ENABLED", request=request, user_id=user.id)
    return raw_codes


@router.post("/mfa/setup", response_model=MfaSetupResponse)
def mfa_setup(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return _start_mfa_setup(user, get_settings(), db, request)


@router.post("/mfa/confirm", response_model=MfaConfirmResponse)
def mfa_confirm(payload: MfaConfirmRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    backup_codes = _finish_mfa_setup(user, payload.code, get_settings(), db, request)
    return MfaConfirmResponse(backup_codes=backup_codes)


@router.post("/mfa/enforce-setup", response_model=MfaSetupResponse)
def mfa_enforce_setup(payload: MfaEnforceSetupRequest, request: Request, db: Session = Depends(get_db)):
    """Same as /mfa/setup, but for a user mid-login who is required to set up
    MFA before finishing - authenticated by the one-time setup_token from
    /login instead of a real session, since they don't have one yet."""
    user_id = decode_mfa_setup_token(payload.setup_token)
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login attempt")
    return _start_mfa_setup(user, get_settings(), db, request)


@router.post("/mfa/enforce-confirm", response_model=MfaEnforceConfirmResponse)
def mfa_enforce_confirm(payload: MfaEnforceConfirmRequest, request: Request, db: Session = Depends(get_db)):
    user_id = decode_mfa_setup_token(payload.setup_token)
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login attempt")

    backup_codes = _finish_mfa_setup(user, payload.code, get_settings(), db, request)
    log_event(db, "LOGIN_SUCCESS", request=request, user_id=user.id)
    token = create_access_token(user.id, user.is_admin, user.token_version)
    return MfaEnforceConfirmResponse(
        access_token=token, is_admin=user.is_admin, username=user.username, id=user.id, backup_codes=backup_codes
    )


@router.post("/mfa/disable")
def mfa_disable(payload: MfaDisableRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    user.mfa_enabled = False
    user.mfa_secret = None
    user.mfa_backup_codes = None
    db.commit()
    log_event(db, "MFA_DISABLED", request=request, user_id=user.id)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(require_user)):
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin, "email": user.email, "mfa_enabled": user.mfa_enabled}


@router.post("/change-password", response_model=TokenResponse)
def change_password(payload: ChangePasswordRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    cfg = get_settings()
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    errors = validate_password(payload.new_password, cfg)
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=" ".join(errors))

    user.password_hash = hash_password(payload.new_password)
    # Kills every other outstanding session for this account. The caller's
    # own session would die too on its next request, so a fresh token is
    # issued below and returned instead of a bare {"ok": true}.
    user.token_version += 1
    db.commit()
    log_event(db, "PASSWORD_CHANGED", request=request, user_id=user.id)
    token = create_access_token(user.id, user.is_admin, user.token_version)
    return TokenResponse(access_token=token, is_admin=user.is_admin, username=user.username, id=user.id)


@router.post("/logout-everywhere", response_model=TokenResponse)
def logout_everywhere(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Invalidates every JWT issued for this account before now, including
    the one used to call this endpoint - a fresh replacement is issued and
    returned so the calling device stays logged in."""
    user.token_version += 1
    db.commit()
    log_event(db, "SESSIONS_REVOKED", request=request, user_id=user.id)
    token = create_access_token(user.id, user.is_admin, user.token_version)
    return TokenResponse(access_token=token, is_admin=user.is_admin, username=user.username, id=user.id)


@router.patch("/email")
def update_email(payload: UpdateEmailRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    email = _normalize_email(payload.email)
    if email and db.query(User).filter(User.email == email, User.id != user.id).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

    user.email = email
    db.commit()
    log_event(db, "EMAIL_UPDATED", request=request, user_id=user.id)
    return {"ok": True, "email": user.email}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    cfg = get_settings()
    if not cfg["smtp_enabled"]:
        return {"message": GENERIC_RESET_MESSAGE}

    identifier = payload.identifier.strip()
    user = (
        db.query(User)
        .filter(or_(User.username == identifier, User.email == identifier.lower()))
        .first()
    )

    # Always return the same generic message whether or not a match was
    # found, an email is on file, or sending actually succeeded - the
    # specifics only ever show up in the audit log, never to the caller.
    if user is None or not user.email or not user.is_active:
        log_event(db, "PASSWORD_RESET_REQUESTED", request=request, detail=f"identifier={identifier} (no eligible match)")
        return {"message": GENERIC_RESET_MESSAGE}

    now = datetime.datetime.now(datetime.timezone.utc)
    recent = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id)
        .order_by(PasswordResetToken.created_at.desc())
        .first()
    )
    if recent and recent.created_at.replace(tzinfo=datetime.timezone.utc) > now - datetime.timedelta(
        seconds=RESET_TOKEN_RESEND_COOLDOWN_SECONDS
    ):
        log_event(db, "PASSWORD_RESET_REQUESTED", request=request, user_id=user.id, detail="throttled")
        return {"message": GENERIC_RESET_MESSAGE}

    # Invalidate any still-outstanding tokens before issuing a new one.
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
    ).delete()

    raw_token = generate_reset_token()
    expiry_minutes = cfg.get("password_reset_token_expiry_minutes", 60)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_reset_token(raw_token),
            expires_at=now + datetime.timedelta(minutes=expiry_minutes),
        )
    )
    db.commit()

    base_url = cfg.get("public_base_url") or str(request.base_url).rstrip("/")
    reset_url = f"{base_url}/reset-password?token={raw_token}"

    try:
        send_password_reset_email(cfg, user.email, reset_url)
        log_event(db, "PASSWORD_RESET_REQUESTED", request=request, user_id=user.id, detail="email sent")
    except Exception as e:
        log_event(db, "PASSWORD_RESET_REQUESTED", request=request, user_id=user.id, detail=f"send failed: {e}")

    return {"message": GENERIC_RESET_MESSAGE}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    cfg = get_settings()
    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == hash_reset_token(payload.token)).first()

    now = datetime.datetime.now(datetime.timezone.utc)
    if (
        reset_token is None
        or reset_token.used_at is not None
        or reset_token.expires_at.replace(tzinfo=datetime.timezone.utc) < now
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or has expired")

    user = db.get(User, reset_token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or has expired")

    errors = validate_password(payload.new_password, cfg)
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=" ".join(errors))

    user.password_hash = hash_password(payload.new_password)
    user.failed_login_attempts = 0
    user.login_locked_until = None
    user.token_version += 1
    reset_token.used_at = now
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.id != reset_token.id,
        PasswordResetToken.used_at.is_(None),
    ).delete()
    db.commit()

    log_event(db, "PASSWORD_RESET_VIA_EMAIL", request=request, user_id=user.id)
    return {"ok": True}


@router.delete("/me")
def delete_own_account(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    from app.models.api_key import ApiKey
    from app.models.file_share import FileShare

    # Orphan (don't delete) their files - links already shared should keep working.
    db.query(FileObject).filter(FileObject.owner_id == user.id).update({"owner_id": None})
    db.query(FileShare).filter(FileShare.recipient_id == user.id).delete()
    db.query(FileShare).filter(FileShare.owner_id == user.id).delete()
    db.query(ApiKey).filter(ApiKey.user_id == user.id).delete()
    user_id = user.id
    db.delete(user)
    db.commit()
    log_event(db, "USER_DELETED_SELF", request=request, user_id=user_id)
    return {"ok": True}
