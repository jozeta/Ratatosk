import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTasks

from app.core.database import get_db
from app.core.dynamic_settings import get_settings
from app.core.security import get_current_user, verify_password
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.models.user import User
from app.schemas.upload import FileMetaResponse, VerifyPasswordRequest
from app.services import storage_service
from app.services.audit_service import log_event
from app.services.email_service import send_download_notification_email

router = APIRouter(prefix="/api/files", tags=["files"])


def _get_active_file(db: Session, file_id: str) -> FileObject:
    f = db.get(FileObject, file_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    if f is None or f.is_deleted or f.expires_at.replace(tzinfo=datetime.timezone.utc) <= now:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found or expired")
    if f.max_downloads and f.download_count >= f.max_downloads:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found or expired")
    return f


def _require_download_access(cfg: dict, user: User | None) -> None:
    if not cfg["allow_anonymous_download"] and user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anonymous downloads are disabled - please log in to download files",
        )


@router.get("/{file_id}/meta", response_model=FileMetaResponse)
def get_meta(file_id: str, db: Session = Depends(get_db), user: User | None = Depends(get_current_user)):
    cfg = get_settings()
    _require_download_access(cfg, user)
    f = _get_active_file(db, file_id)
    return FileMetaResponse(
        file_id=f.id,
        size_bytes=f.size_bytes,
        expires_at=f.expires_at.isoformat(),
        burn_after_download=f.burn_after_download,
        max_downloads=f.max_downloads,
        download_count=f.download_count,
        requires_password=bool(f.password_hash),
    )


@router.post("/{file_id}/verify-password")
def verify_file_password(
    file_id: str,
    payload: VerifyPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    cfg = get_settings()
    _require_download_access(cfg, user)
    f = _get_active_file(db, file_id)
    if not f.password_hash:
        return {"valid": True}

    if f.locked:
        log_event(db, "BRUTE_FORCE_BLOCK", request=request, file_id=f.id)
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Too many failed attempts; file locked")

    if verify_password(payload.password, f.password_hash):
        f.failed_attempts = 0
        db.commit()
        return {"valid": True}

    f.failed_attempts += 1
    if f.failed_attempts >= cfg["max_login_attempts"]:
        f.locked = True
        log_event(db, "BRUTE_FORCE_BLOCK", request=request, file_id=f.id, detail="lockout triggered")
    db.commit()
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")


@router.get("/{file_id}/blob")
def download_blob(file_id: str, request: Request, db: Session = Depends(get_db), user: User | None = Depends(get_current_user)):
    cfg = get_settings()
    _require_download_access(cfg, user)
    f = _get_active_file(db, file_id)

    if f.password_hash:
        supplied = request.headers.get("x-secondary-password")
        if f.locked:
            raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Too many failed attempts; file locked")
        if not supplied or not verify_password(supplied, f.password_hash):
            f.failed_attempts += 1
            if f.failed_attempts >= cfg["max_login_attempts"]:
                f.locked = True
                log_event(db, "BRUTE_FORCE_BLOCK", request=request, file_id=f.id, detail="lockout triggered")
            db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")

    storage_filename = f.storage_filename
    f.download_count += 1
    burn_now = f.burn_after_download or (f.max_downloads and f.download_count >= f.max_downloads)
    size_bytes = f.size_bytes
    db.commit()

    log_event(db, "DOWNLOAD", request=None if cfg["zero_log_mode"] else request, file_id=f.id)

    background = BackgroundTasks()
    if burn_now:
        f.is_deleted = True
        db.commit()
        log_event(db, "FILE_BURNED", request=None if cfg["zero_log_mode"] else request, file_id=f.id)
        # FileResponse streams the file lazily after this handler returns, so
        # the blob must only be removed from disk once that send completes.
        background.add_task(storage_service.delete_blob, f.storage_filename)

    if f.notify_on_download and f.owner_id and cfg["enable_download_notifications"] and cfg["smtp_enabled"]:
        owner = db.get(User, f.owner_id)
        if owner and owner.email:
            def _notify(cfg=cfg, email=owner.email, size=size_bytes):
                try:
                    send_download_notification_email(cfg, email, size)
                except Exception:
                    pass  # best-effort - a mail failure must never affect the download itself
            background.add_task(_notify)

    def iter_blob():
        with storage_service.open_blob(storage_filename) as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        iter_blob(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{f.id}.enc"'},
        background=background,
    )


@router.delete("/{file_id}")
def delete_file(file_id: str, request: Request, db: Session = Depends(get_db), user: User | None = Depends(get_current_user)):
    f = db.get(FileObject, file_id)
    if f is None or f.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    is_owner = user is not None and f.owner_id == user.id
    is_admin = user is not None and user.is_admin
    if not (is_owner or is_admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")

    f.is_deleted = True
    db.query(FileShare).filter(FileShare.file_id == f.id).delete()
    db.commit()
    storage_service.delete_blob(f.storage_filename)
    log_event(db, "FILE_DELETED", request=request, file_id=f.id, user_id=user.id if user else None)
    return {"deleted": True}


@router.get("/mine")
def list_my_files(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    now = datetime.datetime.now(datetime.timezone.utc)
    files = (
        db.query(FileObject)
        .filter(FileObject.owner_id == user.id, FileObject.is_deleted == False)  # noqa: E712
        .order_by(FileObject.created_at.desc())
        .all()
    )

    shares_by_file: dict[str, list[dict]] = {}
    if files:
        rows = (
            db.query(FileShare.file_id, User.id, User.username)
            .join(User, User.id == FileShare.recipient_id)
            .filter(FileShare.file_id.in_([f.id for f in files]))
            .all()
        )
        for file_id, recipient_id, username in rows:
            shares_by_file.setdefault(file_id, []).append({"id": recipient_id, "username": username})

    return [
        {
            "file_id": f.id,
            "size_bytes": f.size_bytes,
            "created_at": f.created_at.isoformat(),
            "expires_at": f.expires_at.isoformat(),
            "burn_after_download": f.burn_after_download,
            "max_downloads": f.max_downloads,
            "download_count": f.download_count,
            "expired": f.expires_at.replace(tzinfo=datetime.timezone.utc) <= now,
            "password_protected": bool(f.password_hash),
            "shared_with": shares_by_file.get(f.id, []),
        }
        for f in files
    ]
