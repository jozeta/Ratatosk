"""A minimal OpenID Connect provider for browser tests (FEAT-010).
Auto-approves every login (no login form) and signs RS256 ID tokens.
Run: uvicorn tests.e2e.fake_idp:app --port N  (env FAKE_IDP_ISSUER, FAKE_IDP_REDIRECT)"""
import base64
import hashlib
import os
import secrets
import time
import urllib.parse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

ISSUER = os.environ["FAKE_IDP_ISSUER"]
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CODES: dict[str, dict] = {}
app = FastAPI()


@app.get("/.well-known/openid-configuration")
def discovery():
    return {"issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize", "token_endpoint": ISSUER + "/token",
            "jwks_uri": ISSUER + "/jwks", "response_types_supported": ["code"]}


@app.get("/jwks")
def jwks():
    return {"keys": [{**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "e2e", "alg": "RS256", "use": "sig"}]}


@app.get("/authorize")
def authorize(redirect_uri: str, state: str, nonce: str, code_challenge: str, client_id: str):
    code = secrets.token_urlsafe(16)
    CODES[code] = {"nonce": nonce, "challenge": code_challenge, "client_id": client_id}
    return RedirectResponse(redirect_uri + "?" + urllib.parse.urlencode({"code": code, "state": state}), status_code=302)


@app.post("/token")
def token(request: Request, code: str = Form(...), code_verifier: str = Form(...)):
    entry = CODES.pop(code, None)
    if entry is None:
        raise HTTPException(400, "bad code")
    expected = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
    if expected != entry["challenge"]:
        raise HTTPException(400, "PKCE mismatch")
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": entry["client_id"], "sub": "browser-sso-user", "iat": now, "exp": now + 300,
              "nonce": entry["nonce"], "preferred_username": "browser.sso", "email": "browser.sso@example.com", "email_verified": True}
    return {"access_token": "unused", "token_type": "Bearer", "id_token": jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "e2e"})}
