"""OIDC single sign-on (FEAT-010) against an in-process fake identity
provider that signs real RS256 ID tokens."""
import time
import urllib.parse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://idp.test"
CLIENT_ID = "ratatosk-test"


class FakeIdP:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        self.jwks = {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}
        self.claims = {"sub": "user-123", "email": "sso@example.com", "email_verified": True, "preferred_username": "ssouser"}
        self.overrides: dict = {}
        self.sign_with = self.key
        self.last_nonce = None

    def get_json(self, url):
        if url.endswith("/.well-known/openid-configuration"):
            return {"issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize",
                    "token_endpoint": ISSUER + "/token", "jwks_uri": ISSUER + "/jwks"}
        assert url == ISSUER + "/jwks"
        return self.jwks

    def post_form(self, url, data, auth):
        assert url == ISSUER + "/token" and auth == (CLIENT_ID, "s3cret") and data["code"] == "good-code"
        assert data["code_verifier"]  # PKCE
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "iat": now, "exp": now + 300, "nonce": self.last_nonce,
                  **self.claims, **self.overrides}
        return {"id_token": jwt.encode(claims, self.sign_with, algorithm="RS256", headers={"kid": "k1"})}


@pytest.fixture()
def idp(client, monkeypatch):
    from app.core.config import settings
    from app.services import oidc

    fake = FakeIdP()
    for k, v in {"oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "s3cret",
                 "oidc_admin_group": "", "oidc_link_by_email": False, "oidc_auto_provision": True}.items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(oidc, "http_get_json", fake.get_json)
    monkeypatch.setattr(oidc, "http_post_form", fake.post_form)
    oidc._discovery_cache.clear()
    oidc._jwks_cache.clear()
    return fake


def sso_login(client, idp, state_override=None):
    start = client.get("/api/auth/oidc/login", follow_redirects=False)
    assert start.status_code == 302
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(start.headers["location"]).query))
    assert params["code_challenge_method"] == "S256" and params["client_id"] == CLIENT_ID
    idp.last_nonce = params["nonce"]
    return client.get("/api/auth/oidc/callback", params={"code": "good-code", "state": state_override or params["state"]},
                      follow_redirects=False)


def test_first_login_provisions_an_sso_only_account(client, idp, db_session):
    from app.models.user import User

    r = sso_login(client, idp)
    assert r.status_code == 302 and r.headers["location"] == "/login?sso=1"
    assert "rt_session=" in r.headers.get("set-cookie", "")
    user = db_session.query(User).filter(User.oidc_subject == "user-123").one()
    assert user.username == "ssouser" and user.password_login is False and user.email == "sso@example.com"
    # Same identity again -> same account, no duplicate.
    sso_login(client, idp)
    assert db_session.query(User).filter(User.oidc_subject == "user-123").count() == 1
    # SSO-only accounts can't be signed into with a password.
    assert client.post("/api/auth/login", json={"username": "ssouser", "password": "anything"}).status_code == 401


def test_admin_group_mapping(client, idp, db_session, monkeypatch):
    from app.core.config import settings
    from app.models.user import User

    monkeypatch.setattr(settings, "oidc_admin_group", "ratatosk-admins")
    idp.overrides = {"groups": ["ratatosk-admins"]}
    sso_login(client, idp)
    assert db_session.query(User).filter(User.oidc_subject == "user-123").one().is_admin
    idp.overrides = {"groups": []}  # removed from the group at the IdP...
    sso_login(client, idp)
    db_session.expire_all()
    # ...but they're the only admin, so they keep the role.
    assert db_session.query(User).filter(User.oidc_subject == "user-123").one().is_admin


def test_email_linking_is_opt_in_and_needs_verified_email(client, idp, db_session, monkeypatch):
    from app.core.config import settings
    from app.models.user import User
    from tests.helpers import make_user

    local = make_user(db_session, "localuser", "CorrectHorse123!", email="sso@example.com")
    sso_login(client, idp)
    db_session.expire_all()
    assert db_session.get(User, local.id).oidc_subject is None  # off: never taken over

    monkeypatch.setattr(settings, "oidc_link_by_email", True)
    idp.claims = {**idp.claims, "sub": "user-456", "email_verified": False}
    sso_login(client, idp)
    db_session.expire_all()
    assert db_session.get(User, local.id).oidc_subject is None  # unverified: not linked
    idp.claims = {**idp.claims, "sub": "user-789", "email_verified": True}
    sso_login(client, idp)
    db_session.expire_all()
    assert db_session.get(User, local.id).oidc_subject == "user-789"


@pytest.mark.parametrize("attack", ["state", "signature", "nonce", "audience", "expired"])
def test_forged_or_replayed_responses_are_rejected(client, idp, attack):
    if attack == "state":
        r = sso_login(client, idp, state_override="forged")
    else:
        if attack == "signature":
            idp.sign_with = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if attack == "nonce":
            idp.overrides = {"nonce": "replayed"}
        if attack == "audience":
            idp.overrides = {"aud": "some-other-app"}
        if attack == "expired":
            idp.overrides = {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}
        r = sso_login(client, idp)
    assert r.status_code == 400
    assert "rt_session=" not in r.headers.get("set-cookie", "")


def test_callback_without_state_cookie_is_rejected(client, idp):
    r = client.get("/api/auth/oidc/callback", params={"code": "good-code", "state": "x"}, follow_redirects=False)
    assert r.status_code == 400


def test_sso_disabled_by_default(client):
    assert client.get("/api/auth/oidc/login", follow_redirects=False).status_code == 404
    assert client.get("/api/config").json()["oidc_enabled"] is False


def test_sso_account_deletion_confirms_by_username(client, idp):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as browser:
        start = browser.get("/api/auth/oidc/login", follow_redirects=False)
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(start.headers["location"]).query))
        idp.last_nonce = params["nonce"]
        browser.get("/api/auth/oidc/callback", params={"code": "good-code", "state": params["state"]}, follow_redirects=False)
        me = browser.get("/api/auth/me").json()
        assert me["sso"] and not me["password_login"]
        h = {"X-Ratatosk-CSRF": "1"}
        assert browser.request("DELETE", "/api/auth/me", json={"confirm_username": "wrong"}, headers=h).status_code == 400
        assert browser.request("DELETE", "/api/auth/me", json={"confirm_username": me["username"]}, headers=h).status_code == 200
