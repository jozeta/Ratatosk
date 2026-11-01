from pydantic import BaseModel, Field


class UserListEntry(BaseModel):
    id: str
    username: str


class E2ERecipient(BaseModel):
    user_id: str = Field(max_length=36)
    wrapped_key: str = Field(min_length=20, max_length=400, pattern=r"^[A-Za-z0-9_-]+$")
    ephemeral_public_key: str = Field(min_length=40, max_length=400, pattern=r"^[A-Za-z0-9_-]+$")


class ShareFileRequest(BaseModel):
    """End-to-end recipients get the file secret wrapped to their own public
    key (FEAT-002). `user_ids` + `key` is the legacy server-held-key path,
    for recipients without keys, if the admin allows it."""
    recipients: list[E2ERecipient] = Field(default_factory=list, max_length=100)
    user_ids: list[str] = Field(default_factory=list, max_length=100)
    key: str | None = Field(default=None, min_length=1, max_length=64)


class SharedFileEntry(BaseModel):
    scheme: str = "server"  # "e2e" or "server"
    file_id: str
    size_bytes: int
    created_at: str
    expires_at: str
    burn_after_download: bool
    max_downloads: int
    download_count: int
    shared_by: str
    shared_with: list[str]
