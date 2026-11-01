"""The one place that decides whether a user who has proven their password
gets a session, an MFA challenge, or a mandatory MFA setup step.

Registration used to mint a session directly and so skipped both "user login
disabled" and "MFA required" (SEC-007). Every path that authenticates a user
now goes through issue_session_or_challenge()."""
from fastapi import HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, create_mfa_setup_token, create_mfa_token, set_session_cookie
from app.models.user import User
from app.schemas.auth import MfaLoginRequired, MfaSetupRequired, TokenResponse
from app.services.audit_service import log_event


def session_for(user: User, request: Request | None = None, response: Response | None = None) -> TokenResponse:
    """A new session token. With request+response, it's also set as the
    HttpOnly session cookie the browser uses (SEC-017); the token is still
    returned in the body for API clients."""
    token = create_access_token(user.id, user.is_admin, user.token_version)
    if request is not None and response is not None:
        set_session_cookie(response, request, token)
    return TokenResponse(access_token=token, is_admin=user.is_admin, username=user.username, id=user.id)


def mfa_required_for(user: User, cfg: dict) -> bool:
    if not cfg["enable_mfa"]:
        return False
    return bool(cfg["enforce_mfa_admins"] if user.is_admin else cfg["enforce_mfa_users"])


def issue_session_or_challenge(db: Session, user: User, cfg: dict, request: Request, skip_mfa: bool = False,
                               response: Response | None = None):
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    # Admins can always log in; regular users can be locked out via policy.
    if not user.is_admin and not cfg["allow_user_login"]:
        log_event(db, "LOGIN_FAILED", request=request, user_id=user.id, detail="login disabled by policy")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User login is currently disabled")
    if not skip_mfa:
        if user.mfa_enabled and cfg["enable_mfa"]:
            return MfaLoginRequired(mfa_token=create_mfa_token(user.id))
        if mfa_required_for(user, cfg) and not user.mfa_enabled:
            return MfaSetupRequired(setup_token=create_mfa_setup_token(user.id))
    log_event(db, "LOGIN_SUCCESS", request=request, user_id=user.id)
    return session_for(user, request, response)
