import datetime

from pydantic import BaseModel, Field


class UserSummary(BaseModel):
    id: str
    username: str
    email: str | None
    is_admin: bool
    is_active: bool
    mfa_enabled: bool
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class AdminCreateUser(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    is_admin: bool = False


class AdminUpdateUser(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=64)
    email: str | None = Field(default=None, max_length=254)  # "email" absent from the request leaves it unchanged; present-as-null clears it (see model_fields_set)
    is_admin: bool | None = None
    is_active: bool | None = None


class AdminResetPassword(BaseModel):
    new_password: str = Field(min_length=1, max_length=256)
