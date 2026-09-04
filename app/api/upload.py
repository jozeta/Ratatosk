import datetime
import os
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dynamic_settings import get_settings
from app.core.security import get_current_user, hash_password
from app.core.ttl import is_allowed_ttl, parse_ttl
from app.models.file import FileObject
from app.models.user import User
from app.schemas.upload import (
    CompleteUploadRequest,
    CompleteUploadResponse,
    InitUploadRequest,
    InitUploadResponse,
)
from app.services import storage_service
from app.services.audit_service import log_event

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

_active_lock = threading.Lock()
_active_uploads: dict[str, set[str]] = {}  # actor_token -> set of upload_ids
_upload_meta: dict[str, dict] = {}  # upload_id -> {"actor": token, "bytes_written": int, "cap": int}


def _actor_token(request: Request, user: User | None) -> str:
    if user:
        return f"user:{user.id}"
    token = request.cookies.get("sd_anon_token")
    return f"anon:{token or request.client.host if request.client else 'unknown'}"


def _validate_extension(extension: str | None, cfg: dict) -> None:
    if not extension:
        return
    ext = extension.lower().lstrip(".")
    listed = {e.strip().lower() for e in cfg["extension_list"].split(",") if e.strip()}
    if cfg["extension_rule_mode"] == "whitelist" and ext not in listed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Extension .{ext} not permitted")
    if cfg["extension_rule_mode"] == "blacklist" and ext in listed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Extension .{ext} not permitted")


@router.post("/init", response_model=InitUploadResponse)
def init_upload(
    payload: InitUploadRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    cfg = get_settings()

    if user is None and not cfg["allow_anonymous_upload"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Anonymous uploads are disabled")

    max_bytes = cfg["max_file_size_mb"] * 1024 * 1024
    if payload.total_size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds max size of {cfg['max_file_size_mb']}MB",
        )

    _validate_extension(payload.extension, cfg)

    if not storage_service.has_capacity(payload.total_size_bytes):
        raise HTTPException(status_code=status.HTTP_507_INSUFFICIENT_STORAGE, detail="Storage capacity exceeded")

    actor = _actor_token(request, user)
    anon_token = request.cookies.get("sd_anon_token")
    if user is None and not anon_token:
        anon_token = str(uuid.uuid4())
        response.set_cookie("sd_anon_token", anon_token, httponly=True, samesite="lax", max_age=3600 * 24 * 30)

    with _active_lock:
        active = _active_uploads.setdefault(actor, set())
        if len(active) >= cfg["max_concurrent_uploads"]:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Max {cfg['max_concurrent_uploads']} concurrent uploads allowed",
            )
        upload_id = str(uuid.uuid4())
        active.add(upload_id)
        _upload_meta[upload_id] = {
            "actor": actor,
            "bytes_written": 0,
            "cap": payload.total_size_bytes,
            "extension": (payload.extension or "").lower().lstrip(".") or None,
        }

    open(storage_service.tmp_path_for(upload_id), "wb").close()

    return InitUploadResponse(
        upload_id=upload_id,
        chunk_size_bytes=cfg["chunk_size_mb"] * 1024 * 1024,
        max_size_bytes=max_bytes,
    )


@router.put("/{upload_id}/chunk")
async def upload_chunk(upload_id: str, request: Request):
    meta = _upload_meta.get(upload_id)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown upload")

    body = await request.body()
    meta["bytes_written"] += len(body)
    if meta["bytes_written"] > meta["cap"] + (10 * 1024 * 1024):
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Upload exceeds declared size")

    path = storage_service.tmp_path_for(upload_id)
    with open(path, "ab") as f:
        f.write(body)

    return {"received_bytes": meta["bytes_written"]}


@router.post("/{upload_id}/complete", response_model=CompleteUploadResponse)
def complete_upload(
    upload_id: str,
    payload: CompleteUploadRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    cfg = get_settings()
    meta = _upload_meta.get(upload_id)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown upload")

    tmp_path = storage_service.tmp_path_for(upload_id)
    if not os.path.exists(tmp_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload data missing")

    # When the admin has locked TTL/max-downloads to a fixed value, ignore
    # whatever the client sent rather than trusting it - the whole point of
    # "off" is that uploaders can't override it themselves.
    ttl = payload.ttl if cfg["allow_custom_ttl"] else cfg["default_ttl"]
    if not is_allowed_ttl(ttl, cfg["allowed_ttl_presets"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TTL not permitted by policy")

    if payload.password and not cfg["allow_secondary_password"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Secondary passphrases are disabled")
    if cfg["enforce_secondary_password"] and not payload.password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A secondary password is required")

    burn = (payload.burn_after_download and cfg["allow_burn_after_download"]) or cfg["force_burn_after_download"]
    max_downloads = (payload.max_downloads or cfg["default_max_downloads"]) if cfg["allow_custom_max_downloads"] else cfg["default_max_downloads"]
    # Anonymous uploads have no owner/email to notify, regardless of what the
    # client sent - same "server enforces what it can actually apply" rule
    # as burn_after_download above.
    notify_on_download = bool(payload.notify_on_download and user is not None)

    storage_filename, size = storage_service.finalize_blob(tmp_path)
    expires_at = datetime.datetime.now(datetime.timezone.utc) + parse_ttl(ttl)

    actor = _actor_token(request, user)
    file_obj = FileObject(
        storage_filename=storage_filename,
        size_bytes=size,
        owner_id=user.id if user else None,
        uploader_token=actor,
        password_hash=hash_password(payload.password) if payload.password else None,
        burn_after_download=burn,
        max_downloads=max_downloads,
        expires_at=expires_at,
        extension=meta.get("extension"),
        notify_on_download=notify_on_download,
    )
    db.add(file_obj)
    db.commit()
    db.refresh(file_obj)

    with _active_lock:
        _active_uploads.get(actor, set()).discard(upload_id)
        _upload_meta.pop(upload_id, None)

    zero_log = cfg["zero_log_mode"]
    log_event(
        db,
        event_type="ANON_UPLOAD" if (user is None and zero_log) else "UPLOAD",
        request=None if zero_log else request,
        file_id=file_obj.id,
        user_id=user.id if user else None,
        actor_token=actor if zero_log else None,
        detail=f"size={size}",
    )

    return CompleteUploadResponse(file_id=file_obj.id, expires_at=expires_at.isoformat())
