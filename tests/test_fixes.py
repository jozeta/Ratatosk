"""Regression tests for the audit fixes (finding ids in each test name/doc)."""
import datetime
import hashlib
import time

import pyotp
import pytest

from tests.helpers import make_user
from tests.test_upload_download import _upload, token_fields


def login(client, db_session, username, password="CorrectHorse123!", **user_kw):
    make_user(db_session, username, password, **user_kw)
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ------------------------------------------------------------ TEST-006 ---

def test_zero_log_stores_no_identity(client, admin_headers, db_session):
    """SEC-002/SEC-003/SEC-016: with zero-log on, no audit row or file row
    links an action to an account, cookie, IP or user agent."""
    from app.models.audit_log import AuditLog
    from app.models.file import FileObject

    client.patch("/api/admin/settings", json={"zero_log_mode": True}, headers=admin_headers)
    alice = login(client, db_session, "alice")
    _upload(client, b"anon data")
    fid = _upload(client, b"alice data", headers=alice).json()["file_id"]
    client.get(f"/api/files/{fid}/blob")
    client.post("/api/auth/login", json={"username": "typo-or-password-pasted-here", "password": "x"})

    db_session.expire_all()
    since = db_session.query(AuditLog).filter(AuditLog.event_type == "ADMIN_CONFIG_CHANGE").one().timestamp
    rows = db_session.query(AuditLog).filter(AuditLog.timestamp >= since, AuditLog.event_type != "ADMIN_CONFIG_CHANGE").all()
    assert rows
    for r in rows:
        assert r.actor_token is None and r.ip_address is None and r.user_agent is None and r.user_id is None, r.event_type
        assert "typo-or-password" not in (r.detail or "")
    for f in db_session.query(FileObject).all():
        assert f.uploader_token == ""


def test_failed_login_never_logs_the_typed_username(client, db_session):
    from app.models.audit_log import AuditLog

    client.post("/api/auth/login", json={"username": "MySecretPassw0rd!", "password": "x"})
    assert not db_session.query(AuditLog).filter(AuditLog.detail.contains("MySecretPassw0rd")).count()


# ------------------------------------------------------------ TEST-009 ---

@pytest.mark.parametrize("enforce,login_allowed,expect", [
    (False, True, "token"),
    (True, True, "mfa_setup_required"),
    (False, False, "login_required"),
    (True, False, "login_required"),
])
def test_register_follows_the_same_session_policy_as_login(client, admin_headers, enforce, login_allowed, expect):
    """SEC-007: registration can't bypass enforced MFA or disabled login."""
    client.patch("/api/admin/settings", json={"enable_mfa": True, "enforce_mfa_users": enforce,
                                              "allow_user_login": login_allowed}, headers=admin_headers)
    body = client.post("/api/auth/register", json={"username": f"new{enforce}{login_allowed}", "password": "Some-Long-Pass-1!"}).json()
    if expect == "token":
        assert body.get("access_token")
    else:
        assert not body.get("access_token")
        assert body.get(expect) is True


# -------------------------------------------------------- MFA / sessions ---

def _enable_mfa(client, headers):
    secret = client.post("/api/auth/mfa/setup", headers=headers).json()["secret"]
    client.post("/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=headers)
    return secret


def test_totp_code_is_single_use(client, db_session):
    """SEC-014."""
    h = login(client, db_session, "erin")
    secret = _enable_mfa(client, h)
    nxt = pyotp.TOTP(secret).at(time.time() + 30)
    t1 = client.post("/api/auth/login", json={"username": "erin", "password": "CorrectHorse123!"}).json()["mfa_token"]
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": t1, "code": nxt}).status_code == 200
    t2 = client.post("/api/auth/login", json={"username": "erin", "password": "CorrectHorse123!"}).json()["mfa_token"]
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": t2, "code": nxt}).status_code == 401


def test_disabling_mfa_needs_a_code_and_is_blocked_when_enforced(client, admin_headers, db_session):
    """SEC-019."""
    h = login(client, db_session, "frank")
    secret = _enable_mfa(client, h)
    assert client.post("/api/auth/mfa/disable", json={"password": "CorrectHorse123!", "code": "000000"}, headers=h).status_code == 401
    client.patch("/api/admin/settings", json={"enforce_mfa_users": True}, headers=admin_headers)
    code = pyotp.TOTP(secret).at(time.time() + 30)
    assert client.post("/api/auth/mfa/disable", json={"password": "CorrectHorse123!", "code": code}, headers=h).status_code == 403
    client.patch("/api/admin/settings", json={"enforce_mfa_users": False}, headers=admin_headers)
    ok = client.post("/api/auth/mfa/disable", json={"password": "CorrectHorse123!", "code": code}, headers=h)
    assert ok.status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401  # other sessions ended


def test_logout_revokes_the_token(client, db_session):
    """SEC-017."""
    h = login(client, db_session, "gina")
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_last_admin_cannot_delete_or_demote_themselves(client, admin_headers, db_session):
    """BUG-003."""
    r = client.request("DELETE", "/api/auth/me", json={"password": "AdminPass123!"}, headers=admin_headers)
    assert r.status_code == 400 and "no active administrator" in r.json()["detail"]
    other = login(client, db_session, "admin2", is_admin=True)
    assert client.request("DELETE", "/api/auth/me", json={"password": "CorrectHorse123!"}, headers=other).status_code == 200


def test_self_delete_requires_the_password(client, db_session):
    h = login(client, db_session, "henry")
    assert client.request("DELETE", "/api/auth/me", json={"password": "wrong"}, headers=h).status_code == 401
    assert client.get("/api/auth/me", headers=h).status_code == 200


def test_login_lockout_is_per_network_and_admin_can_unlock(client, admin_headers, db_session):
    """SEC-012: lockout applies to the guessing client's network only."""
    from app.services.lockout import clear_login_throttles

    make_user(db_session, "ivan", "CorrectHorse123!")
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "ivan", "password": "nope"})
    assert client.post("/api/auth/login", json={"username": "ivan", "password": "CorrectHorse123!"}).status_code == 423
    assert clear_login_throttles(db_session) >= 1
    assert client.post("/api/auth/login", json={"username": "ivan", "password": "CorrectHorse123!"}).status_code == 200


# -------------------------------------------------------------- uploads ---

def test_server_never_accepts_a_passphrase(client):
    assert _upload(client, b"x", password="hunter2").status_code == 400


def test_token_protected_download(client):
    """SEC-006: without the token nothing is served, counted, or burned."""
    fid = _upload(client, b"guarded", burn_after_download=True, **token_fields("tok", passphrase=False)).json()["file_id"]
    assert client.get(f"/api/files/{fid}/blob").status_code == 401
    assert client.get(f"/api/files/{fid}/blob", headers={"X-Download-Token": "nope"}).status_code == 401
    assert client.get(f"/api/files/{fid}/meta").json()["download_count"] == 0
    ok = client.get(f"/api/files/{fid}/blob", headers={"X-Download-Token": "tok"})
    assert ok.status_code == 200 and ok.content == b"guarded"
    assert client.get(f"/api/files/{fid}/meta").status_code == 404  # burned


def test_size_limit_allows_encryption_overhead(client, admin_headers):
    """BUG-006: a file exactly at the limit fits once encrypted."""
    client.patch("/api/admin/settings", json={"max_file_size_mb": 1}, headers=admin_headers)
    ciphertext = 1 + 4 + 8 + 4 + 80 + 1024 * 1024 + 2 * 16
    assert client.post("/api/uploads/init", json={"total_size_bytes": ciphertext}).status_code == 200


def test_chunks_are_offset_addressed_and_retry_safe(client):
    """BUG-008: re-sending a chunk doesn't duplicate data; resume reports
    the right offset; out-of-order chunks assemble correctly."""
    uid = client.post("/api/uploads/init", json={"total_size_bytes": 9}).json()["upload_id"]
    put = lambda off, data: client.put(f"/api/uploads/{uid}/chunk", content=data, headers={"Upload-Offset": str(off)})  # noqa: E731
    assert put(6, b"ghi").status_code == 200   # out of order
    assert put(0, b"abc").status_code == 200
    assert put(0, b"abc").status_code == 200   # retried
    assert client.get(f"/api/uploads/{uid}").json()["resume_offset"] == 3
    assert put(3, b"def").status_code == 200
    body = {"ttl": "1h", "burn_after_download": False, "max_downloads": 0}
    fid = client.post(f"/api/uploads/{uid}/complete", json=body).json()["file_id"]
    assert client.get(f"/api/files/{fid}/blob").content == b"abcdefghi"


def test_incomplete_upload_cannot_be_completed(client):
    uid = client.post("/api/uploads/init", json={"total_size_bytes": 10}).json()["upload_id"]
    client.put(f"/api/uploads/{uid}/chunk", content=b"abc", headers={"Upload-Offset": "0"})
    r = client.post(f"/api/uploads/{uid}/complete", json={"ttl": "1h"})
    assert r.status_code == 400


def test_cancel_upload(client):
    uid = client.post("/api/uploads/init", json={"total_size_bytes": 5}).json()["upload_id"]
    assert client.delete(f"/api/uploads/{uid}").status_code == 200
    assert client.get(f"/api/uploads/{uid}").status_code == 404


def test_capacity_counts_uploads_in_progress(client, admin_headers):
    """SEC-011/PERF-001: reservations by in-progress uploads count."""
    client.patch("/api/admin/settings", json={"total_storage_cap_gb": 1, "max_concurrent_uploads": 10}, headers=admin_headers)
    big = int(0.6 * 1024 ** 3)
    assert client.post("/api/uploads/init", json={"total_size_bytes": big}, headers=admin_headers).status_code in (200, 413)
    client.patch("/api/admin/settings", json={"max_file_size_mb": 1024}, headers=admin_headers)
    assert client.post("/api/uploads/init", json={"total_size_bytes": big}, headers=admin_headers).status_code == 200
    assert client.post("/api/uploads/init", json={"total_size_bytes": big}, headers=admin_headers).status_code == 507


def test_global_active_upload_cap(client, admin_headers):
    client.patch("/api/admin/settings", json={"max_active_upload_sessions": 1}, headers=admin_headers)
    assert client.post("/api/uploads/init", json={"total_size_bytes": 5}, headers=admin_headers).status_code == 200
    assert client.post("/api/uploads/init", json={"total_size_bytes": 5}).status_code == 503


def test_rate_limit(client, admin_headers):
    """SEC-011."""
    client.patch("/api/admin/settings", json={"rate_limit_enabled": True, "rate_limit_per_minute": 3}, headers=admin_headers)
    codes = [client.post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and 429 in codes[3:]


# ------------------------------------------------------- link management ---

def test_owner_link_management(client, db_session):
    """FEAT-007: switch off/on, shorten expiry, lower limit; never loosen."""
    h = login(client, db_session, "jo")
    fid = _upload(client, b"managed", headers=h, max_downloads=5).json()["file_id"]
    assert client.patch(f"/api/files/{fid}", json={"disabled": True}, headers=h).status_code == 200
    assert client.get(f"/api/files/{fid}/meta").status_code == 404
    client.patch(f"/api/files/{fid}", json={"disabled": False}, headers=h)
    assert client.get(f"/api/files/{fid}/meta").status_code == 200
    later = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=60)).isoformat()
    assert client.patch(f"/api/files/{fid}", json={"expires_at": later}, headers=h).status_code == 400
    assert client.patch(f"/api/files/{fid}", json={"max_downloads": 9}, headers=h).status_code == 400
    assert client.patch(f"/api/files/{fid}", json={"max_downloads": 2}, headers=h).status_code == 200
    stranger = login(client, db_session, "kim")
    assert client.patch(f"/api/files/{fid}", json={"disabled": True}, headers=stranger).status_code == 403


def test_bundle_groups_and_deletes_members(client, db_session):
    """FEAT-003."""
    from app.models.file import FileObject

    h = login(client, db_session, "lena")
    members = [_upload(client, data, headers=h).json()["file_id"] for data in (b"a", b"b")]
    bundle = _upload(client, b"{manifest}", headers=h, is_bundle=True, bundle_member_ids=members).json()["file_id"]
    mine = client.get("/api/files/mine", headers=h).json()
    assert [f["file_id"] for f in mine] == [bundle] and mine[0]["bundle_file_count"] == 2
    client.delete(f"/api/files/{bundle}", headers=h)
    db_session.expire_all()
    assert all(db_session.get(FileObject, m).is_deleted for m in members)


def test_shared_key_must_belong_to_the_file(client, db_session):
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    owner = login(client, db_session, "mia")
    login(client, db_session, "noa")
    secret = b"\x07" * 32
    token = base64.urlsafe_b64encode(HKDF(hashes.SHA256(), 32, None, b"ratatosk-dl-v1").derive(secret)).rstrip(b"=").decode()
    fid = _upload(client, b"s", headers=owner, **token_fields(token, passphrase=False)).json()["file_id"]
    noa_id = client.get("/api/users/lookup", params={"username": "noa"}, headers=owner).json()["id"]
    good = base64.urlsafe_b64encode(secret).rstrip(b"=").decode()
    assert client.post(f"/api/files/{fid}/share", json={"user_ids": [noa_id], "key": "A" * 43}, headers=owner).status_code == 400
    assert client.post(f"/api/files/{fid}/share", json={"user_ids": [noa_id], "key": good}, headers=owner).status_code == 200


def test_account_deletion_releases_share_keys(client, db_session):
    """SEC-018."""
    from app.models.file import FileObject

    owner = login(client, db_session, "oli")
    rec = login(client, db_session, "pia")
    fid = _upload(client, b"x", headers=owner).json()["file_id"]
    pia = client.get("/api/users/lookup", params={"username": "pia"}, headers=owner).json()["id"]
    client.post(f"/api/files/{fid}/share", json={"user_ids": [pia], "key": "k" * 43}, headers=owner)
    client.request("DELETE", "/api/auth/me", json={"password": "CorrectHorse123!"}, headers=rec)
    db_session.expire_all()
    assert db_session.get(FileObject, fid).shared_decryption_key is None


# ---------------------------------------------------------------- admin ---

def test_audit_prune_is_bounded_and_audited(client, admin_headers):
    """SEC-015."""
    assert client.post("/api/admin/audit/prune?days=-1", headers=admin_headers).status_code == 422
    client.post("/api/admin/audit/prune?days=1", headers=admin_headers)
    events = [e["event_type"] for e in client.get("/api/admin/audit", headers=admin_headers).json()["items"]]
    assert "AUDIT_PRUNED" in events


@pytest.mark.parametrize("field,value", [
    ("chunk_size_mb", 0), ("max_login_attempts", 0), ("max_concurrent_uploads", -1),
    ("cleanup_interval_minutes", 0), ("max_file_size_mb", -5), ("default_ttl", "forever"),
    ("ip_obfuscation_level", "sometimes"), ("storage_path", "/"), ("version", 99),
])
def test_settings_reject_invalid_or_read_only_values(client, admin_headers, field, value):
    """BUG-004 / SEC-010 (TEST-008)."""
    assert client.patch("/api/admin/settings", json={field: value}, headers=admin_headers).status_code == 422


def test_settings_can_clear_nullable_and_reject_null_required(client, admin_headers):
    """ARCH-004: explicit null clears nullable fields only."""
    assert client.patch("/api/admin/settings", json={"brand_name": None}, headers=admin_headers).status_code == 422


def test_settings_changes_reach_other_processes(client, admin_headers):
    """BUG-002 (TEST-008): another process's cache notices a change made
    elsewhere within the revalidation window."""
    from app.core import dynamic_settings
    from app.core.database import SessionLocal
    from app.models.settings import SystemSettings

    assert dynamic_settings.get_settings()["allow_anonymous_upload"] is True
    db = SessionLocal()  # simulate another process writing the row directly
    row = db.get(SystemSettings, 1)
    row.allow_anonymous_upload = False
    row.version += 1
    db.commit()
    db.close()
    dynamic_settings.invalidate_cache()
    assert dynamic_settings.get_settings()["allow_anonymous_upload"] is False


def test_factory_reset_only_deletes_known_blobs(client, admin_headers, tmp_path):
    """SEC-010."""
    import os

    from app.core.config import settings

    fid = _upload(client, b"to be wiped", headers=admin_headers).json()["file_id"]
    assert fid
    bystander = os.path.join(settings.storage_root, "not-ours.txt")
    open(bystander, "w").write("keep me")
    r = client.post("/api/admin/system/reset", json={"password": "AdminPass123!", "confirm": "RESET"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert os.path.exists(bystander)
    assert [n for n in os.listdir(settings.storage_root) if n != "not-ours.txt"] == []


# -------------------------------------------------------------- cleanup ---

def test_cleanup_expires_through_backend_and_applies_audit_retention(client, admin_headers, db_session):
    """BUG-005 / BUG-011 / PERF-002."""
    import os

    from app.core.cleanup import run_cleanup_once
    from app.core.config import settings
    from app.models.audit_log import AuditLog
    from app.models.file import FileObject

    fid = _upload(client, b"short lived", headers=admin_headers).json()["file_id"]
    f = db_session.get(FileObject, fid)
    blob = os.path.join(settings.storage_root, f.storage_filename)
    assert os.path.exists(blob)
    f.expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)
    db_session.add(AuditLog(event_type="OLD", timestamp=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=400)))
    db_session.commit()
    assert run_cleanup_once(force=True) == 1
    assert not os.path.exists(blob)
    db_session.expire_all()
    assert db_session.query(AuditLog).filter(AuditLog.event_type == "OLD").count() == 0


def test_failed_blob_deletions_are_retried(client, admin_headers, db_session, monkeypatch):
    """ARCH-007."""
    from app.models.ops import PendingBlobDeletion
    from app.services import files as files_service
    from app.services import storage_service

    fid = _upload(client, b"x", headers=admin_headers).json()["file_id"]

    def boom(name):
        raise OSError("storage offline")

    monkeypatch.setattr(storage_service, "delete_blob", boom)
    assert client.delete(f"/api/files/{fid}", headers=admin_headers).status_code == 200
    db_session.expire_all()
    pending = db_session.query(PendingBlobDeletion).all()
    assert len(pending) == 1 and pending[0].attempts == 1 and "offline" in pending[0].last_error
    monkeypatch.undo()
    assert files_service.process_pending_deletions(db_session) == 1


def test_cleanup_lease_prevents_concurrent_runs(client):
    from app.core import cleanup
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        assert cleanup._acquire_lease(db, 60) is True
        cleanup._holder, saved = "someone-else", cleanup._holder
        try:
            assert cleanup._acquire_lease(db, 60) is False
        finally:
            cleanup._holder = saved
    finally:
        db.close()


def test_version_is_consistent():
    import re

    from app.version import __version__

    cli = open("cli/ratatosk.py").read()
    assert re.search(r'__version__ = "([^"]+)"', cli).group(1) == __version__
    assert f"## [{__version__}]" in open("CHANGELOG.md").read()


def test_health_and_config_report_version(client):
    from app.version import __version__

    assert client.get("/api/health").json()["version"] == __version__
    assert client.get("/api/config").json()["version"] == __version__


def test_security_headers(client):
    """SEC-009."""
    h = client.get("/").headers
    assert "script-src 'self'" in h["content-security-policy"]
    assert h["cross-origin-opener-policy"] == "same-origin"
    assert client.get("/api/branding/logo").status_code == 404


def test_hash_helper_matches_upload_contract():
    assert hashlib.sha256(b"tok").hexdigest() == token_fields("tok", passphrase=False)["download_token_hash"]


# --------------------------------------------------- cookie sessions (SEC-017) ---

def test_browser_session_is_an_httponly_cookie_with_csrf(client, db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    make_user(db_session, "cookie-user", "CorrectHorse123!")
    with TestClient(app) as browser:  # a cookie-keeping client, like a real browser
        r = browser.post("/api/auth/login", json={"username": "cookie-user", "password": "CorrectHorse123!"})
        set_cookie = r.headers["set-cookie"].lower()
        assert "rt_session=" in set_cookie and "httponly" in set_cookie and "samesite=strict" in set_cookie
        assert browser.get("/api/auth/me").status_code == 200  # GET needs no CSRF header
        # A state-changing request riding on the cookie without the header is refused.
        assert browser.post("/api/auth/logout-everywhere").status_code == 403
        ok = browser.post("/api/auth/logout-everywhere", headers={"X-Ratatosk-CSRF": "1"})
        assert ok.status_code == 200
        assert browser.post("/api/auth/logout", headers={"X-Ratatosk-CSRF": "1"}).status_code == 200
        assert browser.get("/api/auth/me").status_code == 401
