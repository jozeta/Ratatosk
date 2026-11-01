"""Periodic maintenance: expire files, retry blob deletions, purge stale rows.

- Deletion goes through the storage backend. It used to call os.remove()
  on a local path, so expired files were never removed from S3 (BUG-005).
- Expired/exhausted files are selected in SQL, in batches, instead of
  loading every active row into Python each pass (PERF-002).
- The pass runs in a worker thread, so it no longer blocks the event loop
  and every request on that worker while it runs (PERF-002).
- A database lease makes sure only one process runs a pass at a time, even
  with several workers or hosts (ARCH-001).
"""
import asyncio
import datetime
import logging
import os
import socket
import uuid

from sqlalchemy import delete, or_, update
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal, rowcount, utcnow
from app.core.dynamic_settings import get_settings
from app.models.audit_log import AuditLog
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.models.ops import Lease, LoginThrottle, PendingBlobDeletion, RevokedToken, UploadChunk
from app.models.upload_session import UploadSession
from app.services.audit_service import log_event
from app.services.files import process_pending_deletions

logger = logging.getLogger("ratatosk.cleanup")

LEASE_NAME = "cleanup"
BATCH = 500
_holder = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
_task: asyncio.Task | None = None


def _acquire_lease(db, seconds: int) -> bool:
    now = utcnow()
    until = now + datetime.timedelta(seconds=seconds)
    try:
        db.add(Lease(name=LEASE_NAME, holder=_holder, until=until))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
    res = db.execute(
        update(Lease)
        .where(Lease.name == LEASE_NAME, or_(Lease.until < now, Lease.holder == _holder))
        .values(holder=_holder, until=until)
    )
    db.commit()
    return rowcount(res) > 0


def _expire_files(db, now) -> int:
    removed = 0
    while True:
        batch = (
            db.query(FileObject)
            .filter(
                FileObject.is_deleted == False,  # noqa: E712
                or_(
                    FileObject.expires_at <= now,
                    (FileObject.max_downloads > 0) & (FileObject.download_count >= FileObject.max_downloads),
                ),
            )
            .limit(BATCH)
            .all()
        )
        if not batch:
            return removed
        ids = [f.id for f in batch]
        db.query(FileShare).filter(FileShare.file_id.in_(ids)).delete(synchronize_session=False)
        for f in batch:
            expired = f.expires_at <= now
            f.is_deleted = True
            f.shared_decryption_key = None
            db.add(PendingBlobDeletion(storage_filename=f.storage_filename))
            log_event(db, "FILE_EXPIRED" if expired else "FILE_EXHAUSTED", file_id=f.id,
                      detail="expired" if expired else "max downloads reached", commit=False)
        db.commit()
        removed += len(batch)


def _purge_abandoned_uploads(db, now: datetime.datetime) -> None:
    """Drop upload sessions that never reached /complete (closed tab, crashed
    script) along with their staged .part files and chunk records."""
    from app.api.upload import UPLOAD_SESSION_IDLE_TIMEOUT
    from app.services import storage_service

    cutoff = now - UPLOAD_SESSION_IDLE_TIMEOUT
    for session in db.query(UploadSession).filter(UploadSession.last_activity_at < cutoff).all():
        try:
            os.remove(storage_service.tmp_path_for(session.id))
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Failed to remove staged upload %s", session.id)
        db.execute(delete(UploadChunk).where(UploadChunk.upload_id == session.id))
        db.delete(session)
    db.commit()


def run_cleanup_once(force: bool = False) -> int:
    """One maintenance pass. Returns the number of files expired. Skips
    (returns 0) if another process holds the lease, unless force=True."""
    cfg = get_settings()
    db = SessionLocal()
    try:
        interval = max(1, int(cfg.get("cleanup_interval_minutes", 5))) * 60
        if not force and not _acquire_lease(db, seconds=max(60, interval - 5)):
            return 0
        now = utcnow()
        removed = _expire_files(db, now)
        process_pending_deletions(db)

        # Hard-delete soft-deleted rows a day after expiry to keep tables tidy.
        cutoff = now - datetime.timedelta(days=1)
        stale_ids = [
            row.id
            for row in db.query(FileObject.id).filter(
                FileObject.is_deleted == True,  # noqa: E712
                FileObject.expires_at < cutoff,
            )
        ]
        if stale_ids:
            db.query(FileShare).filter(FileShare.file_id.in_(stale_ids)).delete(synchronize_session=False)
            db.query(FileObject).filter(FileObject.id.in_(stale_ids)).delete(synchronize_session=False)

        _purge_abandoned_uploads(db, now)
        db.execute(delete(RevokedToken).where(RevokedToken.expires_at < now))
        db.execute(delete(LoginThrottle).where(
            or_(LoginThrottle.locked_until < now,
                (LoginThrottle.locked_until.is_(None)) & (LoginThrottle.updated_at < now - datetime.timedelta(days=1)))
        ))
        # The audit retention setting existed but nothing applied it.
        retention = int(cfg.get("audit_log_retention_days") or 0)
        if retention > 0:
            db.execute(delete(AuditLog).where(AuditLog.timestamp < now - datetime.timedelta(days=retention)))
        db.commit()
        return removed
    finally:
        db.close()


async def _loop():
    while True:
        try:
            await asyncio.to_thread(run_cleanup_once)
        except Exception:
            logger.exception("cleanup pass failed")
        interval = max(1, int(get_settings().get("cleanup_interval_minutes", 5)))
        await asyncio.sleep(interval * 60)


def start_background_cleanup():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
    return _task


def stop_background_cleanup():
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
