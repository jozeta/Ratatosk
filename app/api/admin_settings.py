from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dynamic_settings import get_settings, update_settings
from app.core.security import require_admin
from app.models.user import User
from app.schemas.settings import SmtpTestRequest, SystemSettingsSchema, SystemSettingsUpdate
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
    changes = {k: v for k, v in payload.model_dump().items() if v is not None}
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
        send_email(cfg, payload.to_email, "SecureDrop SMTP test", "This is a test email from your SecureDrop instance's Admin Settings page. If you received this, SMTP is configured correctly.")
    except EmailNotConfigured as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to send: {e}")
    return {"ok": True}
