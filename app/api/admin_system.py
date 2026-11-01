import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings as static_settings
from app.core.database import get_db
from app.core.dynamic_settings import reset_settings_to_defaults
from app.core.security import hash_password, require_admin, verify_password
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.models.ops import LoginThrottle, PendingBlobDeletion, RevokedToken, UploadChunk
from app.models.password_reset_token import PasswordResetToken
from app.models.upload_session import UploadSession
from app.models.user import User
from app.schemas.system import SystemResetRequest, SystemResetResponse
from app.services import storage_service
from app.services.audit_service import log_event

router = APIRouter(prefix="/api/admin/system", tags=["admin"])


@router.post("/reset", response_model=SystemResetResponse)
def reset_system(
    payload: SystemResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Full factory reset: wipes every user, file, and setting, then
    re-bootstraps a single fresh admin account exactly like first boot.
    Requires the calling admin's current password as a second confirmation,
    since there is no undo - the acting admin's own account is deleted as
    part of the wipe, which naturally invalidates their session token too
    (it stops resolving to any user on the very next request)."""
    if not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    acting_username = admin.username

    # Remove the branding logo file while the settings cache still knows its
    # filename - reset_settings_to_defaults() below clears that column.
    from app.api.branding import _remove_existing_logo

    _remove_existing_logo()

    # Children before parents, even though this app's SQLite engine doesn't
    # enforce FK constraints - keeps this correct if that ever changes.
    # Collect blob names first: the reset deletes exactly the blobs the
    # database references (plus queued and staged ones), never "everything
    # in the directory" (SEC-010).
    blob_names = [n for (n,) in db.query(FileObject.storage_filename)]
    blob_names += [n for (n,) in db.query(PendingBlobDeletion.storage_filename)]

    db.query(FileShare).delete()
    db.query(UploadChunk).delete()
    db.query(PendingBlobDeletion).delete()
    db.query(LoginThrottle).delete()
    db.query(RevokedToken).delete()
    db.query(ApiKey).delete()
    db.query(PasswordResetToken).delete()
    db.query(UploadSession).delete()
    db.query(FileObject).delete()
    db.query(AuditLog).delete()
    db.query(User).delete()
    db.commit()

    storage_service.clear_blobs(blob_names)

    reset_settings_to_defaults(db)

    new_password = secrets.token_urlsafe(16)
    new_admin = User(
        username=static_settings.default_admin_username,
        password_hash=hash_password(new_password),
        is_admin=True,
    )
    db.add(new_admin)
    db.commit()

    log_event(
        db,
        "SYSTEM_RESET",
        request=request,
        detail=f"reset performed by '{acting_username}'; re-bootstrapped as '{new_admin.username}'",
    )

    return SystemResetResponse(admin_username=new_admin.username, admin_password=new_password)
