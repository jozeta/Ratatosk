# SecureDrop

A self-hosted, zero-knowledge encrypted file-sharing web application. Files are encrypted and decrypted entirely in the browser with the Web Crypto API (AES-256-GCM) — the server only ever stores and serves ciphertext. It never sees plaintext, filenames, or decryption keys.

- **Zero-knowledge**: encryption/decryption happens client-side; decryption keys travel in the URL fragment (never sent over HTTP) or as a passphrase communicated out-of-band.
- **Anonymity-first**: optional zero-log mode, IP masking, timestamp fuzzing, EXIF/metadata stripping, no third-party CDNs or trackers.
- **Self-service admin panel**: every policy (retention, size limits, anonymity level, password rules, storage caps) is editable at runtime from `/admin/settings` — no restart required.
- **Optional TOTP two-factor authentication**, with per-role enforcement (require it for regular users, admins, or both) and a self-service "Log out other sessions" that invalidates every other outstanding session token instantly.
- **Audit logging**: filterable, exportable (CSV/JSON) log of uploads, downloads, admin changes, and failed-password lockouts, all respecting the configured privacy level.
- **Automated test suite** (pytest) covering auth, MFA, upload/download policy enforcement, sharing IDOR checks, and admin settings — see [Running tests](#running-tests).

---

## Table of contents

- [Features](#features)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Quick start (local development)](#quick-start-local-development)
- [Running with Docker](#running-with-docker)
- [Running tests](#running-tests)
- [Configuration](#configuration)
  - [Environment variables (bootstrap config)](#environment-variables-bootstrap-config)
  - [Runtime settings (admin panel)](#runtime-settings-admin-panel)
- [Usage](#usage)
  - [First-run setup](#first-run-setup)
  - [Uploading a file](#uploading-a-file)
  - [API keys / CLI upload](#api-keys--cli-upload)
  - [Downloading a file](#downloading-a-file)
  - [Accounts and "My Files"](#accounts-and-my-files)
  - [Admin panel](#admin-panel)
  - [Audit log](#audit-log)
- [How the encryption works](#how-the-encryption-works)
- [API overview](#api-overview)
- [Project structure](#project-structure)
- [Security notes](#security-notes)
- [License](#license)

---

## Features

**Cryptography**
- AES-256-GCM via `window.crypto.subtle`, entirely client-side.
- Two key-transport modes: a random key embedded in the URL hash fragment, or a key derived from a secondary passphrase via PBKDF2 (250,000 iterations, SHA-256).
- Filename and MIME type are encrypted along with the file content, so the server never learns them either.

**Anonymity**
- Client-side EXIF/GPS/author-metadata stripping for images (canvas re-encode) before encryption.
- Server strips forwarding headers (`X-Forwarded-For`, `Referer`, `Client-IP`, etc.) before they reach any handler.
- Configurable IP handling: `Strict None` (don't capture), `Masked Subnet` (/16 IPv4, /64 IPv6), or `Full IP`.
- Configurable timestamp fuzzing (round to nearest hour/day) to blunt timing-correlation attacks.
- Zero-log mode: uploads are recorded only as an anonymous `ANON_UPLOAD` event with no IP/UA/user link.
- No third-party CDNs or fonts — every asset is self-hosted, safe for `.onion` / air-gapped deployment.

**Access control & policy**
- Toggle anonymous uploading, anonymous downloading, public registration, and public login independently — anonymous uploading/downloading off redirects an unauthenticated visitor straight to `/login` (instead of showing a form that will just fail), and hides the Upload/Download links from the nav bar for anyone not logged in; login off still leaves admin accounts able to sign in at `/login` directly. Registration off replaces the register page with a "Registration is closed" notice and hides the "Register" link on the login page.
- **Two-factor authentication (TOTP)**: an admin-wide on/off switch, plus independent "enforce for regular users" and "enforce for admins" toggles. When enforcement is on, anyone without MFA set up is required to complete setup (scan a QR code, confirm a code, save one-time backup codes) as the very next step after their password, before a session token is issued.
- Account login rate limiting: lock an account out for a configurable number of minutes after too many failed password *or MFA code* attempts in a row. Independently toggle-able; applies to every account, including admins.
- Enforce (or entirely disable) a secondary passphrase on every upload, with a configurable password policy (minimum length, required character classes) applied to registration, admin-created accounts, password resets, and self-service password changes.
- Configurable max file size, chunk size, concurrent-upload limit, and an interactive extension allow/deny list (add/remove chips in the admin UI, no more comma-editing).
- Configurable TTL presets (same chip-list UI) and default TTL — optionally lock every upload to the default, fixed, hiding the "Expires after" field from uploaders.
- Burn-after-download and max-download counts — the max-download count can likewise be locked to a fixed default instead of left to the uploader.
- Total storage cap with automatic rejection at 95% usage, and a background worker that purges expired/exhausted files on a configurable interval.
- Multi-file and folder upload, independently toggle-able: select or drag-drop any number of files (or a whole folder, traversed recursively client-side) into a queue, each encrypted and uploaded separately with its own share link.

**Account self-service**
- Registered users can change their own password (with a live strength meter and policy checklist) or delete their own account from `/account`. Deleting an account orphans (doesn't delete) their previously shared files so existing links keep working.
- Changing your password immediately invalidates every other session token for the account (a stolen or shared-device token stops working on its very next request), and a fresh token is issued so the device you changed it from stays logged in. A separate **"Log out other sessions"** button does the same thing on demand, without requiring a password change.
- **API keys** (`/account`, independently toggle-able as "API keys" in settings): generate high-entropy tokens for scripted/CLI uploads without a browser — see [`cli/securedrop_upload.py`](#api-keys--cli-upload) below. Each key is created with a scope: **Full access** (equivalent to being logged in as you) or **Upload only** (can call the upload endpoints and nothing else — safe to hand to a script or CI pipeline). Revoking a key takes effect immediately; keys are shown once, at creation.
- **Download notifications**: when uploading (while logged in, and if enabled site-wide), opt in to an email each time that specific file is downloaded. Requires SMTP to be configured; the email reports size and time only — the server never learns the real filename, so it can't include it.

**User-to-user sharing** (`/shared`, independently toggle-able as "User-to-user sharing" in settings)
- Right after uploading a file (as a logged-in user, without a secondary passphrase), pick specific registered accounts from a list to share it with directly.
- This is a distinct, opt-in pathway from the normal zero-knowledge link flow: to make "just log in and see it" possible with no link or passphrase exchange, the client-side key is stored server-side, scoped to that specific share. Only the file's owner and the chosen recipients can ever retrieve it (checked on every request) — direct link/passphrase sharing is unaffected and stays fully zero-knowledge. Passphrase-protected files can't be shared this way, since the server never has that key to begin with.
- Recipients see everything shared with them at `/shared` — file size, who shared it, everyone else it's shared with, and a one-click decrypt/download.
- Owners see who a file is shared with from `/files` and can revoke access per-recipient at any time.

**Admin tooling**
- **User Management** (`/admin/users`, independently toggle-able): create users, rename accounts, promote/demote admin status, activate/deactivate accounts, reset passwords, delete users.
- **File Management** (`/admin/files`, independently toggle-able): view and delete any file on the platform, regardless of owner.
- **Statistics** (`/admin/stats`): active file count, all-time upload/download counts, registered users, a grouped bar chart of uploads vs. downloads over a selectable range (7 days / 30 days / 6 months / 1 year), an SVG pie chart of storage used vs. the configured cap, an SVG pie chart of active files by extension, and event totals (burned/expired/deleted).
- **Branding**: replace the top-left mark with a custom logo (PNG/JPEG/WebP/SVG/ICO, max 2MB) and brand name, and edit the footer text — all from the top of `/admin/settings`. With no logo uploaded, a self-hosted default padlock mark is used (no external icon font or emoji dependency).
- Brute-force lockout on secondary-password attempts.
- Filterable, paginated audit log with CSV/JSON export and configurable retention/pruning.
- **Danger Zone — full factory reset** (`/admin/settings#danger-zone`): wipes every user, file, share, API key, and setting back to defaults in one action. Requires re-entering the acting admin's current password and typing a confirmation phrase. Irreversible — the acting admin's own account is deleted as part of the wipe (which invalidates their session on the very next request), a fresh admin account is bootstrapped with a random password, and that password is shown exactly once in a modal after the reset completes.
- All of the above is editable live from `/admin/settings` and takes effect immediately.

---

## Architecture

- **Backend**: Python, [FastAPI](https://fastapi.tiangolo.com/) + [SQLAlchemy](https://www.sqlalchemy.org/) ORM, SQLite by default.
- **Frontend**: Semantic HTML5, vanilla ES6+ JavaScript, and a small hand-written CSS framework (no Bootstrap/jQuery/CDN dependency) with a light/dark theme toggle.
- **Storage**: pluggable backend behind a small interface — local filesystem by default (`./storage/encrypted/`), or an S3-compatible bucket (AWS S3, MinIO, Backblaze B2, etc.) via `SECUREDROP_STORAGE_BACKEND=s3`; see [Environment variables](#environment-variables-bootstrap-config). A background asyncio task purges expired files regardless of backend.
- **Auth**: JWT bearer tokens, stored in the browser's `localStorage`. Each token embeds a version number tied to the account; changing your password or hitting "Log out other sessions" bumps it, instantly invalidating every token issued before that moment.

```
Browser (encrypt/decrypt)  <-- ciphertext only -->  FastAPI  <-->  SQLite (metadata) + filesystem (blobs)
```

---

## Requirements

- Python 3.11+ (developed against 3.13)
- pip
- (Optional) Docker + Docker Compose, for containerized deployment
- (Optional) `boto3` (`pip install -r requirements-s3.txt`), only if using the S3-compatible storage backend
- (Optional) `pytest` + `httpx` (`pip install -r requirements-dev.txt`), only if running the test suite

---

## Quick start (local development)

```bash
# 1. Clone / enter the project directory
cd SecureDrop

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows (PowerShell/Git Bash):
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize the database and create the default admin account
python -m app.init_db
# Prints a one-time generated admin password to the console — save it now,
# it is never shown again and is not stored anywhere in the app.

# 5. Start the server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** in your browser. Log in at `/login` with the admin credentials printed in step 4 to reach `/admin/settings` and `/admin/audit`.

To stop: `Ctrl+C`. To reset everything: stop the server, delete `securedrop.db` and the contents of `storage/encrypted/` and `storage/tmp/`, then repeat steps 4–5.

---

## Running with Docker

```bash
# 1. Copy the example environment file and fill in a real secret key
cp .env.example .env
# Edit .env: set SECUREDROP_SECRET_KEY to a random 32+ character string
# (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`)

# 2. Build and start
docker-compose up --build
```

This builds the image, runs `python -m app.init_db` on container start (idempotent — safe to restart), and serves the app on **http://localhost:8000**. The admin password is printed to the container logs on first run:

```bash
docker-compose logs securedrop | grep -A3 "Created default admin"
```

Data persists across restarts via two bind-mounted host directories:

| Host path   | Container path       | Contents                                   |
|-------------|-----------------------|---------------------------------------------|
| `./data`    | `/app/data`            | `securedrop.db` (SQLite metadata)           |
| `./storage` | `/app/storage`         | Encrypted blobs and in-progress uploads     |

To stop: `docker-compose down`. To wipe all data: also delete `./data` and `./storage`.

---

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

The test suite runs against a completely isolated, temporary SQLite database and storage directory — created fresh per test via `tests/conftest.py`, using the app's own real startup path (the same table creation and migration code that runs on a normal boot), and torn down afterward. It never touches your real `securedrop.db` or `storage/` directory, no matter what's in your working copy when you run it.

---

## Configuration

SecureDrop has two layers of configuration:

1. **Bootstrap config** (environment variables) — read once at process startup. Covers things the app needs before the database is even available: where the database lives, the JWT signing secret, the default admin account.
2. **Runtime settings** (database-backed, admin panel) — every operational policy (limits, retention, anonymity level, etc.). Editable live at `/admin/settings`, applied immediately to the running server, no restart needed.

### Environment variables (bootstrap config)

All variables are prefixed `SECUREDROP_` and can be set directly or via a `.env` file in the project root (see `.env.example`).

| Variable                          | Default                              | Description                                                                 |
|------------------------------------|---------------------------------------|-------------------------------------------------------------------------------|
| `SECUREDROP_DATABASE_URL`          | `sqlite:///./securedrop.db`           | SQLAlchemy database URL.                                                     |
| `SECUREDROP_STORAGE_ROOT`          | `./storage/encrypted`                 | Directory where encrypted blobs are written.                                 |
| `SECUREDROP_TMP_ROOT`              | `./storage/tmp`                       | Directory for in-progress chunked uploads.                                   |
| `SECUREDROP_SECRET_KEY`            | *(insecure placeholder — change me)*  | Secret used to sign JWT session tokens. **Must** be overridden in production. |
| `SECUREDROP_JWT_ALGORITHM`         | `HS256`                               | JWT signing algorithm.                                                       |
| `SECUREDROP_JWT_EXPIRE_MINUTES`    | `720` (12h)                           | Session token lifetime.                                                      |
| `SECUREDROP_FRONTEND_DIR`          | `./frontend`                          | Path to the frontend HTML/CSS/JS bundle.                                     |
| `SECUREDROP_DEFAULT_ADMIN_USERNAME`| `admin`                               | Username created by `app.init_db` if no admin exists yet.                    |
| `SECUREDROP_DEFAULT_ADMIN_PASSWORD`| *(blank — auto-generated)*            | Set this to pin a known admin password instead of generating a random one.   |
| `SECUREDROP_STORAGE_BACKEND`       | `local`                               | `local` (default) or `s3`. Kept as an env var rather than an admin-panel setting so cloud credentials never end up stored in the database. |
| `SECUREDROP_S3_BUCKET`             | *(empty)*                             | Required if `STORAGE_BACKEND=s3`.                                             |
| `SECUREDROP_S3_REGION`             | *(empty)*                             | AWS region, or blank for non-AWS S3-compatible services.                     |
| `SECUREDROP_S3_ENDPOINT_URL`       | *(empty)*                             | Set for non-AWS S3-compatible services (MinIO, Backblaze B2, etc.).          |
| `SECUREDROP_S3_ACCESS_KEY_ID` / `SECUREDROP_S3_SECRET_ACCESS_KEY` | *(empty)* | Credentials, if not relying on the environment's default AWS credential chain. |
| `SECUREDROP_S3_PREFIX`             | *(empty)*                             | Optional key prefix within the bucket, e.g. `prod/`.                         |

> **Production checklist:** always set a real `SECUREDROP_SECRET_KEY`; consider setting `SECUREDROP_DEFAULT_ADMIN_PASSWORD` explicitly if you're scripting deployment; put the app behind HTTPS (the browser's Web Crypto API and clipboard access require a secure context in production, i.e. HTTPS or `localhost`).

### Runtime settings (admin panel)

Log in as an admin and visit **`/admin/settings`**. Changes save to the database and take effect immediately for every subsequent request — no restart, no redeploy.

| Section | Setting | Notes |
|---|---|---|
| **Access & Authentication** | Anonymous uploading | Allow drop-and-go uploads without an account. |
| | Anonymous downloading | Off = force login before any file can be downloaded. |
| | User registration | Public sign-ups vs. invite-only (an admin can still create accounts directly from User Management either way). |
| | User login | Off = only admin accounts can log in; the `/login` page itself stays reachable (just unlinked from the nav) so an admin can still sign in manually. |
| | Allow secondary passphrase | Off removes the passphrase option from the upload form entirely (and turns off "Enforce" below, since there'd be nothing to enforce). |
| | Enforce secondary password | Force every uploader to set a passphrase. |
| | User-to-user sharing | Off disables `/shared`, the "Share with specific users" panel, and their APIs entirely. |
| | Enable MFA | Master switch for TOTP two-factor authentication. Off hides the "Enable 2FA" option on `/account`; anyone who already had it on keeps the option to turn it back off. |
| | Enforce MFA for users / for admins | Independent toggles. When on for a role, anyone in that role without MFA already set up is required to complete setup as the next step after their password, before a session token is issued. |
| **Login Security** | Account login rate limiting | Lock an account out after too many failed logins in a row. Uses the "Max login/password attempts" value from Audit & Security below. |
| | Lockout duration (minutes) | How long an account stays locked before it can try again on its own. |
| **Admin Feature Views** | User management | Show/hide the `/admin/users` page and its API entirely. |
| | File management | Show/hide the `/admin/files` page and its API entirely. |
| | API keys | Allow users to create API keys for CLI/scripted uploads from `/account`. Off immediately stops all existing keys from working too. |
| **Password Policy** | Minimum length | Applied to registration, admin-created users, password resets, and self-service changes. |
| | Require uppercase / lowercase / number / special character | Each is an independent toggle; the register and account pages show a live checklist against the active policy. |
| **Upload & File Constraints** | Max file size (MB) | Enforced both client- and server-side. |
| | Chunk size (MB) | Size of each chunk streamed during upload. |
| | Max concurrent uploads | Per-uploader in-flight upload limit. |
| | Multi-file / folder upload | Let the upload page accept more than one file at once (including whole folders dropped in), queuing and encrypting each separately. Off restricts the page to one file at a time. |
| | Extension rule mode + list | Blacklist (block listed extensions) or whitelist (only allow listed) — edited as add/remove chips, not a raw comma-separated field. |
| **Retention & Expiration** | Allowed TTL presets | Chip-list UI; each entry is a number plus `m`/`h`/`d` (minutes/hours/days), e.g. `10m`, `24h`, `7d`. |
| | Default TTL | Pre-selected in the uploader UI. |
| | Allow custom expiration | Off hides the "Expires after" field entirely; every upload uses the Default TTL, fixed. |
| | Allow / force burn-after-download | Delete immediately after the first successful download. |
| | Allow custom max downloads | Off hides the "Max downloads" field entirely; every upload uses the default below, fixed. |
| | Default max downloads | `0` = unlimited. |
| **Local Storage Engine** | Storage path | Disk directory for encrypted blobs. Only applies to the local backend — see `SECUREDROP_STORAGE_BACKEND` in [Environment variables](#environment-variables-bootstrap-config) for S3. |
| | Total storage cap (GB) | New uploads are rejected once usage would exceed 95% of this cap. |
| | Cleanup interval (minutes) | How often the background worker purges expired/exhausted files. |
| **Email (SMTP)** | Enable password reset emails | Turns on the "Forgot password?" link and the email-sending machinery behind it. |
| | Enable download notifications | Site-wide switch for the per-file "Notify me when downloaded" option on the upload page. Still requires password reset emails (above) to be on, since it shares the same SMTP configuration. |
| | SMTP host / port / username / password / encryption / from-address / from-name | Standard SMTP client settings; a "Send test email" button is available once configured. |
| **Extreme Anonymity Engine** | Zero-log mode | Disable IP/user-agent/precise-timestamp logging for uploads entirely. |
| | IP obfuscation level | `Strict None` / `Masked Subnet` (/16 or /64) / `Full IP`. |
| | Timestamp fuzzing | `None` / round to nearest hour / round to nearest day. |
| **Audit & Security** | Audit log retention (days) | Used by the "Prune" action on `/admin/audit`. |
| | Max login/password attempts | Threshold before an account or a password-protected file is locked out. |

---

## Usage

### First-run setup

The first time an admin logs in with `setup_completed` still unset, they're redirected to `/admin/setup` — a short wizard covering branding (logo, name, footer), then the access & security settings that matter most for a first deployment (anonymous upload/download, public registration, login rate limiting). Every choice can be changed later from `/admin/settings`; "Skip setup" marks it done without changing anything. Subsequent admin logins go straight to `/admin/settings`.

### Uploading a file

1. Go to `/` (or click **Upload** in the nav bar).
2. Drag one or more files (or, with multi-file upload enabled, a whole folder) onto the drop zone, or click it to browse. Each file appears in a queue with its size and a remove button.
3. Choose an expiration, optionally set a max download count, burn-after-download, and/or a secondary passphrase — these apply to every file in the queue.
4. Click **Encrypt & Upload**. Each file is stripped of image metadata (if applicable), encrypted in your browser, and uploaded in chunks, one at a time.
5. For a single file, you'll get a share link, a QR code, and — unless you set a passphrase — a decryption key (already embedded in the link's `#fragment`). For two or more files, you'll get a table with one link per file. Share the link(s) (and, if applicable, the passphrase, through a different channel) with the recipient.

### API keys / CLI upload

Logged-in users can generate an API key from `/account` (if enabled in settings) for uploading without a browser — useful for scripts, cron jobs, or CI. Pick a scope at creation time: **Full access** works exactly like a login token, while **Upload only** can call the upload endpoints and nothing else — the safer choice to hand to an untrusted script or pipeline. Treat a key like a password regardless of scope: it's shown once, at creation.

```bash
export SECUREDROP_API_KEY=sdk_...
python cli/securedrop_upload.py --server http://localhost:8000 ./report.pdf --ttl 24h --max-downloads 3
```

The CLI performs the same client-side AES-256-GCM encryption as the browser (matching wire format), so uploads made this way are just as zero-knowledge — the server never sees the key or plaintext. Run `python cli/securedrop_upload.py --help` for all options (`--password` for passphrase mode, `--burn`, etc.).

### Downloading a file

- **Direct link**: open the `https://.../share/<file_id>#<key>` link you were given, then click **Decrypt & Download**. If the file requires a passphrase instead, you'll be prompted for it.
- **Manual lookup**: go to `/download`, and enter the File ID plus the decryption key or passphrase by hand.

### Accounts and "My Files"

Registering an account (if enabled) lets you track and manage your own uploads at `/files` — remaining TTL, download counts, who it's shared with (with one-click revoke), and one-click deletion — without changing how encryption works (the server still never sees plaintext). From `/account`, any logged-in user can change their own password (live strength meter + policy checklist), enable/disable two-factor authentication, sign out every other session with one click, manage API keys, or delete their own account. Files shared directly with you by another user (see [User-to-user sharing](#features)) show up at `/shared`, ready to decrypt with one click.

### Admin panel

- `/admin/settings` — see [Runtime settings](#runtime-settings-admin-panel) above.
- `/admin/users` — create users, rename accounts, promote/demote admin status, activate/deactivate, reset passwords, or delete accounts. Can be hidden entirely via the "User management" toggle in settings.
- `/admin/files` — view and delete any file on the platform regardless of owner. Can be hidden entirely via the "File management" toggle in settings.
- `/admin/stats` — active files, all-time upload/download counts, registered users, a bar chart of uploads/downloads over a selectable time range, a storage-used-vs-cap pie chart, and a file-extension pie chart.

### Audit log

`/admin/audit` — filter by event type, file ID, or free-text search; export the current filter as CSV or JSON; prune entries older than 30/90/180 days.

---

## How the encryption works

1. The browser generates a random AES-256 key (or derives one from a passphrase via PBKDF2, if secondary-password mode is used).
2. The original filename, MIME type, and file bytes are packed into a small envelope and encrypted with AES-256-GCM.
3. The resulting ciphertext (with a version flag, any PBKDF2 salt, and the GCM IV prepended) is what actually gets uploaded, chunked, and stored — the server only ever handles this opaque blob.
4. **Random-key mode**: the raw key is base64url-encoded into the URL's `#fragment`, which browsers never include in HTTP requests — the server truly never sees it.
5. **Passphrase mode**: no key travels in the URL at all. The recipient must be given the passphrase separately; the server additionally stores a bcrypt hash of it purely to rate-limit and lock out online guessing against the download endpoint — that hash cannot be used to derive the decryption key.
6. On download, the browser fetches the ciphertext and reverses the process locally with `crypto.subtle.decrypt` — AES-GCM's built-in authentication tag means a wrong key/passphrase fails loudly instead of silently returning garbage.

---

## API overview

All endpoints are under `/api`. Interactive docs (Swagger UI) are available at **`/docs`** when the server is running.

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/register`, `/login`, `GET /api/auth/me` | Account management. `/login` may return a session token, or an `mfa_required`/`mfa_setup_required` response if two-factor is enabled/enforced. |
| `POST /api/auth/mfa/setup`, `/mfa/confirm`, `/mfa/verify`, `/mfa/enforce-setup`, `/mfa/enforce-confirm`, `/mfa/disable` | Two-factor authentication setup and login-time verification. |
| `POST /api/auth/change-password`, `/logout-everywhere`, `DELETE /api/auth/me` | Self-service password change (invalidates other sessions, returns a fresh token), sign out every other session on demand, account deletion. |
| `GET /api/config` | Public, non-sensitive subset of current policy (limits, TTL presets, password policy, etc.) for the frontend to render. |
| `GET/POST /api/account/api-keys`, `DELETE /api/account/api-keys/{id}` | API key management, including scope (`full`/`upload`) at creation. |
| `POST /api/uploads/init` → `PUT /api/uploads/{id}/chunk` → `POST /api/uploads/{id}/complete` | Chunked upload flow. |
| `GET /api/files/{id}/meta`, `POST /api/files/{id}/verify-password`, `GET /api/files/{id}/blob` | Download flow (all three respect the anonymous-download policy). |
| `GET /api/files/mine`, `DELETE /api/files/{id}` | Owner file management. |
| `GET /api/users/list`, `POST /api/files/{id}/share`, `GET /api/files/shared-with-me`, `GET /api/files/{id}/shared-key`, `DELETE /api/files/{id}/share/{recipient_id}` | User-to-user sharing (logged in; 403 if disabled in settings). |
| `GET /api/admin/settings`, `PATCH /api/admin/settings` | Runtime configuration (admin only). |
| `GET /api/admin/audit`, `GET /api/admin/audit/export`, `POST /api/admin/audit/prune` | Audit log (admin only). |
| `GET/POST /api/admin/users`, `PATCH/DELETE /api/admin/users/{id}`, `POST /api/admin/users/{id}/reset-password` | User management, including rename (admin only; 403 if disabled in settings). |
| `GET /api/admin/stats`, `GET /api/admin/stats/timeseries` | Statistics for the Statistics page (admin only). |
| `GET /api/branding/logo` | Public — streams the current custom logo, or 404 if none is set. |
| `POST /api/admin/branding/logo`, `DELETE /api/admin/branding/logo` | Upload/remove the custom logo (admin only). |
| `GET /api/admin/files`, `DELETE /api/admin/files/{id}` | Platform-wide file management (admin only; 403 if disabled in settings). |
| `POST /api/admin/system/reset` | Full factory reset — wipes every user, file, and setting; requires the acting admin's current password (admin only). |

---

## Project structure

```
SecureDrop/
├── app/
│   ├── api/              # FastAPI routers (auth, uploads, files, sharing, admin settings/audit/users/files/system, public config, account API keys)
│   ├── core/              # Config, DB session, security/JWT, dynamic settings cache, privacy helpers, cleanup worker, TTL parsing, password policy, SQLite migration helper
│   ├── models/             # SQLAlchemy models (User, FileObject, FileShare, ApiKey, SystemSettings, AuditLog)
│   ├── schemas/             # Pydantic request/response schemas
│   ├── services/             # Storage backend facade + audit-logging + email services
│   │   └── storage_backends/    # StorageBackend interface, LocalDiskBackend, S3Backend
│   ├── init_db.py             # Creates tables + seeds default settings/admin account
│   └── main.py                 # App entrypoint, routing, middleware
├── frontend/
│   ├── *.html                    # Upload, share, download, login, register, account, my-files, admin pages
│   └── static/
│       ├── css/app.css              # Self-hosted UI kit (light/dark themes, tag-list widget, strength bar)
│       └── js/                        # crypto.js, exif-strip.js, upload/download flows, admin UIs, vendor/qrcode.js
├── storage/
│   ├── encrypted/                       # Encrypted blobs when using the local backend (gitignored)
│   └── tmp/                               # In-progress chunked uploads, always local regardless of backend (gitignored)
├── tests/                                     # pytest suite - see [Running tests](#running-tests)
├── cli/                                         # securedrop_upload.py - scripted/CI upload client
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt                     # pytest, httpx (for TestClient)
├── requirements-s3.txt                    # boto3, only needed for the S3 storage backend
└── .env.example
```

---

## Security notes

- This project implements strong client-side cryptography and reasonable operational hardening, but it has **not** been through a professional security audit. Review the code yourself before relying on it for sensitive data.
- Always deploy behind HTTPS in production — besides the general risk of plaintext HTTP, some browsers restrict `window.crypto.subtle` and clipboard APIs to secure contexts.
- Change `SECUREDROP_SECRET_KEY` before any non-local deployment; the default is an intentionally obvious placeholder.
- The "secondary password" server-side check exists only to rate-limit guessing — it is not, and cannot be, a substitute for keeping the actual link/passphrase confidential.
- Zero-knowledge covers *content and keys*; it does not make the server operator blind to traffic metadata an ISP/network observer could see (file sizes, request timing) beyond what the anonymity settings above mitigate.
- Session tokens are versioned per-account: a password change or "Log out other sessions" invalidates every token issued before that moment, on its very next use — there's no waiting for expiry.
- User-to-user sharing (as opposed to link sharing) is a deliberate, narrower exception to the zero-knowledge design: to let a recipient decrypt just by being logged in, the client-side key for that specific share is stored server-side, scoped to the file's owner and chosen recipients only. Direct link/passphrase sharing is unaffected and stays fully zero-knowledge.
- An "Upload only" API key is rejected outside the upload endpoints at the same authentication choke point every other request passes through — a leaked upload-only key can't be used to list, download, or delete anything.

---

## License

Released under the [MIT License](LICENSE).
