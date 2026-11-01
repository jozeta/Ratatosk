from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dynamic_settings import get_settings, update_settings
from app.core.security import require_admin
from app.models.user import User
from app.schemas.settings import SmtpTestRequest, SystemSettingsSchema, SystemSettingsUpdate, nullable
from app.services.audit_service import log_event
from app.services.email_service import EmailNotConfigured, send_email

router = APIRouter(prefix="/api/admin/settings", tags=["admin"])


def _to_schema(cfg: dict) -> SystemSettingsSchema:
    # smtp_password is never serialized out - only whether one is set.
    return SystemSettingsSchema(**cfg, smtp_password_set=bool(cfg.get("smtp_password")))


@router.get("", response_model=SystemSettingsSchema)
def read_settings(admin: User = Depends(require_admin)):
    return _to_schema(get_settings())


@router.patch("", response_model=SystemSettingsSchema)
def patch_settings(
    payload: SystemSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # Only fields the client actually sent. An explicit null clears a
    # nullable field; for the rest null is meaningless and rejected
    # (previously None meant "unchanged", so nullable fields couldn't be
    # cleared at all - ARCH-004).
    changes = {k: getattr(payload, k) for k in payload.model_fields_set}
    bad = [k for k, v in changes.items() if v is None and not nullable(k)]
    if bad:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{', '.join(sorted(bad))} cannot be null")
    if not changes:
        return _to_schema(get_settings())
    new_cfg = update_settings(changes)
    log_event(
        db,
        "ADMIN_CONFIG_CHANGE",
        request=request,
        user_id=admin.id,
        detail=",".join(sorted(k for k in changes if k != "smtp_password")),
    )
    return _to_schema(new_cfg)


@router.post("/smtp-test")
def send_smtp_test(payload: SmtpTestRequest, admin: User = Depends(require_admin)):
    cfg = get_settings()
    try:
        brand = cfg.get("brand_name") or "Ratatosk"
        send_email(cfg, payload.to_email, f"{brand} SMTP test", f"This is a test email from your {brand} instance's Admin Settings page. If you received this, SMTP is configured correctly.")
    except EmailNotConfigured as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None
    except Exception as e:
        # Shown to the admin who is configuring SMTP, so the detail is useful here.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to send: {type(e).__name__}: {e}") from None
    return {"ok": True}
