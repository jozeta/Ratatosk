import datetime
import math
import os
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db, rowcount, utcnow
from app.core.dynamic_settings import get_settings
from app.core.ratelimit import check_rate
from app.core.security import get_current_user
from app.core.ttl import is_allowed_ttl, parse_ttl
from app.models.file import FileObject
from app.models.ops import UploadChunk
from app.models.upload_session import UploadSession
from app.models.user import User
from app.schemas.upload import (
    CompleteUploadRequest,
    CompleteUploadResponse,
    InitUploadRequest,
    InitUploadResponse,
    UploadStatusResponse,
)
from app.services import storage_service
from app.services.audit_service import log_event

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

ANON_COOKIE = "sd_anon_token"
# An upload with no chunk activity for this long no longer counts against the
# uploader's concurrent-upload limit, and the cleanup worker purges it (and
# its staged .part file) - see app/core/cleanup.py.
UPLOAD_SESSION_IDLE_TIMEOUT = datetime.timedelta(hours=1)
# Encryption adds a small fixed header plus a 16-byte tag per 1 MiB segment;
# the size limit admins configure is for the *file*, so allow that overhead
# on the ciphertext (BUG-006: a file exactly at the limit was rejected).
SEGMENT_SIZE = 1024 * 1024
FIXED_OVERHEAD = 64 * 1024
WRITE_BLOCK = 1024 * 1024
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def ciphertext_allowance(max_plain_bytes: int) -> int:
    return max_plain_bytes + math.ceil(max_plain_bytes / SEGMENT_SIZE) * 16 + FIXED_OVERHEAD


def _actor_token(request: Request, user: User | None) -> str | None:
    """Identifies who is uploading: the account if logged in, otherwise the
    anonymous cookie set by /init. Used only to tie an upload session's
    requests together - never stored with the finished file (SEC-003)."""
    if user:
        return f"user:{user.id}"
    token = request.cookies.get(ANON_COOKIE)
    return f"anon:{token}" if token else None


def _get_owned_session(db: Session, upload_id: str, actor: str | None) -> UploadSession:
    session = db.get(UploadSession, upload_id)
    # Same 404 whether the id doesn't exist or belongs to someone else, so a
    # caller can't probe for other people's in-progress upload ids.
    if session is None or actor is None or session.actor != actor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown upload")
    return session


def _validate_extension(extension: str | None, cfg: dict) -> None:
    if not extension:
        return
    ext = extension.lower().lstrip(".")
    listed = {e.strip().lower() for e in cfg["extension_list"].split(",") if e.strip()}
    if cfg["extension_rule_mode"] == "whitelist" and ext not in listed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Extension .{ext} not permitted")
    if cfg["extension_rule_mode"] == "blacklist" and ext in listed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Extension .{ext} not permitted")


def _contiguous_prefix(db: Session, upload_id: str) -> int:
    """Bytes received without gaps from offset 0 - where a resume continues."""
    end = 0
    for off, length in db.execute(
        select(UploadChunk.offset, UploadChunk.length).where(UploadChunk.upload_id == upload_id).order_by(UploadChunk.offset)
    ):
        if off > end:
            break
        end = max(end, off + length)
    return end


@router.post("/init", response_model=InitUploadResponse)
def init_upload(
    payload: InitUploadRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    cfg = get_settings()

    upload_request = None
    if payload.request_id:
        # Request links are the one way to upload without an account even
        # when anonymous uploads are off - that's their purpose (FEAT-001).
        from app.api.e2e import _is_open
        from app.models.upload_request import UploadRequest

        if not cfg["enable_upload_requests"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Upload request links are disabled on this site")
        upload_request = db.get(UploadRequest, payload.request_id)
        if upload_request is None or not _is_open(upload_request):
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="This request link is closed or full")
    elif user is None and not cfg["allow_anonymous_upload"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Anonymous uploads are disabled")
    if user is None:
        # Discarding the cookie used to give unlimited sessions; anonymous
        # starts are now also rate limited per client network (SEC-011).
        check_rate(request, "upload-init", cfg)

    limit_mb = min(cfg["max_file_size_mb"], upload_request.max_file_size_mb) if upload_request else cfg["max_file_size_mb"]
    max_plain = limit_mb * 1024 * 1024
    max_bytes = ciphertext_allowance(max_plain)
    if payload.total_size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds max size of {limit_mb}MB",
        )

    _validate_extension(payload.extension, cfg)

    # Capacity counts bytes already reserved by uploads in progress, so many
    # parallel uploads can't each pass the check and overcommit (SEC-011).
    if not storage_service.has_capacity(db, payload.total_size_bytes):
        raise HTTPException(status_code=status.HTTP_507_INSUFFICIENT_STORAGE, detail="Storage capacity exceeded")

    active_cutoff = utcnow() - UPLOAD_SESSION_IDLE_TIMEOUT
    total_active = db.query(UploadSession).filter(UploadSession.last_activity_at > active_cutoff).count()
    if total_active >= cfg["max_active_upload_sessions"]:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Server is busy - try again shortly")

    if user is None and not request.cookies.get(ANON_COOKIE):
        # Issue the cookie *before* deriving the actor, so this very upload is
        # keyed to the same identity its chunks and /complete will present.
        # Short-lived and scoped to the upload API: it only needs to tie one
        # upload's requests together, not to follow a visitor around (SEC-003).
        anon_token = str(uuid.uuid4())
        response.set_cookie(ANON_COOKIE, anon_token, httponly=True, samesite="strict", max_age=6 * 3600,
                            path="/api/uploads", secure=request.url.scheme == "https")
        actor = f"anon:{anon_token}"
    else:
        maybe_actor = _actor_token(request, user)
        if maybe_actor is None:  # anonymous with a cookie always has an actor; defensive
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing upload session cookie")
        actor = maybe_actor

    active = (
        db.query(UploadSession)
        .filter(UploadSession.actor == actor, UploadSession.last_activity_at > active_cutoff)
        .count()
    )
    if active >= cfg["max_concurrent_uploads"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Max {cfg['max_concurrent_uploads']} concurrent uploads allowed",
        )

    session = UploadSession(
        actor=actor,
        declared_size=payload.total_size_bytes,
        extension=(payload.extension or "").lower().lstrip(".") or None,
        request_id=upload_request.id if upload_request else None,
    )
    db.add(session)
    db.commit()

    open(storage_service.tmp_path_for(session.id), "wb").close()

    return InitUploadResponse(
        upload_id=session.id,
        chunk_size_bytes=cfg["chunk_size_mb"] * 1024 * 1024,
        max_size_bytes=max_bytes,
    )


@router.put("/{upload_id}/chunk")
async def upload_chunk(
    upload_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    """Write one chunk at its byte offset.

    The body is streamed to disk in bounded blocks: the old code buffered the
    whole request in RAM before checking its size, so one 400 MiB request
    grew the server by ~800 MiB (SEC-004). The size bound is positional -
    nothing is ever written past the declared size - and a chunk that was
    already received (a retried PUT) is overwritten in place rather than
    appended a second time (BUG-008). Clients send `Upload-Offset`; without
    it (older clients) the chunk is appended at the current end.
    """
    session = _get_owned_session(db, upload_id, _actor_token(request, user))
    path = storage_service.tmp_path_for(upload_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload data missing")

    header = request.headers.get("upload-offset")
    if header is None:
        offset = os.path.getsize(path)
    else:
        if not header.isdigit():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Upload-Offset")
        offset = int(header)
    limit = session.declared_size - offset
    if limit < 0:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Upload exceeds declared size")
    declared_len = request.headers.get("content-length")
    if declared_len and declared_len.isdigit() and int(declared_len) > limit:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Upload exceeds declared size")

    written = 0
    pending = bytearray()
    with open(path, "r+b") as fh:
        fh.seek(offset)
        async for part in request.stream():
            if written + len(pending) + len(part) > limit:
                raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Upload exceeds declared size")
            pending += part
            if len(pending) >= WRITE_BLOCK:
                fh.write(pending)
                written += len(pending)
                pending.clear()
        if pending:
            fh.write(pending)
            written += len(pending)

    if written:
        # A resume restarts at the end of the contiguous prefix, so it can
        # re-send ranges that were already received out of order at other
        # offsets. The ciphertext is deterministic, so the newest write is
        # correct: drop any record it overlaps so chunks always tile cleanly.
        db.execute(delete(UploadChunk).where(
            UploadChunk.upload_id == upload_id,
            UploadChunk.offset != offset,
            UploadChunk.offset < offset + written,
            UploadChunk.offset + UploadChunk.length > offset,
        ))
        try:
            db.add(UploadChunk(upload_id=upload_id, offset=offset, length=written))
            db.commit()
        except IntegrityError:
            db.rollback()  # same offset received before: a retry, already recorded
            existing = db.execute(
                select(UploadChunk).where(UploadChunk.upload_id == upload_id, UploadChunk.offset == offset)
            ).scalar_one()
            existing.length = max(existing.length, written)
            db.commit()
    received = db.execute(select(func.coalesce(func.sum(UploadChunk.length), 0)).where(UploadChunk.upload_id == upload_id)).scalar_one()
    db.execute(update(UploadSession).where(UploadSession.id == upload_id).values(bytes_written=received, last_activity_at=utcnow()))
    db.commit()
    return {"received_bytes": received, "offset": offset, "length": written}


@router.get("/{upload_id}", response_model=UploadStatusResponse)
def upload_status(upload_id: str, request: Request, db: Session = Depends(get_db), user: User | None = Depends(get_current_user)):
    """Where an interrupted upload should resume from (FEAT-004)."""
    session = _get_owned_session(db, upload_id, _actor_token(request, user))
    return UploadStatusResponse(upload_id=session.id, declared_size=session.declared_size, resume_offset=_contiguous_prefix(db, upload_id))


@router.delete("/{upload_id}")
def cancel_upload(upload_id: str, request: Request, db: Session = Depends(get_db), user: User | None = Depends(get_current_user)):
    """Abandon an upload now instead of waiting for the idle timeout (UI-002)."""
    _get_owned_session(db, upload_id, _actor_token(request, user))
    db.execute(delete(UploadChunk).where(UploadChunk.upload_id == upload_id))
    db.execute(delete(UploadSession).where(UploadSession.id == upload_id))
    db.commit()
    try:
        os.remove(storage_service.tmp_path_for(upload_id))
    except FileNotFoundError:
        pass
    return {"ok": True}


@router.post("/{upload_id}/complete", response_model=CompleteUploadResponse)
def complete_upload(
    upload_id: str,
    payload: CompleteUploadRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    cfg = get_settings()
    actor = _actor_token(request, user)
    session = _get_owned_session(db, upload_id, actor)

    if payload.password is not None:
        # Old clients sent the passphrase itself, which let the server (and
        # anything logging requests) decrypt the file (SEC-001). Refuse rather
        # than silently accept a passphrase the server must never see.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This client sends the passphrase to the server, which is no longer accepted - please update it",
        )
    if payload.download_token_hash is not None and not HEX64.match(payload.download_token_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid download token hash")
    if payload.passphrase_protected and not (payload.download_token_hash and payload.kdf_salt and payload.kdf_iterations):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passphrase uploads must include their KDF parameters and token hash")

    if session.request_id and not (payload.wrapped_key and payload.ephemeral_public_key and payload.download_token_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request-link uploads must be wrapped to the owner's key")
    if session.request_id and (payload.passphrase_protected or payload.is_bundle):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request-link uploads can't use a passphrase or bundles")

    # When the admin has locked TTL/max-downloads to a fixed value, ignore
    # whatever the client sent rather than trusting it.
    ttl = payload.ttl if cfg["allow_custom_ttl"] else cfg["default_ttl"]
    # Request-link uploads use the owner's retention choice, validated when
    # the link was created - the sender's value is ignored entirely.
    if not session.request_id and not is_allowed_ttl(ttl, cfg["allowed_ttl_presets"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TTL not permitted by policy")

    # The server can't verify a passphrase it never sees, so this is the
    # client's declaration - enforced for every unmodified client.
    if payload.passphrase_protected and not cfg["allow_secondary_password"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Secondary passphrases are disabled")
    if cfg["enforce_secondary_password"] and not payload.passphrase_protected and not session.request_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A secondary password is required")

    def _reject(detail: str):
        # If a concurrent /complete already claimed this session, the data
        # looks "incomplete" only because the winner consumed it - report
        # that as the 404 it is, not as a broken upload the client should
        # retry (found by test_parallel_complete_one_wins).
        db.expire_all()
        if db.get(UploadSession, upload_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown upload")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    tmp_path = storage_service.tmp_path_for(upload_id)
    chunks = db.execute(
        select(UploadChunk.offset, UploadChunk.length).where(UploadChunk.upload_id == upload_id).order_by(UploadChunk.offset)
    ).all()
    end = 0
    for off, length in chunks:
        if off != end:
            _reject("Upload has missing or overlapping chunks")
        end = off + length
    try:
        actual_size = os.path.getsize(tmp_path)
    except FileNotFoundError:
        actual_size = -1
    if end != session.declared_size or actual_size != end:
        _reject("Upload data incomplete")

    # Claim the session atomically: of two concurrent /complete calls exactly
    # one proceeds; the other gets a clean 404 instead of a 500 (BUG-009).
    claimed = db.execute(delete(UploadSession).where(UploadSession.id == upload_id, UploadSession.actor == actor))
    db.execute(delete(UploadChunk).where(UploadChunk.upload_id == upload_id))
    db.commit()
    if rowcount(claimed) == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown upload")

    burn = (payload.burn_after_download and cfg["allow_burn_after_download"]) or cfg["force_burn_after_download"]
    max_downloads = (payload.max_downloads or cfg["default_max_downloads"]) if cfg["allow_custom_max_downloads"] else cfg["default_max_downloads"]
    notify_on_download = bool(payload.notify_on_download and user is not None)
    owner_id = user.id if user else None

    upload_request = None
    if session.request_id:
        # The submission belongs to the request's owner and follows the
        # owner's retention choice; the slot is claimed atomically so a
        # link's upload limit can't be exceeded by parallel submissions.
        from app.api.e2e import claim_request_slot

        upload_request = claim_request_slot(db, session.request_id)
        ttl, burn, max_downloads, notify_on_download = upload_request.file_ttl, False, 0, False
        owner_id = upload_request.owner_id

    members: list[FileObject] = []
    if payload.bundle_member_ids:
        # Only a logged-in owner's own, unbundled files can be grouped; for
        # anonymous uploads there's no owner to show the grouping to anyway.
        if user is not None:
            members = (
                db.query(FileObject)
                .filter(FileObject.id.in_(payload.bundle_member_ids), FileObject.owner_id == user.id,
                        FileObject.bundle_parent_id.is_(None), FileObject.is_deleted == False)  # noqa: E712
                .all()
            )

    storage_filename, size = storage_service.finalize_blob(tmp_path)
    expires_at = utcnow() + parse_ttl(ttl)

    file_obj = FileObject(
        storage_filename=storage_filename,
        size_bytes=size,
        owner_id=owner_id,
        uploader_token="",  # nosec B106 - not a password; see FileObject.uploader_token
        download_token_hash=payload.download_token_hash,
        kdf_salt=payload.kdf_salt if payload.passphrase_protected else None,
        kdf_iterations=payload.kdf_iterations if payload.passphrase_protected else None,
        passphrase_protected=bool(payload.passphrase_protected),
        burn_after_download=burn,
        max_downloads=max_downloads,
        expires_at=expires_at,
        extension=session.extension,
        notify_on_download=notify_on_download,
        is_bundle=bool(payload.is_bundle),
        request_id=upload_request.id if upload_request else None,
        wrapped_key=payload.wrapped_key if upload_request else None,
        ephemeral_public_key=payload.ephemeral_public_key if upload_request else None,
    )
    db.add(file_obj)
    db.flush()
    for m in members:
        m.bundle_parent_id = file_obj.id
        # Members live exactly as long as their bundle.
        m.expires_at = expires_at

    zero_log = cfg["zero_log_mode"]
    # In zero-log mode nothing ties the event to anyone: no request (IP/UA),
    # no user id, and no actor token. This used to be inverted - zero-log was
    # the *only* mode that stored the uploader's identity (SEC-002).
    log_event(
        db,
        event_type="REQUEST_UPLOAD" if upload_request else ("ANON_UPLOAD" if (user is None and zero_log) else "UPLOAD"),
        request=None if zero_log else request,
        file_id=file_obj.id,
        user_id=user.id if user else None,
        detail=f"size={size}",
        commit=False,
    )
    db.commit()
    db.refresh(file_obj)
    return CompleteUploadResponse(file_id=file_obj.id, expires_at=expires_at.isoformat())
