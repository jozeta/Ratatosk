from pydantic import BaseModel, Field


class SystemResetRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class SystemResetResponse(BaseModel):
    admin_username: str
    admin_password: str
