"""Browser flows for end-to-end sharing (FEAT-002) and request links (FEAT-001)."""
import os
import re
import sqlite3
import uuid

import httpx
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e
PASSWORD = "Browser-Test-Pass-123!"


def register(base, name):
    r = httpx.post(base + "/api/auth/register", json={"username": name, "password": PASSWORD})
    assert r.status_code == 200, r.text


def browser_login(page, base, name):
    page.goto(base + "/login")
    page.fill("#username", name)
    page.fill("#password", PASSWORD)
    page.click("#loginForm button[type=submit]")
    page.wait_for_url(re.compile(r"/files$"))


def setup_keys(page, base, passphrase, remember):
    page.goto(base + "/account")
    page.click("#keysSetupBtn")
    page.fill("#sdk-pass", passphrase)
    page.fill("#sdk-pass2", passphrase)
    if remember:
        page.check("#sdk-remember")
    page.click(".modal button[type=submit]")
    expect(page.locator("#keysStatus")).to_contain_text("fingerprint")


def db(live_server):
    url = live_server["env"]["RATATOSK_DATABASE_URL"]
    return sqlite3.connect(url.replace("sqlite:///", ""))


def test_end_to_end_share_between_accounts(base, browser, tmp_path, live_server):
    alice_name, bob_name = f"alice{uuid.uuid4().hex[:6]}", f"bob{uuid.uuid4().hex[:6]}"
    register(base, alice_name)
    register(base, bob_name)
    alice = browser.new_context(accept_downloads=True).new_page()
    bob = browser.new_context(accept_downloads=True).new_page()
    browser_login(alice, base, alice_name)
    browser_login(bob, base, bob_name)
    setup_keys(bob, base, "bobs encryption passphrase", remember=False)

    path = tmp_path / "for-bob.txt"
    path.write_bytes(b"only bob can read this")
    alice.goto(base + "/")
    alice.set_input_files("#fileInput", str(path))
    expect(alice.locator(".file-queue-item .badge", has_text="…")).to_have_count(0)
    alice.click("#uploadBtn")
    expect(alice.locator("#resultModal")).to_be_visible(timeout=30000)
    # Nobody has opted into the directory: no empty list box is shown...
    expect(alice.locator("#userPickerList")).to_be_hidden()
    alice.fill("#shareLookupInput", bob_name)
    alice.click("#shareLookupBtn")
    expect(alice.locator("#userPickerList input:checked")).to_have_count(1)
    expect(alice.locator("#userPickerList")).to_be_visible()  # ...until someone is added
    alice.click("#shareWithUsersBtn")
    expect(alice.locator("#shareStatus")).to_contain_text("(end-to-end)")

    # The server only holds a wrapped key - never the file key itself.
    file_id = alice.input_value("#resultLink").split("/share/")[1].split("#")[0]
    with db(live_server) as conn:
        wrapped, = conn.execute("select wrapped_key from file_shares where file_id = ?", (file_id,)).fetchone()
        held, = conn.execute("select shared_decryption_key from files where id = ?", (file_id,)).fetchone()
    assert wrapped and held is None

    bob.goto(base + "/shared")
    bob.get_by_role("button", name="Decrypt & Download").first.click()
    bob.fill("#sdk-pass", "wrong passphrase!!")
    bob.click(".modal button[type=submit]")
    expect(bob.locator(".toast", has_text="Wrong encryption passphrase")).to_be_visible()
    bob.fill("#sdk-pass", "bobs encryption passphrase")
    with bob.expect_download() as dl:
        bob.click(".modal button[type=submit]")
    assert open(dl.value.path(), "rb").read() == b"only bob can read this"


def test_request_link_anonymous_sender_to_owner(base, browser, tmp_path):
    owner_name = f"owner{uuid.uuid4().hex[:6]}"
    register(base, owner_name)
    owner = browser.new_context(accept_downloads=True).new_page()
    browser_login(owner, base, owner_name)
    setup_keys(owner, base, "owner encryption passphrase", remember=True)

    owner.goto(base + "/requests")
    owner.fill("#reqLabel", "Scans of your passport")
    owner.click("#createForm button[type=submit]")
    expect(owner.locator("#requestsBody tr")).to_have_count(1)
    req = owner.evaluate("window.SDApi.get('/api/requests').then(r => r[0])")
    link = f"{base}/r/{req['id']}#{req['fingerprint']}"

    sender = browser.new_context().new_page()  # no account
    sender.goto(link)
    expect(sender.locator("#reqLabel")).to_contain_text("Scans of your passport")
    payload = os.urandom(200_000)
    (tmp_path / "passport.bin").write_bytes(payload)
    sender.set_input_files("#fileInput", str(tmp_path / "passport.bin"))
    expect(sender.locator(".file-queue-status", has_text="Sent ✓")).to_be_visible(timeout=30000)

    owner.goto(base + "/requests")
    owner.get_by_role("button", name="Received files").click()
    with owner.expect_download() as dl:
        owner.get_by_role("button", name="Decrypt & download").click()  # key remembered: no prompt
    assert dl.value.suggested_filename == "passport.bin"
    assert open(dl.value.path(), "rb").read() == payload


def test_request_link_with_wrong_fingerprint_is_refused(base, browser):
    owner_name = f"owner{uuid.uuid4().hex[:6]}"
    register(base, owner_name)
    owner = browser.new_context().new_page()
    browser_login(owner, base, owner_name)
    setup_keys(owner, base, "another passphrase!", remember=True)
    owner.goto(base + "/requests")
    owner.click("#createForm button[type=submit]")
    expect(owner.locator("#requestsBody tr")).to_have_count(1)
    req = owner.evaluate("window.SDApi.get('/api/requests').then(r => r[0])")

    sender = browser.new_context().new_page()
    sender.goto(f"{base}/r/{req['id']}#{'0' * 64}")  # as if the server swapped the key
    expect(sender.locator("#reqClosed")).to_contain_text("Security check failed")
    expect(sender.locator("#sendPanel")).to_be_hidden()
