# Changelog

All notable changes to Ratatosk are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/): **MAJOR** for incompatible changes
(file format, API, configuration), **MINOR** for new features, **PATCH** for
fixes. The version lives in `app/version.py` (and `cli/ratatosk.py`); it is
shown on the About page, in the footer, by `GET /api/health`, and by
`ratatosk --version`.

Finding IDs (e.g. SEC-001) refer to the engineering audit in `docs/AUDIT.md`.

## [Unreleased]

## [2.2.0] - 2026-11-11

**Release digest:** `8dbb3f12dad1e373c2500f26604a9b7abfc02ba008da3d81b70d8aebc665c3e3`

### Changed
- Låda Glass 2.0 look (2.0.0, vendored in `frontend/static/vendor/lada-glass/2.0.0/`, replacing
  1.1.1): rounder corners (cards 12 px, controls 9 px), cards and dialogs with the 2.0 glass surface
  (faint gradient, 1 px glass edge, top light, layered shadow, clean padding-box corners) and a lit
  primary button. An admin custom theme still overrides it.
- Låda Glass family look: frosted-glass cards and navbar on the Låda backdrop, Låda colours, type
  and radii with the slate-steel accent, in both themes (same `data-theme` toggle and system
  setting). An admin custom theme still overrides it.

### Fixed
- Phones: the navbar wraps instead of clipping its links, and the toolbars on the admin Users,
  Audit and Files pages wrap instead of making the page scroll sideways.

### Security
- Development tooling only: force minimatch 11 under ESLint, fixing a
  medium-severity denial-of-service advisory. ESLint lints the same files with
  the same results.

## [2.1.1] - 2026-11-01

**Release digest:** `439bae11c5ccc087b57ff71e8088224470c581ea37847f4d9391410d71748228`

### Fixed
- The "Share with specific users" panel no longer shows an empty list box
  when nobody has opted into the directory; the list appears once someone is
  listed or added by exact username.
- A decrypted text message is now labelled "Message", and the leftover
  "Decrypt & Download" button is hidden.

### Added
- Screenshots in the README, regenerated with `python docs/screenshots/capture.py`.

## [2.1.0] - 2026-11-01

**Release digest:** `60dc8b367246c969c5109aab448f104de305fe4e0b462f9682bfe1dee1bd177a`
Verify a server runs this exact release with
`python cli/ratatosk.py verify https://your-server --expect 60dc8b367246c969c5109aab448f104de305fe4e0b462f9682bfe1dee1bd177a`.

### Added
- **Request links** (FEAT-001): "send me files" links anyone can use without an
  account. Files are encrypted in the sender's browser to the owner's public
  key, and the link carries the key's fingerprint, so the sender's browser
  refuses to encrypt if the server substitutes a different key. The owner's
  inbox is at `/requests`.
- **End-to-end encryption keys and sharing** (FEAT-002): each account can have
  an ECDH P-256 keypair, protected by an encryption passphrase that never
  leaves the browser. Shares to recipients with keys are wrapped to their
  public key (ECDH-ES), so the server can't open them. A server-held key is
  used only for recipients without keys, if the new "allow server-held share
  keys" setting is on (the default, for compatibility).
- **Single sign-on** (FEAT-010): OpenID Connect authorization-code flow with
  PKCE, state and nonce; ID-token signature, issuer, audience and expiry
  checks; optional admin-group mapping (never demotes the last admin);
  opt-in linking by verified email. Configured with `RATATOSK_OIDC_*`.
- **Verifiable frontend** (FEAT-012): Subresource Integrity on every script and
  stylesheet, `GET /api/integrity` (per-file hashes plus a release digest), and
  `ratatosk verify <url> --expect <digest>` to check a live server from your
  own machine. `python -m app.integrity write|check|digest`.

### Security
- Browser sessions moved from `localStorage` to an HttpOnly, `SameSite=Strict`
  cookie; state-changing cookie-authenticated requests need a CSRF header
  (SEC-017). Bearer tokens still work for API clients.

### Fixed
- Upgrading a pre-Alembic (1.x) database would have failed as soon as a schema
  revision beyond the baseline existed. It's now brought to the current schema
  and stamped at head, with data migrations applied explicitly.

### Changed
- The chunked upload engine is a shared module (`upload-engine.js`), used by
  both the upload page and request links.
- README: how to back up a live database safely (WAL mode).

## [2.0.0] - 2026-11-01

The project is renamed from **SecureDrop** to **Ratatosk** (COMP-007): the old
name is a trademark of the Freedom of the Press Foundation's whistleblower
platform, which users could mistake this project for.

### Security
- **The server never receives passphrases any more (SEC-001).** Previously the
  browser sent the passphrase itself at upload and with every download, which
  let anyone with access to the server decrypt passphrase-protected files. The
  key is now split with HKDF into the encryption key and an independent
  download token; the server only stores a hash of the token.
- Downloads require proof of holding the key (SEC-006): knowing a file's id is
  no longer enough to download it, use up its download limit, burn it, or
  lock it.
- Zero-log mode no longer records the uploader's identity - the condition was
  inverted, so it was the *only* mode that did (SEC-002). Files no longer store
  the uploader's account or cookie id at all (SEC-003).
- Brute-force limits hold under parallel requests (SEC-005): attempts are
  reserved atomically before any password check. Wrong-passphrase lockouts are
  temporary and the owner can lift them; login lockouts are per network, so an
  attacker can't lock the real user or an admin out (SEC-012).
- Upload chunks stream to disk with a hard size bound - one request could
  previously grow server memory by ~800 MiB (SEC-004).
- Registration follows the same policy as login: enforced two-factor and
  "user login disabled" can't be bypassed by registering (SEC-007).
- Metadata stripping is lossless and fails closed: JPEG/PNG/WebP are cleaned at
  the container level (no re-encoding, orientation and colour profile kept);
  formats that can't be cleaned (HEIC, video, PDF, Office) are flagged and the
  user must confirm (SEC-008).
- Strict Content-Security-Policy, HSTS (on HTTPS), COOP and Permissions-Policy
  headers; all inline scripts moved to files (SEC-009).
- The storage location is environment-only, and a factory reset only deletes
  blobs the database knows about (SEC-010).
- Per-network rate limiting for logins, registration, password resets,
  anonymous uploads and passphrase checks; storage-capacity checks count
  uploads in progress; server-wide cap on active uploads (SEC-011).
- Dependencies upgraded: Starlette 1.10 (CVE-2025-62727), python-jose replaced
  by PyJWT (CVE-2024-33663/33664), python-multipart 0.0.33 (several 2026
  advisories), cryptography 50 (SEC-013). `pip-audit` reports no known
  vulnerabilities.
- TOTP codes are single-use (SEC-014); turning two-factor off needs a current
  code and is refused where it's mandatory (SEC-019).
- Logout revokes the session on the server (SEC-017).
- Audit-log pruning is bounded and always recorded (SEC-015); typed usernames,
  email addresses and SMTP error text are no longer logged (SEC-016).
- Server-held keys for user-to-user shares are released as soon as no share
  needs them (SEC-018).
- The sharing directory is opt-in; others can still share with you by exact
  username (SEC-020).

### Fixed
- Burn-after-download and download limits are exactly-once under concurrency;
  concurrent streams are no longer cut off mid-file (BUG-001).
- Admin settings changes reach every server process within a second (BUG-002).
- The last active admin can't delete, demote or deactivate themselves (BUG-003).
- Numeric settings are validated (a chunk size of 0 used to hang uploads) (BUG-004).
- Expired files are deleted from S3, not just from local disk (BUG-005).
- A file exactly at the size limit is accepted once encrypted (BUG-006).
- Identity columns are wide enough for non-SQLite databases (BUG-007).
- Retried chunk uploads no longer corrupt files (BUG-008); concurrent
  `/complete` calls no longer error (BUG-009).
- Expired files no longer hand out share keys (BUG-010).
- The audit-log retention setting is now actually applied (BUG-011).

### Added
- About page with version, how it works, trust model and license.
- Encrypted text messages, shown in the recipient's browser (FEAT-006).
- Several files behind one link (FEAT-003).
- Resumable uploads after a dropped connection or a reload; Cancel button;
  automatic chunk retries (FEAT-004, UI-002).
- Large downloads stream straight to disk (FEAT-005, PERF-005).
- Link management for owners: switch a link off/on, expire it now, lower its
  limit, unlock it (FEAT-007).
- Tor support: `Onion-Location` header and a docker-compose `tor` profile
  (FEAT-009, `docs/TOR.md`).
- `ratatosk` CLI with `upload` (including `--stdin`) and `download` commands,
  `--json` output and `--version` (FEAT-011). `securedrop_upload.py` still
  works as an alias.
- Download progress, confirmation before a file is destroyed, and pre-checking
  the key/passphrase before anything is consumed (UI-001, UI-003).
- Out-of-band unlock: `python -m app.unlock <username>`.

### Changed
- New encrypted file format (flags 0x05/0x06). Files uploaded with every
  earlier format still decrypt.
- Environment variables are now `RATATOSK_*`; `SECUREDROP_*` still work, with a
  deprecation warning. An existing `securedrop.db` is used automatically.
- Database schema is managed by Alembic (ARCH-002); existing databases are
  upgraded on first start.
- Faster: database-based capacity accounting, SQL-side statistics and cleanup,
  cleanup off the event loop and in one process only, SQLite WAL mode,
  parallel chunk uploads, fewer config requests, compressed static assets
  (PERF-001-PERF-010).
- Hardened Docker image: non-root user, health check, hash-pinned dependencies
  (ARCH-005).

### Removed
- Accepting passphrases from clients (old clients get a clear error asking
  them to update).
- The unused `apscheduler` dependency.

## [1.0.0] - 2026-09-04

First release, as **SecureDrop**.
