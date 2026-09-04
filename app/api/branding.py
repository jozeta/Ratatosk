import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings as static_settings
from app.core.database import get_db
from app.core.dynamic_settings import get_settings, update_settings
from app.core.security import require_admin
from app.models.user import User
from app.services.audit_service import log_event

router = APIRouter(tags=["branding"])

MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2MB is plenty for a nav-bar logo
ALLOWED_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/svg+xml": "svg",
    "image/webp": "webp",
    "image/x-icon": "ico",
}


def _branding_dir() -> str:
    os.makedirs(static_settings.branding_root, exist_ok=True)
    return static_settings.branding_root


@router.get("/api/branding/logo")
def get_logo():
    cfg = get_settings()
    filename = cfg.get("brand_logo_filename")
    if not filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No custom logo set")
    path = os.path.join(_branding_dir(), filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No custom logo set")
    media_type = "image/svg+xml" if filename.endswith(".svg") else None
    response = FileResponse(path, media_type=media_type)
    # An admin-uploaded SVG can carry embedded <script>; it's only ever meant
    # to be painted via <img>, which never executes it, but a direct
    # navigation to this URL would otherwise run it as this origin. Block
    # script execution outright so that path can't turn into stored XSS.
    response.headers["Content-Security-Policy"] = "script-src 'none'; sandbox"
    return response


@router.post("/api/admin/branding/logo")
async def upload_logo(request: Request, file: UploadFile, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Logo must be PNG, JPEG, WebP, SVG, or ICO",
        )

    body = await file.read(MAX_LOGO_BYTES + 1)
    if len(body) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Logo must be under 2MB")

    _remove_existing_logo()

    ext = ALLOWED_TYPES[file.content_type]
    filename = f"logo-{uuid.uuid4().hex[:8]}.{ext}"
    with open(os.path.join(_branding_dir(), filename), "wb") as f:
        f.write(body)

    update_settings({"brand_logo_filename": filename})
    log_event(db, "ADMIN_CONFIG_CHANGE", request=request, user_id=admin.id, detail="brand_logo_filename")
    return {"ok": True, "filename": filename}


@router.delete("/api/admin/branding/logo")
def delete_logo(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _remove_existing_logo()
    update_settings({"brand_logo_filename": None})
    log_event(db, "ADMIN_CONFIG_CHANGE", request=request, user_id=admin.id, detail="brand_logo_filename cleared")
    return {"ok": True}


def _remove_existing_logo() -> None:
    cfg = get_settings()
    existing = cfg.get("brand_logo_filename")
    if existing:
        path = os.path.join(_branding_dir(), existing)
        if os.path.exists(path):
            os.remove(path)
