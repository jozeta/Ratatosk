def test_settings_patch_round_trips_and_reaches_public_config(client, admin_headers):
    patch = client.patch("/api/admin/settings", json={"brand_name": "Test Brand"}, headers=admin_headers)
    assert patch.status_code == 200
    assert patch.json()["brand_name"] == "Test Brand"

    get = client.get("/api/admin/settings", headers=admin_headers)
    assert get.json()["brand_name"] == "Test Brand"

    public = client.get("/api/config")
    assert public.json()["brand_name"] == "Test Brand"


def test_non_admin_cannot_read_admin_settings(client):
    client.post("/api/auth/register", json={"username": "notadmin", "password": "correcthorse123"})
    token = client.post("/api/auth/login", json={"username": "notadmin", "password": "correcthorse123"}).json()["access_token"]
    resp = client.get("/api/admin/settings", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_api_keys_disabled_blocks_endpoint(client, admin_headers):
    client.patch("/api/admin/settings", json={"enable_api_keys": False}, headers=admin_headers)
    resp = client.post("/api/account/api-keys", json={"name": "should fail"}, headers=admin_headers)
    assert resp.status_code == 403


def test_user_management_disabled_blocks_endpoint(client, admin_headers):
    client.patch("/api/admin/settings", json={"enable_user_management": False}, headers=admin_headers)
    resp = client.get("/api/admin/users", headers=admin_headers)
    assert resp.status_code == 403


def test_upload_scoped_api_key_cannot_reach_other_endpoints(client, admin_headers):
    create = client.post("/api/account/api-keys", json={"name": "ci key", "scope": "upload"}, headers=admin_headers)
    assert create.status_code == 200
    assert create.json()["key"].startswith("sdk_")
    raw_key = create.json()["key"]
    key_headers = {"Authorization": f"Bearer {raw_key}"}

    init = client.post("/api/uploads/init", json={"total_size_bytes": 10}, headers=key_headers)
    assert init.status_code == 200

    denied = client.get("/api/files/mine", headers=key_headers)
    assert denied.status_code == 401


def test_full_scope_api_key_works_everywhere(client, admin_headers):
    create = client.post("/api/account/api-keys", json={"name": "full key", "scope": "full"}, headers=admin_headers)
    raw_key = create.json()["key"]
    key_headers = {"Authorization": f"Bearer {raw_key}"}

    assert client.post("/api/uploads/init", json={"total_size_bytes": 10}, headers=key_headers).status_code == 200
    assert client.get("/api/files/mine", headers=key_headers).status_code == 200
