"""S3 storage backend tests against moto's in-process S3 (TEST-005).
These would have caught BUG-005 (expired files never deleted from S3)."""
import datetime

import boto3
import pytest
from moto import mock_aws

from tests.test_upload_download import _upload

BUCKET = "ratatosk-test"


@pytest.fixture()
def s3(client, monkeypatch):
    from app.core.config import settings
    from app.services import storage_backends

    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        monkeypatch.setattr(settings, "storage_backend", "s3")
        monkeypatch.setattr(settings, "s3_bucket", BUCKET)
        monkeypatch.setattr(settings, "s3_region", "us-east-1")
        monkeypatch.setattr(settings, "s3_prefix", "prod")
        monkeypatch.setattr(storage_backends, "_backend", None)
        yield boto3.client("s3", region_name="us-east-1")
        storage_backends._backend = None


def _keys(s3):
    return sorted(o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", []))


def test_round_trip_and_delete(client, admin_headers, s3):
    fid = _upload(client, b"in the bucket", headers=admin_headers).json()["file_id"]
    assert len(_keys(s3)) == 1 and _keys(s3)[0].startswith("prod/")
    assert client.get(f"/api/files/{fid}/blob").content == b"in the bucket"
    client.delete(f"/api/files/{fid}", headers=admin_headers)
    assert _keys(s3) == []


def test_burn_deletes_the_object(client, s3):
    fid = _upload(client, b"burn me", burn_after_download=True).json()["file_id"]
    assert client.get(f"/api/files/{fid}/blob").content == b"burn me"
    assert _keys(s3) == []


def test_cleanup_deletes_expired_objects_from_s3(client, admin_headers, db_session, s3):
    """BUG-005."""
    from app.core.cleanup import run_cleanup_once
    from app.models.file import FileObject

    fid = _upload(client, b"expiring", headers=admin_headers).json()["file_id"]
    assert len(_keys(s3)) == 1
    f = db_session.get(FileObject, fid)
    f.expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
    db_session.commit()
    assert run_cleanup_once(force=True) == 1
    assert _keys(s3) == []


def test_factory_reset_only_deletes_known_objects(client, admin_headers, s3):
    _upload(client, b"ours", headers=admin_headers)
    s3.put_object(Bucket=BUCKET, Key="unrelated/keep.txt", Body=b"someone else's")
    r = client.post("/api/admin/system/reset", json={"password": "AdminPass123!"}, headers=admin_headers)
    assert r.status_code == 200
    assert _keys(s3) == ["unrelated/keep.txt"]
