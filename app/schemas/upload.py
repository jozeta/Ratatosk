from pydantic import BaseModel, Field


class InitUploadRequest(BaseModel):
    total_size_bytes: int = Field(gt=0)
    extension: str | None = Field(default=None, max_length=16)
    request_id: str | None = Field(default=None, max_length=36)  # uploading into a request link (FEAT-001)


class InitUploadResponse(BaseModel):
    upload_id: str
    chunk_size_bytes: int
    max_size_bytes: int


class CompleteUploadRequest(BaseModel):
    ttl: str = Field(max_length=16)
    burn_after_download: bool = False
    max_downloads: int = Field(default=0, ge=0, le=1000000)
    # Legacy field: old clients sent the passphrase itself here. Always
    # rejected now (SEC-001) - kept only to give those clients a clear error.
    password: str | None = Field(default=None, max_length=256)
    notify_on_download: bool = False
    # SHA-256 (hex) of the download token the client derived from the file's
    # secret with HKDF - see FileObject.download_token_hash.
    download_token_hash: str | None = Field(default=None, max_length=64)
    passphrase_protected: bool = False
    kdf_salt: str | None = Field(default=None, max_length=64)  # base64url, passphrase mode only
    kdf_iterations: int | None = Field(default=None, ge=100000, le=10000000)
    # Multi-file bundles (FEAT-003): this upload is the encrypted manifest.
    is_bundle: bool = False
    bundle_member_ids: list[str] = Field(default_factory=list, max_length=1000)
    # Request-link submissions (FEAT-001): the file secret wrapped (ECDH-ES)
    # to the request owner's public key.
    wrapped_key: str | None = Field(default=None, max_length=400, pattern=r"^[A-Za-z0-9_-]+$")
    ephemeral_public_key: str | None = Field(default=None, max_length=400, pattern=r"^[A-Za-z0-9_-]+$")


class UploadStatusResponse(BaseModel):
    upload_id: str
    declared_size: int
    resume_offset: int


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
    # How the downloader proves they hold the key: "token" (current),
    # "legacy_password" (old passphrase files) or "none" (old link files).
    auth_scheme: str
    kdf_salt: str | None = None
    kdf_iterations: int | None = None
    is_bundle: bool = False


class VerifyTokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)


class UpdateFileRequest(BaseModel):
    """Owner-side link management (FEAT-007). Limits can only be tightened."""
    disabled: bool | None = None
    expires_at: str | None = None
    max_downloads: int | None = Field(default=None, ge=0, le=1000000)


class VerifyPasswordRequest(BaseModel):
    password: str
