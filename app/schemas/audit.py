import datetime

from pydantic import BaseModel


class AuditLogEntry(BaseModel):
    id: str
    event_type: str
    file_id: str | None
    user_id: str | None
    actor_token: str | None
    ip_address: str | None
    user_agent: str | None
    detail: str | None
    timestamp: datetime.datetime

    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    total: int
    items: list[AuditLogEntry]
