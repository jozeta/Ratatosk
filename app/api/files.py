import contextlib
import datetime
import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTasks

from app.core.database import SessionLocal, get_db, utcnow
from app.core.dynamic_settings import get_settings
from app.core.ratelimit import check_rate
from app.core.security import get_current_user, require_user, verify_password
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.models.user import User
from app.schemas.upload import FileMetaResponse, UpdateFileRequest, VerifyPasswordRequest, VerifyTokenRequest
from app.services import lockout, storage_service
from app.services.audit_service import log_event
from app.services.email_service import send_download_notification_email
from app.services.files import active_file_filter, claim_download, delete_files, process_pending_deletions, queue_blob_deletion

logger = logging.getLogger("ratatosk.files")

router = APIRouter(prefix="/api/files", tags=["files"])


def _get_active_file(db: Session, file_id: str) -> FileObject:
    f = db.query(FileObject).filter(FileObject.id == file_id, active_file_filter()).first()
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found or expired")
    return f


def _require_download_access(cfg: dict, user: User | None) -> None:
    if not cfg["allow_anonymous_download"] and user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anonymous downloads are disabled - please log in to download files",
        )


def _token_matches(f: FileObject, token: str | None) -> bool:
    if not token or not f.download_token_hash:
        return False
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, f.download_token_hash)


def _authorize_download(db: Session, f: FileObject, request: Request, cfg: dict, token: str | None, legacy_password: str | None) -> None:
    """Prove the caller holds the file's secret before anything is counted.

    Current files: the client presents a token derived (HKDF) from the URL
    key or the passphrase, so knowing only the file id can't consume, burn,
    or lock a file (SEC-006) and the server never sees the passphrase
    (SEC-001). Passphrase-derived tokens are guessable, so each wrong one
    uses an atomically reserved attempt (SEC-005); URL-key tokens are 256
    bits and don't need that. Older files keep their original rules."""
    scheme = f.auth_scheme
    if scheme == "token":
        if f.passphrase_protected:
            check_rate(request, "passphrase", cfg)
            lockout.reserve_file_attempt(db, f.id, cfg)
            ok = _token_matches(f, token)
            lockout.record_file_attempt(db, f.id, ok, cfg)
        else:
            ok = _token_matches(f, token)
        if not ok:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong key or passphrase")
    elif scheme == "legacy_password":
        check_rate(request, "passphrase", cfg)
        lockout.reserve_file_attempt(db, f.id, cfg)
        ok = bool(legacy_password) and verify_password(legacy_password or "", f.password_hash or "")
        lockout.record_file_attempt(db, f.id, ok, cfg)
        if not ok:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")


def _meta(f: FileObject) -> FileMetaResponse:
    return FileMetaResponse(
        file_id=f.id,
        size_bytes=f.size_bytes,
        expires_at=f.expires_at.isoformat(),
        burn_after_download=f.burn_after_download,
        max_downloads=f.max_downloads,
        download_count=f.download_count,
        requires_password=f.passphrase_protected or f.auth_scheme == "legacy_password",
        auth_scheme=f.auth_scheme,
        kdf_salt=f.kdf_salt,
        kdf_iterations=f.kdf_iterations,
        is_bundle=f.is_bundle,
    )


@router.get("/{file_id}/meta", response_model=FileMetaResponse)
def get_meta(file_id: str, db: Session = Depends(get_db), user: User | None = Depends(get_current_user)):
    cfg = get_settings()
    _require_download_access(cfg, user)
    return _meta(_get_active_file(db, file_id))


@router.post("/{file_id}/verify-token")
def verify_file_token(file_id: str, payload: VerifyTokenRequest, request: Request, db: Session = Depends(get_db),
                      user: User | None = Depends(get_current_user)):
    """Check the key/passphrase *before* downloading, so a wrong passphrase or
    a truncated link never burns a single-use file (UI-003)."""
    cfg = get_settings()
    _require_download_access(cfg, user)
    f = _get_active_file(db, file_id)
    if f.auth_scheme != "token":
        return {"valid": True}
    _authorize_download(db, f, request, cfg, payload.token, None)
    return {"valid": True}


@router.post("/{file_id}/verify-password")
def verify_file_password(file_id: str, payload: VerifyPasswordRequest, request: Request, db: Session = Depends(get_db),
                         user: User | None = Depends(get_current_user)):
    """Legacy (pre-token) passphrase files only."""
    cfg = get_settings()
    _require_download_access(cfg, user)
    f = _get_active_file(db, file_id)
    if f.auth_scheme != "legacy_password":
        return {"valid": True}
    _authorize_download(db, f, request, cfg, None, payload.password)
    return {"valid": True}


def _delete_burned_blob(storage_filename: str) -> None:
    db = SessionLocal()
    try:
        queue_blob_deletion(db, storage_filename)
        process_pending_deletions(db, only=[storage_filename])
    finally:
        db.close()


@router.get("/{file_id}/blob")
def download_blob(file_id: str, request: Request, db: Session = Depends(get_db), user: User | None = Depends(get_current_user)):
    cfg = get_settings()
    _require_download_access(cfg, user)
    f = _get_active_file(db, file_id)
    _authorize_download(db, f, request, cfg, request.headers.get("x-download-token"), request.headers.get("x-secondary-password"))

    storage_filename, size_bytes = f.storage_filename, f.size_bytes
    notify = f.notify_on_download and f.owner_id and cfg["enable_download_notifications"] and cfg["smtp_enabled"]
    owner_id = f.owner_id

    # Open the blob *before* claiming, so the claim is the last thing that can
    # fail, and a burn can never delete a blob a stream is still reading -
    # concurrent streams used to be cut off mid-file (BUG-001).
    stack = contextlib.ExitStack()
    try:
        fh = stack.enter_context(storage_service.open_blob(storage_filename))
    except FileNotFoundError:
        stack.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found or expired") from None

    claimed, burned = claim_download(db, file_id)
    if not claimed:
        stack.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found or expired")

    zero_log = cfg["zero_log_mode"]
    log_event(db, "DOWNLOAD", request=None if zero_log else request, file_id=file_id, commit=not burned)
    background = BackgroundTasks()
    if burned:
        db.query(FileShare).filter(FileShare.file_id == file_id).delete()
        db.query(FileObject).filter(FileObject.id == file_id).update({"shared_decryption_key": None})
        log_event(db, "FILE_BURNED", request=None if zero_log else request, file_id=file_id, commit=False)
        db.commit()
        background.add_task(_delete_burned_blob, storage_filename)

    if notify:
        owner = db.get(User, owner_id)
        if owner and owner.email:
            def _notify(cfg=cfg, email=owner.email, size=size_bytes):
                try:
                    send_download_notification_email(cfg, email, size)
                except Exception as e:
                    # Best-effort: a mail failure must never affect the download.
                    # Logged without the address.
                    logger.warning("download notification failed: %s", type(e).__name__)
            background.add_task(_notify)

    def iter_blob():
        with stack:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        iter_blob(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{file_id}.enc"', "Content-Length": str(size_bytes)},
        background=background,
    )


def _owned_or_admin(db: Session, file_id: str, user: User) -> FileObject:
    f = db.get(FileObject, file_id)
    if f is None or f.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if f.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
    return f


@router.delete("/{file_id}")
def delete_file(file_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    f = _owned_or_admin(db, file_id, user)
    delete_files(db, [f])
    log_event(db, "FILE_DELETED", request=request, file_id=file_id, user_id=user.id)
    return {"deleted": True}


@router.patch("/{file_id}")
def update_file(file_id: str, payload: UpdateFileRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Owner link management (FEAT-007): switch a link off and on, or
    tighten its expiry / download limit. Limits can only be made stricter,
    so this can never extend what the admin policy allowed at upload."""
    f = _owned_or_admin(db, file_id, user)
    now = utcnow()
    if payload.disabled is not None:
        f.disabled = payload.disabled
    if payload.expires_at is not None:
        try:
            new_exp = datetime.datetime.fromisoformat(payload.expires_at)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid expiry date") from None
        if new_exp.tzinfo is None:
            new_exp = new_exp.replace(tzinfo=datetime.UTC)
        if new_exp > f.expires_at:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expiry can only be shortened")
        f.expires_at = max(new_exp, now)
    if payload.max_downloads is not None:
        if payload.max_downloads == 0 and f.max_downloads != 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A download limit can't be removed")
        if payload.max_downloads and f.max_downloads and payload.max_downloads > f.max_downloads:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The download limit can only be lowered")
        if payload.max_downloads and payload.max_downloads < f.download_count:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Limit is below the downloads already made")
        f.max_downloads = payload.max_downloads
    if f.is_bundle:
        db.query(FileObject).filter(FileObject.bundle_parent_id == f.id).update(
            {"disabled": f.disabled, "expires_at": f.expires_at}, synchronize_session=False
        )
    db.commit()
    log_event(db, "FILE_UPDATED", request=request, file_id=file_id, user_id=user.id)
    return {"ok": True, "disabled": f.disabled, "expires_at": f.expires_at.isoformat(), "max_downloads": f.max_downloads}


@router.post("/{file_id}/unlock")
def unlock_file(file_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Lift a wrong-passphrase lockout early (owner or admin) - SEC-006."""
    _owned_or_admin(db, file_id, user)
    lockout.unlock_file(db, file_id)
    log_event(db, "FILE_UNLOCKED", request=request, file_id=file_id, user_id=user.id)
    return {"ok": True}


@router.get("/mine")
def list_my_files(db: Session = Depends(get_db), user: User = Depends(require_user)):
    now = utcnow()
    files = (
        db.query(FileObject)
        .filter(FileObject.owner_id == user.id, FileObject.is_deleted == False,  # noqa: E712
                FileObject.bundle_parent_id.is_(None), FileObject.request_id.is_(None))
        .order_by(FileObject.created_at.desc())
        .all()
    )

    ids = [f.id for f in files]
    shares_by_file: dict[str, list[dict]] = {}
    member_counts: dict[str, int] = {}
    if ids:
        rows = (
            db.query(FileShare.file_id, User.id, User.username)
            .join(User, User.id == FileShare.recipient_id)
            .filter(FileShare.file_id.in_(ids))
            .all()
        )
        for file_id, recipient_id, username in rows:
            shares_by_file.setdefault(file_id, []).append({"id": recipient_id, "username": username})
        bundle_ids = [f.id for f in files if f.is_bundle]
        if bundle_ids:
            for (parent,) in db.query(FileObject.bundle_parent_id).filter(FileObject.bundle_parent_id.in_(bundle_ids), FileObject.is_deleted == False):  # noqa: E712
                if parent:
                    member_counts[parent] = member_counts.get(parent, 0) + 1

    return [
        {
            "file_id": f.id,
            "size_bytes": f.size_bytes,
            "created_at": f.created_at.isoformat(),
            "expires_at": f.expires_at.isoformat(),
            "burn_after_download": f.burn_after_download,
            "max_downloads": f.max_downloads,
            "download_count": f.download_count,
            "expired": f.expires_at <= now,
            "disabled": f.disabled,
            "locked": bool(f.locked_until and f.locked_until > now) or f.locked,
            "password_protected": f.passphrase_protected or f.auth_scheme == "legacy_password",
            "is_bundle": f.is_bundle,
            "bundle_file_count": member_counts.get(f.id, 0),
            "shared_with": shares_by_file.get(f.id, []),
        }
        for f in files
    ]
