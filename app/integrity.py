"""Verifiable frontend (FEAT-012).

Browser-based encryption has one unavoidable trust gap: the server supplies
the code that does the encrypting, so a malicious or compelled operator could
serve modified JavaScript. This module makes such tampering *detectable*:

- **Subresource Integrity.** Every <script> and stylesheet tag in every page
  carries an `integrity="sha384-..."` hash, so a page only runs exactly the
  code it was released with. `write` (below) maintains these attributes, and
  a test fails if anyone forgets to.
- **A release manifest and digest.** `manifest()` hashes every file the
  browser can load. `release_digest()` is one SHA-256 over that manifest -
  a single value to publish with each release (see CHANGELOG.md) and compare
  against what a server actually serves.
- **Independent verification.** `cli/ratatosk.py verify <url>` downloads every
  page and asset from a live server *outside the browser* and compares them
  with a release. The page itself can't do that check: a server that lies
  about its code can also lie about its hashes.

Usage:
    python -m app.integrity write    # refresh SRI attributes after editing JS/CSS
    python -m app.integrity check    # verify they're current (CI)
    python -m app.integrity digest   # print the release digest
"""
import base64
import hashlib
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
# URL path -> file, for everything the browser loads.
SPECIAL_PATHS = {"/sw.js": "static/js/sw.js"}
PAGE_ROUTES = {
    "/": "index.html", "/about": "about.html", "/download": "download.html", "/login": "login.html",
    "/register": "register.html", "/forgot-password": "forgot_password.html", "/reset-password": "reset_password.html",
    "/files": "my_files.html", "/shared": "shared_with_me.html", "/account": "account.html",
    "/admin/settings": "admin_settings.html", "/admin/setup": "admin_setup.html", "/admin/audit": "admin_audit.html",
    "/admin/users": "admin_users.html", "/admin/files": "admin_files.html", "/admin/stats": "admin_stats.html",
    "/share/_": "share.html", "/requests": "requests.html", "/r/_": "request_upload.html",
}
TAG_RE = re.compile(r'<(script|link)\b([^>]*?)\b(src|href)="(/static/[^"]+\.(?:js|css))"([^>]*)>')


def sri(data: bytes) -> str:
    return "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode()


def _assets() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in sorted((FRONTEND / "static").rglob("*")):
        if p.is_file() and p.suffix in {".js", ".css", ".svg", ".png", ".ico", ".woff2"}:
            out["/" + p.relative_to(FRONTEND).as_posix()] = p
    for url, rel in SPECIAL_PATHS.items():
        out[url] = FRONTEND / rel
    for url, rel in PAGE_ROUTES.items():
        out[url] = FRONTEND / rel
    return out


def manifest() -> dict[str, str]:
    """URL path -> SRI hash of what the server serves there."""
    return {url: sri(path.read_bytes()) for url, path in _assets().items()}


def release_digest(m: dict[str, str] | None = None) -> str:
    m = manifest() if m is None else m
    canonical = json.dumps(m, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


@lru_cache(maxsize=1)
def served_manifest() -> dict:
    """Computed once per process from the files actually on disk."""
    m = manifest()
    from app.version import __version__

    return {"version": __version__, "release_digest": release_digest(m), "files": m}


def _rewrite_tags(html: str) -> str:
    """Set integrity="sha384-..." on every local <script src>/<link href>."""
    def repl(match: re.Match) -> str:
        tag, before, attr, url, after = match.groups()
        attrs = f'{before}{attr}="{url}"{after}'
        attrs = re.sub(r'\s+(integrity|crossorigin)="[^"]*"', "", attrs).rstrip()
        return f'<{tag}{attrs} integrity="{sri((FRONTEND / url.lstrip("/")).read_bytes())}">'

    return TAG_RE.sub(repl, html)


def pages() -> list[Path]:
    return sorted(FRONTEND.glob("*.html"))


def write() -> list[str]:
    """Refresh SRI attributes in every page. HTML pages are rewritten last,
    since their own hashes depend on the attributes. Returns changed files."""
    changed = []
    for page in pages():
        old = page.read_text()
        new = _rewrite_tags(old)
        if new != old:
            page.write_text(new)
            changed.append(page.name)
    served_manifest.cache_clear()
    return changed


def stale_pages() -> list[str]:
    return [p.name for p in pages() if _rewrite_tags(p.read_text()) != p.read_text()]


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    if cmd == "write":
        changed = write()
        print("updated: " + ", ".join(changed) if changed else "all pages already current")
        print("release digest:", release_digest())
        return 0
    if cmd == "check":
        stale = stale_pages()
        if stale:
            print("SRI attributes out of date in: " + ", ".join(stale) + " - run: python -m app.integrity write", file=sys.stderr)
            return 1
        print("SRI attributes current. release digest:", release_digest())
        return 0
    if cmd == "digest":
        print(release_digest())
        return 0
    if cmd == "manifest":
        print(json.dumps(served_manifest(), indent=2, sort_keys=True))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
