import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ApiKeySummary(BaseModel):
    id: str
    name: str
    prefix: str
    scope: str
    created_at: datetime.datetime
    last_used_at: datetime.datetime | None

    model_config = {"from_attributes": True}


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scope: Literal["full", "upload"] = "full"


class CreateApiKeyResponse(BaseModel):
    id: str
    name: str
    key: str  # shown once
