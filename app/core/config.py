"""Static bootstrap configuration - values needed before the DB is available.

Everything that can change at runtime (retention policy, anonymity level,
size limits, etc.) lives in the `system_settings` DB table instead, managed
by app.core.dynamic_settings.SettingsService.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SECUREDROP_", env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{BASE_DIR / 'securedrop.db'}"
    storage_root: str = str(BASE_DIR / "storage" / "encrypted")
    tmp_root: str = str(BASE_DIR / "storage" / "tmp")
    branding_root: str = str(BASE_DIR / "storage" / "branding")
    secret_key: str = "CHANGE_ME_IN_PRODUCTION_" + "x" * 32
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    frontend_dir: str = str(BASE_DIR / "frontend")
    default_admin_username: str = "admin"
    default_admin_password: str = ""  # if blank, a random password is generated at init

    # --- Storage backend ---
    # "local" (default) keeps everything on disk under the dynamic storage_path
    # setting, same as always. "s3" stores finished blobs in an S3-compatible
    # bucket instead - kept static/env-only (like secret_key) rather than in
    # the admin-UI dynamic settings, since those would otherwise store cloud
    # credentials in plaintext in securedrop.db.
    storage_backend: str = "local"  # local|s3
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""  # for non-AWS S3-compatible services (MinIO, Backblaze B2, etc)
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_prefix: str = ""  # optional key prefix, e.g. "prod/"


settings = Settings()

if settings.secret_key == Settings.model_fields["secret_key"].default:
    raise RuntimeError(
        "SECUREDROP_SECRET_KEY is still set to the built-in placeholder value. "
        "This key signs every session token, so anyone who reads the source can forge "
        "admin sessions. Set a unique SECUREDROP_SECRET_KEY (e.g. via .env) before starting "
        "the app - generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
