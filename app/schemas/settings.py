from pydantic import BaseModel, Field

HEX_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


class SystemSettingsSchema(BaseModel):
    allow_anonymous_upload: bool
    allow_anonymous_download: bool
    allow_user_registration: bool
    allow_user_login: bool
    allow_secondary_password: bool
    enforce_secondary_password: bool

    enable_mfa: bool
    enforce_mfa_users: bool
    enforce_mfa_admins: bool

    enable_login_rate_limit: bool
    login_lockout_minutes: int

    enable_user_management: bool
    enable_file_management: bool
    enable_user_sharing: bool
    enable_api_keys: bool
    enable_multi_file_upload: bool
    setup_completed: bool

    brand_name: str
    brand_logo_filename: str | None
    footer_text: str

    password_min_length: int
    password_require_uppercase: bool
    password_require_lowercase: bool
    password_require_number: bool
    password_require_special: bool

    max_file_size_mb: int
    chunk_size_mb: int
    max_concurrent_uploads: int
    extension_rule_mode: str
    extension_list: str

    allowed_ttl_presets: str
    default_ttl: str
    allow_custom_ttl: bool
    force_burn_after_download: bool
    allow_burn_after_download: bool
    default_max_downloads: int
    allow_custom_max_downloads: bool

    storage_path: str
    total_storage_cap_gb: int
    cleanup_interval_minutes: int

    zero_log_mode: bool
    ip_obfuscation_level: str
    timestamp_fuzzing: str

    audit_log_retention_days: int
    disable_audit_log: bool
    max_login_attempts: int

    hide_upload_link: bool
    hide_download_link: bool

    custom_theme_enabled: bool
    custom_theme_paper: str
    custom_theme_surface: str
    custom_theme_navbar_bg: str
    custom_theme_border: str
    custom_theme_text: str
    custom_theme_accent: str
    custom_theme_danger: str
    custom_theme_heading_color: str
    custom_theme_heading_scale: int
    custom_theme_body_scale: int

    smtp_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password_set: bool  # never the actual password - just whether one is configured
    smtp_encryption: str
    smtp_from_email: str
    smtp_from_name: str
    public_base_url: str
    password_reset_token_expiry_minutes: int
    enable_download_notifications: bool

    model_config = {"from_attributes": True}


class SystemSettingsUpdate(BaseModel):
    allow_anonymous_upload: bool | None = None
    allow_anonymous_download: bool | None = None
    allow_user_registration: bool | None = None
    allow_user_login: bool | None = None
    allow_secondary_password: bool | None = None
    enforce_secondary_password: bool | None = None

    enable_mfa: bool | None = None
    enforce_mfa_users: bool | None = None
    enforce_mfa_admins: bool | None = None

    enable_login_rate_limit: bool | None = None
    login_lockout_minutes: int | None = None

    enable_user_management: bool | None = None
    enable_file_management: bool | None = None
    enable_user_sharing: bool | None = None
    enable_api_keys: bool | None = None
    enable_multi_file_upload: bool | None = None
    setup_completed: bool | None = None

    brand_name: str | None = Field(default=None, min_length=1, max_length=64)
    footer_text: str | None = Field(default=None, max_length=512)

    password_min_length: int | None = None
    password_require_uppercase: bool | None = None
    password_require_lowercase: bool | None = None
    password_require_number: bool | None = None
    password_require_special: bool | None = None

    max_file_size_mb: int | None = None
    chunk_size_mb: int | None = None
    max_concurrent_uploads: int | None = None
    extension_rule_mode: str | None = None
    extension_list: str | None = None

    allowed_ttl_presets: str | None = None
    default_ttl: str | None = None
    allow_custom_ttl: bool | None = None
    force_burn_after_download: bool | None = None
    allow_burn_after_download: bool | None = None
    default_max_downloads: int | None = None
    allow_custom_max_downloads: bool | None = None

    storage_path: str | None = None
    total_storage_cap_gb: int | None = None
    cleanup_interval_minutes: int | None = None

    zero_log_mode: bool | None = None
    ip_obfuscation_level: str | None = None
    timestamp_fuzzing: str | None = None

    audit_log_retention_days: int | None = None
    disable_audit_log: bool | None = None
    max_login_attempts: int | None = None

    hide_upload_link: bool | None = None
    hide_download_link: bool | None = None

    custom_theme_enabled: bool | None = None
    custom_theme_paper: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)
    custom_theme_surface: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)
    custom_theme_navbar_bg: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)
    custom_theme_border: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)
    custom_theme_text: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)
    custom_theme_accent: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)
    custom_theme_danger: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)
    custom_theme_heading_color: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)
    custom_theme_heading_scale: int | None = Field(default=None, ge=70, le=160)
    custom_theme_body_scale: int | None = Field(default=None, ge=85, le=125)

    smtp_enabled: bool | None = None
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: str | None = Field(default=None, max_length=255)  # write-only; omit to leave unchanged
    smtp_encryption: str | None = Field(default=None, pattern=r"^(none|starttls|ssl)$")
    smtp_from_email: str | None = Field(default=None, max_length=254)
    smtp_from_name: str | None = Field(default=None, max_length=64)
    public_base_url: str | None = Field(default=None, max_length=255)
    password_reset_token_expiry_minutes: int | None = Field(default=None, ge=5, le=1440)
    enable_download_notifications: bool | None = None


class SmtpTestRequest(BaseModel):
    to_email: str = Field(min_length=3, max_length=254)
