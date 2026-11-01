import datetime

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.dynamic_settings import get_settings
from app.core.privacy import fuzz_timestamp, get_client_ip, mask_ip, sanitize_user_agent
from app.models.audit_log import AuditLog


def log_event(
    db: Session,
    event_type: str,
    request: Request | None = None,
    file_id: str | None = None,
    user_id: str | None = None,
    actor_token: str | None = None,
    detail: str | None = None,
    commit: bool = True,
) -> AuditLog | None:
    """Record an audit event. Pass commit=False to add it to the caller's
    transaction instead of paying for a separate commit (PERF-009)."""
    cfg = get_settings()
    if cfg.get("disable_audit_log"):
        return None
    zero_log = bool(cfg.get("zero_log_mode"))
    ip_level = "none" if zero_log else cfg.get("ip_obfuscation_level", "masked")

    raw_ip = get_client_ip(request) if request else None
    ip = mask_ip(raw_ip, ip_level)
    ua = sanitize_user_agent(request.headers.get("user-agent") if request else None, zero_log)

    ts = fuzz_timestamp(datetime.datetime.now(datetime.UTC), cfg.get("timestamp_fuzzing", "none"))
    if zero_log:
        actor_token = None  # zero-log means nothing links an event to anyone (SEC-002)

    entry = AuditLog(
        event_type=event_type,
        file_id=file_id,
        user_id=None if zero_log else user_id,
        actor_token=actor_token,
        ip_address=ip,
        user_agent=ua,
        detail=detail,
        timestamp=ts,
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry
