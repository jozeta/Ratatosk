import collections
import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dynamic_settings import get_settings
from app.core.security import require_admin
from app.models.audit_log import AuditLog
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.models.user import User
from app.schemas.common import BatchIds
from app.services import storage_service
from app.services.audit_service import log_event

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_enabled():
    if not get_settings()["enable_file_management"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="File management is disabled in settings")


@router.get("/files")
def list_all_files(
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    _require_enabled()
    now = datetime.datetime.now(datetime.timezone.utc)
    q = db.query(FileObject).filter(FileObject.is_deleted == False)  # noqa: E712
    total = q.count()
    files = q.order_by(FileObject.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    owner_ids = {f.owner_id for f in files if f.owner_id}
    owners = {}
    if owner_ids:
        for u in db.query(User).filter(User.id.in_(owner_ids)).all():
            owners[u.id] = u.username

    items = [
        {
            "file_id": f.id,
            "owner": owners.get(f.owner_id, "anonymous"),
            "size_bytes": f.size_bytes,
            "created_at": f.created_at.isoformat(),
            "expires_at": f.expires_at.isoformat(),
            "burn_after_download": f.burn_after_download,
            "max_downloads": f.max_downloads,
            "download_count": f.download_count,
            "password_protected": bool(f.password_hash),
            "expired": f.expires_at.replace(tzinfo=datetime.timezone.utc) <= now,
        }
        for f in files
    ]
    return {"total": total, "items": items}


@router.delete("/files/{file_id}")
def admin_delete_file(file_id: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _require_enabled()
    f = db.get(FileObject, file_id)
    if f is None or f.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    f.is_deleted = True
    db.query(FileShare).filter(FileShare.file_id == f.id).delete()
    db.commit()
    storage_service.delete_blob(f.storage_filename)
    log_event(db, "FILE_DELETED", request=request, file_id=f.id, user_id=admin.id, detail="deleted by admin")
    return {"ok": True}


@router.post("/files/batch-delete")
def admin_batch_delete_files(payload: BatchIds, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _require_enabled()
    files = db.query(FileObject).filter(FileObject.id.in_(payload.ids), FileObject.is_deleted == False).all()  # noqa: E712
    deleted_ids = [f.id for f in files]

    if deleted_ids:
        db.query(FileShare).filter(FileShare.file_id.in_(deleted_ids)).delete(synchronize_session=False)
        db.query(FileObject).filter(FileObject.id.in_(deleted_ids)).update(
            {"is_deleted": True}, synchronize_session=False
        )
        db.commit()
        for f in files:
            storage_service.delete_blob(f.storage_filename)
        log_event(
            db,
            "FILE_DELETED",
            request=request,
            user_id=admin.id,
            detail=f"batch deleted {len(deleted_ids)} file(s) by admin",
        )

    skipped = [i for i in payload.ids if i not in deleted_ids]
    return {"deleted": len(deleted_ids), "skipped": skipped}


@router.get("/stats")
def get_stats(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cfg = get_settings()
    now = datetime.datetime.now(datetime.timezone.utc)

    active_files_q = db.query(FileObject).filter(FileObject.is_deleted == False)  # noqa: E712
    active_files = active_files_q.all()
    active_count = len(active_files)
    active_bytes = sum(f.size_bytes for f in active_files)
    expired_active_count = sum(
        1 for f in active_files if f.expires_at.replace(tzinfo=datetime.timezone.utc) <= now
    )

    total_uploads = db.query(AuditLog).filter(AuditLog.event_type.in_(["UPLOAD", "ANON_UPLOAD"])).count()
    total_downloads = db.query(AuditLog).filter(AuditLog.event_type == "DOWNLOAD").count()
    total_burned = db.query(AuditLog).filter(AuditLog.event_type == "FILE_BURNED").count()
    total_expired_events = db.query(AuditLog).filter(AuditLog.event_type == "FILE_EXPIRED").count()
    total_deleted_events = db.query(AuditLog).filter(AuditLog.event_type == "FILE_DELETED").count()
    total_users = db.query(User).count()

    storage_used_bytes = storage_service.get_storage_usage_bytes()
    storage_cap_bytes = cfg["total_storage_cap_gb"] * 1024 * 1024 * 1024

    ext_counts: collections.Counter = collections.Counter()
    for f in active_files:
        ext_counts[(f.extension or "(none)").lower()] += 1
    extension_breakdown = [{"extension": ext, "count": count} for ext, count in ext_counts.most_common(8)]
    other_count = sum(ext_counts.values()) - sum(e["count"] for e in extension_breakdown)
    if other_count > 0:
        extension_breakdown.append({"extension": "other", "count": other_count})

    return {
        "active_files": active_count,
        "active_files_pending_cleanup": expired_active_count,
        "active_bytes": active_bytes,
        "total_uploads": total_uploads,
        "total_downloads": total_downloads,
        "total_burned": total_burned,
        "total_expired_events": total_expired_events,
        "total_deleted_events": total_deleted_events,
        "total_users": total_users,
        "storage_used_bytes": storage_used_bytes,
        "storage_cap_bytes": storage_cap_bytes,
        "extension_breakdown": extension_breakdown,
    }


_RANGE_CONFIG = {
    "7d": (7, "day"),
    "30d": (30, "day"),
    "6m": (183, "week"),
    "1y": (365, "month"),
}


def _bucket_key(ts: datetime.datetime, granularity: str) -> str:
    if granularity == "day":
        return ts.date().isoformat()
    if granularity == "week":
        monday = ts.date() - datetime.timedelta(days=ts.weekday())
        return monday.isoformat()
    return f"{ts.year:04d}-{ts.month:02d}"


def _build_buckets(cutoff: datetime.date, today: datetime.date, granularity: str) -> list[str]:
    keys: list[str] = []
    if granularity == "day":
        d = cutoff
        while d <= today:
            keys.append(d.isoformat())
            d += datetime.timedelta(days=1)
    elif granularity == "week":
        d = cutoff - datetime.timedelta(days=cutoff.weekday())
        end = today
        while d <= end:
            keys.append(d.isoformat())
            d += datetime.timedelta(weeks=1)
    else:  # month
        y, m = cutoff.year, cutoff.month
        while (y, m) <= (today.year, today.month):
            keys.append(f"{y:04d}-{m:02d}")
            m += 1
            if m > 12:
                m = 1
                y += 1
    return keys


@router.get("/stats/timeseries")
def get_stats_timeseries(range: str = "30d", db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if range not in _RANGE_CONFIG:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid range")
    days, granularity = _RANGE_CONFIG[range]

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=days)

    rows = (
        db.query(AuditLog.event_type, AuditLog.timestamp)
        .filter(AuditLog.event_type.in_(["UPLOAD", "ANON_UPLOAD", "DOWNLOAD"]), AuditLog.timestamp >= cutoff)
        .all()
    )

    counts: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"uploads": 0, "downloads": 0})
    for event_type, ts in rows:
        ts = ts.replace(tzinfo=datetime.timezone.utc) if ts.tzinfo is None else ts
        key = _bucket_key(ts, granularity)
        if event_type in ("UPLOAD", "ANON_UPLOAD"):
            counts[key]["uploads"] += 1
        else:
            counts[key]["downloads"] += 1

    bucket_keys = _build_buckets(cutoff.date(), now.date(), granularity)
    buckets = [{"label": key, "uploads": counts[key]["uploads"], "downloads": counts[key]["downloads"]} for key in bucket_keys]

    return {"granularity": granularity, "buckets": buckets}
