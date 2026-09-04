from tests.test_upload_download import _upload


def _register_and_login(client, username):
    client.post("/api/auth/register", json={"username": username, "password": "correcthorse123"})
    token = client.post("/api/auth/login", json={"username": username, "password": "correcthorse123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_owner_can_share_recipient_can_read_key_stranger_cannot(client):
    owner = _register_and_login(client, "owner2")
    recipient = _register_and_login(client, "recipient2")
    stranger = _register_and_login(client, "stranger2")

    complete = _upload(client, b"shared content", headers=owner)
    file_id = complete.json()["file_id"]

    recipient_id = client.get("/api/users/list", headers=owner).json()
    recipient_user_id = next(u["id"] for u in recipient_id if u["username"] == "recipient2")

    share = client.post(
        f"/api/files/{file_id}/share",
        json={"user_ids": [recipient_user_id], "key": "fake-url-key-for-test"},
        headers=owner,
    )
    assert share.status_code == 200, share.text

    got_key = client.get(f"/api/files/{file_id}/shared-key", headers=recipient)
    assert got_key.status_code == 200
    assert got_key.json()["key"] == "fake-url-key-for-test"

    denied = client.get(f"/api/files/{file_id}/shared-key", headers=stranger)
    assert denied.status_code in (403, 404)


def test_only_owner_can_share(client):
    owner = _register_and_login(client, "owner3")
    stranger = _register_and_login(client, "stranger3")

    complete = _upload(client, b"owned only", headers=owner)
    file_id = complete.json()["file_id"]

    users = client.get("/api/users/list", headers=stranger).json()
    owner_user_id = next(u["id"] for u in users if u["username"] == "owner3")

    resp = client.post(
        f"/api/files/{file_id}/share",
        json={"user_ids": [owner_user_id], "key": "irrelevant"},
        headers=stranger,
    )
    assert resp.status_code == 403


def test_only_owner_or_admin_can_revoke_share(client, admin_headers):
    owner = _register_and_login(client, "owner4")
    recipient = _register_and_login(client, "recipient4")
    stranger = _register_and_login(client, "stranger4")

    complete = _upload(client, b"revoke test", headers=owner)
    file_id = complete.json()["file_id"]
    recipient_user_id = next(u["id"] for u in client.get("/api/users/list", headers=owner).json() if u["username"] == "recipient4")
    client.post(f"/api/files/{file_id}/share", json={"user_ids": [recipient_user_id], "key": "k"}, headers=owner)

    denied = client.delete(f"/api/files/{file_id}/share/{recipient_user_id}", headers=stranger)
    assert denied.status_code == 403

    allowed = client.delete(f"/api/files/{file_id}/share/{recipient_user_id}", headers=owner)
    assert allowed.status_code == 200


def test_sharing_disabled_blocks_endpoints(client, admin_headers):
    client.patch("/api/admin/settings", json={"enable_user_sharing": False}, headers=admin_headers)
    resp = client.get("/api/files/shared-with-me", headers=admin_headers)
    assert resp.status_code == 403
