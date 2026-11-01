"""SSO endpoints (FEAT-010). See app/services/oidc.py for the protocol."""
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dynamic_settings import get_settings
from app.core.ratelimit import check_rate
from app.core.security import hash_password
from app.models.user import User
from app.services import oidc
from app.services.audit_service import log_event
from app.services.session_policy import issue_session_or_challenge
from app.services.users import active_admin_count

router = APIRouter(prefix="/api/auth/oidc", tags=["auth"])


def _redirect_uri(request: Request) -> str:
    return settings.oidc_redirect_url or str(request.url_for("oidc_callback"))


def _unique_username(db: Session, claims: dict) -> str:
    raw = claims.get("preferred_username") or (claims.get("email") or "").split("@")[0] or "user"
    base = re.sub(r"[^A-Za-z0-9._-]", "", raw)[:48] or "user"
    if len(base) < 3:
        base = (base + "-user")[:48]
    name = base
    while db.query(User).filter(User.username == name).first() is not None:
        name = f"{base}-{secrets.token_hex(2)}"
    return name


def _find_or_create(db: Session, claims: dict, request: Request) -> User:
    issuer, subject = claims["iss"], str(claims["sub"])
    user = db.query(User).filter(User.oidc_issuer == issuer, User.oidc_subject == subject).first()
    email = (claims.get("email") or "").strip().lower() or None
    if user is None and settings.oidc_link_by_email and email and claims.get("email_verified") is True:
        user = db.query(User).filter(User.email == email, User.oidc_subject.is_(None)).first()
        if user is not None:
            user.oidc_issuer, user.oidc_subject = issuer, subject
            log_event(db, "SSO_ACCOUNT_LINKED", request=request, user_id=user.id, commit=False)
    if user is None:
        if not settings.oidc_auto_provision:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No account here for that sign-in - ask an administrator")
        email_taken = email and db.query(User).filter(User.email == email).first() is not None
        user = User(
            username=_unique_username(db, claims), email=None if email_taken else email,
            password_hash=hash_password(secrets.token_urlsafe(32)),  # unusable: SSO-only account
            password_login=False, oidc_issuer=issuer, oidc_subject=subject,
        )
        db.add(user)
        db.flush()
        log_event(db, "SSO_USER_PROVISIONED", request=request, user_id=user.id, commit=False)
    admin = oidc.is_admin_by_claims(claims)
    if admin is not None and admin != user.is_admin:
        # Group membership drives the admin role, but never demotes the last admin.
        if admin or active_admin_count(db, excluding=[user.id]) > 0:
            user.is_admin = admin
    db.commit()
    return user


@router.get("/login")
def oidc_login(request: Request):
    if not oidc.enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO is not configured")
    check_rate(request, "login", get_settings())
    url, state = oidc.start(_redirect_uri(request))
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    # Lax, not Strict: the provider's redirect back to us is a cross-site
    # top-level navigation, and the state cookie must come along with it.
    response.set_cookie(oidc.STATE_COOKIE, oidc.sign_state(state), max_age=oidc.STATE_MAX_AGE, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https", path="/api/auth/oidc")
    return response


@router.get("/callback", name="oidc_callback")
def oidc_callback(request: Request, code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)):
    if not oidc.enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO is not configured")
    if error:
        return RedirectResponse("/login?sso_error=" + re.sub(r"[^a-z_]", "", error.lower())[:40], status_code=status.HTTP_302_FOUND)
    saved = oidc.read_state(request.cookies.get(oidc.STATE_COOKIE))
    claims = oidc.finish(code, state, saved)
    user = _find_or_create(db, claims, request)
    response = RedirectResponse("/login?sso=1", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(oidc.STATE_COOKIE, path="/api/auth/oidc")
    # Second factor is the identity provider's job for SSO logins; the other
    # policies (account active, user login allowed) still apply here.
    issue_session_or_challenge(db, user, get_settings(), request, skip_mfa=True, response=response)
    return response
