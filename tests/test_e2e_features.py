"""End-to-end keys (FEAT-002), request links (FEAT-001) and the migration
runner. Wrapped values are opaque to the server, so random strings stand in
for them here; the real cryptography is covered by tests/js/keys.test.mjs
and the browser tests."""
import base64
import hashlib
import os

from tests.helpers import make_user
from tests.test_upload_download import _upload, token_fields


def b64(n=48):
    return base64.urlsafe_b64encode(os.urandom(n)).rstrip(b"=").decode()


def keys_payload():
    return {"public_key": b64(91), "wrapped_private_key": b64(150), "kdf_salt": b64(16), "kdf_iterations": 600000}


def login(client, db_session, name, **kw):
    make_user(db_session, name, "CorrectHorse123!", **kw)
    tok = client.post("/api/auth/login", json={"username": name, "password": "CorrectHorse123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def wrap():
    return {"wrapped_key": b64(60), "ephemeral_public_key": b64(91)}


# ------------------------------------------------------------------ keys ---

def test_key_lifecycle_and_public_lookup(client, db_session):
    alice = login(client, db_session, "alice")
    bob = login(client, db_session, "bob")
    assert client.get("/api/account/keys", headers=alice).status_code == 404
    k = keys_payload()
    out = client.put("/api/account/keys", json=k, headers=alice).json()
    expected_fp = hashlib.sha256(base64.urlsafe_b64decode(k["public_key"] + "==")).hexdigest()
    assert out["fingerprint"] == expected_fp
    alice_id = client.get("/api/auth/me", headers=alice).json()["id"]
    pub = client.get(f"/api/users/{alice_id}/public-key", headers=bob).json()
    assert pub["public_key"] == k["public_key"] and pub["fingerprint"] == expected_fp
    # Only the owner ever gets the wrapped private key back.
    assert "wrapped_private_key" not in pub


def test_e2e_share_and_server_never_holds_the_key(client, db_session):
    from app.models.file import FileObject

    alice = login(client, db_session, "alice")
    bob = login(client, db_session, "bob")
    client.put("/api/account/keys", json=keys_payload(), headers=bob)
    bob_id = client.get("/api/auth/me", headers=bob).json()["id"]
    fid = _upload(client, b"for bob", headers=alice).json()["file_id"]
    w = wrap()
    r = client.post(f"/api/files/{fid}/share", json={"recipients": [{"user_id": bob_id, **w}]}, headers=alice)
    assert r.status_code == 200, r.text
    got = client.get(f"/api/files/{fid}/shared-key", headers=bob).json()
    assert got == {"scheme": "e2e", **w}
    assert client.get("/api/files/shared-with-me", headers=bob).json()[0]["scheme"] == "e2e"
    db_session.expire_all()
    assert db_session.get(FileObject, fid).shared_decryption_key is None


def test_server_held_keys_can_be_disabled(client, admin_headers, db_session):
    alice = login(client, db_session, "alice")
    login(client, db_session, "carol")  # no keys
    carol_id = client.get("/api/users/lookup", params={"username": "carol"}, headers=alice).json()["id"]
    fid = _upload(client, b"x", headers=alice).json()["file_id"]
    client.patch("/api/admin/settings", json={"allow_server_held_share_keys": False}, headers=admin_headers)
    r = client.post(f"/api/files/{fid}/share", json={"user_ids": [carol_id], "key": "k" * 43}, headers=alice)
    assert r.status_code == 400 and "encryption keys" in r.json()["detail"]


def test_replacing_keys_drops_old_e2e_shares_and_closes_requests(client, db_session):
    alice = login(client, db_session, "alice")
    bob = login(client, db_session, "bob")
    client.put("/api/account/keys", json=keys_payload(), headers=bob)
    bob_id = client.get("/api/auth/me", headers=bob).json()["id"]
    fid = _upload(client, b"x", headers=alice).json()["file_id"]
    client.post(f"/api/files/{fid}/share", json={"recipients": [{"user_id": bob_id, **wrap()}]}, headers=alice)
    req = client.post("/api/requests", json={"label": "docs"}, headers=bob).json()
    client.put("/api/account/keys", json=keys_payload(), headers=bob)  # new keypair
    assert client.get("/api/files/shared-with-me", headers=bob).json() == []
    assert client.get(f"/api/requests/{req['id']}/public").json()["open"] is False
    # Re-wrapping under a new passphrase (same public key) changes nothing.
    current = client.get("/api/account/keys", headers=bob).json()
    rewrap = {**keys_payload(), "public_key": current["public_key"]}
    assert client.put("/api/account/keys", json=rewrap, headers=bob).status_code == 200


# ------------------------------------------------------------- requests ---

def _request_upload(client, request_id, data=b"secret submission", with_wrap=True):
    init = client.post("/api/uploads/init", json={"total_size_bytes": len(data), "request_id": request_id})
    if init.status_code != 200:
        return init
    uid = init.json()["upload_id"]
    client.put(f"/api/uploads/{uid}/chunk", content=data, headers={"Upload-Offset": "0"})
    body = {"ttl": "nonsense-ignored", **token_fields("tok", passphrase=False)}
    if with_wrap:
        body.update(wrap())
    return client.post(f"/api/uploads/{uid}/complete", json=body)


def test_request_link_flow(client, admin_headers, db_session):
    owner = login(client, db_session, "owner")
    assert client.post("/api/requests", json={"label": "x"}, headers=owner).status_code == 400  # needs keys first
    client.put("/api/account/keys", json=keys_payload(), headers=owner)
    req = client.post("/api/requests", json={"label": "Tax documents", "max_uploads": 2}, headers=owner).json()

    # Works for strangers even when anonymous uploads are off - that's the point.
    client.patch("/api/admin/settings", json={"allow_anonymous_upload": False}, headers=admin_headers)
    pub = client.get(f"/api/requests/{req['id']}/public").json()
    assert pub["label"] == "Tax documents" and pub["open"] and pub["uploads_left"] == 2
    assert _request_upload(client, req["id"], with_wrap=False).status_code == 400  # must be wrapped to the owner
    first = _request_upload(client, req["id"])
    assert first.status_code == 200, first.text
    assert _request_upload(client, req["id"]).status_code == 200
    assert _request_upload(client, req["id"]).status_code == 410  # limit reached
    assert client.get(f"/api/requests/{req['id']}/public").json()["open"] is False

    files = client.get(f"/api/requests/{req['id']}/files", headers=owner).json()
    assert len(files) == 2 and all(f["wrapped_key"] and f["ephemeral_public_key"] for f in files)
    # Submissions live in the request inbox, not in "My Files".
    assert client.get("/api/files/mine", headers=owner).json() == []
    # The blob is still protected by the download token.
    fid = first.json()["file_id"]
    assert client.get(f"/api/files/{fid}/blob").status_code == 401
    assert client.get(f"/api/files/{fid}/blob", headers={"X-Download-Token": "tok"}).content == b"secret submission"


def test_request_inbox_is_private(client, db_session):
    owner = login(client, db_session, "owner")
    other = login(client, db_session, "other")
    client.put("/api/account/keys", json=keys_payload(), headers=owner)
    req = client.post("/api/requests", json={}, headers=owner).json()
    assert client.get(f"/api/requests/{req['id']}/files", headers=other).status_code == 404
    assert client.post(f"/api/requests/{req['id']}/close", headers=other).status_code == 404
    assert client.delete(f"/api/requests/{req['id']}", headers=other).status_code == 404


def test_request_size_limit_and_closing(client, db_session):
    owner = login(client, db_session, "owner")
    client.put("/api/account/keys", json=keys_payload(), headers=owner)
    req = client.post("/api/requests", json={"max_file_size_mb": 1}, headers=owner).json()
    big = client.post("/api/uploads/init", json={"total_size_bytes": 3 * 1024 * 1024, "request_id": req["id"]})
    assert big.status_code == 413
    client.post(f"/api/requests/{req['id']}/close", headers=owner)
    assert _request_upload(client, req["id"]).status_code == 410


def test_deleting_the_owner_removes_requests_and_submissions(client, db_session):
    from app.models.file import FileObject
    from app.models.upload_request import UploadRequest

    owner = login(client, db_session, "owner")
    client.put("/api/account/keys", json=keys_payload(), headers=owner)
    req = client.post("/api/requests", json={}, headers=owner).json()
    fid = _request_upload(client, req["id"]).json()["file_id"]
    client.request("DELETE", "/api/auth/me", json={"password": "CorrectHorse123!"}, headers=owner)
    db_session.expire_all()
    assert db_session.get(UploadRequest, req["id"]) is None
    assert db_session.get(FileObject, fid).is_deleted


# ------------------------------------------------------------- migrations ---

def test_pre_alembic_database_is_brought_to_head(tmp_path):
    """Regression: the legacy path used to stamp the baseline and then re-run
    later revisions on top of the already-current schema."""
    import subprocess
    import sys

    db = tmp_path / "legacy.db"
    script = f"""
import os
os.environ["RATATOSK_DATABASE_URL"] = "sqlite:///{db}"
os.environ["RATATOSK_SECRET_KEY"] = "migration-test-" + "m" * 40
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["RATATOSK_DATABASE_URL"])
with eng.begin() as c:  # a minimal 1.x-era schema: no alembic_version, old columns only
    c.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, username VARCHAR(64) NOT NULL, password_hash VARCHAR(255) NOT NULL, is_admin BOOLEAN NOT NULL DEFAULT 0, is_active BOOLEAN NOT NULL DEFAULT 1)"))
    c.execute(text("CREATE TABLE system_settings (id INTEGER PRIMARY KEY, brand_name VARCHAR(64), smtp_from_name VARCHAR(64))"))
    c.execute(text("INSERT INTO users (id, username, password_hash) VALUES ('u1', 'admin', 'x')"))
    c.execute(text("INSERT INTO system_settings (id, brand_name, smtp_from_name) VALUES (1, 'SecureDrop', '')"))
from app.core.migrate import run_migrations
run_migrations()
with eng.connect() as c:
    print(c.execute(text("select version_num from alembic_version")).scalar())
    print(c.execute(text("select brand_name from system_settings")).scalar())
    print(c.execute(text("select username from users")).scalar())
"""
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=os.getcwd())
    assert out.returncode == 0, out.stderr
    version, brand, user = out.stdout.split()
    from alembic.script import ScriptDirectory

    from app.core.migrate import alembic_config

    assert version == ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert brand == "Ratatosk" and user == "admin"
