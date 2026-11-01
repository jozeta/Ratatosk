"""OpenID Connect authorization-code flow with PKCE (FEAT-010).

Security properties:
- `state` (CSRF), `nonce` (ID-token replay) and a PKCE verifier are created
  per login attempt and kept in a short-lived, HttpOnly, signed cookie, so
  nothing is stored server-side and a callback can't be forged or replayed.
- The ID token's signature is checked against the provider's published keys
  (JWKS), along with issuer, audience, expiry and nonce. Only asymmetric
  algorithms are accepted.
- Accounts are matched by (issuer, subject) - the only stable identity an IdP
  guarantees. Matching by email is opt-in and requires `email_verified`.

All network access goes through http_get_json / http_post_form, which tests
replace with a fake provider.
"""
import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import urllib.request

import jwt
from fastapi import HTTPException, status

from app.core.config import settings

STATE_COOKIE = "rt_oidc"
STATE_MAX_AGE = 600
ALLOWED_ALGS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"]
_discovery_cache: dict[str, tuple[float, dict]] = {}
_jwks_cache: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 3600


def enabled() -> bool:
    return bool(settings.oidc_issuer and settings.oidc_client_id and settings.oidc_client_secret)


def _require_https(url: str) -> None:
    scheme = urllib.parse.urlsplit(url).scheme
    host = urllib.parse.urlsplit(url).hostname or ""
    if scheme != "https" and host not in ("localhost", "127.0.0.1"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="SSO provider must use https")


def http_get_json(url: str) -> dict:
    _require_https(url)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - https enforced above
        return json.loads(resp.read())


def http_post_form(url: str, data: dict, auth: tuple[str, str]) -> dict:
    _require_https(url)
    basic = base64.b64encode(f"{urllib.parse.quote(auth[0])}:{urllib.parse.quote(auth[1])}".encode()).decode()
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "Authorization": f"Basic {basic}",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - https enforced above
        return json.loads(resp.read())


def _cached(cache: dict, key: str, fetch) -> dict:
    hit = cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = fetch()
    cache[key] = (time.monotonic(), value)
    return value


def discovery() -> dict:
    issuer = settings.oidc_issuer.rstrip("/")
    doc = _cached(_discovery_cache, issuer, lambda: http_get_json(issuer + "/.well-known/openid-configuration"))
    if doc.get("issuer", "").rstrip("/") != issuer:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="SSO provider issuer mismatch")
    return doc


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def start(redirect_uri: str) -> tuple[str, dict]:
    """Returns (authorization URL, state to keep in the signed cookie)."""
    doc = discovery()
    verifier = _b64url(secrets.token_bytes(32))
    state = {"state": _b64url(secrets.token_bytes(16)), "nonce": _b64url(secrets.token_bytes(16)),
             "verifier": verifier, "redirect_uri": redirect_uri, "t": int(time.time())}
    params = {
        "response_type": "code", "client_id": settings.oidc_client_id, "redirect_uri": redirect_uri,
        "scope": settings.oidc_scopes, "state": state["state"], "nonce": state["nonce"],
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
    }
    return doc["authorization_endpoint"] + "?" + urllib.parse.urlencode(params), state


def sign_state(state: dict) -> str:
    return jwt.encode({**state, "purpose": "oidc", "exp": int(time.time()) + STATE_MAX_AGE}, settings.secret_key, algorithm="HS256")


def read_state(token: str | None) -> dict:
    if not token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sign-in expired - please try again")
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sign-in expired - please try again") from None
    if data.get("purpose") != "oidc":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sign-in state")
    return data


def finish(code: str, returned_state: str, saved: dict) -> dict:
    """Exchange the code and return the verified ID-token claims."""
    if not secrets.compare_digest(returned_state or "", saved["state"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sign-in state mismatch")
    doc = discovery()
    tokens = http_post_form(doc["token_endpoint"], {
        "grant_type": "authorization_code", "code": code, "redirect_uri": saved["redirect_uri"],
        "code_verifier": saved["verifier"], "client_id": settings.oidc_client_id,
    }, (settings.oidc_client_id, settings.oidc_client_secret))
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="SSO provider returned no ID token")
    jwks = _cached(_jwks_cache, doc["jwks_uri"], lambda: http_get_json(doc["jwks_uri"]))
    header = jwt.get_unverified_header(id_token)
    if header.get("alg") not in ALLOWED_ALGS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported ID token algorithm")
    keyset = jwt.PyJWKSet.from_dict(jwks)
    candidates = [k for k in keyset.keys if not header.get("kid") or k.key_id == header.get("kid")]
    if not candidates:
        _jwks_cache.pop(doc["jwks_uri"], None)  # keys may have rotated; next attempt refetches
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ID token signing key")
    try:
        claims = jwt.decode(id_token, candidates[0].key, algorithms=[header["alg"]], audience=settings.oidc_client_id,
                            issuer=doc["issuer"], options={"require": ["exp", "iat", "sub", "iss", "aud"]}, leeway=60)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid ID token: {type(e).__name__}") from None
    if not secrets.compare_digest(str(claims.get("nonce", "")), saved["nonce"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID token nonce mismatch")
    return claims


def is_admin_by_claims(claims: dict) -> bool | None:
    """True/False if an admin group is configured, None if not managed by SSO."""
    if not settings.oidc_admin_group:
        return None
    groups = claims.get(settings.oidc_groups_claim) or []
    if isinstance(groups, str):
        groups = [groups]
    return settings.oidc_admin_group in groups
