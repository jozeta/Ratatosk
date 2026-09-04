from pydantic import BaseModel, Field


class InitUploadRequest(BaseModel):
    total_size_bytes: int = Field(gt=0)
    extension: str | None = Field(default=None, max_length=16)


class InitUploadResponse(BaseModel):
    upload_id: str
    chunk_size_bytes: int
    max_size_bytes: int


class CompleteUploadRequest(BaseModel):
    ttl: str
    burn_after_download: bool = False
    max_downloads: int = 0
    password: str | None = Field(default=None, max_length=256)
    notify_on_download: bool = False


class CompleteUploadResponse(BaseModel):
    file_id: str
    expires_at: str


class FileMetaResponse(BaseModel):
    file_id: str
    size_bytes: int
    expires_at: str
    burn_after_download: bool
    max_downloads: int
    download_count: int
    requires_password: bool


class VerifyPasswordRequest(BaseModel):
    password: str
