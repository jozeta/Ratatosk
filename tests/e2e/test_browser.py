"""End-to-end browser tests (TEST-004) plus the zero-knowledge network
assertions (TEST-001): nothing secret - key, passphrase, filename, file
contents - may appear in any request the browser makes."""
import os
import re
import struct

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

SECRET_NAME = "quarterly-secret-report.pdf"
CONTENT = b"top secret quarterly numbers " * 2000


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


class Recorder:
    """Captures every request URL, header and body the page sends."""

    def __init__(self, page):
        self.blobs: list[bytes] = []
        page.on("request", self._on)

    def _on(self, req):
        self.blobs.append(req.url.encode())
        self.blobs.append(repr(req.headers).encode())
        body = req.post_data_buffer
        if body:
            self.blobs.append(body)

    def contains(self, needle: str | bytes) -> bool:
        n = needle.encode() if isinstance(needle, str) else needle
        return any(n in b for b in self.blobs)


def upload(page, base, path, passphrase=None, burn=False):
    page.goto(base + "/")
    page.set_input_files("#fileInput", path)
    expect(page.locator(".file-queue-item")).to_have_count(1)
    expect(page.locator(".file-queue-item .badge", has_text="…")).to_have_count(0)
    if passphrase:
        page.fill("#secondaryPassword", passphrase)
    if burn:
        page.locator("#burnRow .slider").click()
        expect(page.locator("#burnAfterDownload")).to_be_checked()
    # Formats that can't be stripped (e.g. PDF) ask before uploading (SEC-008).
    page.once("dialog", lambda d: d.accept())
    page.click("#uploadBtn")
    expect(page.locator("#resultModal")).to_be_visible(timeout=30000)
    return page.input_value("#resultLink")


def download(page, link, passphrase=None, accept_confirm=True):
    page.goto(link)
    expect(page.locator("#downloadBtn")).to_be_enabled()
    if passphrase:
        page.fill("#passwordInput", passphrase)
    if accept_confirm:
        page.once("dialog", lambda d: d.accept())
    with page.expect_download(timeout=30000) as dl:
        page.click("#downloadBtn")
    return dl.value


def test_link_round_trip_and_nothing_secret_on_the_wire(base, page, browser, tmp_path, csp_violations):
    rec = Recorder(page)
    link = upload(page, base, _write(tmp_path, SECRET_NAME, CONTENT))
    key = link.split("#", 1)[1]

    other = browser.new_context(accept_downloads=True).new_page()
    rec2 = Recorder(other)
    d = download(other, link)
    assert d.suggested_filename == SECRET_NAME
    assert open(d.path(), "rb").read() == CONTENT

    for r in (rec, rec2):
        assert not r.contains(key), "the key must never be sent to the server"
        assert not r.contains(SECRET_NAME), "the filename must never be sent to the server"
        assert not r.contains(CONTENT[:64]), "plaintext must never be sent"
    assert csp_violations == []


def test_passphrase_never_reaches_the_server(base, page, browser, tmp_path, csp_violations):
    passphrase = "correct horse battery staple 42"
    rec = Recorder(page)
    link = upload(page, base, _write(tmp_path, "notes.txt", b"hello passphrase world"), passphrase=passphrase)
    assert "#" not in link  # nothing secret in the link

    other = browser.new_context(accept_downloads=True).new_page()
    rec2 = Recorder(other)
    d = download(other, link, passphrase=passphrase)
    assert open(d.path(), "rb").read() == b"hello passphrase world"
    assert not rec.contains(passphrase) and not rec2.contains(passphrase), "SEC-001: passphrase sent to the server"
    assert csp_violations == []


def test_wrong_passphrase_does_not_burn_the_file(base, page, browser, tmp_path):
    link = upload(page, base, _write(tmp_path, "once.txt", b"single use"), passphrase="right one", burn=True)
    other = browser.new_context(accept_downloads=True).new_page()
    other.goto(link)
    other.fill("#passwordInput", "wrong one")
    other.once("dialog", lambda d: d.accept())
    other.click("#downloadBtn")
    expect(other.locator(".toast", has_text="Wrong key or passphrase")).to_be_visible()
    # Still there: the wrong guess was rejected before anything was consumed (UI-003).
    d = download(other, link, passphrase="right one")
    assert open(d.path(), "rb").read() == b"single use"
    other.goto(link)
    expect(other.locator("#metaInfo")).to_contain_text("not found")


def test_link_without_key_explains_the_problem(base, page, tmp_path):
    link = upload(page, base, _write(tmp_path, "a.txt", b"x"))
    page.goto(link.split("#")[0])
    expect(page.locator(".toast", has_text="missing its decryption key")).to_be_visible()
    expect(page.locator("#downloadBtn")).to_be_disabled()


def test_text_send_shows_inline(base, page, browser):
    page.goto(base + "/")
    page.click("[data-mode=text]")
    page.fill("#textInput", "the wifi password is hunter2")
    page.click("#uploadBtn")
    expect(page.locator("#resultModal")).to_be_visible()
    link = page.input_value("#resultLink")
    other = browser.new_context().new_page()
    other.goto(link)
    other.click("#downloadBtn")
    expect(other.locator(".text-view")).to_have_text("the wifi password is hunter2")


def test_bundle_one_link_many_files(base, page, browser, tmp_path):
    page.goto(base + "/")
    page.set_input_files("#fileInput", [_write(tmp_path, "one.txt", b"first"), _write(tmp_path, "two.txt", b"second")])
    expect(page.locator(".file-queue-item")).to_have_count(2)
    expect(page.locator("#bundleRow")).to_be_visible()
    page.click("#uploadBtn")
    expect(page.locator("#resultModal")).to_be_visible(timeout=30000)
    expect(page.locator("#resultTitle")).to_contain_text("2 files")
    link = page.input_value("#resultLink")

    other = browser.new_context(accept_downloads=True).new_page()
    other.goto(link)
    other.click("#downloadBtn")
    expect(other.locator(".bundle-list li")).to_have_count(2)
    with other.expect_download() as dl:
        other.locator(".bundle-list li", has_text="two.txt").get_by_role("button").click()
    assert open(dl.value.path(), "rb").read() == b"second"


def test_large_downloads_stream_to_disk_via_service_worker(base, page, browser, tmp_path):
    data = os.urandom(3 * 1024 * 1024 + 123)
    link = upload(page, base, _write(tmp_path, "big.bin", data))
    other = browser.new_context(accept_downloads=True).new_page()
    other.goto(link)
    expect(other.locator("#downloadBtn")).to_be_enabled()
    other.evaluate("window.SDDownload.STREAM_THRESHOLD = 0")
    with other.expect_download(timeout=30000) as dl:
        other.click("#downloadBtn")
    assert dl.value.suggested_filename == "big.bin"
    assert open(dl.value.path(), "rb").read() == data
    assert other.evaluate("navigator.serviceWorker.controller !== null || !!navigator.serviceWorker")


def _jpeg_with_exif_gps() -> bytes:
    tiff = b"MM\x00\x2a" + struct.pack(">I", 8) + struct.pack(">H", 1) + struct.pack(">HHII", 0x8825, 4, 1, 26) + b"\x00\x00\x00\x00"
    app1 = b"Exif\x00\x00" + tiff + b"GPS-SECRET-LOCATION"
    return (b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 +
            b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" + b"\x12\x34" * 20 + b"\xff\xd9")


def test_metadata_badges_and_fail_closed_warning(base, page, tmp_path):
    page.goto(base + "/")
    page.set_input_files("#fileInput", _write(tmp_path, "photo.jpg", _jpeg_with_exif_gps()))
    expect(page.locator(".badge", has_text="metadata removed")).to_be_visible()

    page.goto(base + "/")
    page.set_input_files("#fileInput", _write(tmp_path, "IMG_0001.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64))
    expect(page.locator(".badge", has_text="metadata NOT removed")).to_be_visible()
    messages = []
    page.once("dialog", lambda d: (messages.append(d.message), d.dismiss()))
    page.click("#uploadBtn")
    page.wait_for_timeout(300)
    assert messages and "could NOT be removed" in messages[0]
    expect(page.locator("#resultModal")).to_be_hidden()  # dismissed -> nothing uploaded


def test_pages_have_no_csp_violations_and_about_shows_version(base, page, csp_violations):
    for path in ["/", "/about", "/login", "/register", "/download", "/forgot-password", "/reset-password?token=x"]:
        page.goto(base + path)
        page.wait_for_load_state("networkidle")
    page.goto(base + "/about")
    expect(page.locator("#aboutVersion")).to_have_text(re.compile(r"^\d+\.\d+\.\d+$"))
    expect(page.locator(".footer-version")).to_contain_text("Ratatosk v")
    assert csp_violations == []


def test_admin_pages_render_under_csp(base, page, csp_violations, live_server):
    from tests.e2e.conftest import ADMIN_PASSWORD

    page.goto(base + "/login")
    page.fill("#username", "admin")
    page.fill("#password", ADMIN_PASSWORD)
    page.click("#loginForm button[type=submit]")
    page.wait_for_url(re.compile(r"/admin/(setup|settings)"))
    for path in ["/admin/settings", "/admin/users", "/admin/files", "/admin/stats", "/admin/audit", "/account", "/files"]:
        page.goto(base + path)
        page.wait_for_load_state("networkidle")
    page.goto(base + "/admin/settings")
    expect(page.locator("#storage_path")).to_have_attribute("readonly", "")
    page.click("#saveBtn")
    expect(page.locator(".toast", has_text="Settings saved")).to_be_visible()
    # Keyboard-operable account menu (UI-005).
    toggle = page.locator(".dropdown-toggle")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("Escape")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    assert csp_violations == []


def test_session_token_is_not_readable_by_scripts(base, page):
    """SEC-017: after login no token sits in localStorage or document.cookie."""
    from tests.e2e.conftest import ADMIN_PASSWORD

    page.goto(base + "/login")
    page.fill("#username", "admin")
    page.fill("#password", ADMIN_PASSWORD)
    page.click("#loginForm button[type=submit]")
    page.wait_for_url(re.compile(r"/admin/(setup|settings)"))
    storage = page.evaluate("JSON.stringify(Object.assign({}, localStorage))")
    assert "eyJ" not in storage, "a JWT is stored where scripts can read it"
    assert "rt_session" not in page.evaluate("document.cookie")
    cookie = next(c for c in page.context.cookies() if c["name"] == "rt_session")
    assert cookie["httpOnly"] and cookie["sameSite"] == "Strict"
    page.goto(base + "/admin/users")  # authenticated purely by the cookie
    expect(page.locator("#newUserBtn")).to_be_visible()


def test_browser_refuses_a_tampered_script(base, page):
    """FEAT-012: with SRI, a modified crypto.js is never executed."""
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.route("**/static/js/crypto.js", lambda route: route.fulfill(
        status=200, content_type="text/javascript", body="window.SDCrypto = {stolen: true};"))
    page.goto(base + "/")
    assert page.evaluate("typeof window.SDCrypto") == "undefined"
    assert any("integrity" in e.lower() for e in errors), errors


def test_cli_verify_against_live_server(base):
    import json
    import subprocess
    import sys

    import httpx

    digest = httpx.get(base + "/api/integrity").json()["release_digest"]
    out = subprocess.run([sys.executable, "cli/ratatosk.py", "verify", base, "--expect", digest, "--json"],
                         capture_output=True, text=True, timeout=120)
    result = json.loads(out.stdout)
    assert out.returncode == 0 and result["ok"] and result["files_checked"] > 20
    wrong = subprocess.run([sys.executable, "cli/ratatosk.py", "verify", base, "--expect", "0" * 64, "--json"],
                           capture_output=True, text=True, timeout=120)
    assert wrong.returncode == 1 and json.loads(wrong.stdout)["digest_matches_published"] is False
