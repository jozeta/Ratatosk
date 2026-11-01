"""Admin settings schemas, generated from the SystemSettings model.

There used to be three hand-maintained copies of the ~80 settings (model,
read schema, update schema) plus a fourth in the public config endpoint, and
nothing stopped them drifting (ARCH-004). Now the model is the single source
of truth: this module derives the read/update schemas from its columns and
only lists what genuinely needs saying - validation bounds (BUG-004), which
fields are read-only, which are write-only, and which are public.
"""
from typing import Any, Optional

from pydantic import BaseModel, Field, create_model

from app.models.settings import SystemSettings

HEX_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"
TTL_LIST_PATTERN = r"^\s*\d+[mhd]\s*(,\s*\d+[mhd]\s*)*$"

# Validation for every field that needs more than its column type. Unbounded
# numbers here previously let e.g. chunk_size_mb=0 put the browser uploader
# in an endless loop, and max_login_attempts=0 lock everything on first try.
CONSTRAINTS: dict[str, dict[str, Any]] = {
    "brand_name": {"min_length": 1, "max_length": 64},
    "footer_text": {"max_length": 512},
    "login_lockout_minutes": {"ge": 1, "le": 1440},
    "max_login_attempts": {"ge": 1, "le": 100},
    "password_min_length": {"ge": 8, "le": 256},
    "max_file_size_mb": {"ge": 1, "le": 1024 * 1024},
    "chunk_size_mb": {"ge": 1, "le": 64},
    "max_concurrent_uploads": {"ge": 1, "le": 100},
    "max_active_upload_sessions": {"ge": 1, "le": 100000},
    "extension_rule_mode": {"pattern": r"^(whitelist|blacklist)$"},
    "extension_list": {"max_length": 1024},
    "allowed_ttl_presets": {"pattern": TTL_LIST_PATTERN, "max_length": 256},
    "default_ttl": {"pattern": r"^\s*\d+[mhd]\s*$"},
    "default_max_downloads": {"ge": 0, "le": 1000000},
    "total_storage_cap_gb": {"ge": 1, "le": 1024 * 1024},
    "cleanup_interval_minutes": {"ge": 1, "le": 1440},
    "ip_obfuscation_level": {"pattern": r"^(none|masked|full)$"},
    "timestamp_fuzzing": {"pattern": r"^(none|hour|day)$"},
    "audit_log_retention_days": {"ge": 1, "le": 36500},
    "rate_limit_per_minute": {"ge": 1, "le": 10000},
    "onion_address": {"pattern": r"^$|^(https?://)?[a-z2-7]{56}\.onion/?$", "max_length": 255},
    "custom_theme_heading_scale": {"ge": 70, "le": 160},
    "custom_theme_body_scale": {"ge": 85, "le": 125},
    "smtp_host": {"max_length": 255},
    "smtp_port": {"ge": 1, "le": 65535},
    "smtp_username": {"max_length": 255},
    "smtp_password": {"max_length": 255},
    "smtp_encryption": {"pattern": r"^(none|starttls|ssl)$"},
    "smtp_from_email": {"max_length": 254},
    "smtp_from_name": {"max_length": 64},
    "public_base_url": {"max_length": 255},
    "password_reset_token_expiry_minutes": {"ge": 5, "le": 1440},
}
for _col in SystemSettings.__table__.columns:
    if _col.name.startswith("custom_theme_") and _col.type.python_type is str:
        CONSTRAINTS[_col.name] = {"pattern": HEX_COLOR_PATTERN}

# Never accepted from the API: internal bookkeeping, set via a dedicated
# endpoint (logo upload), or env-only (storage_path, SEC-010).
READ_ONLY = {"id", "version", "brand_logo_filename", "storage_path"}
# Accepted but never returned - only whether a value is set.
WRITE_ONLY = {"smtp_password"}

# Non-sensitive subset served to everyone by GET /api/config.
PUBLIC_FIELDS = (
    "brand_name", "brand_logo_filename", "footer_text",
    "allow_anonymous_upload", "allow_anonymous_download", "allow_user_registration", "allow_user_login",
    "enable_user_sharing", "enable_api_keys", "enable_user_management", "enable_file_management",
    "enable_multi_file_upload", "allow_secondary_password", "enforce_secondary_password", "enable_mfa",
    "password_min_length", "password_require_uppercase", "password_require_lowercase",
    "password_require_number", "password_require_special",
    "max_file_size_mb", "chunk_size_mb", "extension_rule_mode", "extension_list",
    "allowed_ttl_presets", "default_ttl", "allow_custom_ttl", "allow_burn_after_download",
    "force_burn_after_download", "default_max_downloads", "allow_custom_max_downloads",
    "hide_upload_link", "hide_download_link",
    "custom_theme_enabled", "custom_theme_paper", "custom_theme_surface", "custom_theme_navbar_bg",
    "custom_theme_border", "custom_theme_text", "custom_theme_accent", "custom_theme_danger",
    "custom_theme_heading_color", "custom_theme_heading_scale", "custom_theme_body_scale",
    "enable_download_notifications", "enable_upload_requests", "allow_server_held_share_keys",
)

_COLUMNS = {c.name: c for c in SystemSettings.__table__.columns}
for _name in PUBLIC_FIELDS + tuple(CONSTRAINTS) + tuple(READ_ONLY) + tuple(WRITE_ONLY):
    if _name not in _COLUMNS:
        raise RuntimeError(f"settings schema references unknown column {_name!r}")


def _py_type(name: str):
    return _COLUMNS[name].type.python_type


def nullable(name: str) -> bool:
    return bool(_COLUMNS[name].nullable)


SystemSettingsSchema = create_model(  # type: ignore[call-overload]
    "SystemSettingsSchema",
    __config__={"from_attributes": True},
    **{
        name: (Optional[_py_type(name)] if nullable(name) else _py_type(name), ...)
        for name in _COLUMNS
        if name not in WRITE_ONLY and name != "id"
    },
    smtp_password_set=(bool, ...),
)

SystemSettingsUpdate = create_model(  # type: ignore[call-overload]
    "SystemSettingsUpdate",
    __config__={"extra": "forbid"},
    **{
        name: (Optional[_py_type(name)], Field(default=None, **CONSTRAINTS.get(name, {})))
        for name in _COLUMNS
        if name not in READ_ONLY
    },
)


def public_config(cfg: dict) -> dict:
    out = {k: cfg[k] for k in PUBLIC_FIELDS}
    out["password_reset_enabled"] = cfg["smtp_enabled"]
    from app.version import __version__

    out["version"] = __version__
    from app.core.config import settings as static_settings
    from app.services.oidc import enabled as oidc_enabled

    out["oidc_enabled"] = oidc_enabled()
    out["oidc_button_label"] = static_settings.oidc_button_label
    return out


class SmtpTestRequest(BaseModel):
    to_email: str = Field(min_length=3, max_length=254)
