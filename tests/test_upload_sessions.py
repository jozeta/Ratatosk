"""Upload sessions: DB-backed (survive restarts / multiple workers) and bound
to the actor that started them."""
import datetime

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import make_user


def _login(client, db_session, username):
    make_user(db_session, username, "CorrectHorse123!")
    token = client.post("/api/auth/login", json={"username": username, "password": "CorrectHorse123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _init(client, size, headers=None):
    resp = client.post("/api/uploads/init", json={"total_size_bytes": size}, headers=headers or {})
    assert resp.status_code == 200, resp.text
    return resp.json()["upload_id"]


def _chunk(client, upload_id, data, headers=None):
    return client.put(
        f"/api/uploads/{upload_id}/chunk",
        content=data,
        headers={**(headers or {}), "Content-Type": "application/octet-stream"},
    )


def _complete(client, upload_id, headers=None):
    payload = {"ttl": "1h", "burn_after_download": False, "max_downloads": 0, "password": None}
    return client.post(f"/api/uploads/{upload_id}/complete", json=payload, headers=headers or {})


def test_other_user_cannot_append_or_complete(client, db_session):
    alice = _login(client, db_session, "alice")
    mallory = _login(client, db_session, "mallory")
    upload_id = _init(client, 5, alice)

    assert _chunk(client, upload_id, b"evil!", mallory).status_code == 404
    assert _complete(client, upload_id, mallory).status_code == 404

    # The legitimate owner is unaffected.
    assert _chunk(client, upload_id, b"hello", alice).status_code == 200
    assert _complete(client, upload_id, alice).status_code == 200


def test_other_anonymous_visitor_cannot_append(client):
    upload_id = _init(client, 5)  # this client now holds the anon cookie

    with TestClient(app) as stranger:  # separate cookie jar = different visitor
        assert _chunk(stranger, upload_id, b"evil!").status_code == 404
        assert _complete(stranger, upload_id).status_code == 404

    assert _chunk(client, upload_id, b"hello").status_code == 200
    assert _complete(client, upload_id).status_code == 200


def test_logged_in_upload_rejects_anonymous_chunks(client, db_session):
    alice = _login(client, db_session, "alice")
    upload_id = _init(client, 5, alice)
    assert _chunk(client, upload_id, b"hello").status_code == 404  # no auth header


def test_first_anonymous_upload_releases_its_concurrency_slot(client, admin_headers):
    """Regression: /init used to key a cookie-less visitor by IP but /complete
    by the cookie /init had just set, so the first upload's slot leaked."""
    client.patch("/api/admin/settings", json={"max_concurrent_uploads": 1}, headers=admin_headers)

    with TestClient(app) as anon:
        for _ in range(3):
            upload_id = _init(anon, 4)
            assert _chunk(anon, upload_id, b"data").status_code == 200
            assert _complete(anon, upload_id).status_code == 200


def test_concurrency_limit_enforced(client, admin_headers):
    client.patch("/api/admin/settings", json={"max_concurrent_uploads": 1}, headers=admin_headers)
    _init(client, 4, admin_headers)
    resp = client.post("/api/uploads/init", json={"total_size_bytes": 4}, headers=admin_headers)
    assert resp.status_code == 429


def test_chunks_beyond_declared_size_rejected(client):
    upload_id = _init(client, 10)
    assert _chunk(client, upload_id, b"x" * 11).status_code == 413
    # Nothing past the declared size was written (positional bound).
    assert _chunk(client, upload_id, b"x" * 10).status_code == 200


def test_session_persists_in_database(client, db_session):
    """In-progress uploads live in the DB, not process memory - so a restart
    or a different worker can still accept the next chunk."""
    from app.models.upload_session import UploadSession

    upload_id = _init(client, 5)
    assert _chunk(client, upload_id, b"hel").status_code == 200

    row = db_session.get(UploadSession, upload_id)
    assert row is not None and row.bytes_written == 3

    assert _chunk(client, upload_id, b"lo").status_code == 200
    file_id = _complete(client, upload_id).json()["file_id"]
    assert client.get(f"/api/files/{file_id}/blob").content == b"hello"
    db_session.expire_all()
    assert db_session.get(UploadSession, upload_id) is None


def test_cleanup_purges_abandoned_uploads(client, db_session):
    import os

    from app.core.cleanup import run_cleanup_once
    from app.models.upload_session import UploadSession
    from app.services import storage_service

    upload_id = _init(client, 5)
    _chunk(client, upload_id, b"hel")
    part = storage_service.tmp_path_for(upload_id)
    assert os.path.exists(part)

    row = db_session.get(UploadSession, upload_id)
    row.last_activity_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
    db_session.commit()

    run_cleanup_once()

    db_session.expire_all()
    assert db_session.get(UploadSession, upload_id) is None
    assert not os.path.exists(part)
