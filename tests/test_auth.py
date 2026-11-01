import time

import pyotp


def test_register_login_happy_path(client):
    reg = client.post("/api/auth/register", json={"username": "alice", "password": "correcthorse123"})
    assert reg.status_code == 200
    assert reg.json()["username"] == "alice"

    login = client.post("/api/auth/login", json={"username": "alice", "password": "correcthorse123"})
    assert login.status_code == 200
    assert "access_token" in login.json()

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={"username": "bob", "password": "correcthorse123"})
    resp = client.post("/api/auth/login", json={"username": "bob", "password": "wrong-password"})
    assert resp.status_code == 401


def test_login_lockout_after_max_attempts(client, admin_headers):
    client.post("/api/auth/register", json={"username": "carol", "password": "correcthorse123"})
    max_attempts = client.get("/api/admin/settings", headers=admin_headers).json()["max_login_attempts"]

    for _ in range(max_attempts):
        client.post("/api/auth/login", json={"username": "carol", "password": "wrong"})

    # Even the correct password is now rejected while locked out.
    resp = client.post("/api/auth/login", json={"username": "carol", "password": "correcthorse123"})
    assert resp.status_code == 423


def test_unknown_username_and_wrong_password_get_same_status(client):
    client.post("/api/auth/register", json={"username": "dave", "password": "correcthorse123"})
    wrong_pw = client.post("/api/auth/login", json={"username": "dave", "password": "wrong"})
    unknown_user = client.post("/api/auth/login", json={"username": "nobody-like-this", "password": "wrong"})
    assert wrong_pw.status_code == unknown_user.status_code == 401


def test_mfa_setup_confirm_and_login_roundtrip(client):
    client.post("/api/auth/register", json={"username": "erin", "password": "correcthorse123"})
    login = client.post("/api/auth/login", json={"username": "erin", "password": "correcthorse123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    setup = client.post("/api/auth/mfa/setup", headers=headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]

    code = pyotp.TOTP(secret).now()
    confirm = client.post("/api/auth/mfa/confirm", json={"code": code}, headers=headers)
    assert confirm.status_code == 200
    assert len(confirm.json()["backup_codes"]) == 10

    # A fresh login must now stop at the MFA step instead of returning a session token.
    second_login = client.post("/api/auth/login", json={"username": "erin", "password": "correcthorse123"})
    assert second_login.status_code == 200
    body = second_login.json()
    assert body.get("mfa_required") is True
    mfa_token = body["mfa_token"]

    # The mfa_token proves the password step only - it must not work as a session token.
    denied = client.get("/api/auth/me", headers={"Authorization": f"Bearer {mfa_token}"})
    assert denied.status_code == 401

    # The code used to confirm setup is spent (single-use, SEC-014); the user's
    # next login uses the following time step's code.
    next_code = pyotp.TOTP(secret).at(time.time() + 30)
    replay = client.post("/api/auth/mfa/verify", json={"mfa_token": mfa_token, "code": code})
    assert replay.status_code == 401
    verify = client.post("/api/auth/mfa/verify", json={"mfa_token": mfa_token, "code": next_code})
    assert verify.status_code == 200
    real_token = verify.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {real_token}"})
    assert me.status_code == 200
    assert me.json()["mfa_enabled"] is True


def test_enforced_mfa_forces_setup_at_login(client, admin_headers):
    client.patch("/api/admin/settings", json={"enforce_mfa_users": True}, headers=admin_headers)
    client.post("/api/auth/register", json={"username": "frank", "password": "correcthorse123"})

    login = client.post("/api/auth/login", json={"username": "frank", "password": "correcthorse123"})
    assert login.status_code == 200
    body = login.json()
    assert body.get("mfa_setup_required") is True
    setup_token = body["setup_token"]

    # The setup_token must not work as a session token either.
    denied = client.get("/api/auth/me", headers={"Authorization": f"Bearer {setup_token}"})
    assert denied.status_code == 401

    setup = client.post("/api/auth/mfa/enforce-setup", json={"setup_token": setup_token})
    secret = setup.json()["secret"]
    confirm = client.post(
        "/api/auth/mfa/enforce-confirm",
        json={"setup_token": setup_token, "code": pyotp.TOTP(secret).now()},
    )
    assert confirm.status_code == 200
    assert "access_token" in confirm.json()


def test_session_revocation_on_password_change(client):
    client.post("/api/auth/register", json={"username": "grace", "password": "correcthorse123"})
    session_a = client.post("/api/auth/login", json={"username": "grace", "password": "correcthorse123"}).json()["access_token"]
    session_b = client.post("/api/auth/login", json={"username": "grace", "password": "correcthorse123"}).json()["access_token"]

    change = client.post(
        "/api/auth/change-password",
        json={"current_password": "correcthorse123", "new_password": "correcthorse123-new"},
        headers={"Authorization": f"Bearer {session_a}"},
    )
    assert change.status_code == 200
    new_token = change.json()["access_token"]

    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {session_b}"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {session_a}"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200


def test_logout_everywhere(client):
    client.post("/api/auth/register", json={"username": "heidi", "password": "correcthorse123"})
    session_a = client.post("/api/auth/login", json={"username": "heidi", "password": "correcthorse123"}).json()["access_token"]
    session_b = client.post("/api/auth/login", json={"username": "heidi", "password": "correcthorse123"}).json()["access_token"]

    resp = client.post("/api/auth/logout-everywhere", headers={"Authorization": f"Bearer {session_a}"})
    assert resp.status_code == 200
    new_token = resp.json()["access_token"]

    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {session_b}"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
