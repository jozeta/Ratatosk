from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from app.api import (
    account_api_keys,
    admin_audit,
    admin_files,
    admin_settings,
    admin_system,
    admin_users,
    auth,
    branding,
    e2e,
    files,
    oidc,
    public_config,
    sharing,
    upload,
)
from app.core.cleanup import start_background_cleanup, stop_background_cleanup
from app.core.config import settings
from app.core.dynamic_settings import get_settings, load_cache
from app.core.migrate import run_migrations
from app.core.privacy import SENSITIVE_HEADERS
from app.version import __version__


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    load_cache()
    start_background_cleanup()
    yield
    stop_background_cleanup()


app = FastAPI(title="Ratatosk", version=__version__, lifespan=lifespan)

# Strict CSP (SEC-009). In a browser-crypto app any injected script could read
# the key from the URL fragment, so scripts may only come from this origin -
# no inline scripts, no eval. Inline *style attributes* are still allowed;
# style injection can't read secrets. The logo endpoint sets its own,
# stricter policy and is left alone.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "connect-src 'self'",
    "worker-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
])


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    """Strip identifying forwarding headers before the request reaches any
    handler, so nothing downstream can accidentally log or trust them, and
    add security headers to every response."""
    scope_headers = request.scope.get("headers", [])
    request.scope["headers"] = [
        (k, v) for (k, v) in scope_headers if k.decode("latin-1").lower() not in SENSITIVE_HEADERS - {"user-agent"}
    ]
    response = await call_next(request)
    h = response.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
    h.setdefault("Content-Security-Policy", CSP)
    if request.url.scheme == "https":
        h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    onion = (get_settings().get("onion_address") or "").strip().rstrip("/")
    host = request.url.hostname or ""
    if onion and not host.endswith(".onion") and not request.url.path.startswith(("/api/", "/static/")):
        base = onion if onion.startswith("http") else f"http://{onion}"
        h["Onion-Location"] = base + request.url.path  # FEAT-009: Tor Browser offers the .onion mirror
    if request.url.path.startswith("/static/"):
        # Force revalidation (via the ETag/Last-Modified StaticFiles already
        # sends) instead of letting browsers cache heuristically - otherwise
        # a deployed JS/CSS fix can silently not show up without a hard-refresh.
        h["Cache-Control"] = "no-cache"
    return response


class SelectiveGZip:
    """Compress static assets and HTML pages only (PERF-010). API responses
    are left alone: ciphertext doesn't compress, and compressing responses
    that mix secrets with attacker-influenced input invites BREACH-style
    length leaks."""

    def __init__(self, app):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1024)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not scope.get("path", "").startswith("/api/"):
            return await self.gzip(scope, receive, send)
        return await self.app(scope, receive, send)


app.add_middleware(SelectiveGZip)

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
app.include_router(e2e.router)
app.include_router(oidc.router)

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


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    """Streams large decrypted downloads straight to disk (PERF-005). Served
    from the root so its scope covers the whole site."""
    return FileResponse(
        f"{settings.frontend_dir}/static/js/sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


app.add_api_route("/", _page("index.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/about", _page("about.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/requests", _page("requests.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/r/{request_id}", _page("request_upload.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/share/{file_id}", _page("share.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/download", _page("download.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/login", _page("login.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/register", _page("register.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/forgot-password", _page("forgot_password.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/reset-password", _page("reset_password.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/files", _page("my_files.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/shared", _page("shared_with_me.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/account", _page("account.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/admin/settings", _page("admin_settings.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/admin/setup", _page("admin_setup.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/admin/audit", _page("admin_audit.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/admin/users", _page("admin_users.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/admin/files", _page("admin_files.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/admin/stats", _page("admin_stats.html"), methods=["GET", "HEAD"], include_in_schema=False)
app.add_api_route("/admin", _page("admin_settings.html"), methods=["GET", "HEAD"], include_in_schema=False)


@app.get("/api/integrity", include_in_schema=False)
def integrity():
    """Hashes of every file the browser loads, plus the release digest that
    commits to all of them (FEAT-012). Verify a server independently with
    `ratatosk verify <url> --expect <digest published for this version>`."""
    from app.integrity import served_manifest

    return served_manifest()


@app.get("/api/health", include_in_schema=False)
def health():
    return {"status": "ok", "version": __version__}
