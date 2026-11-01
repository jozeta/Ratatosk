"""Static bootstrap configuration - values needed before the DB is available.

Everything that can change at runtime (retention policy, anonymity level,
size limits, etc.) lives in the `system_settings` DB table instead, managed
by app.core.dynamic_settings.

Environment variables use the RATATOSK_ prefix. The project's previous name
was SecureDrop, so SECUREDROP_* variables (in the environment or in .env) are
still honoured as a fallback, with a deprecation warning, so existing
deployments keep working across the rename.
"""
import logging
import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("ratatosk.config")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PREFIX = "RATATOSK_"
LEGACY_ENV_PREFIX = "SECUREDROP_"


def _import_legacy_env() -> None:
    """Copy SECUREDROP_X to RATATOSK_X (environment and .env) unless the new
    name is already set, so old configurations keep working after the rename."""
    legacy: dict[str, str] = {}
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        legacy.update({k: v for k, v in dotenv_values(env_file).items() if k.startswith(LEGACY_ENV_PREFIX) and v is not None})
    legacy.update({k: v for k, v in os.environ.items() if k.startswith(LEGACY_ENV_PREFIX)})
    used = []
    for key, value in legacy.items():
        new_key = ENV_PREFIX + key[len(LEGACY_ENV_PREFIX):]
        if new_key not in os.environ:
            os.environ[new_key] = value
            used.append(key)
    if used:
        logger.warning("Deprecated %s* settings in use (%s) - rename them to %s*", LEGACY_ENV_PREFIX, ", ".join(sorted(used)), ENV_PREFIX)


_import_legacy_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=str(BASE_DIR / ".env"), extra="ignore")

    database_url: str = f"sqlite:///{BASE_DIR / 'ratatosk.db'}"
    # Where finished encrypted blobs are written (local backend). Deliberately
    # env-only, not an admin-panel setting: a web-editable path let a hijacked
    # admin session point the factory reset at an arbitrary directory (SEC-010).
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
    # "local" (default) keeps blobs on disk under storage_root. "s3" stores
    # finished blobs in an S3-compatible bucket - env-only (like secret_key),
    # since admin-UI settings would put cloud credentials in plaintext in the DB.
    storage_backend: str = "local"  # local|s3
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""  # for non-AWS S3-compatible services (MinIO, Backblaze B2, etc)
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_prefix: str = ""  # optional key prefix, e.g. "prod/"

    # --- Single sign-on (OIDC, FEAT-010) --- env-only: includes a secret.
    # Set issuer + client id + secret to enable "Sign in with SSO".
    oidc_issuer: str = ""  # e.g. https://login.example.com/realms/acme
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_url: str = ""  # default: <site>/api/auth/oidc/callback
    oidc_scopes: str = "openid email profile"
    oidc_button_label: str = "Sign in with SSO"
    oidc_auto_provision: bool = True  # create an account on first SSO login
    # Link an SSO login to an existing local account with the same *verified*
    # email. Off by default: whoever controls the IdP could otherwise take
    # over any local account by asserting its email address.
    oidc_link_by_email: bool = False
    oidc_groups_claim: str = "groups"
    oidc_admin_group: str = ""  # members become admins (re-checked every login)


def _default_database_url() -> str:
    """Keep using an existing pre-rename securedrop.db rather than silently
    starting a fresh, empty database next to it."""
    legacy = BASE_DIR / "securedrop.db"
    current = BASE_DIR / "ratatosk.db"
    if legacy.exists() and not current.exists():
        return f"sqlite:///{legacy}"
    return f"sqlite:///{current}"


def _explicitly_set(field: str) -> bool:
    key = ENV_PREFIX + field.upper()
    if key in os.environ:
        return True
    env_file = BASE_DIR / ".env"
    return env_file.exists() and bool(dotenv_values(env_file).get(key))


settings = Settings()
if not _explicitly_set("database_url"):
    settings.database_url = _default_database_url()
# Whether the operator set the storage root explicitly (vs. the default) -
# used to honour a storage_path that was configured in the admin UI before it
# became env-only (see storage_backends/local.py).
storage_root_explicit = _explicitly_set("storage_root")

if settings.secret_key == Settings.model_fields["secret_key"].default:
    raise RuntimeError(
        "RATATOSK_SECRET_KEY is still set to the built-in placeholder value. "
        "This key signs every session token, so anyone who reads the source can forge "
        "admin sessions. Set a unique RATATOSK_SECRET_KEY (e.g. via .env) before starting "
        "the app - generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
