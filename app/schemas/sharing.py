from pydantic import BaseModel, Field


class UserListEntry(BaseModel):
    id: str
    username: str


class ShareFileRequest(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=100)
    key: str = Field(min_length=1, max_length=64)


class SharedFileEntry(BaseModel):
    file_id: str
    size_bytes: int
    created_at: str
    expires_at: str
    burn_after_download: bool
    max_downloads: int
    download_count: int
    shared_by: str
    shared_with: list[str]
