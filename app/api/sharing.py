import base64
import hashlib
import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dynamic_settings import get_settings
from app.core.ratelimit import check_rate
from app.core.security import require_user
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.models.user import User
from app.schemas.sharing import SharedFileEntry, ShareFileRequest, UserListEntry
from app.services.audit_service import log_event
from app.services.files import active_file_filter
from app.services.users import release_unneeded_share_keys

router = APIRouter(tags=["sharing"])

DL_TOKEN_INFO = b"ratatosk-dl-v1"


def _require_enabled():
    if not get_settings()["enable_user_sharing"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User-to-user sharing is disabled in settings")


def _download_token_for(key_b64url: str) -> str | None:
    """The same HKDF derivation the browser and CLI use - lets the server
    check that a key submitted for sharing really belongs to the file."""
    try:
        raw = base64.urlsafe_b64decode(key_b64url + "=" * (-len(key_b64url) % 4))
    except (ValueError, TypeError):
        return None
    if len(raw) != 32:
        return None
    token = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=DL_TOKEN_INFO).derive(raw)
    return base64.urlsafe_b64encode(token).rstrip(b"=").decode()


@router.get("/api/users/list", response_model=list[UserListEntry])
def list_users_for_sharing(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Only users who opted in to being discoverable (SEC-020)."""
    _require_enabled()
    return (
        db.query(User)
        .filter(User.id != user.id, User.is_active == True, User.discoverable == True)  # noqa: E712
        .order_by(User.username)
        .all()
    )


@router.get("/api/users/lookup", response_model=UserListEntry)
def lookup_user(username: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Find a share recipient by exact username, discoverable or not -
    rate limited so it can't be used to enumerate accounts."""
    _require_enabled()
    check_rate(request, "user-lookup", get_settings())
    target = db.query(User).filter(User.username == username.strip(), User.is_active == True, User.id != user.id).first()  # noqa: E712
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user")
    return target


@router.post("/api/files/{file_id}/share")
def share_file(file_id: str, payload: ShareFileRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Share with accounts. Recipients in `recipients` get the file secret
    wrapped (in the sender's browser) to their own public key - the server
    can't open it (FEAT-002). `user_ids` + `key` is the legacy path for
    recipients without keys: the server holds the key, if the admin allows."""
    _require_enabled()
    cfg = get_settings()
    f = db.query(FileObject).filter(FileObject.id == file_id, active_file_filter()).first()
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if f.owner_id != user.id or f.request_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the file's owner can share it")
    if f.passphrase_protected or f.auth_scheme == "legacy_password":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passphrase-protected files can't be shared this way - the server never has that key",
        )
    if not payload.recipients and not payload.user_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No recipients")

    shared_with: list[str] = []
    e2e_ids = [r.user_id for r in payload.recipients]
    e2e_users = {u.id: u for u in db.query(User).filter(User.id.in_(e2e_ids), User.id != user.id, User.is_active == True)}  # noqa: E712
    for r in payload.recipients:
        target = e2e_users.get(r.user_id)
        if target is None:
            continue
        if not target.enc_public_key:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{target.username} has no encryption keys")
        share = db.query(FileShare).filter(FileShare.file_id == file_id, FileShare.recipient_id == target.id).first()
        if share is None:
            share = FileShare(file_id=file_id, owner_id=user.id, recipient_id=target.id)
            db.add(share)
        share.wrapped_key = r.wrapped_key
        share.ephemeral_public_key = r.ephemeral_public_key
        shared_with.append(target.username)

    legacy_users = db.query(User).filter(User.id.in_(payload.user_ids), User.id != user.id, User.is_active == True).all()  # noqa: E712
    if legacy_users:
        if not cfg["allow_server_held_share_keys"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Recipients must set up encryption keys before files can be shared with them")
        if not payload.key:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing key")
        if f.download_token_hash:
            token = _download_token_for(payload.key)
            if token is None or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), f.download_token_hash):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That key doesn't belong to this file")
        f.shared_decryption_key = payload.key
        for target in legacy_users:
            share = db.query(FileShare).filter(FileShare.file_id == file_id, FileShare.recipient_id == target.id).first()
            if share is None:
                db.add(FileShare(file_id=file_id, owner_id=user.id, recipient_id=target.id))
            elif share.wrapped_key:
                continue  # already shared end-to-end; never downgrade
            shared_with.append(target.username)

    if not shared_with:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid recipients")
    db.commit()
    log_event(db, "FILE_SHARED", request=request, file_id=file_id, user_id=user.id,
              detail=f"e2e={len(e2e_users)} server_held={len(legacy_users)}")
    return {"ok": True, "shared_with": shared_with}


@router.get("/api/files/shared-with-me", response_model=list[SharedFileEntry])
def list_shared_with_me(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Two queries in total instead of four per share (PERF-004)."""
    _require_enabled()
    rows = (
        db.query(FileObject, User.username, FileShare.wrapped_key)
        .join(FileShare, FileShare.file_id == FileObject.id)
        .outerjoin(User, User.id == FileObject.owner_id)
        .filter(FileShare.recipient_id == user.id, active_file_filter())
        .order_by(FileObject.created_at.desc())
        .all()
    )
    file_ids = list({f.id for f, _, _ in rows})
    recipients_by_file: dict[str, list[str]] = {}
    if file_ids:
        for fid, uname in (
            db.query(FileShare.file_id, User.username).join(User, User.id == FileShare.recipient_id).filter(FileShare.file_id.in_(file_ids))
        ):
            recipients_by_file.setdefault(fid, []).append(uname)

    seen: set[str] = set()
    entries: list[SharedFileEntry] = []
    for f, owner_name, wrapped in rows:
        if f.id in seen:
            continue
        seen.add(f.id)
        entries.append(SharedFileEntry(
            scheme="e2e" if wrapped else "server",
            file_id=f.id,
            size_bytes=f.size_bytes,
            created_at=f.created_at.isoformat(),
            expires_at=f.expires_at.isoformat(),
            burn_after_download=f.burn_after_download,
            max_downloads=f.max_downloads,
            download_count=f.download_count,
            shared_by=owner_name or "(deleted user)",
            shared_with=sorted(recipients_by_file.get(f.id, [])),
        ))
    return entries


@router.get("/api/files/{file_id}/shared-key")
def get_shared_key(file_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_enabled()
    # Only for files that can still be downloaded - an expired-but-not-yet-
    # cleaned-up file no longer hands out its key (BUG-010).
    f = db.query(FileObject).filter(FileObject.id == file_id, active_file_filter()).first()
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    share = db.query(FileShare).filter(FileShare.file_id == file_id, FileShare.recipient_id == user.id).first()
    if share is not None and share.wrapped_key:
        # End-to-end share: only the recipient's private key can unwrap this.
        return {"scheme": "e2e", "wrapped_key": share.wrapped_key, "ephemeral_public_key": share.ephemeral_public_key}
    if not f.shared_decryption_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if not (f.owner_id == user.id or share is not None):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This file wasn't shared with you")
    return {"scheme": "server", "key": f.shared_decryption_key}


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
    db.flush()
    release_unneeded_share_keys(db, {file_id})
    db.commit()
    log_event(db, "FILE_UNSHARED", request=request, file_id=file_id, user_id=user.id)
    return {"ok": True}
