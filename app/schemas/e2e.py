from pydantic import BaseModel, Field

B64URL = r"^[A-Za-z0-9_-]+$"


class AccountKeys(BaseModel):
    """A user's ECDH P-256 keypair. The private key arrives already wrapped
    in the browser with a key derived from the user's *encryption passphrase*;
    the server can store it but never open it."""
    public_key: str = Field(min_length=40, max_length=400, pattern=B64URL)  # SPKI
    wrapped_private_key: str = Field(min_length=40, max_length=1000, pattern=B64URL)
    kdf_salt: str = Field(min_length=16, max_length=64, pattern=B64URL)
    kdf_iterations: int = Field(ge=100000, le=10000000)


class AccountKeysOut(AccountKeys):
    fingerprint: str


class PublicKeyOut(BaseModel):
    user_id: str
    username: str
    public_key: str
    fingerprint: str


class WrappedKey(BaseModel):
    wrapped_key: str = Field(min_length=20, max_length=400, pattern=B64URL)
    ephemeral_public_key: str = Field(min_length=40, max_length=400, pattern=B64URL)


class E2EShareRecipient(WrappedKey):
    user_id: str = Field(max_length=36)


class CreateUploadRequest(BaseModel):
    label: str = Field(default="", max_length=120)
    expires_in: str = Field(default="7d", pattern=r"^\d+[mhd]$")
    max_uploads: int = Field(default=0, ge=0, le=10000)
    max_file_size_mb: int | None = Field(default=None, ge=1)
    file_ttl: str | None = Field(default=None, pattern=r"^\d+[mhd]$")


class UploadRequestOut(BaseModel):
    id: str
    label: str
    fingerprint: str
    created_at: str
    expires_at: str
    max_uploads: int
    upload_count: int
    max_file_size_mb: int
    file_ttl: str
    open: bool


class UploadRequestPublic(BaseModel):
    id: str
    label: str
    public_key: str
    fingerprint: str
    max_file_size_mb: int
    expires_at: str
    open: bool
    uploads_left: int | None


class RequestSubmission(BaseModel):
    file_id: str
    size_bytes: int
    created_at: str
    expires_at: str
    download_count: int
    wrapped_key: str
    ephemeral_public_key: str
