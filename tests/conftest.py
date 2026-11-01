"""Test isolation setup.

IMPORTANT: every env var below MUST be set before `app.main` (or anything
that imports app.core.config/app.core.database) is imported anywhere -
those modules read them once, at import time, into module-level globals
(`engine`, `settings`). Pytest imports conftest.py before any test module in
the same directory, so this top-level code (not a fixture) is what
guarantees that ordering.

This exists because an earlier, ad hoc "isolated" test server during this
project's development wasn't actually isolated: it overrode the static
env-var storage settings but not the *dynamic*, DB-backed `storage_path`
setting that the app's storage backend actually reads - and a destructive
test then deleted every real uploaded file. The `client` fixture below
overrides both, every time, so that mistake can't happen again here.
"""
import os
import shutil
import tempfile

_TEST_ROOT = tempfile.mkdtemp(prefix="securedrop_test_")

os.environ["RATATOSK_DATABASE_URL"] = "sqlite:///" + os.path.join(_TEST_ROOT, "test.db")
os.environ["RATATOSK_STORAGE_ROOT"] = os.path.join(_TEST_ROOT, "storage")
os.environ["RATATOSK_TMP_ROOT"] = os.path.join(_TEST_ROOT, "tmp")
os.environ["RATATOSK_BRANDING_ROOT"] = os.path.join(_TEST_ROOT, "branding")
os.environ["RATATOSK_SECRET_KEY"] = "pytest-only-secret-key-never-used-for-anything-real"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import ratelimit  # noqa: E402
from app.core.config import settings as static_settings  # noqa: E402
from app.core.database import Base, engine  # noqa: E402
from app.core.dynamic_settings import update_settings  # noqa: E402
from app.main import app  # noqa: E402
from tests.helpers import make_user  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)


@pytest.fixture()
def client(tmp_path):
    """A TestClient against a completely fresh DB and storage dir, built via
    the app's own real startup path (app.main's lifespan does
    Base.metadata.create_all + sync_table_columns + load_cache) rather than
    a hand-rolled substitute - so migrations get exercised by every test."""
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    # Storage is env-only now (SEC-010); point it at an isolated per-test dir.
    static_settings.storage_root = str(tmp_path / "storage")
    ratelimit.reset()
    with TestClient(app) as c:
        # The rate limiter is tested explicitly; keep it out of every other test.
        update_settings({"rate_limit_enabled": False})
        # These tests authenticate with explicit bearer headers, so a login
        # must not silently turn the shared client into a logged-in browser.
        # Cookie sessions (SEC-017) are covered with their own clients.
        c.event_hooks["response"].append(lambda r: c.cookies.delete("rt_session"))
        yield c


@pytest.fixture()
def db_session():
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def admin_headers(client, db_session):
    """Directly seeds an admin (bypassing registration, since anonymous
    registration can't create admins) then logs in through the real endpoint
    so the returned token is exactly what a real client would get."""
    make_user(db_session, "admin", "AdminPass123!", is_admin=True)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "AdminPass123!"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
