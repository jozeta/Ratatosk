"""Regenerate the README screenshots from a throwaway demo instance.

    python docs/screenshots/capture.py

Starts a private Ratatosk server with a temporary database, fills it with
made-up demo users and files, and photographs the main screens with
Playwright/Chromium (python -m playwright install chromium). Nothing touches
your real data, and the demo server is gone when the script exits.
"""
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ADMIN_PW = "Demo-Admin-Password-1!"
USER_PW = "Demo-User-Password-1!"
PASSPHRASE = "demo encryption passphrase"
VIEWPORT = {"width": 1280, "height": 860}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server():
    tmp = tempfile.mkdtemp(prefix="ratatosk_shots_")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RATATOSK_", "SECUREDROP_"))}
    env.update({
        "RATATOSK_DATABASE_URL": "sqlite:///" + os.path.join(tmp, "demo.db"),
        "RATATOSK_STORAGE_ROOT": os.path.join(tmp, "s"), "RATATOSK_TMP_ROOT": os.path.join(tmp, "t"),
        "RATATOSK_BRANDING_ROOT": os.path.join(tmp, "b"), "RATATOSK_SECRET_KEY": "screenshots-" + "x" * 40,
        "RATATOSK_DEFAULT_ADMIN_PASSWORD": ADMIN_PW,
    })
    subprocess.run([sys.executable, "-m", "app.init_db"], cwd=ROOT, env=env, check=True, capture_output=True)
    subprocess.run([sys.executable, "-c", "from app.core.dynamic_settings import update_settings; "
                    "update_settings({'rate_limit_enabled': False, 'setup_completed': True})"],
                   cwd=ROOT, env=env, check=True, capture_output=True)
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/api/health").status_code == 200:
                return proc, base, tmp
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("demo server did not start")


def demo_jpeg() -> bytes:
    """A tiny JPEG whose EXIF block carries a fake GPS position."""
    tiff = b"MM\x00\x2a" + struct.pack(">I", 8) + struct.pack(">H", 1) + struct.pack(">HHII", 0x8825, 4, 1, 26) + b"\x00" * 4
    app1 = b"Exif\x00\x00" + tiff + b"GPS 59.3293N 18.0686E"
    return (b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 +
            b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" + b"\x12\x34" * 4000 + b"\xff\xd9")


def shot(page, name, full_page=False):
    page.wait_for_timeout(400)  # let fonts, toasts and transitions settle
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full_page)
    print("saved", name)


def login(page, base, username, password):
    page.goto(base + "/login")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#loginForm button[type=submit]")
    page.wait_for_url(re.compile(r"/(files|admin/settings|admin/setup)$"))


def main():
    proc, base, tmp = start_server()
    files = Path(tmp) / "demo-files"
    files.mkdir()
    (files / "holiday-photo.jpg").write_bytes(demo_jpeg())
    (files / "contract-draft.pdf").write_bytes(b"%PDF-1.7\n" + os.urandom(180_000))
    (files / "quarterly-report.xlsx").write_bytes(os.urandom(420_000))
    for name in ("alice", "bob"):
        httpx.post(base + "/api/auth/register", json={"username": name, "password": USER_PW})
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()

            def context(scheme="light"):
                return browser.new_context(viewport=VIEWPORT, device_scale_factor=2, color_scheme=scheme, accept_downloads=True)

            # 1. Upload page with a queue and metadata badges
            alice = context().new_page()
            login(alice, base, "alice", USER_PW)
            # Office/PDF files can't have metadata stripped; the app asks first.
            alice.on("dialog", lambda d: d.accept())
            alice.goto(base + "/")
            alice.set_input_files("#fileInput", [str(files / "holiday-photo.jpg"), str(files / "contract-draft.pdf")])
            expect(alice.locator(".badge", has_text="metadata removed")).to_be_visible()
            expect(alice.locator(".badge", has_text="metadata NOT removed")).to_be_visible()
            shot(alice, "upload")

            # 2. Result: link + QR
            alice.goto(base + "/")
            alice.set_input_files("#fileInput", str(files / "quarterly-report.xlsx"))
            expect(alice.locator(".file-queue-item .badge", has_text="…")).to_have_count(0)
            alice.click("#uploadBtn")
            expect(alice.locator("#resultModal")).to_be_visible(timeout=30000)
            link = alice.input_value("#resultLink")
            shot(alice, "share-link")

            # 3. Recipient's download page
            recipient = context().new_page()
            recipient.goto(link)
            expect(recipient.locator("#downloadBtn")).to_be_enabled()
            shot(recipient, "download")

            # 4. Encrypted text message, as the recipient sees it
            alice.goto(base + "/")
            alice.click("[data-mode=text]")
            alice.fill("#textInput", "Wi-Fi at the cabin:\n  network  Stuga-5G\n  password correct-horse-battery-staple\n\nThis message deletes itself after it's read.")
            alice.click("#uploadBtn")
            expect(alice.locator("#resultModal")).to_be_visible(timeout=30000)
            text_link = alice.input_value("#resultLink")
            recipient.goto(text_link)
            recipient.click("#downloadBtn")
            expect(recipient.locator(".text-view")).to_be_visible()
            shot(recipient, "text-message")

            # 5. Request links: owner sets up keys, creates links, receives a file
            alice.goto(base + "/account")
            alice.click("#keysSetupBtn")
            alice.fill("#sdk-pass", PASSPHRASE)
            alice.fill("#sdk-pass2", PASSPHRASE)
            alice.check("#sdk-remember")
            alice.click(".modal button[type=submit]")
            expect(alice.locator("#keysStatus")).to_contain_text("fingerprint")
            alice.goto(base + "/requests")
            for label in ("Signed lease agreement", "Photos from the conference"):
                alice.fill("#reqLabel", label)
                alice.click("#createForm button[type=submit]")
                alice.wait_for_timeout(500)
            expect(alice.locator("#requestsBody tr")).to_have_count(2)
            req = alice.evaluate("window.SDApi.get('/api/requests').then(r => r.find(x => x.label.startsWith('Signed')))")

            sender = context().new_page()
            sender.goto(f"{base}/r/{req['id']}#{req['fingerprint']}")
            sender.on("dialog", lambda d: d.accept())
            sender.set_input_files("#fileInput", [str(files / "contract-draft.pdf")])
            expect(sender.locator(".file-queue-status", has_text="Sent ✓")).to_be_visible(timeout=30000)
            shot(sender, "request-upload")

            alice.goto(base + "/requests")
            alice.locator("#requestsBody tr", has_text="Signed lease").get_by_role("button", name="Received files").click()
            expect(alice.locator("#inboxBody tr")).to_have_count(1)
            alice.evaluate("window.scrollTo(0, 0)")
            shot(alice, "request-links", full_page=True)

            # 6. Admin settings and About, plus dark mode
            admin = context().new_page()
            login(admin, base, "admin", ADMIN_PW)
            admin.goto(base + "/admin/settings")
            admin.wait_for_load_state("networkidle")
            shot(admin, "admin-settings")

            dark = context("dark").new_page()
            dark.goto(base + "/about")
            dark.wait_for_load_state("networkidle")
            shot(dark, "about-dark")
            browser.close()
    finally:
        proc.terminate()
        proc.wait(10)


if __name__ == "__main__":
    main()
