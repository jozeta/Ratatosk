"""Real-browser SSO round trip (FEAT-010). The app runs on 127.0.0.1 and the
identity provider on localhost - different *sites* to the browser, so the
SameSite cookie behaviour matches a real deployment."""
import os
import re
import subprocess
import sys
import tempfile
import time

import httpx
import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import ROOT, _free_port

pytestmark = pytest.mark.e2e


def _wait(url):
    for _ in range(100):
        try:
            if httpx.get(url).status_code < 500:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError(f"{url} did not start")


@pytest.fixture(scope="module")
def sso_app():
    idp_port, app_port = _free_port(), _free_port()
    issuer = f"http://localhost:{idp_port}"
    tmp = tempfile.mkdtemp(prefix="ratatosk_sso_")
    base_env = {k: v for k, v in os.environ.items() if not k.startswith(("RATATOSK_", "SECUREDROP_"))}
    idp = subprocess.Popen([sys.executable, "-m", "uvicorn", "tests.e2e.fake_idp:app", "--host", "localhost", "--port", str(idp_port)],
                           cwd=ROOT, env={**base_env, "FAKE_IDP_ISSUER": issuer}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = {**base_env,
           "RATATOSK_DATABASE_URL": "sqlite:///" + os.path.join(tmp, "sso.db"),
           "RATATOSK_STORAGE_ROOT": os.path.join(tmp, "s"), "RATATOSK_TMP_ROOT": os.path.join(tmp, "t"),
           "RATATOSK_BRANDING_ROOT": os.path.join(tmp, "b"), "RATATOSK_SECRET_KEY": "sso-e2e-" + "q" * 40,
           "RATATOSK_OIDC_ISSUER": issuer, "RATATOSK_OIDC_CLIENT_ID": "ratatosk-e2e", "RATATOSK_OIDC_CLIENT_SECRET": "e2e-secret",
           "RATATOSK_OIDC_BUTTON_LABEL": "Sign in with Acme SSO"}
    subprocess.run([sys.executable, "-m", "app.init_db"], cwd=ROOT, env=env, check=True, capture_output=True)
    app = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(app_port)],
                           cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait(issuer + "/jwks")
        _wait(f"http://127.0.0.1:{app_port}/api/health")
        yield f"http://127.0.0.1:{app_port}"
    finally:
        app.terminate()
        idp.terminate()


def test_sso_round_trip_in_a_real_browser(sso_app, page):
    page.goto(sso_app + "/login")
    button = page.locator("#ssoBtn")
    expect(button).to_have_text("Sign in with Acme SSO")
    button.click()
    page.wait_for_url(re.compile(r"/files$"), timeout=20000)
    expect(page.locator(".dropdown-toggle")).to_contain_text("browser.sso")
    # Authenticated purely by the HttpOnly cookie set at the callback.
    me = page.evaluate("window.SDApi.get('/api/auth/me')")
    assert me["sso"] is True and me["password_login"] is False
    page.goto(sso_app + "/account")
    expect(page.locator("#changePasswordForm")).to_be_hidden()
    expect(page.locator("#keysCard")).to_be_visible()  # SSO users can still have E2E keys
