from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SystemSettings(Base):
    """Singleton row (id=1) holding every admin-configurable, hot-reloadable setting."""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # --- Access & Authentication ---
    allow_anonymous_upload: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_anonymous_download: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_user_registration: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_user_login: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_secondary_password: Mapped[bool] = mapped_column(Boolean, default=True)
    enforce_secondary_password: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Multi-factor authentication (TOTP) ---
    enable_mfa: Mapped[bool] = mapped_column(Boolean, default=True)  # off = feature unavailable app-wide, existing setups stop being prompted
    enforce_mfa_users: Mapped[bool] = mapped_column(Boolean, default=False)  # non-admins must set up MFA at next login
    enforce_mfa_admins: Mapped[bool] = mapped_column(Boolean, default=False)  # admins must set up MFA at next login

    # --- Account login brute-force protection ---
    enable_login_rate_limit: Mapped[bool] = mapped_column(Boolean, default=True)
    login_lockout_minutes: Mapped[int] = mapped_column(Integer, default=15)

    # --- Admin feature views (defense in depth: can be switched off entirely) ---
    enable_user_management: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_file_management: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- User-to-user sharing ---
    enable_user_sharing: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- API keys / CLI upload ---
    enable_api_keys: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- Multi-file / folder upload ---
    enable_multi_file_upload: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- First-run setup wizard ---
    setup_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Branding ---
    brand_name: Mapped[str] = mapped_column(String(64), default="SecureDrop")
    brand_logo_filename: Mapped[str | None] = mapped_column(String(64), nullable=True)
    footer_text: Mapped[str] = mapped_column(
        String(512),
        default="Zero-knowledge encryption happens entirely in your browser. The server never sees your files, filenames, or decryption keys.",
    )

    # --- Password policy ---
    password_min_length: Mapped[int] = mapped_column(Integer, default=8)
    password_require_uppercase: Mapped[bool] = mapped_column(Boolean, default=False)
    password_require_lowercase: Mapped[bool] = mapped_column(Boolean, default=False)
    password_require_number: Mapped[bool] = mapped_column(Boolean, default=False)
    password_require_special: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Upload & File Constraints ---
    max_file_size_mb: Mapped[int] = mapped_column(Integer, default=500)
    chunk_size_mb: Mapped[int] = mapped_column(Integer, default=5)
    max_concurrent_uploads: Mapped[int] = mapped_column(Integer, default=3)
    extension_rule_mode: Mapped[str] = mapped_column(String(16), default="blacklist")  # whitelist|blacklist
    extension_list: Mapped[str] = mapped_column(String(1024), default="exe,bat,cmd,sh,msi,scr,com,vbs,ps1")

    # --- Retention & Expiration ---
    allowed_ttl_presets: Mapped[str] = mapped_column(String(256), default="10m,1h,24h,7d,30d")
    default_ttl: Mapped[str] = mapped_column(String(16), default="24h")
    allow_custom_ttl: Mapped[bool] = mapped_column(Boolean, default=True)  # off = every upload uses default_ttl, fixed
    force_burn_after_download: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_burn_after_download: Mapped[bool] = mapped_column(Boolean, default=True)
    default_max_downloads: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited
    allow_custom_max_downloads: Mapped[bool] = mapped_column(Boolean, default=True)  # off = every upload uses default_max_downloads, fixed

    # --- Storage Engine ---
    storage_path: Mapped[str] = mapped_column(String(512), default="./storage/encrypted")
    total_storage_cap_gb: Mapped[int] = mapped_column(Integer, default=50)
    cleanup_interval_minutes: Mapped[int] = mapped_column(Integer, default=5)

    # --- Anonymity / Privacy Engine ---
    zero_log_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    ip_obfuscation_level: Mapped[str] = mapped_column(String(16), default="masked")  # none|masked|full
    timestamp_fuzzing: Mapped[str] = mapped_column(String(16), default="none")  # none|hour|day

    # --- Audit Log ---
    audit_log_retention_days: Mapped[int] = mapped_column(Integer, default=90)
    disable_audit_log: Mapped[bool] = mapped_column(Boolean, default=False)

    max_login_attempts: Mapped[int] = mapped_column(Integer, default=5)

    # --- Navigation ---
    hide_upload_link: Mapped[bool] = mapped_column(Boolean, default=False)
    hide_download_link: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Custom Theme (overrides the light/dark toggle for every visitor) ---
    custom_theme_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_theme_paper: Mapped[str] = mapped_column(String(7), default="#0c0f14")
    custom_theme_surface: Mapped[str] = mapped_column(String(7), default="#141822")
    custom_theme_navbar_bg: Mapped[str] = mapped_column(String(7), default="#141822")  # top nav bar; defaults to match surface
    custom_theme_border: Mapped[str] = mapped_column(String(7), default="#262c39")
    custom_theme_text: Mapped[str] = mapped_column(String(7), default="#e7eaf0")
    custom_theme_accent: Mapped[str] = mapped_column(String(7), default="#7c93d6")
    custom_theme_danger: Mapped[str] = mapped_column(String(7), default="#e0685f")  # destructive actions (Delete, etc.) - kept separate from accent on purpose
    custom_theme_heading_color: Mapped[str] = mapped_column(String(7), default="#e7eaf0")
    custom_theme_heading_scale: Mapped[int] = mapped_column(Integer, default=100)  # percent, applied to h2/h3/h4
    custom_theme_body_scale: Mapped[int] = mapped_column(Integer, default=100)  # percent, applied to the base body font size

    # --- Email (SMTP) / password reset ---
    smtp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    smtp_host: Mapped[str] = mapped_column(String(255), default="")
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_username: Mapped[str] = mapped_column(String(255), default="")
    smtp_password: Mapped[str] = mapped_column(String(255), default="")  # never returned by the settings API
    smtp_encryption: Mapped[str] = mapped_column(String(16), default="starttls")  # none|starttls|ssl
    smtp_from_email: Mapped[str] = mapped_column(String(254), default="")
    smtp_from_name: Mapped[str] = mapped_column(String(64), default="")
    public_base_url: Mapped[str] = mapped_column(String(255), default="")  # used to build reset links; falls back to the request's own host
    password_reset_token_expiry_minutes: Mapped[int] = mapped_column(Integer, default=60)

    # --- Download notifications --- site-wide kill switch; the per-file
    # opt-in still requires smtp_enabled too (see files.py::download_blob).
    enable_download_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
