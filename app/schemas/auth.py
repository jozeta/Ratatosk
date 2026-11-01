from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    email: str | None = Field(default=None, max_length=254)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    is_admin: bool = False
    username: str
    id: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1, max_length=256)


class UpdateEmailRequest(BaseModel):
    email: str | None = Field(default=None, max_length=254)


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)  # username or email


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=1, max_length=256)


class MfaLoginRequired(BaseModel):
    mfa_required: bool = True
    mfa_token: str


class MfaSetupRequired(BaseModel):
    mfa_setup_required: bool = True
    setup_token: str


class MfaEnforceSetupRequest(BaseModel):
    setup_token: str


class MfaEnforceConfirmRequest(BaseModel):
    setup_token: str
    code: str = Field(min_length=1, max_length=16)


class MfaEnforceConfirmResponse(TokenResponse):
    backup_codes: list[str]


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=1, max_length=16)


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_url: str


class MfaConfirmRequest(BaseModel):
    code: str = Field(min_length=1, max_length=16)


class MfaConfirmResponse(BaseModel):
    backup_codes: list[str]


class MfaDisableRequest(BaseModel):
    password: str
    code: str = Field(min_length=1, max_length=16)  # current TOTP or a backup code (SEC-019)


class RegisteredLoginRequired(BaseModel):
    registered: bool = True
    login_required: bool = True
    detail: str


class DeleteAccountRequest(BaseModel):
    password: str | None = Field(default=None, max_length=256)
    confirm_username: str | None = Field(default=None, max_length=64)  # SSO-only accounts have no password


class UpdateDiscoverableRequest(BaseModel):
    discoverable: bool
