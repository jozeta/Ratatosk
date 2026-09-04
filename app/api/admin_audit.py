import csv
import datetime
import io
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit import AuditLogEntry, AuditLogPage

router = APIRouter(prefix="/api/admin/audit", tags=["admin"])


def _apply_filters(query, event_type, file_id, since, until, search):
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    if file_id:
        query = query.filter(AuditLog.file_id == file_id)
    if since:
        query = query.filter(AuditLog.timestamp >= since)
    if until:
        query = query.filter(AuditLog.timestamp <= until)
    if search:
        like = f"%{search}%"
        query = query.filter(AuditLog.detail.ilike(like))
    return query


@router.get("", response_model=AuditLogPage)
def list_audit_logs(
    event_type: str | None = None,
    file_id: str | None = None,
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = _apply_filters(db.query(AuditLog), event_type, file_id, since, until, search)
    total = q.count()
    items = q.order_by(AuditLog.timestamp.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return AuditLogPage(total=total, items=[AuditLogEntry.model_validate(i) for i in items])


@router.get("/export")
def export_audit_logs(
    format: str = Query("csv", pattern="^(csv|json)$"),
    event_type: str | None = None,
    file_id: str | None = None,
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = _apply_filters(db.query(AuditLog), event_type, file_id, since, until, search)
    items = q.order_by(AuditLog.timestamp.desc()).all()

    fields = ["id", "event_type", "file_id", "user_id", "actor_token", "ip_address", "user_agent", "detail", "timestamp"]

    if format == "json":
        payload = [{k: (getattr(i, k).isoformat() if k == "timestamp" else getattr(i, k)) for k in fields} for i in items]
        return StreamingResponse(
            io.BytesIO(json.dumps(payload, indent=2).encode()),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=audit_log.json"},
        )

    def _csv_safe(value):
        # Several of these fields (detail, user_agent, actor_token) can
        # contain attacker-influenced text - e.g. a failed-login username
        # gets logged verbatim. Excel/Sheets treats a leading =, +, -, or @
        # as a formula, so a crafted username could execute code on whoever
        # opens the export. Prefixing with a quote neutralizes that without
        # changing the visible value for anything legitimate.
        s = "" if value is None else str(value)
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for i in items:
        writer.writerow({k: _csv_safe(getattr(i, k).isoformat() if k == "timestamp" else getattr(i, k)) for k in fields})
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


@router.post("/prune")
def prune_audit_logs(days: int = Query(90), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    deleted = db.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete()
    db.commit()
    return {"deleted": deleted}
