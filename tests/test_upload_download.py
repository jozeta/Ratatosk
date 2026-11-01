def _upload(client, data: bytes, headers=None, **complete_overrides):
    headers = headers or {}
    init = client.post("/api/uploads/init", json={"total_size_bytes": len(data)}, headers=headers)
    assert init.status_code == 200, init.text
    upload_id = init.json()["upload_id"]

    chunk = client.put(
        f"/api/uploads/{upload_id}/chunk",
        content=data,
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert chunk.status_code == 200, chunk.text

    payload = {"ttl": "1h", "burn_after_download": False, "max_downloads": 0, "password": None}
    payload.update(complete_overrides)
    complete = client.post(f"/api/uploads/{upload_id}/complete", json=payload, headers=headers)
    return complete


def test_anonymous_upload_download_round_trip(client):
    data = b"hello from a completely anonymous uploader"
    complete = _upload(client, data)
    assert complete.status_code == 200, complete.text
    file_id = complete.json()["file_id"]

    blob = client.get(f"/api/files/{file_id}/blob")
    assert blob.status_code == 200
    assert blob.content == data


def test_anonymous_upload_disabled(client, admin_headers):
    client.patch("/api/admin/settings", json={"allow_anonymous_upload": False}, headers=admin_headers)
    resp = client.post("/api/uploads/init", json={"total_size_bytes": 10})
    assert resp.status_code == 403


def test_anonymous_download_disabled(client, admin_headers):
    complete = _upload(client, b"some content", headers=admin_headers)
    file_id = complete.json()["file_id"]

    client.patch("/api/admin/settings", json={"allow_anonymous_download": False}, headers=admin_headers)
    resp = client.get(f"/api/files/{file_id}/blob")
    assert resp.status_code == 403


def test_custom_ttl_ignored_when_admin_locks_it(client, admin_headers):
    client.patch(
        "/api/admin/settings",
        json={"allow_custom_ttl": False, "default_ttl": "10m", "allowed_ttl_presets": "10m,1h,24h,7d,30d"},
        headers=admin_headers,
    )
    # Client asks for 30 days; the server must silently use default_ttl (10m) instead.
    complete = _upload(client, b"ttl test", headers=admin_headers, ttl="30d")
    assert complete.status_code == 200, complete.text

    import datetime

    expires_at = datetime.datetime.fromisoformat(complete.json()["expires_at"])
    now = datetime.datetime.now(datetime.UTC)
    assert expires_at - now < datetime.timedelta(hours=1)  # consistent with ~10m, not 30d


def test_burn_after_download_forced_off_by_server(client, admin_headers):
    """Regression test for a real bug fixed this session: the UI hid the burn
    toggle when allow_burn_after_download was off, but the API itself still
    honored a client-sent burn_after_download=True. The server must ignore it."""
    client.patch(
        "/api/admin/settings",
        json={"allow_burn_after_download": False, "force_burn_after_download": False},
        headers=admin_headers,
    )
    complete = _upload(client, b"should not burn", headers=admin_headers, burn_after_download=True)
    assert complete.status_code == 200, complete.text
    file_id = complete.json()["file_id"]

    meta = client.get(f"/api/files/{file_id}/meta", headers=admin_headers)
    assert meta.json()["burn_after_download"] is False


def test_force_burn_after_download_applies_even_if_client_says_no(client, admin_headers):
    client.patch(
        "/api/admin/settings",
        json={"allow_burn_after_download": True, "force_burn_after_download": True},
        headers=admin_headers,
    )
    complete = _upload(client, b"forced burn", headers=admin_headers, burn_after_download=False)
    file_id = complete.json()["file_id"]

    meta = client.get(f"/api/files/{file_id}/meta", headers=admin_headers)
    assert meta.json()["burn_after_download"] is True


def token_fields(token: str, passphrase: bool = True) -> dict:
    """What a client sends at /complete for a token-protected upload."""
    import hashlib

    fields = {"download_token_hash": hashlib.sha256(token.encode()).hexdigest()}
    if passphrase:
        fields.update(passphrase_protected=True, kdf_salt="c2FsdHNhbHRzYWx0c2FsdA", kdf_iterations=600000)
    return fields


def test_secondary_password_lockout(client, admin_headers):
    """Exactly max_login_attempts wrong guesses are checked, then the file is
    locked - even for the right passphrase - until the lockout expires."""
    complete = _upload(client, b"secret content", headers=admin_headers, **token_fields("right-token"))
    assert complete.status_code == 200, complete.text
    file_id = complete.json()["file_id"]
    max_attempts = client.get("/api/admin/settings", headers=admin_headers).json()["max_login_attempts"]

    codes = [client.post(f"/api/files/{file_id}/verify-token", json={"token": "wrong"}).status_code for _ in range(max_attempts)]
    assert codes == [401] * max_attempts

    resp = client.post(f"/api/files/{file_id}/verify-token", json={"token": "right-token"})
    assert resp.status_code == 423
    # The lock is temporary and the owner can lift it (SEC-006).
    assert client.post(f"/api/files/{file_id}/unlock", headers=admin_headers).status_code == 200
    assert client.post(f"/api/files/{file_id}/verify-token", json={"token": "right-token"}).status_code == 200


def test_plaintext_passphrase_is_refused(client):
    """SEC-001: the server must never receive a passphrase."""
    resp = _upload(client, b"x", password="hunter2")
    assert resp.status_code == 400
    assert "passphrase" in resp.json()["detail"]


def test_owner_can_delete_others_cannot(client):
    client.post("/api/auth/register", json={"username": "owner1", "password": "correcthorse123"})
    owner_headers = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'owner1', 'password': 'correcthorse123'}).json()['access_token']}"}
    client.post("/api/auth/register", json={"username": "stranger1", "password": "correcthorse123"})
    stranger_headers = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'stranger1', 'password': 'correcthorse123'}).json()['access_token']}"}

    complete = _upload(client, b"owned file", headers=owner_headers)
    file_id = complete.json()["file_id"]

    denied = client.delete(f"/api/files/{file_id}", headers=stranger_headers)
    assert denied.status_code == 403

    allowed = client.delete(f"/api/files/{file_id}", headers=owner_headers)
    assert allowed.status_code == 200
