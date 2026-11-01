"""Browser end-to-end fixtures (TEST-004): a throwaway Ratatosk server in its
own process, database and storage, driven with Playwright/Chromium.

Run:  pytest tests/e2e        (after: python -m playwright install chromium)
"""
import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ADMIN_PASSWORD = "E2E-Admin-Pass-123!"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    tmp = tempfile.mkdtemp(prefix="ratatosk_e2e_")
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("RATATOSK_", "SECUREDROP_"))},
        "RATATOSK_DATABASE_URL": "sqlite:///" + os.path.join(tmp, "e2e.db"),
        "RATATOSK_STORAGE_ROOT": os.path.join(tmp, "storage"),
        "RATATOSK_TMP_ROOT": os.path.join(tmp, "tmp"),
        "RATATOSK_BRANDING_ROOT": os.path.join(tmp, "branding"),
        "RATATOSK_SECRET_KEY": "e2e-only-secret-" + "k" * 40,
        "RATATOSK_DEFAULT_ADMIN_PASSWORD": ADMIN_PASSWORD,
    }
    py = sys.executable
    subprocess.run([py, "-m", "app.init_db"], cwd=ROOT, env=env, check=True, capture_output=True)
    subprocess.run([py, "-c", "from app.core.dynamic_settings import update_settings; update_settings({'rate_limit_enabled': False})"],
                   cwd=ROOT, env=env, check=True, capture_output=True)
    port = _free_port()
    log = open(os.path.join(tmp, "server.log"), "wb")
    proc = subprocess.Popen([py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/api/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("e2e server did not start; see " + log.name)
    yield {"base": base, "env": env, "tmp": tmp, "pid": proc.pid, "port": port}
    proc.terminate()
    proc.wait(10)


@pytest.fixture()
def base(live_server):
    return live_server["base"]


@pytest.fixture()
def csp_violations(page):
    """Collects Content-Security-Policy violations reported by the browser."""
    seen: list[str] = []
    page.on("console", lambda m: seen.append(m.text) if "Content Security Policy" in m.text else None)
    page.on("pageerror", lambda e: seen.append(f"pageerror: {e}"))
    return seen
