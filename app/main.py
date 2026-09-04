from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    account_api_keys,
    admin_audit,
    admin_files,
    admin_settings,
    admin_system,
    admin_users,
    auth,
    branding,
    files,
    public_config,
    sharing,
    upload,
)
from app.core.cleanup import start_background_cleanup, stop_background_cleanup
from app.core.config import settings
from app.core.database import Base, engine
from app.core.dynamic_settings import load_cache
from app.core.migrate import sync_table_columns
from app.core.privacy import SENSITIVE_HEADERS
from app.models.api_key import ApiKey
from app.models.file import FileObject
from app.models.settings import SystemSettings
from app.models.user import User


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    sync_table_columns(engine, SystemSettings)
    sync_table_columns(engine, FileObject)
    sync_table_columns(engine, User)
    sync_table_columns(engine, ApiKey)
    load_cache()
    task = start_background_cleanup()
    yield
    stop_background_cleanup()


app = FastAPI(title="SecureDrop", lifespan=lifespan)


@app.middleware("http")
async def sanitize_headers_middleware(request, call_next):
    """Strip identifying forwarding headers before the request reaches any
    handler, so nothing downstream can accidentally log or trust them."""
    scope_headers = request.scope.get("headers", [])
    request.scope["headers"] = [
        (k, v) for (k, v) in scope_headers if k.decode("latin-1").lower() not in SENSITIVE_HEADERS - {"user-agent"}
    ]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/static/"):
        # Force revalidation (via the ETag/Last-Modified StaticFiles already
        # sends) instead of letting browsers cache heuristically - otherwise
        # a deployed JS/CSS fix can silently not show up without a hard-refresh.
        response.headers["Cache-Control"] = "no-cache"
    return response


app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(files.router)
app.include_router(public_config.router)
app.include_router(admin_settings.router)
app.include_router(admin_audit.router)
app.include_router(admin_users.router)
app.include_router(admin_files.router)
app.include_router(admin_system.router)
app.include_router(sharing.router)
app.include_router(branding.router)
app.include_router(account_api_keys.router)

app.mount("/static", StaticFiles(directory=settings.frontend_dir + "/static"), name="static")


def _page(name: str):
    def handler():
        # Auth for these pages is enforced client-side against localStorage, so a
        # cached or bfcache-restored copy would show a previously logged-in user's
        # page (including data already fetched into the DOM) without re-checking
        # auth. no-store keeps every page out of both HTTP cache and bfcache.
        return FileResponse(
            f"{settings.frontend_dir}/{name}",
            headers={"Cache-Control": "no-store"},
        )

    return handler


app.add_api_route("/", _page("index.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/share/{file_id}", _page("share.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/download", _page("download.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/login", _page("login.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/register", _page("register.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/forgot-password", _page("forgot_password.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/reset-password", _page("reset_password.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/files", _page("my_files.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/shared", _page("shared_with_me.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/account", _page("account.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/admin/settings", _page("admin_settings.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/admin/setup", _page("admin_setup.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/admin/audit", _page("admin_audit.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/admin/users", _page("admin_users.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/admin/files", _page("admin_files.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/admin/stats", _page("admin_stats.html"), methods=["GET"], include_in_schema=False)
app.add_api_route("/admin", _page("admin_settings.html"), methods=["GET"], include_in_schema=False)


@app.get("/api/health", include_in_schema=False)
def health():
    return {"status": "ok"}
