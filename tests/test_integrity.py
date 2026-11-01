"""Verifiable frontend (FEAT-012)."""
import importlib.util
import os

import pytest


def _cli():
    path = os.path.join(os.path.dirname(__file__), "..", "cli", "ratatosk.py")
    spec = importlib.util.spec_from_file_location("ratatosk_cli", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sri_attributes_are_current():
    """Fails if JS/CSS changed without running `python -m app.integrity write`."""
    from app.integrity import stale_pages

    assert stale_pages() == []


def test_every_script_and_stylesheet_is_pinned():
    import re

    from app.integrity import pages

    for page in pages():
        for tag in re.findall(r"<(?:script|link)\b[^>]*(?:src|href)=\"/static/[^\"]+\.(?:js|css)\"[^>]*>", page.read_text()):
            assert 'integrity="sha384-' in tag, (page.name, tag)


def test_manifest_matches_what_is_served(client):
    from app.integrity import sri

    m = client.get("/api/integrity").json()
    assert m["files"] and len(m["release_digest"]) == 64
    for path, expected in m["files"].items():
        served = client.get(path.replace("/share/_", "/share/x").replace("/r/_", "/r/x"))
        assert served.status_code == 200, path
        assert sri(served.content) == expected, path


def test_cli_verify_accepts_genuine_and_detects_tampering(client):
    cli = _cli()
    manifest = client.get("/api/integrity").json()
    genuine = lambda p: client.get(p).content  # noqa: E731
    ok = cli.verify_manifest(manifest, genuine, manifest["release_digest"])
    assert ok["ok"] and not ok["mismatched"]

    def tampered(p):
        body = client.get(p).content
        return body + b"/* injected */" if p == "/static/js/crypto.js" else body

    bad = cli.verify_manifest(manifest, tampered, manifest["release_digest"])
    assert not bad["ok"] and bad["mismatched"] == ["/static/js/crypto.js"]

    # A server that also lies in its manifest stays self-consistent - but no
    # longer matches the digest published for the release.
    lying = dict(manifest, files=dict(manifest["files"], **{"/static/js/crypto.js": cli._sri(tampered("/static/js/crypto.js"))}))
    caught = cli.verify_manifest(lying, tampered, manifest["release_digest"])
    assert not caught["ok"] and caught["mismatched"] == [] and caught["digest_matches_published"] is False


@pytest.mark.parametrize("cmd", ["check", "digest"])
def test_integrity_cli(cmd, capsys):
    from app.integrity import main

    assert main([cmd]) == 0
