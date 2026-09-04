import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dynamic_settings import get_settings
from app.core.security import require_user
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.models.user import User
from app.schemas.sharing import ShareFileRequest, SharedFileEntry, UserListEntry
from app.services.audit_service import log_event

router = APIRouter(tags=["sharing"])


def _require_enabled():
    if not get_settings()["enable_user_sharing"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User-to-user sharing is disabled in settings")


@router.get("/api/users/list", response_model=list[UserListEntry])
def list_users_for_sharing(db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_enabled()
    others = db.query(User).filter(User.id != user.id, User.is_active == True).order_by(User.username).all()  # noqa: E712
    return others


@router.post("/api/files/{file_id}/share")
def share_file(file_id: str, payload: ShareFileRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_enabled()
    f = db.get(FileObject, file_id)
    if f is None or f.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if f.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the file's owner can share it")
    if f.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passphrase-protected files can't be shared this way - the server never has that key",
        )

    recipients = db.query(User).filter(User.id.in_(payload.user_ids), User.id != user.id).all()
    if not recipients:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid recipients")

    f.shared_decryption_key = payload.key
    db.add(f)

    existing = {
        r.recipient_id
        for r in db.query(FileShare).filter(FileShare.file_id == file_id, FileShare.recipient_id.in_([r.id for r in recipients])).all()
    }
    added = []
    for recipient in recipients:
        if recipient.id in existing:
            continue
        db.add(FileShare(file_id=file_id, owner_id=user.id, recipient_id=recipient.id))
        added.append(recipient.username)

    db.commit()
    log_event(db, "FILE_SHARED", request=request, file_id=file_id, user_id=user.id, detail=f"with={','.join(added) if added else '(already shared)'}")
    return {"ok": True, "shared_with": [r.username for r in recipients]}


@router.get("/api/files/shared-with-me", response_model=list[SharedFileEntry])
def list_shared_with_me(db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_enabled()
    now = datetime.datetime.now(datetime.timezone.utc)
    my_shares = db.query(FileShare).filter(FileShare.recipient_id == user.id).all()

    entries: list[SharedFileEntry] = []
    seen_files: set[str] = set()
    for share in my_shares:
        if share.file_id in seen_files:
            continue
        seen_files.add(share.file_id)

        f = db.get(FileObject, share.file_id)
        if f is None or f.is_deleted or f.expires_at.replace(tzinfo=datetime.timezone.utc) <= now:
            continue

        owner = db.get(User, f.owner_id)
        all_shares = db.query(FileShare).filter(FileShare.file_id == f.id).all()
        recipient_ids = [s.recipient_id for s in all_shares]
        recipients = db.query(User).filter(User.id.in_(recipient_ids)).all()

        entries.append(SharedFileEntry(
            file_id=f.id,
            size_bytes=f.size_bytes,
            created_at=f.created_at.isoformat(),
            expires_at=f.expires_at.isoformat(),
            burn_after_download=f.burn_after_download,
            max_downloads=f.max_downloads,
            download_count=f.download_count,
            shared_by=owner.username if owner else "(deleted user)",
            shared_with=[r.username for r in recipients],
        ))

    entries.sort(key=lambda e: e.created_at, reverse=True)
    return entries


@router.get("/api/files/{file_id}/shared-key")
def get_shared_key(file_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_enabled()
    f = db.get(FileObject, file_id)
    if f is None or f.is_deleted or not f.shared_decryption_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    is_owner = f.owner_id == user.id
    is_recipient = db.query(FileShare).filter(FileShare.file_id == file_id, FileShare.recipient_id == user.id).first() is not None
    if not (is_owner or is_recipient):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This file wasn't shared with you")

    return {"key": f.shared_decryption_key}


@router.delete("/api/files/{file_id}/share/{recipient_id}")
def revoke_share(file_id: str, recipient_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    f = db.get(FileObject, file_id)
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if f.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")

    share = db.query(FileShare).filter(FileShare.file_id == file_id, FileShare.recipient_id == recipient_id).first()
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    db.delete(share)

    remaining = db.query(FileShare).filter(FileShare.file_id == file_id).count()
    if remaining <= 1:  # the one we're about to delete still counts until commit
        f.shared_decryption_key = None

    db.commit()
    log_event(db, "FILE_UNSHARED", request=request, file_id=file_id, user_id=user.id)
    return {"ok": True}
