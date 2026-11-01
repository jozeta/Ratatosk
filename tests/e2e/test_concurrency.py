"""Concurrency regression tests against a real server process (TEST-002).
These reproduce the audit's original race findings, which a single-threaded
TestClient can't."""
import concurrent.futures as cf
import hashlib
import os
import subprocess
import sys
import time

import httpx
import pytest

from tests.e2e.conftest import ADMIN_PASSWORD, ROOT, _free_port

pytestmark = pytest.mark.e2e


def admin_headers(base):
    tok = httpx.post(base + "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def upload(base, data: bytes, token: str, **complete):
    h = admin_headers(base)
    with httpx.Client(base_url=base, headers=h, timeout=60) as c:
        uid = c.post("/api/uploads/init", json={"total_size_bytes": len(data)}).json()["upload_id"]
        c.put(f"/api/uploads/{uid}/chunk", content=data, headers={"Upload-Offset": "0"})
        body = {"ttl": "1h", "download_token_hash": hashlib.sha256(token.encode()).hexdigest(), **complete}
        return c.post(f"/api/uploads/{uid}/complete", json=body).json()["file_id"]


def test_burn_after_download_is_exactly_once(base):
    """BUG-001: was 3 of 8 admitted, two of them cut off mid-stream."""
    data = os.urandom(2 * 1024 * 1024)
    fid = upload(base, data, "tok", burn_after_download=True)

    def get(_):
        try:
            r = httpx.get(f"{base}/api/files/{fid}/blob", headers={"X-Download-Token": "tok"}, timeout=60)
            if r.status_code != 200:
                return str(r.status_code)
            return "full" if r.content == data else "corrupt"
        except httpx.HTTPError:
            return "truncated"

    with cf.ThreadPoolExecutor(10) as ex:
        outcomes = list(ex.map(get, range(10)))
    assert outcomes.count("full") == 1, outcomes
    assert outcomes.count("404") == 9, outcomes


def test_passphrase_attempts_cannot_be_raced(base):
    """SEC-005: was 32 of 32 checked against a limit of 5."""
    fid = upload(base, b"locked", "right", passphrase_protected=True, kdf_salt="c2FsdHNhbHRzYWx0c2FsdA", kdf_iterations=600000)

    def guess(i):
        return httpx.post(f"{base}/api/files/{fid}/verify-token", json={"token": f"wrong{i}"}, timeout=60).status_code

    with cf.ThreadPoolExecutor(32) as ex:
        codes = list(ex.map(guess, range(32)))
    assert codes.count(401) == 5, codes
    assert codes.count(423) == 27, codes


def test_parallel_complete_one_wins(base):
    """BUG-009."""
    h = admin_headers(base)
    with httpx.Client(base_url=base, headers=h) as c:
        uid = c.post("/api/uploads/init", json={"total_size_bytes": 3}).json()["upload_id"]
        c.put(f"/api/uploads/{uid}/chunk", content=b"abc", headers={"Upload-Offset": "0"})

    def complete(_):
        return httpx.post(f"{base}/api/uploads/{uid}/complete", json={"ttl": "1h"}, headers=h, timeout=60).status_code

    with cf.ThreadPoolExecutor(4) as ex:
        codes = sorted(ex.map(complete, range(4)))
    assert codes.count(200) == 1 and all(c in (200, 404) for c in codes), codes


def _rss_mib(pid):
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return int(out or 0) // 1024


def test_oversized_chunk_does_not_balloon_memory(base, live_server):
    """SEC-004: a 400 MiB body on a 10-byte upload used to add ~800 MiB."""
    with httpx.Client(base_url=base, timeout=120) as anon:
        uid = anon.post("/api/uploads/init", json={"total_size_bytes": 10}).json()["upload_id"]
        before = _rss_mib(live_server["pid"])

        def body():  # streamed, no Content-Length: forces the streaming bound
            for _ in range(400):
                yield b"\0" * (1024 * 1024)

        t0 = time.time()
        try:
            r = anon.put(f"/api/uploads/{uid}/chunk", content=body(), headers={"Upload-Offset": "0"})
            status = r.status_code
        except httpx.HTTPError:
            status = "connection closed early"
        elapsed = time.time() - t0
        after = _rss_mib(live_server["pid"])
    assert status in (413, "connection closed early")
    assert after - before < 50, f"server grew {after - before} MiB"
    # With Content-Length the rejection is immediate, before any body is read.
    with httpx.Client(base_url=base, timeout=30) as anon:
        uid = anon.post("/api/uploads/init", json={"total_size_bytes": 10}).json()["upload_id"]
        r = anon.put(f"/api/uploads/{uid}/chunk", content=b"x" * (5 * 1024 * 1024), headers={"Upload-Offset": "0"})
        assert r.status_code == 413
    assert elapsed < 60


def test_settings_change_reaches_a_second_process(live_server):
    """BUG-002: was never propagated at all."""
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=ROOT, env=live_server["env"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    other = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(other + "/api/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        base = live_server["base"]
        h = admin_headers(base)
        assert httpx.post(other + "/api/uploads/init", json={"total_size_bytes": 5}).status_code == 200
        httpx.patch(base + "/api/admin/settings", json={"allow_anonymous_upload": False}, headers=h)
        time.sleep(1.5)
        assert httpx.post(other + "/api/uploads/init", json={"total_size_bytes": 5}).status_code == 403
        httpx.patch(base + "/api/admin/settings", json={"allow_anonymous_upload": True}, headers=h)
    finally:
        proc.terminate()
        proc.wait(10)
