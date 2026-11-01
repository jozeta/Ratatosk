"""File lifecycle rules: claiming a download, deleting files, and the
retryable blob-deletion queue."""
import logging

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.orm import Session

from app.core.database import rowcount, utcnow
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.models.ops import PendingBlobDeletion
from app.services import storage_service

logger = logging.getLogger("ratatosk.files")


def active_file_filter(now=None):
    """SQL condition for 'this file can currently be downloaded'."""
    now = now or utcnow()
    return and_(
        FileObject.is_deleted == False,  # noqa: E712
        FileObject.disabled == False,  # noqa: E712
        FileObject.expires_at > now,
        or_(FileObject.max_downloads == 0, FileObject.download_count < FileObject.max_downloads),
    )


def claim_download(db: Session, file_id: str) -> tuple[bool, bool]:
    """Atomically count one download. Returns (claimed, burned).

    A single conditional UPDATE both checks the limits and consumes the
    download, so concurrent requests can never all pass the check: exactly
    one request gets the last download of a burn-after-download or
    max-downloads file, the rest get (False, _) - BUG-001. (SET expressions
    see the row's pre-update values, so the burn condition uses the old count.)
    """
    will_burn = or_(
        FileObject.burn_after_download == True,  # noqa: E712
        and_(FileObject.max_downloads > 0, FileObject.download_count + 1 >= FileObject.max_downloads),
    )
    res = db.execute(
        update(FileObject)
        .where(FileObject.id == file_id, active_file_filter())
        .values(
            download_count=FileObject.download_count + 1,
            is_deleted=case((will_burn, True), else_=FileObject.is_deleted),
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if rowcount(res) == 0:
        return False, False
    burned = db.execute(select(FileObject.is_deleted).where(FileObject.id == file_id)).scalar_one()
    return True, bool(burned)


def _members_of(db: Session, ids: list[str]) -> list[FileObject]:
    return db.query(FileObject).filter(FileObject.bundle_parent_id.in_(ids), FileObject.is_deleted == False).all()  # noqa: E712


def delete_files(db: Session, files: list[FileObject]) -> list[str]:
    """Mark files (and the members of any bundle among them) deleted, drop
    their shares and server-held keys, and queue their blobs for deletion -
    all in one transaction. Blob removal is then attempted right away; any
    failure stays queued for the cleanup worker to retry (ARCH-007)."""
    targets = {f.id: f for f in files}
    for m in _members_of(db, [f.id for f in files if f.is_bundle]):
        targets.setdefault(m.id, m)
    ids = list(targets)
    if not ids:
        return []
    db.query(FileShare).filter(FileShare.file_id.in_(ids)).delete(synchronize_session=False)
    for f in targets.values():
        f.is_deleted = True
        f.shared_decryption_key = None
        db.add(PendingBlobDeletion(storage_filename=f.storage_filename))
    db.commit()
    process_pending_deletions(db, only=[f.storage_filename for f in targets.values()])
    return ids


def queue_blob_deletion(db: Session, storage_filename: str) -> None:
    db.add(PendingBlobDeletion(storage_filename=storage_filename))
    db.commit()


def process_pending_deletions(db: Session, only: list[str] | None = None, limit: int = 500) -> int:
    """Delete queued blobs; failures stay queued with their error. Returns
    how many were deleted."""
    q = db.query(PendingBlobDeletion)
    if only is not None:
        q = q.filter(PendingBlobDeletion.storage_filename.in_(only))
    done = 0
    for row in q.order_by(PendingBlobDeletion.created_at).limit(limit).all():
        try:
            storage_service.delete_blob(row.storage_filename)
        except Exception as e:  # storage outage etc. - retry next pass
            row.attempts += 1
            row.last_error = f"{type(e).__name__}: {e}"[:256]
            logger.warning("blob deletion failed (attempt %d): %s", row.attempts, row.last_error)
        else:
            db.delete(row)
            done += 1
    db.commit()
    return done
