import datetime
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db, utcnow
from app.core.dynamic_settings import get_settings
from app.core.password_policy import validate_password
from app.core.ratelimit import check_rate
from app.core.security import (
    _DUMMY_PASSWORD_HASH,
    bearer_scheme,
    clear_session_cookie,
    decode_mfa_setup_token,
    decode_mfa_token,
    decode_token,
    generate_backup_codes,
    generate_reset_token,
    generate_totp_secret,
    hash_backup_code,
    hash_password,
    hash_reset_token,
    require_user,
    revoke_token,
    session_token_from,
    totp_provisioning_uri,
    verify_password,
    verify_totp_code,
)
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    DeleteAccountRequest,
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
    RegisteredLoginRequired,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UpdateDiscoverableRequest,
    UpdateEmailRequest,
)
from app.services import lockout
from app.services.audit_service import log_event
from app.services.email_service import send_password_reset_email
from app.services.session_policy import issue_session_or_challenge, mfa_required_for, session_for
from app.services.users import delete_users

router = APIRouter(prefix="/api/auth", tags=["auth"])

RESET_TOKEN_RESEND_COOLDOWN_SECONDS = 60
GENERIC_RESET_MESSAGE = "If an account matches, a password reset email has been sent."


def _normalize_email(email: str | None) -> str | None:
    email = (email or "").strip().lower()
    return email or None


def _check_password_or_fail(db: Session, user: User, password: str, request: Request, cfg: dict) -> None:
    """Verify a password with an atomically reserved attempt (SEC-005), so
    neither logins nor in-session checks can be brute forced in parallel."""
    if not user.password_login:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This account signs in with SSO and has no password here")
    lockout.reserve_login_attempt(db, user.id, request, cfg)
    ok = verify_password(password, user.password_hash)
    triggered = lockout.record_login_attempt(db, user.id, request, ok, cfg)
    if not ok:
        if triggered:
            log_event(db, "BRUTE_FORCE_BLOCK", request=request, user_id=user.id, detail="lockout triggered")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")


def _check_second_factor(db: Session, user: User, code: str) -> str | None:
    """Accept a fresh TOTP code (single use, SEC-014) or an unused backup
    code. Returns "totp", "backup", or None. The caller commits."""
    step = verify_totp_code(user.mfa_secret or "", code, user.mfa_last_step)
    if step is not None:
        user.mfa_last_step = step
        return "totp"
    if user.mfa_backup_codes:
        codes = json.loads(user.mfa_backup_codes)
        code_hash = hash_backup_code(code)
        if code_hash in codes:
            codes.remove(code_hash)
            user.mfa_backup_codes = json.dumps(codes)
            return "backup"
    return None


@router.post("/register", response_model=TokenResponse | MfaSetupRequired | RegisteredLoginRequired)
def register(payload: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    cfg = get_settings()
    check_rate(request, "register", cfg, per_minute=max(1, cfg["rate_limit_per_minute"] // 3))
    if not cfg["allow_user_registration"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registration is disabled")

    errors = validate_password(payload.password, cfg)
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=" ".join(errors))

    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    email = _normalize_email(payload.email)
    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

    user = User(username=payload.username, password_hash=hash_password(payload.password), email=email)
    db.add(user)
    db.commit()
    db.refresh(user)
    log_event(db, "USER_REGISTERED", request=request, user_id=user.id)

    # Same policy as /login (SEC-007): no session while user login is
    # disabled, and enforced MFA must be set up before the first session.
    if not cfg["allow_user_login"]:
        return RegisteredLoginRequired(detail="Account created. Sign-in is currently disabled for regular users.")
    return issue_session_or_challenge(db, user, cfg, request, response=response)


@router.post("/login", response_model=TokenResponse | MfaLoginRequired | MfaSetupRequired)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    cfg = get_settings()
    check_rate(request, "login", cfg)
    user = db.query(User).filter(User.username == payload.username).first()

    if user is not None and not user.password_login:
        user = None  # SSO-only accounts can't sign in with a password
    if user is None:
        # Same bcrypt cost as a real account, so response time doesn't reveal
        # which usernames exist. The typed name is never logged (SEC-016):
        # people regularly paste their password into the username field.
        verify_password(payload.password, _DUMMY_PASSWORD_HASH)
        log_event(db, "LOGIN_FAILED", request=request, detail="unknown account")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    lockout.reserve_login_attempt(db, user.id, request, cfg)
    ok = verify_password(payload.password, user.password_hash)
    triggered = lockout.record_login_attempt(db, user.id, request, ok, cfg)
    if not ok:
        log_event(db, "BRUTE_FORCE_BLOCK" if triggered else "LOGIN_FAILED", request=request, user_id=user.id,
                  detail="lockout triggered" if triggered else "wrong password")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return issue_session_or_challenge(db, user, cfg, request, response=response)


@router.post("/mfa/verify", response_model=TokenResponse)
def mfa_verify(payload: MfaVerifyRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    cfg = get_settings()
    check_rate(request, "login", cfg)
    user_id = decode_mfa_token(payload.mfa_token)
    user = db.get(User, user_id)
    if user is None or not user.is_active or not user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login attempt")

    # Wrong codes share the same reserved-attempt counter as wrong passwords.
    lockout.reserve_login_attempt(db, user.id, request, cfg)
    factor = _check_second_factor(db, user, payload.code)
    ok = factor is not None
    db.commit()
    triggered = lockout.record_login_attempt(db, user.id, request, ok, cfg)
    if not ok:
        log_event(db, "BRUTE_FORCE_BLOCK" if triggered else "MFA_FAILED", request=request, user_id=user.id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")

    if factor == "backup":
        log_event(db, "MFA_BACKUP_CODE_USED", request=request, user_id=user.id)
    return issue_session_or_challenge(db, user, cfg, request, skip_mfa=True, response=response)


def _mfa_issuer(cfg: dict) -> str:
    # The admin-configured brand, so authenticator apps show the right
    # instance name (UI-007).
    return (cfg.get("brand_name") or "Ratatosk").strip() or "Ratatosk"


def _start_mfa_setup(user: User, cfg: dict, db: Session, request: Request) -> MfaSetupResponse:
    if not cfg["enable_mfa"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Two-factor authentication is disabled on this site")
    if user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is already enabled")

    secret = generate_totp_secret()
    user.mfa_secret = secret
    user.mfa_last_step = None
    db.commit()
    log_event(db, "MFA_SETUP_STARTED", request=request, user_id=user.id)
    return MfaSetupResponse(secret=secret, otpauth_url=totp_provisioning_uri(secret, user.username, _mfa_issuer(cfg)))


def _finish_mfa_setup(user: User, code: str, cfg: dict, db: Session, request: Request) -> list[str]:
    if not cfg["enable_mfa"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Two-factor authentication is disabled on this site")
    if user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is already enabled")
    if not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start MFA setup first")
    step = verify_totp_code(user.mfa_secret, code)
    if step is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

    raw_codes = generate_backup_codes()
    user.mfa_backup_codes = json.dumps([hash_backup_code(c) for c in raw_codes])
    user.mfa_enabled = True
    user.mfa_last_step = step
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
def mfa_enforce_confirm(payload: MfaEnforceConfirmRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    cfg = get_settings()
    user_id = decode_mfa_setup_token(payload.setup_token)
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login attempt")

    backup_codes = _finish_mfa_setup(user, payload.code, cfg, db, request)
    session = issue_session_or_challenge(db, user, cfg, request, skip_mfa=True, response=response)
    return MfaEnforceConfirmResponse(**session.model_dump(), backup_codes=backup_codes)


@router.post("/mfa/disable", response_model=TokenResponse)
def mfa_disable(payload: MfaDisableRequest, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Turning MFA off needs the password *and* a current code (SEC-019): a
    stolen session plus a phished password must not be enough to remove the
    second factor. Not allowed at all where MFA is mandatory for this user."""
    cfg = get_settings()
    if not user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")
    if mfa_required_for(user, cfg):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Two-factor authentication is mandatory for your account")
    _check_password_or_fail(db, user, payload.password, request, cfg)
    if not _check_second_factor(db, user, payload.code):
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")

    user.mfa_enabled = False
    user.mfa_secret = None
    user.mfa_backup_codes = None
    user.mfa_last_step = None
    user.token_version += 1  # other sessions were authorised with MFA; end them
    db.commit()
    log_event(db, "MFA_DISABLED", request=request, user_id=user.id)
    return session_for(user, request, response)


@router.get("/me")
def me(user: User = Depends(require_user)):
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "email": user.email,
        "mfa_enabled": user.mfa_enabled,
        "discoverable": user.discoverable,
        "password_login": user.password_login,
        "sso": bool(user.oidc_subject),
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    user: User = Depends(require_user),
):
    """Revokes this session's token server-side and clears the session
    cookie (SEC-017) - previously logging out only forgot the token in the
    browser, and it stayed valid for its full lifetime."""
    token = session_token_from(request, creds)
    if token and not token.startswith("sdk_"):
        revoke_token(db, decode_token(token))
    clear_session_cookie(response, request)
    log_event(db, "LOGOUT", request=request, user_id=user.id)
    return {"ok": True}


@router.post("/change-password", response_model=TokenResponse)
def change_password(payload: ChangePasswordRequest, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_user)):
    cfg = get_settings()
    _check_password_or_fail(db, user, payload.current_password, request, cfg)

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
    return session_for(user, request, response)


@router.post("/logout-everywhere", response_model=TokenResponse)
def logout_everywhere(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Invalidates every JWT issued for this account before now, including
    the one used to call this endpoint - a fresh replacement is issued and
    returned so the calling device stays logged in."""
    user.token_version += 1
    db.commit()
    log_event(db, "SESSIONS_REVOKED", request=request, user_id=user.id)
    return session_for(user, request, response)


@router.patch("/email")
def update_email(payload: UpdateEmailRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    email = _normalize_email(payload.email)
    if email and db.query(User).filter(User.email == email, User.id != user.id).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

    user.email = email
    db.commit()
    log_event(db, "EMAIL_UPDATED", request=request, user_id=user.id)
    return {"ok": True, "email": user.email}


@router.patch("/discoverable")
def update_discoverable(payload: UpdateDiscoverableRequest, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Opt in or out of the sharing directory (SEC-020)."""
    user.discoverable = payload.discoverable
    db.commit()
    return {"ok": True, "discoverable": user.discoverable}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    cfg = get_settings()
    check_rate(request, "forgot", cfg, per_minute=max(1, cfg["rate_limit_per_minute"] // 3))
    if not cfg["smtp_enabled"]:
        return {"message": GENERIC_RESET_MESSAGE}

    identifier = payload.identifier.strip()
    user = (
        db.query(User)
        .filter(or_(User.username == identifier, User.email == identifier.lower()))
        .first()
    )

    # Always the same generic answer, and the email is sent in the background
    # so response *time* can't reveal whether an account matched either. The
    # typed identifier is never logged (SEC-016).
    if user is None or not user.email or not user.is_active:
        log_event(db, "PASSWORD_RESET_REQUESTED", request=request, detail="no eligible match")
        return {"message": GENERIC_RESET_MESSAGE}

    now = utcnow()
    recent = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id)
        .order_by(PasswordResetToken.created_at.desc())
        .first()
    )
    if recent and recent.created_at > now - datetime.timedelta(seconds=RESET_TOKEN_RESEND_COOLDOWN_SECONDS):
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
    user_id, email = user.id, user.email
    log_event(db, "PASSWORD_RESET_REQUESTED", request=request, user_id=user_id, detail="email queued")

    def _send():
        from app.core.database import SessionLocal

        try:
            send_password_reset_email(cfg, email, reset_url)
        except Exception as e:
            s = SessionLocal()
            try:
                # Error class only - SMTP messages can carry server details.
                log_event(s, "PASSWORD_RESET_EMAIL_FAILED", user_id=user_id, detail=type(e).__name__)
            finally:
                s.close()

    background.add_task(_send)
    return {"message": GENERIC_RESET_MESSAGE}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    cfg = get_settings()
    check_rate(request, "forgot", cfg)
    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == hash_reset_token(payload.token)).first()

    now = utcnow()
    if reset_token is None or reset_token.used_at is not None or reset_token.expires_at < now:
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
    lockout.clear_login_throttles(db, user.id)

    log_event(db, "PASSWORD_RESET_VIA_EMAIL", request=request, user_id=user.id)
    return {"ok": True}


@router.delete("/me")
def delete_own_account(payload: DeleteAccountRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Requires the current password, and refuses to remove the last active
    admin (BUG-003). Files are orphaned, not deleted, so links keep working."""
    cfg = get_settings()
    if user.password_login:
        _check_password_or_fail(db, user, payload.password or "", request, cfg)
    elif (payload.confirm_username or "") != user.username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Type your username to confirm")
    user_id = user.id
    delete_users(db, [user_id])
    log_event(db, "USER_DELETED_SELF", request=request, user_id=user_id)
    return {"ok": True}
