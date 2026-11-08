# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Ratatosk (formerly "SecureDrop") is a self-hosted, zero-knowledge, end-to-end encrypted file and
message sharing server. Files are encrypted in the browser (Web Crypto, AES-256-GCM) before
upload and decrypted in the recipient's browser; the server only stores ciphertext. FastAPI +
SQLAlchemy/Alembic on SQLite (WAL) with optional S3 storage, vanilla-JS frontend, Python CLI, and
an optional Tor onion-service sidecar.

## Commands

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                                # set RATATOSK_SECRET_KEY
python -m app.init_db                               # migrations + one-time admin password
uvicorn app.main:app --host 127.0.0.1 --port 8000

pytest -q --ignore=tests/e2e                        # unit + API tests
python -m playwright install chromium && pytest -q tests/e2e
npm install && node --test "tests/js/*.test.mjs"    # crypto, EXIF stripping, CLI<->browser interop
ruff check app cli tests migrations/env.py
mypy app cli
bandit -c pyproject.toml -r app cli
pip-audit -r requirements.txt
npx eslint frontend/static/js tests/js
python -m app.integrity check                       # SRI hashes match the frontend files
docker compose up -d --build
```

CI (`.github/workflows/ci.yml`) runs all of these plus a Docker build. Run the relevant ones before
committing.

## Layout

`app/api/` (FastAPI routers), `app/core/` (config, database, security: JWT/TOTP, rate limiting,
cleanup worker, privacy helpers), `app/models/`, `app/schemas/`, `app/services/` (users, files,
storage local/S3, audit, email, lockout), `cli/ratatosk.py`, `frontend/` (pages and
`static/js/`: `crypto.js`, `exif-strip.js`, upload/download flows, `sw.js`, admin UIs),
`migrations/` (Alembic), `deploy/tor/`, `docs/AUDIT.md`, `tests/` (pytest, `tests/e2e`,
`tests/js`).

## Required follow-ups (tests enforce several)

- **After editing any frontend JS/CSS:** `python -m app.integrity write` to refresh Subresource
  Integrity hashes, or a test fails.
- **Model changes:** `alembic revision --autogenerate -m "..."`, review the generated file.
- **Dependencies:** edit `requirements.txt`, then
  `uv pip compile requirements.txt --generate-hashes -o requirements.lock`.
- **Version:** `app/version.py` and the CLI must match (test-enforced); add a `CHANGELOG.md`
  entry, tag `vX.Y.Z`; record `python -m app.integrity digest` at release.

## Security invariants (don't regress)

- The server must never see file keys or passphrases. Link secrets live only in the URL
  `#fragment`; passphrase mode sends only an HKDF-derived token (server stores `SHA-256(token)`).
- The byte-level format (PBKDF2 600k / HKDF split / 1 MiB STREAM segments with index in the IV and a
  final-segment flag) is documented at the top of `frontend/static/js/crypto.js`. The CLI must
  stay byte-compatible; the interop test checks it. Format changes are a MAJOR version.
- No third-party scripts, fonts or trackers (it must work as an onion service); strict CSP.
- Frontend: no unsanitized DOM sinks (eslint `no-unsanitized` enforces this).
- Sessions: HttpOnly `SameSite=Strict` cookie + CSRF header for state-changing requests.
- Never copy the live `.db` for backups; use `sqlite3 .backup` (WAL mode).

## Look (Låda Glass)

`design=family`: every page loads `static/vendor/lada-glass/<version>/lada-glass.css` and
`static/css/lada.css` after `app.css`. `lada.css` points Ratatosk's variables (`--paper`, `--surface`,
`--text`, `--accent`, …) at the Låda tokens (slate-steel accent); the Bootstrap bridge isn't used,
because Ratatosk has its own `.btn`/`.card`/`.navbar` classes. An admin custom theme (theme.js,
`data-custom-theme`) still wins. After changing CSS or JS run `python -m app.integrity write`.

## App standards

This repo follows the app standards in `~/Desktop/code/tools/standards/STANDARDS.md` (rule IDs,
severities; decisions and waivers in `.claude-standards`). `claude-check --repo .` checks it.
