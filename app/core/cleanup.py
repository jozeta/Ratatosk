import asyncio
import datetime
import logging
import os

from app.core.database import SessionLocal
from app.core.dynamic_settings import get_settings
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.services.audit_service import log_event

logger = logging.getLogger("securedrop.cleanup")

_task: asyncio.Task | None = None


def _delete_blob(storage_dir: str, storage_filename: str) -> None:
    path = os.path.join(storage_dir, storage_filename)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        logger.warning("Failed to remove blob %s", path)


def run_cleanup_once() -> int:
    """Purge expired / exhausted / soft-deleted files from disk and DB. Returns count removed."""
    cfg = get_settings()
    db = SessionLocal()
    removed = 0
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        candidates = db.query(FileObject).filter(FileObject.is_deleted == False).all()  # noqa: E712
        for f in candidates:
            expired = f.expires_at.replace(tzinfo=datetime.timezone.utc) <= now if f.expires_at else False
            exhausted = f.max_downloads > 0 and f.download_count >= f.max_downloads
            if expired or exhausted:
                _delete_blob(cfg["storage_path"], f.storage_filename)
                f.is_deleted = True
                db.add(f)
                db.query(FileShare).filter(FileShare.file_id == f.id).delete()
                log_event(
                    db,
                    event_type="FILE_EXPIRED" if expired else "FILE_EXHAUSTED",
                    file_id=f.id,
                    detail="expired" if expired else "max downloads reached",
                )
                removed += 1
        # hard-delete soft-deleted rows older than a day to keep table tidy
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
        db.commit()
    finally:
        db.close()
    return removed


async def _loop():
    while True:
        try:
            run_cleanup_once()
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
