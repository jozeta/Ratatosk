"""End-to-end encryption keys (FEAT-002) and upload request links (FEAT-001).

Nothing here can decrypt anything: the server stores public keys, private
keys wrapped by a passphrase it never sees, and file secrets wrapped to
public keys (ECDH-ES). All wrapping and unwrapping happens in the browser.
"""
import base64
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.database import get_db, rowcount, utcnow
from app.core.dynamic_settings import get_settings
from app.core.ratelimit import check_rate
from app.core.security import require_user
from app.core.ttl import is_allowed_ttl, parse_ttl
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.models.upload_request import UploadRequest
from app.models.user import User
from app.schemas.e2e import (
    AccountKeys,
    AccountKeysOut,
    CreateUploadRequest,
    PublicKeyOut,
    RequestSubmission,
    UploadRequestOut,
    UploadRequestPublic,
)
from app.services.audit_service import log_event
from app.services.files import active_file_filter, delete_files

router = APIRouter(tags=["e2e"])


def fingerprint_of(public_key_b64url: str) -> str:
    raw = base64.urlsafe_b64decode(public_key_b64url + "=" * (-len(public_key_b64url) % 4))
    return hashlib.sha256(raw).hexdigest()


def _keys_out(user: User) -> AccountKeysOut:
    return AccountKeysOut(
        public_key=user.enc_public_key or "", wrapped_private_key=user.enc_wrapped_private_key or "",
        kdf_salt=user.enc_kdf_salt or "", kdf_iterations=user.enc_kdf_iterations or 0,
        fingerprint=user.enc_key_fingerprint or "",
    )


# ------------------------------------------------------------- account keys ---

@router.get("/api/account/keys", response_model=AccountKeysOut)
def get_my_keys(user: User = Depends(require_user)):
    if not user.enc_public_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encryption keys set up yet")
    return _keys_out(user)


@router.put("/api/account/keys", response_model=AccountKeysOut)
def put_my_keys(payload: AccountKeys, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Set up keys, re-wrap the same key under a new passphrase, or replace
    the keypair. Replacing it makes anything wrapped to the old key
    unreadable, so those shares are removed and open request links (which
    encrypt to the old key) are closed."""
    replacing = bool(user.enc_public_key) and user.enc_public_key != payload.public_key
    try:
        fp = fingerprint_of(payload.public_key)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid public key") from None
    user.enc_public_key = payload.public_key
    user.enc_wrapped_private_key = payload.wrapped_private_key
    user.enc_kdf_salt = payload.kdf_salt
    user.enc_kdf_iterations = payload.kdf_iterations
    user.enc_key_fingerprint = fp
    removed_shares = 0
    if replacing:
        removed_shares = db.query(FileShare).filter(FileShare.recipient_id == user.id, FileShare.wrapped_key.is_not(None)).delete()
        db.query(UploadRequest).filter(UploadRequest.owner_id == user.id, UploadRequest.closed == False).update({"closed": True})  # noqa: E712
    db.commit()
    log_event(db, "ENCRYPTION_KEYS_REPLACED" if replacing else "ENCRYPTION_KEYS_SET", request=request, user_id=user.id,
              detail=f"shares_removed={removed_shares}" if replacing else None)
    return _keys_out(user)


@router.get("/api/users/{user_id}/public-key", response_model=PublicKeyOut)
def get_public_key(user_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    target = db.get(User, user_id)
    if target is None or not target.is_active or not target.enc_public_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That user hasn't set up encryption keys")
    return PublicKeyOut(user_id=target.id, username=target.username, public_key=target.enc_public_key,
                        fingerprint=target.enc_key_fingerprint or "")


# ----------------------------------------------------------- upload requests ---

def _require_requests_enabled() -> dict:
    cfg = get_settings()
    if not cfg["enable_upload_requests"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Upload request links are disabled on this site")
    return cfg


def _is_open(r: UploadRequest) -> bool:
    return not r.closed and r.expires_at > utcnow() and (r.max_uploads == 0 or r.upload_count < r.max_uploads)


def _request_out(r: UploadRequest) -> UploadRequestOut:
    return UploadRequestOut(
        id=r.id, label=r.label, fingerprint=r.fingerprint, created_at=r.created_at.isoformat(),
        expires_at=r.expires_at.isoformat(), max_uploads=r.max_uploads, upload_count=r.upload_count,
        max_file_size_mb=r.max_file_size_mb, file_ttl=r.file_ttl, open=_is_open(r),
    )


@router.post("/api/requests", response_model=UploadRequestOut)
def create_request(payload: CreateUploadRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    cfg = _require_requests_enabled()
    if not user.enc_public_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Set up encryption keys on your Profile page first")
    file_ttl = payload.file_ttl or cfg["default_ttl"]
    if not is_allowed_ttl(file_ttl, cfg["allowed_ttl_presets"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That retention period isn't allowed on this site")
    max_mb = min(payload.max_file_size_mb or cfg["max_file_size_mb"], cfg["max_file_size_mb"])
    r = UploadRequest(
        owner_id=user.id, label=payload.label.strip(), public_key=user.enc_public_key,
        fingerprint=user.enc_key_fingerprint or fingerprint_of(user.enc_public_key),
        expires_at=utcnow() + parse_ttl(payload.expires_in), max_uploads=payload.max_uploads,
        max_file_size_mb=max_mb, file_ttl=file_ttl,
    )
    db.add(r)
    db.commit()
    log_event(db, "UPLOAD_REQUEST_CREATED", request=request, user_id=user.id)
    return _request_out(r)


@router.get("/api/requests", response_model=list[UploadRequestOut])
def list_requests(db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_requests_enabled()
    rows = db.query(UploadRequest).filter(UploadRequest.owner_id == user.id).order_by(UploadRequest.created_at.desc()).all()
    return [_request_out(r) for r in rows]


@router.post("/api/requests/{request_id}/close", response_model=UploadRequestOut)
def close_request(request_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    r = db.get(UploadRequest, request_id)
    if r is None or r.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    r.closed = True
    db.commit()
    return _request_out(r)


@router.delete("/api/requests/{request_id}")
def delete_request(request_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Delete the link and every file submitted through it."""
    r = db.get(UploadRequest, request_id)
    if r is None or r.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    delete_files(db, db.query(FileObject).filter(FileObject.request_id == r.id, FileObject.is_deleted == False).all())  # noqa: E712
    db.delete(r)
    db.commit()
    log_event(db, "UPLOAD_REQUEST_DELETED", request=request, user_id=user.id)
    return {"ok": True}


@router.get("/api/requests/{request_id}/files", response_model=list[RequestSubmission])
def request_files(request_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    r = db.get(UploadRequest, request_id)
    if r is None or r.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    files = (
        db.query(FileObject)
        .filter(FileObject.request_id == r.id, active_file_filter())
        .order_by(FileObject.created_at.desc())
        .all()
    )
    return [
        RequestSubmission(file_id=f.id, size_bytes=f.size_bytes, created_at=f.created_at.isoformat(),
                          expires_at=f.expires_at.isoformat(), download_count=f.download_count,
                          wrapped_key=f.wrapped_key or "", ephemeral_public_key=f.ephemeral_public_key or "")
        for f in files
    ]


@router.get("/api/requests/{request_id}/public", response_model=UploadRequestPublic)
def request_public(request_id: str, request: Request, db: Session = Depends(get_db)):
    """What an uploader's browser needs. No account required."""
    _require_requests_enabled()
    check_rate(request, "request-public", get_settings())
    r = db.get(UploadRequest, request_id)
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This request link doesn't exist")
    left = None if r.max_uploads == 0 else max(0, r.max_uploads - r.upload_count)
    return UploadRequestPublic(id=r.id, label=r.label, public_key=r.public_key, fingerprint=r.fingerprint,
                               max_file_size_mb=r.max_file_size_mb, expires_at=r.expires_at.isoformat(),
                               open=_is_open(r), uploads_left=left)


def claim_request_slot(db: Session, request_id: str) -> UploadRequest:
    """Atomically count one submission against a request's limit."""
    res = db.execute(
        update(UploadRequest)
        .where(UploadRequest.id == request_id, UploadRequest.closed == False,  # noqa: E712
               UploadRequest.expires_at > utcnow(),
               (UploadRequest.max_uploads == 0) | (UploadRequest.upload_count < UploadRequest.max_uploads))
        .values(upload_count=UploadRequest.upload_count + 1)
    )
    db.commit()
    if rowcount(res) == 0:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This request link is closed or full")
    r = db.get(UploadRequest, request_id)
    if r is None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This request link is closed or full")
    return r
