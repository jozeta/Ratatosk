# Engineering audit and remediation status

This file has two parts:
1. **Status after Ratatosk 2.1.0.** What happened to every finding, and where its regression test lives.
2. **The original audit** (2026-11-01, made against "SecureDrop" 1.x), unchanged below, so finding IDs stay stable for future reference.

**Status values:**
- **Fixed:** implemented and covered by a test.
- **Fixed (docs):** the remedy is documentation.
- **Partial:** part of the recommendation is implemented; the note says what's left.
- **Deferred:** intentionally left for a later release.

**Test locations:** `tests/test_fixes.py` (fixes), `tests/e2e/` (browser and live concurrency), `tests/js/` (crypto and metadata), `tests/test_s3_backend.py` (S3).

## Corrections to the original audit

- **SEC-013 was understated.** Running `pip-audit` during remediation (which wasn't possible during the audit) showed that python-multipart 0.0.20 had **six** advisories (PYSEC-2026-1852 and PYSEC-2026-3036 to -3040), and that cryptography 44.0.0's advisory (PYSEC-2026-1284, plus PYSEC-2026-2141) was real, not just "potential". All are fixed by the upgrade.
- **New finding, BUG-011.** The "audit log retention (days)" setting was never applied by anything. Fixed: the cleanup worker now prunes by it.

## Status

| ID | Status | Notes / where verified |
|---|---|---|
| BUG-001 | Fixed | Atomic conditional `UPDATE` claims each download; the blob is opened before claiming. `e2e/test_concurrency.py::test_burn_after_download_is_exactly_once` (1 full + 9×404) |
| BUG-002 | Fixed | Versioned settings row, revalidated ≤1 s. `test_settings_change_reaches_a_second_process` |
| BUG-003 | Fixed | `services/users.assert_not_last_admin` on delete, demote and deactivate; self-delete needs the password |
| BUG-004 | Fixed | Bounds on every numeric setting; the client rejects a chunk size ≤ 0 |
| BUG-005 | Fixed | Cleanup deletes through the storage backend. `test_s3_backend.py` |
| BUG-006 | Fixed | The server allows for encryption overhead on the size limit |
| BUG-007 | Fixed | Identity columns widened to 64; values no longer stored (SEC-003) |
| BUG-008 | Fixed | `Upload-Offset` positional writes and an `upload_chunks` table; `/complete` verifies exact tiling |
| BUG-009 | Fixed | `/complete` atomically claims the session |
| BUG-010 | Fixed | The shared-key endpoint uses the active-file filter |
| BUG-011 | Fixed | *(new)* Audit retention applied by the cleanup worker |
| PERF-001 | Fixed | Usage from a DB `SUM` plus in-progress reservations, instead of storage listing |
| PERF-002 | Fixed | SQL-filtered batches, `asyncio.to_thread`, single-runner lease |
| PERF-003 | Fixed | SQL aggregates for stats |
| PERF-004 | Fixed | Shared-with-me in 2 queries |
| PERF-005 | Fixed | Service worker streams large downloads to disk. E2E `test_large_downloads_stream_to_disk_via_service_worker` |
| PERF-006 | Fixed | Progress updates patch one row, throttled with `requestAnimationFrame` |
| PERF-007 | Fixed | Memoised `SDApi.config()` |
| PERF-008 | Fixed | 3 chunks in flight (offset-addressed). Throughput gain not benchmarked |
| PERF-009 | Fixed | SQLite WAL, `synchronous=NORMAL`, `busy_timeout`; batched audit commits on hot paths |
| PERF-010 | Fixed | Compression for static files and pages; API responses excluded (BREACH) |
| SEC-001 | Fixed | HKDF download token; the server never receives passphrases. E2E `test_passphrase_never_reaches_the_server` (network capture) |
| SEC-002 | Fixed | No actor/IP/UA/user in zero-log mode. `test_zero_log_stores_no_identity` |
| SEC-003 | Fixed | `uploader_token` no longer stored; anonymous cookie scoped to the upload API and limited to 6 h |
| SEC-004 | Fixed | Streamed, positionally bounded chunk bodies. `test_oversized_chunk_does_not_balloon_memory` |
| SEC-005 | Fixed | Atomic attempt reservation (files and logins). `test_passphrase_attempts_cannot_be_raced` (5 checked) |
| SEC-006 | Fixed | Token required to download; timed lockout; owner unlock |
| SEC-007 | Fixed | `services/session_policy` shared by login and register. Policy-matrix test |
| SEC-008 | Fixed | Lossless JPEG/PNG/WebP stripping; fail-closed confirmation. `tests/js/exif.test.mjs` plus E2E |
| SEC-009 | Fixed | Strict CSP (`script-src 'self'`), HSTS on HTTPS, COOP, Permissions-Policy; inline scripts removed. E2E asserts zero CSP violations |
| SEC-010 | Fixed | Storage root env-only; factory reset deletes only DB-referenced blobs |
| SEC-011 | Fixed | Per-network in-memory rate limits; reservations counted in capacity; global active-upload cap |
| SEC-012 | Fixed | Login lockout keyed by (account, HMAC of network); `python -m app.unlock`; admin "Unlock login" |
| SEC-013 | Fixed | Starlette 1.10, PyJWT, python-multipart 0.0.33, cryptography 50. `pip-audit`: none |
| SEC-014 | Fixed | TOTP single-use (`mfa_last_step`) |
| SEC-015 | Fixed | Prune bounded (`days ≥ 1`) and always logged |
| SEC-016 | Fixed | No typed usernames or identifiers logged; SMTP errors logged by class only |
| SEC-017 | Fixed | 2.0: server-side revocation. 2.1: sessions in an HttpOnly SameSite=Strict cookie plus CSRF header; no token readable by scripts (e2e `test_session_token_is_not_readable_by_scripts`) |
| SEC-018 | Fixed | Keys released when no share needs them, on every deletion path |
| SEC-019 | Fixed | Turning off MFA needs password and code; refused when mandatory; other sessions revoked |
| SEC-020 | Fixed | Opt-in directory plus rate-limited exact-username lookup |
| SEC-021 | Fixed | Trust model documented (2.0) and made verifiable via FEAT-012 (2.1) |
| ARCH-001 | Fixed | Settings versioning plus cleanup lease. Multi-host is verified with two processes on one SQLite file; PostgreSQL itself is untested |
| ARCH-002 | Fixed | Alembic, baseline plus brand data migration; legacy databases synced and stamped |
| ARCH-003 | Fixed | `services/{users,files,lockout,session_policy}.py`; shared JS `util.js` |
| ARCH-004 | Fixed | Settings schemas generated from the model; PATCH uses explicitly sent fields only |
| ARCH-005 | Fixed | Digest-pinned base, `--require-hashes`, non-root, read-only, health check; `apscheduler` removed. Image built and run |
| ARCH-006 | Fixed | `UTCDateTime` type; manual tz handling removed |
| ARCH-007 | Fixed | `pending_blob_deletions` queue with retries. `test_failed_blob_deletions_are_retried` |
| ARCH-008 | Partial | Inline scripts removed (CSP) and helpers de-duplicated. A full conversion to ES-module imports was deliberately not done: high churn for little benefit now |
| UI-001 | Fixed | Download progress (share, portal, shared-with-me) |
| UI-002 | Fixed | Cancel, automatic chunk retry, resume |
| UI-003 | Fixed | Token pre-check before anything is consumed, plus confirmation for single-use files. E2E `test_wrong_passphrase_does_not_burn_the_file` |
| UI-004 | Fixed | Per-file metadata badges plus confirmation |
| UI-005 | Fixed | Menu button pattern (`aria-expanded`, arrow keys, Escape), labelled theme toggle, keyboard dropzone, progress-bar roles. E2E keyboard check |
| UI-006 | Fixed | `SDUtil.copyText`, with feedback and a manual fallback |
| UI-007 | Fixed | MFA issuer uses the brand name |
| COMP-001…006 | n/a | Research |
| COMP-007 | Fixed | Renamed to Ratatosk (default brand migrated on existing installs) |
| COMP-008 | n/a | Positioning |
| FEAT-001 | Fixed (2.1) | Request links with owner-key fingerprint pinning. `test_e2e_features.py`, e2e `test_request_link_*` |
| FEAT-002 | Fixed (2.1) | Per-user ECDH keypairs, ECDH-ES wrapped shares. `tests/js/keys.test.mjs`, e2e `test_end_to_end_share_between_accounts` |
| FEAT-003 | Fixed | One-link bundles (encrypted manifest) |
| FEAT-004 | Fixed | Resumable uploads (IndexedDB plus `GET /api/uploads/{id}`) |
| FEAT-005 | Fixed | Stream to disk (see PERF-005) |
| FEAT-006 | Fixed | Text sends |
| FEAT-007 | Fixed | Owner link management |
| FEAT-008 | Fixed (docs) | "No server-side scanning" stated in the README and About page |
| FEAT-009 | Fixed | `Onion-Location`, compose `tor` profile, `docs/TOR.md` |
| FEAT-010 | Fixed (2.1) | OIDC code+PKCE flow, no new dependency. `test_oidc.py` (fake IdP, forged-response cases), e2e `test_sso_round_trip_in_a_real_browser` (cross-site) |
| FEAT-011 | Fixed | `ratatosk upload/download`, `--stdin`, `--json`, `--version` |
| FEAT-012 | Fixed (2.1) | SRI on all pages, `/api/integrity`, `ratatosk verify`. `test_integrity.py`, e2e `test_browser_refuses_a_tampered_script` |
| TEST-001 | Fixed | E2E network capture: key, passphrase, filename and plaintext never sent |
| TEST-002 | Fixed | `tests/e2e/test_concurrency.py` |
| TEST-003 | Fixed | Lockout test asserts exactly `max` attempts |
| TEST-004 | Fixed | `tests/e2e/test_browser.py` (Playwright/Chromium) |
| TEST-005 | Fixed | `tests/test_s3_backend.py` (moto) |
| TEST-006 | Fixed | Zero-log privacy test |
| TEST-007 | Fixed | `.github/workflows/ci.yml`: ruff, mypy, bandit, pip-audit, eslint (+no-unsanitized), all tests, Docker smoke |
| TEST-008 | Fixed | Settings bounds plus multi-process propagation |
| TEST-009 | Fixed | Session-policy matrix |

---

# SecureDrop (self-hosted E2EE file sharing): engineering audit

**Date:** 2026-11-01. **Scope:** the whole working tree at `/Users/zeta/Desktop/code/SecureDrop`, including the streaming-encryption and upload-session changes made earlier in this session, which are audited with the same scrutiny as the rest.
**Mode:** assessment only. No project source files were changed for this audit. All reproductions ran against throwaway databases and storage in the scratchpad, never against `securedrop.db`.

Identifiers are stable. Reference them in follow-ups (for example "implement SEC-001").

**Confidence vocabulary:**
- **Reproduced:** demonstrated by running code; the output is in [Verification Results](#verification-results).
- **Code-verified:** established by reading the exact code path, but not executed.
- **Potential:** plausible, with the stated limitation.

---

## Executive Summary

SecureDrop is a carefully written small codebase: about 7.4k lines of FastAPI plus vanilla JS. It has good habits throughout: timing-equalised login, versioned JWTs, CSV-injection guards, consistent `textContent` use in the DOM, and scoped API keys. The test suite passes (34 Python + 14 JS tests).

However, **its headline promise, "the server never sees plaintext, filenames, or keys", is not true for passphrase-protected files.** The browser sends the passphrase itself to the server, both at upload and on every download (**SEC-001, P0**). Since the AES key is derived from that passphrase, any operator, log, TLS-terminating proxy or attacker with server access can decrypt those files.

The other most important findings, all reproduced:

| ID | Finding |
|---|---|
| SEC-002 | **"Zero-log mode" records the uploader's identity, and only when zero-log is on.** The condition is inverted. |
| BUG-001 | **Burn-after-download is not atomic.** 3 of 8 parallel requests passed the single-use check. |
| SEC-005 | **The passphrase lockout can be bypassed by guessing in parallel.** 32 guesses were checked against a limit of 5. |
| SEC-004 | **One request can push server memory up by about 800 MiB.** A 400 MiB body on a 10-byte upload is fully buffered in RAM before being rejected. |
| SEC-007 | **Registration bypasses enforced MFA and the "user login disabled" policy.** |
| SEC-006 | **Anyone who knows only a file's ID (no key) can burn it, exhaust it, or permanently lock it.** |
| BUG-002 | **Admin settings changes don't reach other server processes.** Disabling anonymous uploads left a second process accepting them. |
| BUG-005 | **The cleanup worker never deletes expired files from S3.** It bypasses the storage backend (code-verified). |
| SEC-008 | **Metadata stripping fails open.** HEIC (iPhone), GIF, video and PDF, and any canvas failure, upload the original file with GPS and author data intact. |

**What to do first:** SEC-001 → SEC-002 → BUG-001 together with SEC-005 and SEC-006 (one fix: atomic counters plus a proof-of-key download token) → SEC-004 → SEC-007 → SEC-013 (dependency CVEs) → BUG-002 together with ARCH-001.

---

## Application Architecture

**Purpose and users:** a self-hostable, zero-knowledge file drop. It's for individuals and small organisations who want Firefox-Send-style encrypted links on their own infrastructure, possibly on `.onion`, with an admin policy layer (retention, quotas, anonymity, MFA, audit).

**Stack:**
- **Runtime:** Python 3.11+ with FastAPI 0.115.6 / Starlette 0.41.3, SQLAlchemy 2.0 on SQLite, JWTs via python-jose and bcrypt.
- **Frontend:** vanilla ES2020 in 23 IIFE scripts with no build step. WebCrypto AES-256-GCM.
- **Deployment:** Docker (a single uvicorn worker).

```
Browser                                            FastAPI (single process today)
───────                                            ──────────────────────────────
crypto.js  STREAM-segmented AES-GCM (1 MiB)        upload.py   init → chunk* → complete  (UploadSession rows)
upload.js  encrypt-as-you-upload                   files.py    meta / verify-password / blob (burn, counters)
download-common.js  decrypt-as-you-download        sharing.py  per-recipient server-held key (opt-in)
key in #fragment  OR  passphrase → PBKDF2          auth.py     JWT (tv claim), TOTP, reset tokens, API keys
                                                   admin_*     settings / users / files / stats / audit / reset
                                                   dynamic_settings  in-process cache of 1 DB row  ← per-process!
                                                   cleanup.py  asyncio loop, every N min           ← per-process!
                                                   storage: local disk | S3   (tmp staging always local)
```

**Critical paths:**
1. Upload: `/init` → `PUT /chunk` × n → `/complete`.
2. Download: `/meta` → `/blob` (counter increment, optional burn).
3. Login, optionally through MFA.
4. Admin `PATCH /settings`.

**Most expensive operations:**
- Client-side encryption and decryption, and PBKDF2 at 600k iterations.
- Server-side bcrypt (login and passphrase checks).
- `has_capacity()` storage scans (PERF-001).
- Stats aggregation in Python (PERF-003).

**Likely failure points:** concurrency on counters (BUG-001, SEC-005), multi-process deployment (BUG-002, ARCH-001), the S3 backend (BUG-005), and large files in memory (SEC-004, PERF-005).

**Where the implementation differs from its promises:**
- SEC-001: the server does see passphrases.
- SEC-002: zero-log stores identity.
- SEC-008: metadata stripping fails open.
- BUG-005: "purges expired files regardless of backend" is false for S3.
- BUG-002: "takes effect immediately" holds only for the process that handled the change.

---

## Critical Findings

| Rank | ID | Priority | Title |
|---|---|---|---|
| 1 | SEC-001 | P0 | Passphrase disclosed to the server at upload and on every download |
| 2 | SEC-002 | P1 | Zero-log mode stores the uploader's identity |
| 3 | BUG-001 | P1 | Burn-after-download / max-downloads race (multiple recipients receive the file) |
| 4 | SEC-005 | P1 | Brute-force lockouts bypassable by parallel requests |
| 5 | SEC-006 | P1 | A file ID alone (no key) is enough to burn, exhaust or permanently lock a file |
| 6 | SEC-004 | P1 | Unbounded in-memory request bodies on the chunk endpoint |
| 7 | SEC-007 | P1 | Registration bypasses MFA enforcement and the login-disabled policy |
| 8 | SEC-008 | P1 | EXIF/metadata stripping fails open |
| 9 | SEC-013 | P1 | Known-vulnerable dependencies (Starlette, python-jose) |
| 10 | BUG-002 | P1 | Settings changes don't propagate across processes |
| 11 | BUG-005 | P1 | Expired files never deleted from S3 |

---

## Functional Bug Report

### BUG-001 [P1] Burn-after-download and max-download limits are not atomic

**Category:** Bug (security-relevant). **Confidence:** High (reproduced).

**Affected files:** `app/api/files.py` (`_get_active_file`, `download_blob`, lines 22–29 and 87–145).

**Problem:** The handler reads `download_count` and `burn_after_download`, checks them in Python, then writes `download_count += 1` back. That read-modify-write runs in each request's own session with no lock or conditional update. Parallel requests all pass the check. Separately, the burn path deletes the blob in a background task while other already-admitted streams are still reading it, so those responses are cut off mid-stream.

**Evidence:** In `repro_live.py` [A], 8 parallel GETs of one burn-after-download file produced `['truncated', 'truncated', 'full', '404', '404', '404', '404', '404']`. Three requests were admitted. With a smaller file, all of the admitted ones would likely get complete copies.

**Root cause:** The check-then-act runs on ORM-loaded state instead of an atomic conditional `UPDATE`.

**Impact:**
- A "single-use" link can be consumed several times.
- `max_downloads` can be exceeded.
- Legitimate concurrent downloaders can receive truncated ciphertext, which then fails decryption with a confusing error.

**Recommendation:** Claim a download slot atomically before streaming anything.

**Implementation approach:**
1. Run `UPDATE files SET download_count = download_count + 1, is_deleted = CASE WHEN burn OR (max_downloads > 0 AND download_count + 1 >= max_downloads) THEN 1 ELSE is_deleted END WHERE id = :id AND is_deleted = 0 AND expires_at > :now AND (max_downloads = 0 OR download_count < max_downloads)`.
2. If `rowcount == 0`, return 404.
3. Only the request that flipped `is_deleted` schedules the blob deletion.
4. On local disk, an already-open file descriptor survives an unlink, so open the blob *before* returning the response. That makes the deletion race-free.

**Validation:** TEST-002, a parallel-download test: exactly one 200 with full length, and the rest 404.

**Complexity:** Small. **Dependencies:** none. Pairs with SEC-005 and SEC-006.

### BUG-002 [P1] Admin settings changes only reach the process that handled them

**Category:** Bug / Architecture. **Confidence:** High (reproduced).

**Affected files:** `app/core/dynamic_settings.py` (`_cache`, `get_settings`, `update_settings`).

**Problem:** Settings are cached per process. `update_settings` refreshes only the local cache, and nothing ever invalidates the cache in other processes.

**Evidence:** Two uvicorn processes ran on one database. The admin disabled anonymous uploads through process A. Process A then returned 403 and process B still returned **200**, including 2 seconds later. Note that an earlier test with `--workers 2` on macOS appeared fine only because macOS sent every connection to one worker.

**Root cause:** The process-local cache has no versioning or expiry (see ARCH-001).

**Impact:** Under `--workers N`, several containers or a rolling deploy, every policy toggle applies randomly. That includes anonymous upload/download, MFA enforcement, zero-log, size limits and extension rules: a security policy you can't rely on. The README promises immediate effect. The UploadSession work earlier in this session made multi-worker deployment *look* supported; this finding shows it isn't yet.

**Recommendation:** Version the settings row and revalidate cheaply.

**Implementation approach:**
1. Add an integer `settings.version`, bumped by `update_settings`.
2. In `get_settings()`, re-read the version (one indexed primary-key `SELECT`) at most every N ms, for example 1 s, and reload when it changes.
3. Alternatively, apply a short TTL cache.

**Validation:** A two-process test (TEST-008): PATCH through A, then assert B enforces the change within the TTL.

**Complexity:** Small. **Dependencies:** ARCH-001.

### BUG-003 [P2] The only admin can delete their own account, leaving no admins

**Category:** Bug. **Confidence:** High (reproduced: `DELETE /api/auth/me` → 200, 0 admins left).

**Affected files:** `app/api/auth.py` (`delete_own_account`).

**Problem:** The admin delete endpoint forbids self-deletion. The self-service endpoint has no guard at all, and also requires no password re-confirmation.

**Root cause:** The two deletion paths enforce different invariants (see ARCH-003).

**Impact:** The instance becomes unmanageable until someone with shell access runs `init_db`. A stolen session can delete the account without knowing the password.

**Recommendation:** Refuse the deletion if the caller is the last active admin, and require the current password.

**Implementation approach:** Add a shared `assert_not_last_admin(db, user)` used by every deletion, demotion and deactivation path. Add `password` to the request body.

**Validation:** Unit test: the sole admin gets 400, and the deletion succeeds when a second admin exists.

**Complexity:** Small. **Dependencies:** ARCH-003.

### BUG-004 [P2] Numeric settings accept nonsense values (one causes an endless client upload loop)

**Category:** Bug. **Confidence:** High (reproduced: `PATCH {"chunk_size_mb":0,"max_login_attempts":0,"max_concurrent_uploads":-1,"cleanup_interval_minutes":0,"max_file_size_mb":-5}` → 200).

**Affected files:** `app/schemas/settings.py` (`SystemSettingsUpdate`, lines 125–149), `frontend/static/js/upload.js` (`streamUpload`).

**Problem:** None of these numeric fields have bounds.
- `chunk_size_mb = 0` makes `streamUpload` loop forever sending empty PUTs (`take = 0`). The original `uploadInChunks` looped forever too.
- `max_login_attempts = 0` locks every account and file on the first failed attempt.
- A negative maximum size rejects every upload.

**Root cause:** The schema is missing `Field(ge=…, le=…)` constraints.

**Impact:** One admin typo can effectively take the service down, and the client-side loop also burns the uploader's CPU and network.

**Recommendation:** Bound every numeric field. For example: `chunk_size_mb` 1–64, `max_file_size_mb` ≥ 1, `max_concurrent_uploads` 1–100, `cleanup_interval_minutes` ≥ 1, `max_login_attempts` 1–100. Also make the client treat `chunk_size_bytes <= 0` as a fatal error.

**Validation:** Parametrised test: out-of-range values return 422.

**Complexity:** Small. **Dependencies:** none.

### BUG-005 [P1] The cleanup worker never deletes expired files on the S3 backend

**Category:** Bug (data-retention promise). **Confidence:** High (code-verified; S3 itself not exercised).

**Affected files:** `app/core/cleanup.py` (`_delete_blob`, `run_cleanup_once`).

**Problem:** `_delete_blob` calls `os.remove(os.path.join(cfg["storage_path"], name))` instead of `storage_service.delete_blob(name)`. On S3 that local path doesn't exist, so the call does nothing, yet the row is still marked deleted and an audit event is logged.

**Root cause:** The cleanup code predates the storage-backend abstraction and wasn't migrated to it.

**Impact:**
- Expired ciphertext stays in the bucket forever, which contradicts the README: "a background asyncio task purges expired files regardless of backend".
- Storage costs grow without bound.
- `usage_bytes()` (a full bucket listing) keeps counting the dead objects, so the 95% cap is eventually hit permanently.

**Recommendation:** Route deletion through the backend, and retry failed deletions (see ARCH-007).

**Validation:** TEST-005: an S3 backend test with moto or MinIO in which expired objects are gone after `run_cleanup_once()`.

**Complexity:** Small. **Dependencies:** none.

### BUG-006 [P3] A file exactly at the advertised size limit is rejected

**Category:** Bug. **Confidence:** High (reproduced: a 1 MiB file is 1,048,690 ciphertext bytes, and `/init` returns 413 with `max_file_size_mb=1`).

**Affected files:** `frontend/static/js/upload.js` (size precheck against `file.size`), `app/api/upload.py` (`init_upload`, which compares the ciphertext size).

**Problem:** The client checks the plaintext size. The server checks the ciphertext size, which adds the header, the metadata envelope and 16 bytes per MiB. The "Max file size: X MB" hint is therefore slightly wrong.

**Impact:** A confusing "exceeds max size" error for files at or just under the limit.

**Recommendation:** Have the server allow the cryptographic overhead (limit × (1 + 16/2²⁰) + 4 KiB), or have the client check `encryptor.size`.

**Validation:** Boundary test at exactly the limit.

**Complexity:** Small. **Dependencies:** none.

### BUG-007 [P3] Identity columns are shorter than the values stored in them

**Category:** Bug (portability). **Confidence:** High (code-verified).

**Affected files:** `app/models/file.py` (`uploader_token String(36)`), `app/models/audit_log.py` (`actor_token String(36)`).

**Problem:** These columns store values like `"user:" + uuid4`, which is 41 characters. SQLite ignores `VARCHAR` lengths, but PostgreSQL and MySQL would reject or truncate the value.

**Impact:** It blocks migrating off SQLite, which you'll eventually need for multi-node deployments (ARCH-001).

**Recommendation:** Widen the columns to 64 characters, or better, stop storing these values at all (SEC-003).

**Validation:** Run the test suite against PostgreSQL in CI.

**Complexity:** Small. **Dependencies:** ARCH-002.

### BUG-008 [P2] Chunk upload isn't idempotent: a retried PUT silently corrupts the file

**Category:** Bug. **Confidence:** Medium (code-verified; a proxy retry wasn't reproduced).

**Affected files:** `app/api/upload.py` (`upload_chunk`).

**Problem:**
- Chunks are appended with no offset. A PUT replayed by a client, an HTTP library or a proxy is appended twice. HTTP treats PUT as idempotent, so intermediaries are allowed to retry it.
- The byte counter is incremented *before* the disk write, so a failed write leaves the counter ahead of the file.

**Impact:** The corrupt ciphertext is only discovered when the recipient's decryption fails ("file is corrupted"), long after the uploader has left.

**Recommendation:** Make chunks offset-addressed.

**Implementation approach:**
1. The client sends `Upload-Offset` or `Content-Range` with each chunk.
2. The server accepts the chunk only when `offset == bytes_written`, and returns 409 with the current offset otherwise (the tus.io semantics).
3. Write the data first, then advance `bytes_written` with a conditional `UPDATE ... WHERE bytes_written = :offset`.

This also enables FEAT-004 (resume) and PERF-008.

**Validation:** Replaying the same chunk is a no-op, and a gap returns 409.

**Complexity:** Medium. **Dependencies:** none.

### BUG-009 [P3] Two concurrent `/complete` calls on one upload session can return 500

**Category:** Bug. **Confidence:** Medium (code-verified).

**Affected files:** `app/api/upload.py` (`complete_upload`).

**Problem:** Both calls pass the `os.path.exists(tmp_path)` check. The second one's `os.replace` (local) or `upload_file` (S3) then raises an exception, which surfaces as a 500. This is in code written earlier in this session.

**Impact:** A double-click or client retry produces an error even though the first call succeeded.

**Recommendation:** Atomically claim the session first (`DELETE FROM upload_sessions WHERE id=:id AND actor=:actor`, then check rowcount), and only then finalize the file.

**Validation:** Parallel `/complete` test: one 200 and one 404.

**Complexity:** Small. **Dependencies:** none.

### BUG-010 [P3] The shared-key endpoint and the share list ignore expiry

**Category:** Bug. **Confidence:** High (code-verified).

**Affected files:** `app/api/sharing.py` (`get_shared_key`).

**Problem:** `get_shared_key` checks `is_deleted` but not `expires_at`. Between expiry and the next cleanup pass, the server still returns decryption keys for expired files.

**Impact:** Minor. The blob itself is refused (`_get_active_file`), but the key outlives the file's stated lifetime.

**Recommendation:** Reuse `_get_active_file` semantics. Also clear `shared_decryption_key` when a file expires, is burned or is deleted (SEC-018).

**Validation:** An expired file returns 404 from `/shared-key`.

**Complexity:** Small. **Dependencies:** none.

*Hypothesis refuted during the audit and not reported as a bug:*
- `revoke_share`'s `remaining <= 1` logic is correct, because `SessionLocal` uses `autoflush=False`.
- "An exhausted shared file still listed" was not reproduced: exhausting the download limit burns the file.

---

## Performance Report

No load tests or Core Web Vitals were measured; the tools weren't available and installs weren't allowed. The figures below come from code analysis plus the one measured case (SEC-004).

### PERF-001 [P2] The storage-capacity check scans all storage on every upload

**Category:** Performance. **Confidence:** High (code-verified).

**Affected files:** `app/services/storage_service.py` (`has_capacity`), `local.py` / `s3.py` (`usage_bytes`).

**Problem:** Every `/init` calls `usage_bytes()`.
- **Local disk:** `os.scandir` plus a `stat` call on every blob, which is O(files).
- **S3:** a full paginated `ListObjectsV2` of the bucket, roughly one request per 1,000 objects, plus network round-trips.

The stats page does the same.

**Root cause:** No usage counter is kept anywhere.

**Impact:** Upload-start latency grows linearly with the number of stored files, and S3 request costs grow with it.

**Recommendation:** Use `SELECT SUM(size_bytes) FROM files WHERE is_deleted=0`, plus the declared size of active upload sessions (which also fixes the overcommit in SEC-011). Keep backend listing as an occasional reconciliation job.

**Expected benefit:** O(1) per upload with an index or covering aggregate. Milliseconds instead of seconds on S3.

**Trade-offs:** The database total can drift from actual storage if a blob deletion fails. Reconcile periodically (ARCH-007).

**Validation:** Seed 50k rows and time `/init` before and after.

**Complexity:** Small. **Dependencies:** BUG-005.

### PERF-002 [P2] The cleanup pass loads every file into Python and blocks the event loop

**Category:** Performance. **Confidence:** High (code-verified).

**Affected files:** `app/core/cleanup.py` (`run_cleanup_once`, `_loop`).

**Problem:**
- The pass runs `query(FileObject).filter(is_deleted==False).all()` and then filters in Python.
- It's called *synchronously* inside the `async _loop`, so every request on that worker stalls while it runs, including disk or S3 deletions.
- Every worker runs its own copy of the loop (ARCH-001).

**Recommendation:**
1. Filter in SQL: `expires_at <= now OR (max_downloads>0 AND download_count>=max_downloads)`.
2. Process in batches.
3. Run the pass with `await asyncio.to_thread(run_cleanup_once)`.
4. Run it in only one process, using a lease row.

**Expected benefit:** No request-latency spikes every N minutes. Work proportional to the number of expired files rather than all files.

**Validation:** Measure p99 latency during a cleanup pass with 10k expiring rows.

**Complexity:** Small. **Dependencies:** ARCH-001.

### PERF-003 [P3] The admin stats endpoint loads every active row to count and sum

**Category:** Performance. **Confidence:** High (code-verified).

**Affected files:** `app/api/admin_files.py` (`get_stats`).

**Problem:** It counts, sums and groups by extension in Python over all active rows, and also triggers a full storage scan (PERF-001).

**Recommendation:** Use `COUNT`, `SUM` and `GROUP BY extension ... ORDER BY count DESC LIMIT 8` in SQL.

**Expected benefit:** O(1) memory use. Faster dashboards on large instances.

**Validation:** Time the endpoint with 100k rows seeded.

**Complexity:** Small. **Dependencies:** PERF-001.

### PERF-004 [P3] "Shared with me" makes four queries per share (N+1)

**Category:** Performance. **Confidence:** High (code-verified).

**Affected files:** `app/api/sharing.py` (`list_shared_with_me`).

**Problem:** For each share it runs `db.get(File)`, `db.get(owner)`, `query(all_shares)` and `query(recipients)`.

**Recommendation:** Use two joined queries: shares joined to files joined to owners, then all recipients for those file IDs grouped in Python.

**Expected benefit:** 4N+1 queries → 2.

**Validation:** Count queries with an SQLAlchemy event listener in a test.

**Complexity:** Small. **Dependencies:** none.

### PERF-005 [P2] Downloads still collect the whole decrypted file in browser memory

**Category:** Performance. **Confidence:** High (code-verified; this session's streaming work removed the 3–4 extra copies but not this).

**Affected files:** `frontend/static/js/crypto.js` (`EnvelopeReader.finish`), `download-common.js` (`saveDecrypted`).

**Problem:** Decryption streams, but the plaintext segments are accumulated into one `Blob` before the browser saves it. Multi-GB files can exhaust tab memory, especially on mobile.

**Recommendation:** Stream straight to disk.
1. Use `showSaveFilePicker()` with `createWritable()` where it's available (Chromium).
2. Otherwise, use a service worker that serves a `ReadableStream` as a download (the StreamSaver pattern).
3. Fall back to the in-memory Blob.

Wormhole.app streams its decryption (COMP-003).

**Expected benefit:** Flat memory use regardless of file size.

**Trade-offs:** The service-worker path adds complexity, and Safari support varies.

**Validation:** Download a 4 GB file while watching tab memory in DevTools' Performance monitor.

**Complexity:** Medium. **Dependencies:** none.

### PERF-006 [P3] Batch uploads rebuild the entire queue DOM on every progress update

**Category:** Performance. **Confidence:** High (code-verified).

**Affected files:** `frontend/static/js/upload.js` (`renderQueue` called from the progress callback).

**Problem:** Each progress update (once per chunk, per file) rebuilds every row, which is O(n) per update and O(n²) over a batch.

**Recommendation:** Keep a map from item to row element, update only that row's progress, and throttle updates with `requestAnimationFrame`.

**Expected benefit:** A responsive UI (better INP) for 100+ file batches.

**Validation:** Record a 500-file folder upload in the DevTools Performance panel.

**Complexity:** Small. **Dependencies:** none.

### PERF-007 [P3] `/api/config` is fetched two or three times per page load

**Category:** Performance. **Confidence:** High (code-verified).

**Affected files:** `layout.js`, `upload.js`, `download-common.js`, `account.js`, `shared-with-me.js`, `password-strength.js`, `admin-users.js`.

**Problem:** Each script fetches the config independently.

**Recommendation:** Add a memoised `SDApi.config()` that returns one shared promise.

**Expected benefit:** One fewer round-trip per page. That's noticeable over Tor, where round-trips take seconds.

**Validation:** Count requests in the Network panel.

**Complexity:** Small. **Dependencies:** none.

### PERF-008 [P3] Chunks upload strictly one at a time

**Category:** Performance. **Confidence:** Medium (potential; throughput not measured).

**Affected files:** `upload.js` (`streamUpload`).

**Problem:** Only one PUT is in flight at a time. On high-latency links (Tor, intercontinental), throughput is capped at roughly chunk_size ÷ RTT.

**Recommendation:** Once chunks are offset-addressed (BUG-008), allow 2–4 chunks in flight, with a bounded queue so memory stays flat.

**Expected benefit:** About 2–3× throughput on high-RTT links (to be measured).

**Validation:** Measure upload time with `tc netem` or a Tor-like 500 ms RTT.

**Complexity:** Medium. **Dependencies:** BUG-008.

### PERF-009 [P2] SQLite runs with default journaling, and every audit event is its own commit

**Category:** Performance / Reliability. **Confidence:** Medium (potential; not load-tested).

**Affected files:** `app/core/database.py`, `app/services/audit_service.py` (`log_event` commits per event).

**Problem:**
- The default rollback journal has no `busy_timeout`, so concurrent writers can hit `database is locked`.
- A single download performs 2–4 separate commits (counter, DOWNLOAD event, burn, FILE_BURNED event), each with its own fsync.

**Recommendation:**
1. On connect, set `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout=5000`.
2. Let `log_event` add to the caller's transaction instead of committing on its own.

**Expected benefit:** Fewer fsyncs per request. No lock errors under parallel load.

**Validation:** Load-test parallel downloads with `hey` or `wrk` before and after.

**Complexity:** Small. **Dependencies:** none.

### PERF-010 [P3] Static assets are served uncompressed

**Category:** Performance. **Confidence:** High (code-verified: no GZip middleware; about 200 KB of JS and CSS, unminified).

**Affected files:** `app/main.py`.

**Problem:** Everything is sent uncompressed. The `no-cache` setting is fine because ETags make revalidation cheap.

**Recommendation:** Add Starlette's `GZipMiddleware` for text types, or document proxy compression.
- **Don't** compress `/api/files/*/blob`: it's already-encrypted, incompressible data.
- Preferably, also avoid compressing responses that mix secrets with attacker-controlled input (the BREACH attack).

**Expected benefit:** About 70% fewer bytes on first load, improving LCP on slow links.

**Validation:** Compare transfer sizes in the Network panel.

**Complexity:** Small. **Dependencies:** none.

---

## Security Report

**Threat model assumed:** a malicious or compelled server operator, plus anonymous internet attackers. The product's own README sets that bar.

### SEC-001 [P0] Passphrase-mode files: the passphrase is sent to the server

**Category:** Security. **Severity:** High. **Confidence:** High (code-verified).

**Classification:** CWE-201 (sensitive information in sent data), CWE-522. OWASP A02:2021 Cryptographic Failures.

**Affected files:**
- `frontend/static/js/upload.js` (`encryptAndUploadOne`: `password: password` in the `/complete` body).
- `frontend/static/js/download-common.js` (`X-Secondary-Password` header on every `/blob` request).
- `frontend/static/js/share.js`.
- `app/api/upload.py` (`hash_password(payload.password)`).
- `app/api/files.py` (`verify_password(supplied, ...)`).

**Problem:** In passphrase mode, the AES key is `PBKDF2(passphrase)`. The browser sends **the passphrase itself** to the server at upload and with every download attempt. The server, its access logs, a TLS-terminating reverse proxy or CDN, any APM tool, or an attacker with code execution on the server can capture it and decrypt the file.

This directly contradicts `crypto.js` ("it never learns the passphrase itself") and the README's promise that the server never sees decryption keys.

**Attack scenario:** The operator, or anyone who compromises the server, adds one log line to `download_blob` and gets the passphrase of every protected file the next time it's downloaded.

**Impact:** Zero-knowledge is lost for the very mode users pick when they want *extra* protection.

**Mitigation:** Send a derived verifier, never the passphrase. This is the same approach Send uses (COMP-001).
1. **Client:** `authToken = HKDF(PBKDF2(passphrase, salt, 600k), info="sd-auth-v1")`. Derive this separately from the encryption key (`info="sd-enc-v1"`), so knowing the token reveals nothing about the key.
2. **Server:** store `bcrypt(authToken)`. Downloads send the token in a header.
3. **Old files:** existing passphrase files keep their current check (add a `verifier_version` column). New uploads use the verifier.
4. Fix the README and code comments to match.

**Verification:** TEST-001 inspects every request body and header produced by the upload and download flows and asserts the passphrase never appears.

**Complexity:** Medium. **Dependencies:** none. Unlocks SEC-006.

### SEC-002 [P1] Zero-log mode records the uploader's identity (the condition is inverted)

**Category:** Security / Privacy. **Severity:** High. **Confidence:** High (reproduced: zero-log ON → `actor_token='user:a193…'`; zero-log OFF → `None`).

**Classification:** CWE-359 (exposure of private personal information).

**Affected files:** `app/api/upload.py` (`complete_upload`: `actor_token=actor if zero_log else None`).

**Problem:** The setting that promises to store "no IP/UA/user link" is the *only* condition under which the uploader's account ID or anonymous-cookie ID is written to the audit log. `log_event` nulls `user_id`, but this column bypasses that protection.

**Attack scenario:** An instance advertised as "zero-log" is seized. The audit table maps every upload to an account, or links all uploads from one anonymous browser over the cookie's 30-day lifetime.

**Mitigation:** Never store `actor_token` in zero-log mode. Audit the other `log_event` call sites the same way (SEC-016).

**Verification:** TEST-006.

**Complexity:** Small. **Dependencies:** none.

### SEC-003 [P2] `files.uploader_token` permanently links a browser's anonymous uploads

**Category:** Security / Privacy. **Severity:** Medium. **Confidence:** High (code-verified).

**Classification:** CWE-359.

**Affected files:** `app/api/upload.py` (`uploader_token=actor`), `app/models/file.py`.

**Problem:** Every file row keeps `anon:<cookie>` or `user:<id>` regardless of privacy settings. The anonymous cookie lives 30 days, so all anonymous uploads from one browser stay linkable to each other until the files are hard-deleted. Nothing reads this column except the record itself.

**Mitigation:**
- Stop storing it, or store an HMAC under a key that rotates daily.
- Scope the anonymous cookie to `/api/uploads` with a lifetime of hours, since it's only needed to tie one upload session together.

**Verification:** Inspect the database after anonymous uploads: no stable identifier is present.

**Complexity:** Small. **Dependencies:** SEC-002.

### SEC-004 [P1] The chunk endpoint buffers unbounded request bodies in memory

**Category:** Security (DoS). **Severity:** High. **Confidence:** High (reproduced: a 400 MiB body sent to a 10-byte upload session took server RSS from 116 MiB to 926 MiB before the 413).

**Classification:** CWE-770 (allocation without limits), CWE-400.

**Affected files:** `app/api/upload.py` (`upload_chunk`: `await request.body()` before any size check).

**Problem:** The size limit is enforced only *after* the entire body is in RAM. If anonymous uploads are enabled (the default), anyone can create an upload session and then send a few parallel multi-GB PUTs to exhaust the server's memory and get it OOM-killed. This existed before this session's changes and is still present.

**Mitigation:**
1. Reject early on `Content-Length > remaining allowance`.
2. Otherwise, stream `request.stream()` to the `.part` file with a running counter and abort once the allowance is exceeded.
3. Document `client_max_body_size` (or the equivalent) for reverse proxies.

**Verification:** Rerun `repro_live.py` [C]: memory should stay flat and the 413 should arrive immediately.

**Complexity:** Small. **Dependencies:** pairs with BUG-008.

### SEC-005 [P1] Brute-force lockouts can be bypassed with parallel requests

**Category:** Security. **Severity:** Medium-High. **Confidence:** High (reproduced: 32 parallel wrong passphrases with a limit of 5 → 32 were checked and 0 locked).

**Classification:** CWE-307, CWE-367 (TOCTOU race).

**Affected files:**
- `app/api/files.py` (`verify_file_password`, `download_blob`).
- `app/api/auth.py` (`login`, `_register_login_failure`: the same pattern on `failed_login_attempts`).

**Problem:** The counter is read, bcrypt runs (about 250 ms), and then the counter is written back with a read-modify-write. Every request in flight during that bcrypt window gets a free guess.

**Attack scenario:** Online guessing at roughly (parallelism × the limit) per lockout window instead of the configured limit. That matters most for weak passphrases and account passwords.

**Mitigation:**
1. *Reserve* an attempt atomically before verifying: `UPDATE ... SET failed_attempts = failed_attempts + 1 WHERE id=:id AND failed_attempts < :max AND NOT locked`.
2. If `rowcount == 0`, return 423.
3. After a successful verify, reset the counter.

**Verification:** TEST-002: the parallel-guess test admits at most `max` attempts.

**Complexity:** Small. **Dependencies:** none.

### SEC-006 [P1] A file ID alone, with no key, is enough to burn, exhaust or permanently lock a file

**Category:** Security (integrity/availability). **Severity:** Medium. **Confidence:** High.
- **Reproduced:** a stranger's 10 wrong guesses lock the file permanently, and the owner then gets 423 even with the correct passphrase.
- **Code-verified:** a GET from someone without the key burns the file.

**Classification:** CWE-284, CWE-645 (overly restrictive lockout).

**Affected files:** `app/api/files.py`.

**Problem:**
- `/blob` serves and counts a download for anyone who knows the file ID. The key lives in the URL fragment, but the ID is in the path, so it appears in proxy logs and browser history, and gets shared in previews.
- A partially copied link (with the fragment truncated) burns the file before decryption fails.
- The passphrase lockout is permanent (`locked=True`) with no expiry and no owner unlock.

**Mitigation:**
1. **Proof of key possession,** as Send does with an HMAC auth key (COMP-001): derive `dlToken = HKDF(key, "sd-dl-v1")` at upload, store its SHA-256, and require the token on `/blob`. Without the key there's no download, no counter increment and no burn.
2. Replace the permanent lockout with an exponentially growing temporary one, plus an owner "unlock" action.

**Verification:** Without the token, `/blob` returns 401 and the counter is unchanged. The lock expires.

**Complexity:** Medium. **Dependencies:** SEC-001 (the same derivation machinery).

### SEC-007 [P1] Registration bypasses MFA enforcement and the "user login disabled" policy

**Category:** Security. **Severity:** Medium. **Confidence:** High (reproduced: with `enforce_mfa_users` and `allow_user_login=false`, `/register` returns a working token (`/me` 200, `mfa_enabled=False`), while `/login` for the same user returns 403).

**Classification:** CWE-287, CWE-863.

**Affected files:** `app/api/auth.py` (`register`).

**Problem:** `register` mints a full access token directly and skips the policy checks that run after login.

**Attack scenario:** When registration is open, anyone gets a full session without ever enrolling in the "mandatory" MFA. That session lasts 12 hours, and accounts can be re-registered indefinitely.

**Mitigation:** Move the post-password policy (login allowed? MFA enforced?) into one function and call it from both `/login` and `/register`. Return `MfaSetupRequired` or 403 accordingly.

**Verification:** The policy-matrix test in TEST-009.

**Complexity:** Small. **Dependencies:** ARCH-003.

### SEC-008 [P1] Metadata stripping fails open and silently

**Category:** Security / Privacy. **Severity:** Medium-High. **Confidence:** High (code-verified).

**Classification:** CWE-212 (improper removal of sensitive information).

**Affected files:** `frontend/static/js/exif-strip.js`.

**Problem:** Only JPEG, PNG and WebP are stripped. These are uploaded with their metadata intact:
- HEIC/HEIF, the default iPhone camera format, which carries GPS.
- TIFF and GIF.
- Video (MP4/MOV, which carry GPS).
- PDF and Office documents (author and edit history).

On decode, canvas-size or `toBlob` failure (for example over Safari's canvas limits), the code silently resolves with the **original** file. Separately, JPEG re-encoding at quality 0.95 lossily degrades every photo and drops ICC colour profiles.

**Attack scenario:** An anonymous source uploads an iPhone photo, trusting the "EXIF/GPS stripping" feature, and the photo still contains their home coordinates.

**Mitigation:**
1. Strip JPEG losslessly by removing APP1–APP15 segments, rather than re-encoding.
2. Add HEIC/MP4 container handling, or warn explicitly about formats that can't be stripped.
3. On failure, *fail closed* or ask the user ("metadata could not be removed — upload anyway?").
4. Show the per-file status (UI-004).

**Verification:** A fixture set (HEIC with GPS, a large JPEG, MP4): either verified-stripped output or an explicit warning.

**Complexity:** Medium. **Dependencies:** UI-004.

### SEC-009 [P2] No Content-Security-Policy or HSTS

**Category:** Security. **Severity:** Medium. **Confidence:** High (code-verified: the only CSP in the codebase is on the logo route).

**Classification:** CWE-1021 / OWASP A05 Security Misconfiguration.

**Affected files:** `app/main.py` (`sanitize_headers_middleware`), plus 4 inline `<script>` blocks in `login.html`, `register.html`, `forgot_password.html` and `reset_password.html`.

**Problem:** In a browser-crypto app, any script injection reveals the URL fragment key and the passphrase, and the session JWT sits in `localStorage` (SEC-017). The output-encoding discipline is good today, but there's no defence in depth if it ever slips.

**Mitigation:**
1. Move the 4 inline scripts into files.
2. Send `Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`.
3. Add `Strict-Transport-Security` when the site is served over HTTPS, plus `Cross-Origin-Opener-Policy: same-origin`.

**Verification:** Browser console shows zero CSP violations across all pages (TEST-004).

**Complexity:** Small. **Dependencies:** ARCH-008 (optional).

### SEC-010 [P2] The admin-editable storage path can point anywhere, and a factory reset deletes every file in it

**Category:** Security. **Severity:** Medium. **Confidence:** High (code-verified).

**Classification:** CWE-73 (external control of file path).

**Affected files:** `app/schemas/settings.py` (`storage_path`), `app/services/storage_service.py` (`clear_all_blobs`), `app/core/cleanup.py`.

**Problem:**
- `storage_path` is an unvalidated string set from the web UI.
- A factory reset runs `os.scandir(path)` and then `os.remove` on **every file** in that directory.
- Changing the path also orphans every existing blob (downloads return 404 and usage drops to 0).

**Attack scenario:** A hijacked admin session (an XSS-adjacent attack, phishing, or a token stolen from `localStorage`) sets `storage_path=/app/data` and runs a reset. The database and other host files are deleted.

**Mitigation:**
- Make the storage path environment-only, like the S3 settings, or confine it under a configured root.
- Have the reset delete only blobs referenced in the database, plus `.part` files.

**Verification:** A test that a `storage_path` outside the root is rejected, and that a reset with foreign files present leaves them untouched.

**Complexity:** Small. **Dependencies:** none.

### SEC-011 [P2] Anonymous uploaders can exhaust resources: the concurrency limit is bypassable and storage can be overcommitted

**Category:** Security (DoS). **Severity:** Medium. **Confidence:** High (code-verified).

**Classification:** CWE-770.

**Affected files:** `app/api/upload.py` (`init_upload`), `storage_service.has_capacity`.

**Problem:**
- The concurrency limit is keyed by a cookie, so a client simply discards the cookie and gets unlimited sessions.
- `has_capacity` counts only finished blobs, not sessions still in progress, so N parallel uploads each pass the check and together blow past the cap.
- `/register`, `/login` and `/forgot-password` have no per-client rate limit.

**Mitigation:**
1. Include the declared sizes of active sessions in the capacity check.
2. Add a global cap on active sessions.
3. Add an in-memory, never-persisted token bucket keyed by masked IP (/24 or /48). That's consistent with the privacy model because nothing is written to disk.
4. Optionally offer a proof-of-work challenge for anonymous uploads on `.onion` deployments.

**Verification:** A load script with a fresh client per request is stopped by the limits.

**Complexity:** Medium. **Dependencies:** PERF-001.

### SEC-012 [P2] Anyone can lock the admin out by guessing their password

**Category:** Security (DoS). **Severity:** Medium. **Confidence:** High (code-verified; this is the documented behaviour).

**Classification:** CWE-645.

**Affected files:** `app/api/auth.py` (`login`).

**Problem:** The lockout is per account and applies to admins too. Combined with SEC-011 (no per-IP limit), an anonymous attacker can keep `admin` permanently locked out.

**Mitigation:**
- Key failures by account and client network, or use progressive delays instead of a hard lock.
- Provide an out-of-band unlock, for example a CLI `python -m app.unlock admin`.

**Verification:** Failures from client A don't lock out client B.

**Complexity:** Small. **Dependencies:** SEC-011.

### SEC-013 [P1] Known-vulnerable dependency versions

**Category:** Security. **Severity:** Medium. **Confidence:** Medium. Versions were read from the installed `.venv`. pip-audit wasn't available, so applicability rests on public advisories.

**Classification:** OWASP A06:2021 Vulnerable and Outdated Components.

**Affected files:** `requirements.txt` (`fastapi==0.115.6` → Starlette 0.41.3; `python-jose[cryptography]==3.3.0`; `cryptography==44.0.0`).

**Problem:**
- **Starlette 0.41.3** is within the range affected by CVE-2025-62727: quadratic-time Range-header parsing in `FileResponse`, triggerable by unauthenticated requests, fixed in 0.49.1 ([Debian tracker](https://security-tracker.debian.org/CVE-2025-62727), [cvefeed](https://cvefeed.io/vuln/detail/CVE-2025-62727)). This app serves every HTML page, all static files and the logo through `FileResponse`/`StaticFiles`, so the vulnerable code is reachable. FastAPI 0.115.6 pins Starlette below 0.42, so a FastAPI upgrade is required.
- **python-jose 3.3.0** has CVE-2024-33663 (algorithm confusion) and CVE-2024-33664 (JWE decompression DoS), both fixed in 3.4.0 ([openSUSE changelog](https://build.opensuse.org/projects/openSUSE/packages/python-python-jose/files/python-python-jose.changes?expand=0)). Practical exposure here is low: the app uses HS256 with a pinned algorithm list and no JWE. Still, the library is slow-moving; PyJWT is the common replacement.
- **cryptography 44.0.0:** *Potential.* I believe a bundled-OpenSSL advisory was fixed in 44.0.1, but couldn't confirm it without pip-audit. Upgrade and verify.

**Mitigation:** Upgrade FastAPI and Starlette (≥ 0.49.1), move to PyJWT ≥ 2.x (or python-jose ≥ 3.4), upgrade cryptography, and add `pip-audit` to CI (TEST-007).

**Verification:** `pip-audit -r requirements.txt` reports nothing; the full test suite passes.

**Complexity:** Small–Medium (watch for FastAPI/Starlette API changes). **Dependencies:** TEST-007.

### SEC-014 [P3] TOTP codes can be replayed

**Category:** Security. **Severity:** Low. **Confidence:** High (code-verified: no record of the last-used time step).

**Classification:** CWE-294.

**Affected files:** `app/core/security.py` (`verify_totp_code`), `app/api/auth.py` (`mfa_verify`).

**Problem:** With `valid_window=1`, a code observed by an attacker (shoulder-surfing, phishing relay) can be reused for about 90 seconds.

**Mitigation:** Store `mfa_last_step` and reject time steps at or below it.

**Verification:** Reusing the same code twice returns 401 the second time.

**Complexity:** Small. **Dependencies:** none.

### SEC-015 [P2] The audit log can be wiped silently

**Category:** Security (accountability). **Severity:** Medium. **Confidence:** High (reproduced: `POST /api/admin/audit/prune?days=-1` deleted all entries, and nothing recorded the prune).

**Classification:** CWE-778 (insufficient logging).

**Affected files:** `app/api/admin_audit.py` (`prune_audit_logs`).

**Problem:** `days` is unbounded, and the prune itself isn't logged.

**Impact:** A compromised admin account can erase its tracks without leaving a trace.

**Mitigation:** Require `days ≥ 1`, and always write an `AUDIT_PRUNED` event, without IP or user agent when zero-log is on.

**Verification:** After a prune, exactly one `AUDIT_PRUNED` event remains.

**Complexity:** Small. **Dependencies:** none.

### SEC-016 [P3] Sensitive values written to the audit log

**Category:** Security / Privacy. **Severity:** Low. **Confidence:** High (code-verified).

**Classification:** CWE-532.

**Affected files:** `app/api/auth.py` (lines 151 and 373: `detail=f"username={payload.username}"`, `identifier=…`, `send failed: {e}`).

**Problem:**
- Failed logins store the typed username verbatim, and users often paste passwords into the username field.
- Password-reset requests store email addresses.
- SMTP exception text may include server details.

All of this is kept even in zero-log mode.

**Mitigation:** Don't store unknown identifiers, or store a keyed hash. Log only the class of SMTP error.

**Verification:** Grep the audit table after a test run.

**Complexity:** Small. **Dependencies:** SEC-002.

### SEC-017 [P3] Session token in localStorage, and logout doesn't revoke it

**Category:** Security. **Severity:** Low-Medium. **Confidence:** High (code-verified: logout only clears localStorage, and the JWT stays valid for 12 hours).

**Classification:** CWE-613 (insufficient session expiration).

**Affected files:** `frontend/static/js/layout.js` (`sd-logout`), `api.js`, `app/core/config.py` (`jwt_expire_minutes`).

**Problem:** Clicking Logout leaves the token usable for its full lifetime, and any script injection can read it.

**Mitigation:**
1. Add `POST /api/auth/logout` that bumps a per-token or per-session identifier. A `jti` deny-list is simple at this scale.
2. Consider `HttpOnly; Secure; SameSite=Strict` cookies with a CSRF header.
3. Shorten the lifetime and add refresh tokens.

**Verification:** After logout, the old token returns 401.

**Complexity:** Medium. **Dependencies:** SEC-009.

### SEC-018 [P3] Shared-file keys stored in plaintext and kept longer than needed

**Category:** Security. **Severity:** Low. **Confidence:** High (code-verified: `delete_own_account`, `delete_user` and `batch_delete_users` remove the share rows but never clear `files.shared_decryption_key`).

**Classification:** CWE-312.

**Affected files:** `app/api/auth.py`, `app/api/admin_users.py`, `app/api/sharing.py`.

**Problem:** After all shares are gone, the server still holds the file's decryption key until the row is hard-deleted.

**Mitigation:** Clear the key whenever the last share disappears, whatever the path (ARCH-003). Long term, FEAT-002.

**Verification:** Delete the recipient's account, then check the key is null.

**Complexity:** Small. **Dependencies:** ARCH-003.

### SEC-019 [P3] Turning off MFA needs only the password, even when MFA is mandatory

**Category:** Security. **Severity:** Low. **Confidence:** High (code-verified).

**Classification:** CWE-308.

**Affected files:** `app/api/auth.py` (`mfa_disable`).

**Problem:**
- A stolen session plus the password is enough to remove the second factor; no TOTP code is required.
- It's allowed even when `enforce_mfa_*` applies to that user.
- Other sessions aren't revoked.

**Mitigation:** Require a current TOTP or backup code, refuse when MFA is enforced for the user, and bump `token_version`.

**Verification:** Unit tests for each case.

**Complexity:** Small. **Dependencies:** none.

### SEC-020 [P3] Every username is visible to every logged-in user

**Category:** Security / Privacy. **Severity:** Low. **Confidence:** High (code-verified).

**Classification:** CWE-203 / CWE-359.

**Affected files:** `app/api/sharing.py` (`list_users_for_sharing`).

**Problem:** When sharing is enabled, any account can list every active username. That's a surprising directory for an anonymity-focused product.

**Mitigation:** Let users opt in to being discoverable. Otherwise, require typing an exact username, rate-limited.

**Verification:** Undiscoverable users are absent from the list.

**Complexity:** Small. **Dependencies:** none.

### SEC-021 [P4] Users must trust the JavaScript the server sends (informational)

**Category:** Security. **Severity:** Informational. **Confidence:** High.

**Affected files:** the frontend delivery model as a whole.

**Problem:** A malicious or compelled operator can serve modified `crypto.js` and capture keys. This is inherent to browser E2EE; PrivateBin documents the same limitation (COMP-002), and the README understates it.

**Mitigation:**
- State the limitation in the README.
- FEAT-012: published asset hashes, SRI, and a verification page or extension.
- Recommend the CLI for high-risk users.

**Verification:** Documentation review.

**Complexity:** Small (docs) to Medium (FEAT-012). **Dependencies:** FEAT-012.

---

## Architecture and Maintainability

### ARCH-001 [P1] Process-local state stops the app scaling past one process

**Category:** Architecture. **Confidence:** High (BUG-002 reproduced).

**Affected files:** `app/core/dynamic_settings.py`, `app/core/cleanup.py`, `app/main.py` (`lifespan`).

**Problem:**
- The settings cache isn't invalidated across processes (BUG-002).
- Every process runs its own cleanup loop, so passes are duplicated, `FILE_EXPIRED` events can be written twice, and deletions race each other.

Upload sessions were moved into the database earlier in this session, but these two remain.

**Recommendation:**
1. Settings: a version check plus a short TTL (see BUG-002).
2. Cleanup: a lease row (`UPDATE leases SET holder=:me, until=:t WHERE name='cleanup' AND until < now`), so only one process runs it per interval.
3. Document the supported topologies.

**Validation:** The two-process test (TEST-008).

**Complexity:** Small–Medium. **Dependencies:** none.

### ARCH-002 [P2] Database migrations are ad hoc, and some tables are never checked

**Category:** Architecture. **Confidence:** High (code-verified).

**Affected files:** `app/core/migrate.py`, `app/main.py`, `app/init_db.py`.

**Problem:**
- `sync_table_columns` can only *add* columns. It can't change indexes, constraints or types, or rename or backfill anything.
- It's never called for `FileShare`, `AuditLog` or `PasswordResetToken`, so new columns on those tables would silently never appear on existing installs.
- `init_db.py` syncs only 3 tables, while `main.py` syncs 5.

**Recommendation:** Adopt Alembic with a baseline migration that matches today's schema, and run `alembic upgrade head` at startup.

**Validation:** Run the migrations up and down in CI against SQLite and PostgreSQL.

**Complexity:** Medium. **Dependencies:** BUG-007.

### ARCH-003 [P2] The same business rules are implemented several times, and the copies have drifted

**Category:** Architecture. **Confidence:** High (code-verified).

**Affected files:** `auth.py`, `admin_users.py` (user deletion in three places), `files.py` (file deletion in three places), `files.py`/`auth.py` (lockout logic in four places), two copies of `_csv_safe`, and `humanSize` duplicated in JS.

**Problem:** The copies have already diverged:
- BUG-003: only one deletion path refuses self-deletion.
- SEC-018: no path clears the shared key.
- SEC-007: register skips the policy check that login applies.

**Recommendation:** Extract `services/users.py` (`delete_user`, `assert_not_last_admin`), `services/files.py` (`delete_file`, `consume_download`), `services/lockout.py` (atomic reservation) and `services/session_policy.py` (`issue_session_or_challenge`).

**Validation:** The existing tests keep passing, plus the new invariant tests.

**Complexity:** Medium. **Dependencies:** none.

### ARCH-004 [P3] Every setting is listed by hand in four places

**Category:** Architecture. **Confidence:** High (code-verified).

**Affected files:** `app/models/settings.py`, `app/schemas/settings.py` (×2), `app/api/public_config.py`.

**Problem:**
- About 80 settings are each listed by hand in four places, and adding one means editing all four.
- `PATCH` treats `None` as "unchanged", so nullable fields such as `public_base_url` can't be reset to null.

**Recommendation:**
- Generate the public subset from a `public=True` marker on each field.
- Use `model_fields_set` for PATCH semantics, as `AdminUpdateUser` already does.

**Validation:** A test that every model column appears in the admin schema.

**Complexity:** Small. **Dependencies:** none.

### ARCH-005 [P2] The deployment needs hardening

**Category:** Architecture / Security. **Confidence:** High (code-verified).

**Affected files:** `Dockerfile`, `docker-compose.yml`, `requirements*.txt`.

**Problem:**
- The container runs as root.
- There's no `HEALTHCHECK`.
- The base image isn't pinned to a digest.
- `apscheduler` is an unused dependency (zero imports).
- There's no lock file or hash pinning.
- There's no CI pipeline.

**Recommendation:**
- Add a non-root `USER` and a `HEALTHCHECK` against `/api/health`.
- Mount the filesystem read-only except `/app/data` and `/app/storage`.
- Drop `apscheduler`.
- Generate a lock file (`uv pip compile --generate-hashes`).

**Validation:** `docker run --read-only` works, and `docker inspect` shows a non-root user.

**Complexity:** Small. **Dependencies:** TEST-007.

### ARCH-006 [P3] Datetimes are stored without time zones

**Category:** Architecture. **Confidence:** High (code-verified: `.replace(tzinfo=utc)` appears at about 12 call sites).

**Affected files:** the models (`DateTime` without `timezone=True`), `files.py`, `auth.py`, `cleanup.py`, `sharing.py`.

**Problem:** SQLite stores naive datetimes, and every reader has to remember to call `.replace(tzinfo=utc)`. The SQL comparisons work only because every value is formatted the same way.

**Recommendation:** A `TypeDecorator` (`UTCDateTime`) that always stores and returns aware UTC datetimes.

**Validation:** Remove the `.replace` calls; the tests still pass.

**Complexity:** Small. **Dependencies:** ARCH-002.

### ARCH-007 [P3] Blob deletion isn't transactional with the database

**Category:** Architecture / Reliability. **Confidence:** High (code-verified).

**Affected files:** `files.py` (`delete_file`), `admin_files.py`.

**Problem:** The code commits the row deletion, *then* deletes the blob. If the blob deletion fails (an S3 outage), the client gets a 500 even though the file is gone from the database, and the orphaned blob is never retried.

**Recommendation:** Write a `pending_blob_deletions` row in the same transaction. The cleanup worker deletes the blob and removes the row, retrying with backoff.

**Validation:** Inject a backend failure: the row stays queued, then succeeds on retry.

**Complexity:** Small. **Dependencies:** BUG-005.

### ARCH-008 [P3] Frontend scripts share global objects and some code is inline

**Category:** Architecture. **Confidence:** High (code-verified).

**Affected files:** `frontend/static/js/*`, `frontend/*.html`.

**Problem:** There are 23 IIFEs communicating through `window.SD*` globals, duplicated helpers, and inline scripts that block a strict CSP.

**Recommendation:** Move to native ES modules (`<script type="module">`). That keeps the no-build, no-CDN principle while giving imports, de-duplication and an easy CSP.

**Validation:** Pages work with `script-src 'self'`.

**Complexity:** Medium. **Dependencies:** SEC-009.

---

## UI/UX Report

> **Limitation:** Playwright couldn't launch because Chrome isn't installed, and installing it would violate the no-install rule. These findings come from reading the code, not from screenshots. Visual hierarchy, contrast and responsive layout have **not** been verified.

### UI-001 [P2] Downloads show no progress

**Category:** UI. **Confidence:** High (code-verified: the label is only "Downloading...").

**Affected files:** `share.js`, `download-portal.js`, `shared-with-me.js`, `download-common.js`.

**Problem:** Multi-GB downloads give no feedback and look frozen.

**Improvement:** Compare streamed bytes against `size_bytes` from `/meta` to show a percentage, speed and ETA.

**Benefit:** Users don't abandon or retry large downloads, and retrying is destructive for burn files.

**Implementation:** Add an `onProgress` callback to `decryptStream`'s source iterator.

**Acceptance criteria:** The progress bar updates at least once per segment.

**Complexity:** Small. **Dependencies:** none.

### UI-002 [P2] Uploads can't be cancelled, retried or resumed

**Category:** UI. **Confidence:** High (code-verified).

**Affected files:** `upload.js`.

**Problem:** One failed chunk discards the whole upload, and there's no cancel button.

**Improvement:** A Cancel button using `AbortController`, automatic retry of a failed chunk with backoff, and "Resume" for interrupted uploads (FEAT-004).

**Acceptance criteria:** Killing the network for 10 seconds mid-upload still completes the upload.

**Complexity:** Medium. **Dependencies:** BUG-008, FEAT-004.

### UI-003 [P2] Burn-after-download destroys the file with no confirmation or key check

**Category:** UI. **Confidence:** High (code-verified).

**Affected files:** `share.js`.

**Problem:** The recipient clicks Download, the file is burned server-side, and *then* decryption may fail (wrong passphrase, truncated key). The only warning is a small "burns after this download" text.

**Improvement:**
- Verify the key before downloading, which needs the token from SEC-006.
- Show a confirmation: "This file will be permanently deleted after this download. Make sure you can save it now."

**Acceptance criteria:** A wrong key never burns the file.

**Complexity:** Small (after SEC-006). **Dependencies:** SEC-006.

### UI-004 [P2] Users can't see whether metadata was removed

**Category:** UI. **Confidence:** High (code-verified).

**Affected files:** `upload.js`, `exif-strip.js`.

**Problem:** The user can't tell which files had metadata removed and which didn't (see SEC-008).

**Improvement:** A per-file badge in the queue: "metadata removed", "not supported for this file type", or "failed — uploading original?" with a confirmation.

**Acceptance criteria:** A HEIC photo shows a visible warning before upload.

**Complexity:** Small. **Dependencies:** SEC-008.

### UI-005 [P3] Navigation menus and the theme toggle aren't accessible

**Category:** UI / Accessibility. **Confidence:** High (code-verified: 0 occurrences of `aria-expanded`, and the theme button is the 🌓 emoji with only a `title`).

**Affected files:** `frontend/static/js/layout.js`.

**Problem:**
- Screen readers aren't told whether a dropdown is open.
- Menu items can't be reached with arrow keys, and focus isn't moved into an opened menu.
- The theme toggle is announced as "first quarter moon".

**Improvement:**
- Add `aria-haspopup="menu"` and `aria-expanded` to the toggles.
- Use roving tabindex with arrow-key navigation, Escape returning focus to the toggle.
- Give the theme button an `aria-label`.

**Acceptance criteria:** The axe tool reports zero serious issues, and the menus work with the keyboard alone.

**Complexity:** Small. **Dependencies:** none.

### UI-006 [P3] Copy buttons give no feedback and fail silently

**Category:** UI. **Confidence:** High (code-verified: 7 `clipboard.writeText` calls without `.then`/`.catch`).

**Affected files:** `upload.js`, `account.js`, `admin-settings.js`.

**Problem:** There's no "Copied" confirmation, and on plain-HTTP deployments or when permission is denied, the copy fails silently. That's risky for one-time secrets (backup codes, the reset password, API keys).

**Improvement:** Show a toast or swap the button label on success. On failure, select the text and say "Press Ctrl/Cmd+C".

**Acceptance criteria:** Every copy shows visible success or fallback feedback.

**Complexity:** Small. **Dependencies:** none.

### UI-007 [P3] Authenticator apps always show "SecureDrop", ignoring the brand name

**Category:** UI. **Confidence:** High (code-verified: `auth.py:234` hardcodes the issuer).

**Affected files:** `app/api/auth.py` (`_start_mfa_setup`).

**Problem:** Rebranded instances, and users with several instances, can't tell their authenticator entries apart.

**Improvement:** Use `cfg["brand_name"]`.

**Acceptance criteria:** The provisioning URI carries the brand name.

**Complexity:** Small. **Dependencies:** none.

---

## Competitive Analysis

Research was done live with web search and fetches. Third-party pages are labelled as such, and claims I couldn't verify are marked as unverified.

### COMP-001 Send (Mozilla Send → timvisee/send fork) and the ffsend CLI

**Verified:**
- Client-side encryption with the key in the URL fragment.
- The **secret is expanded with HKDF into separate encryption, metadata and auth keys**. Downloads are authorised by signing a server nonce with the auth key (HMAC).
- In password mode, a PBKDF2-derived key replaces the auth key, so the server never receives the password.
- Streaming via ECE.
- The project lineage runs mozilla/send → timvisee/send → tarnover/send.

Sources: [mozilla/send docs/encryption.md](https://github.com/mozilla/send/blob/master/docs/encryption.md), [tarnover/send](https://github.com/tarnover/send), [ffsend](https://www.Github.com/timvisee/ffsend).

**Relevance:** This is the reference design for the fixes to SEC-001 and SEC-006. ffsend is a CLI that both uploads *and downloads*; this app's CLI only uploads (FEAT-011).

**Weakness:** Maintenance activity appears to have slowed (third-party listings).

### COMP-002 PrivateBin

**Verified (official README):**
- AES-256-GCM in the browser.
- Burn-after-reading and expiry, password protection, discussions, optional file uploads, QR codes, templates and translations.
- **Explicitly documented limitations:** HTTPS and HSTS are required, users must trust the administrator not to inject code, and access logs can still reveal who accessed what.

Source: [PrivateBin/PrivateBin](https://github.com/PrivateBin/PrivateBin).

**Relevance:**
- Text "pastes" (FEAT-006).
- Honest threat-model documentation (SEC-021).
- Its HTTPS/HSTS requirement (SEC-009).

### COMP-003 Wormhole.app

**Verified (official security page plus app listings):**
- Web Crypto E2EE, with **streaming encryption via Encrypted Content-Encoding (RFC 8188)** through an open-source `wormhole-crypto` library.
- Server storage for files up to 5 GB, with **peer-to-peer transfer above 5 GB**.
- 24-hour default expiry. A 100-download default was reported by a 2023 third-party review (Gigazine), not verified first-hand.

Sources: [wormhole.app/security](https://Wormhole.app/security), [Gigazine review](https://gigazine.net/gsc_news/en/20230115-wormhole-file-transfer).

**Relevance:**
- Streaming downloads straight to disk (PERF-005, FEAT-005).
- P2P for huge files (FEAT, deferred).

### COMP-004 Pingvin Share and Pingvin Share X

**Verified:**
- The original is **archived** (June 2025); Pingvin Share X is the maintained fork.
- Features: link sharing, expiry, visitor limits, passwords, email notifications, **reverse shares** (upload links for outsiders), OIDC and LDAP, **ClamAV scanning**, and local or S3 storage.

Sources: [archived README](https://cdn.jsdelivr.net/gh/stonith404/pingvin-share@main/README.md), [GitHub](https://github.com/stonith404/pingvin-share), [linuxlinks on Pingvin Share X](https://www.linuxlinks.com/pingvin-share-x-self-hosted-file-sharing-platform/).

**Relevance:**
- Reverse shares (FEAT-001).
- SSO (FEAT-010).
- **Don't copy:** server-side virus scanning is fundamentally incompatible with zero-knowledge. This should be an explicit non-goal.

### COMP-005 OnionShare

**Verified (secondary and older sources: itsfoss, man pages):**
- Hosts shares from the user's own machine as a Tor onion service.
- Modes: share, **receive** (an anonymous dropbox), public, website and chat.
- No account or third-party server needed. The CLI supports `--receive`, webhooks and auto-stop.

Sources: [itsfoss](https://itsfoss.com/onionshare/), [onionshare man page](https://manpages.ubuntu.com/manpages/kinetic/man1/onionshare.1.html).

**Relevance:**
- Receive mode supports FEAT-001.
- Tor-first deployment guidance (FEAT-009).

### COMP-006 Bitwarden Send

**Verified (official help center):**
- Deletion date (default 7 days, maximum 31), expiration date, maximum access count, password, **hide sender email**, private notes, and a **manual disable toggle**.
- File Sends require Premium and are capped at 500 MB; text Sends are free.

Source: [bitwarden.com/help/create-send](https://bitwarden.com/help/create-send).

**Relevance:**
- Owner-side disable and edit after creation (FEAT-007).
- Text sends (FEAT-006).

### COMP-007 "SecureDrop" name collision with the Freedom of the Press Foundation

**Verified:** FPF's **SecureDrop** is a well-known open-source whistleblower submission platform. FPF holds SECUREDROP trademark filings (serials 87959441 and 87960114, as reported by trademark aggregators; the USPTO's own records weren't checked).

Sources: [docs.securedrop.org](https://docs.securedrop.org/en/stable/what_is_securedrop.html), [Wikipedia](https://en.wikipedia.org/wiki/SecureDrop), [Justia trademarks](https://trademarks.justia.com/owners/freedom-of-the-press-foundation-3861738).

**Finding [P2]:** This project's name invites confusion with an *audited, whistleblower-grade* system. That's a user-safety risk, because sources may over-trust it, as well as a legal and branding risk.

**Recommendation:** Rename before any public release. Default `brand_name` is already configurable, but the repository, README and CLI names aren't.

### COMP-008 Positioning summary

**Unique strengths of this app compared with the others:**
- Self-hosted E2EE *plus* an operator policy layer: runtime admin settings, an audit log with privacy levels, MFA enforcement, scoped API keys, S3 storage and statistics.
- None of the E2EE competitors above offer that combination. Pingvin offers the admin features but without E2EE.

**Biggest gaps:**
- The cryptographic hygiene Send already solved: the auth key and password handling (SEC-001, SEC-006).
- Reverse shares.
- Text sends.
- Streaming to disk.
- A CLI download command.

### Comparison matrix

| App | Primary purpose | Key features | Unique capabilities | Strengths | Weaknesses | What this app lacks | Opportunity |
|---|---|---|---|---|---|---|---|
| **This app** | Self-hosted E2EE file drop with an admin layer | Fragment keys, passphrase mode, burn/limits, MFA, audit, API keys, S3 | Runtime policy plus a privacy-levelled audit log | Operator control, clean code | SEC-001/002/006, single-process limits | — | — |
| Send / ffsend (COMP-001) | Ephemeral E2EE links | HKDF key split, nonce-HMAC download auth, ECE streaming, CLI | Server never gets the password or the key | Proven crypto design | Slow maintenance | Download auth key; password verifier; CLI download | SEC-001, SEC-006, FEAT-011 |
| PrivateBin (COMP-002) | E2EE pastebin | Burn-after-reading, discussions, QR, templates | Honest threat-model documentation | Mature, widely deployed | Text-first | Text sends; threat-model docs | FEAT-006, SEC-021 |
| Wormhole (COMP-003) | Large-file E2EE transfer | RFC 8188 streaming, P2P above 5 GB | Streaming plus P2P fallback | Speed, very large files | Hosted service only | Stream-to-disk; P2P | PERF-005, FEAT-005 |
| Pingvin Share X (COMP-004) | Self-hosted sharing (not E2EE) | Reverse shares, OIDC/LDAP, ClamAV, S3 | Reverse shares | Admin/organisation features | No E2EE | Reverse shares, SSO | FEAT-001, FEAT-010 |
| OnionShare (COMP-005) | P2P over Tor | Share, receive, website, chat modes | No server at all | Strongest anonymity | Sender must stay online | Receive dropbox; Tor guidance | FEAT-001, FEAT-009 |
| Bitwarden Send (COMP-006) | Password-manager sharing | Deletion/expiry dates, max access, hide email, disable toggle | Integrated in the vault | Polished UX | 500 MB, Premium-only for files | Edit or disable after creation; text | FEAT-007, FEAT-006 |

---

## Feature Recommendations

### FEAT-001 [P4] Reverse shares: encrypted "send me a file" links

**Category:** Feature. **Confidence:** Medium. **Supporting research:** COMP-004, COMP-005.

**User problem:** A journalist, lawyer or IT admin needs *outsiders* to send them files securely, without the outsider having an account.

**Expected value:** This is the single most differentiating feature for an "anonymity-first" product, and it fits the existing anonymous-upload path.

**Description and implementation:**
1. The owner creates a request link that embeds an **ECDH P-256 public key** in its fragment (WebCrypto supports P-256 natively).
2. The uploader's browser runs ephemeral ECDH, then HKDF, then a file key, and encrypts with the existing STREAM format (a new flag `0x05`).
3. Only the owner's private key can decrypt. It's stored wrapped by a key derived from the owner's password, or kept locally.
4. Options: expiry, maximum number of uploads, and a size cap per request link.

**Architectural changes:** a `request_links` table, an owner key pair (shared with FEAT-002), and an inbox UI.

**Dependencies:** SEC-001 (verifier pattern), ARCH-003.

**Complexity:** Large.

**Risks:** Owner key management and recovery.

**Acceptance criteria:** An anonymous uploader completes a submission; the owner decrypts it in the inbox; the server holds only ciphertext and the public key.

### FEAT-002 [P4] Public-key user-to-user sharing (makes sharing zero-knowledge again)

**Category:** Feature. **Confidence:** Medium. **Supporting research:** own analysis; no COMP verified.

**User problem:** Today's user-to-user sharing stores file keys on the server (SEC-018).

**Expected value:** Closes the README's stated exception to zero-knowledge.

**Implementation:** Each account gets a key pair, with the private key wrapped by `PBKDF2(password)` and stored. Sharing wraps the file key to each recipient's public key. Password changes re-wrap the private key, and an admin password reset must warn that old shares become unreadable.

**Dependencies:** FEAT-001 (shared key infrastructure).

**Complexity:** Large.

**Risks:** Key loss when a user forgets their password; this needs a recovery code.

**Acceptance criteria:** The `shared_decryption_key` column is no longer needed for new shares.

### FEAT-003 [P3] One link for multiple files

**Category:** Feature. **Confidence:** Medium. **Supporting research:** own analysis; competitor parity not verified.

**User problem:** A folder upload today produces N separate links.

**Expected value:** One link to share, one expiry to manage.

**Implementation:** An encrypted manifest blob listing each file's ID and key, one share link pointing at the manifest, and a recipient UI with "download all" (streamed ZIP via the client).

**Dependencies:** PERF-005.

**Complexity:** Medium.

**Acceptance criteria:** 100 files are shared through one link and all download successfully.

### FEAT-004 [P3] Resumable uploads

**Category:** Feature. **Confidence:** High (enabled by this session's database-backed sessions).

**User problem:** On flaky or Tor connections, large uploads fail and restart from zero.

**Implementation:** Offset-addressed chunks (BUG-008), `HEAD /api/uploads/{id}` returning the current offset, and a client that keeps upload state in IndexedDB (never the key in the clear for the passphrase flow).

**Dependencies:** BUG-008.

**Complexity:** Medium.

**Acceptance criteria:** After a tab reload mid-upload, the upload resumes from the last acknowledged offset.

### FEAT-005 [P3] Stream downloads straight to disk

**Category:** Feature. **Confidence:** High. **Supporting research:** COMP-003.

This is the user-facing form of PERF-005. **Acceptance criteria:** a 10 GB download completes with flat memory use in Chromium.

**Complexity:** Medium.

### FEAT-006 [P3] Encrypted text and secret sends

**Category:** Feature. **Confidence:** High. **Supporting research:** COMP-002, COMP-006.

**User problem:** People share passwords and snippets through chat.

**Expected value:** A cheap way to grow the product's use cases, reusing the whole crypto, burn and expiry pipeline.

**Implementation:** A text area on the upload page, enveloped as `type: text/plain` with an inline viewer on the share page and no download needed.

**Dependencies:** none.

**Complexity:** Small.

**Acceptance criteria:** Pasting text produces a link, and the recipient sees the text inline.

### FEAT-007 [P3] Manage a link after creating it

**Category:** Feature. **Confidence:** High. **Supporting research:** COMP-006.

**User problem:** Today the only control after upload is deleting the file.

**Implementation:** `PATCH /api/files/{id}` for `disabled`, `expires_at` (shortening only) and `max_downloads` (lowering only), plus toggles in My Files.

**Dependencies:** none.

**Complexity:** Small.

**Acceptance criteria:** A disabled link returns 404 until it's re-enabled.

### FEAT-008 [P3] Explicit non-goal: server-side malware scanning

**Category:** Feature (decision). **Supporting research:** COMP-004.

Document in the README that ClamAV-style scanning is impossible under zero-knowledge, and suggest client-side "open in sandbox" guidance instead. **Complexity:** Small (documentation).

### FEAT-009 [P3] Tor and .onion deployment profile

**Category:** Feature. **Supporting research:** COMP-005.

**Implementation:**
- An `Onion-Location` header option.
- A docs page covering a `tor` sidecar in docker-compose.
- Tuned defaults for onion deployments: larger timeouts, smaller chunks, and per-session rate limits (SEC-011).

**Complexity:** Small.

**Acceptance criteria:** `docker compose --profile tor up` serves the app on an onion address.

### FEAT-010 [P4] Single sign-on (OIDC)

**Category:** Feature. **Supporting research:** COMP-004.

**User problem:** Organisations want SSO.

**Implementation:** Authlib, an OIDC callback that maps users and roles, and MFA delegated to the identity provider.

**Complexity:** Medium.

**Risks:** Widens the attack surface. Keep it off by default.

### FEAT-011 [P3] CLI download, verify and list commands

**Category:** Feature. **Supporting research:** COMP-001 (ffsend).

**Implementation:** `securedrop download <link>` (streaming decryption to a file), a `--stdin` upload option, and JSON output for scripts.

**Dependencies:** none (the format is already shared and tested).

**Complexity:** Small.

**Acceptance criteria:** Uploading with the CLI and then downloading with the CLI round-trips byte-identically.

### FEAT-012 [P4] Verifiable frontend code

**Category:** Feature. **Supporting research:** COMP-002 (the limitation it documents).

**Implementation:**
- Build-time SHA-256 hashes of every JS file, published in releases.
- SRI attributes on the `<script>` tags.
- An `/about/integrity` page comparing the hashes.
- Optionally, a tiny browser extension that pins the hashes.

**Complexity:** Medium.

**Acceptance criteria:** A modified `crypto.js` is detected by the extension or the published hash.

---

## Testing and Quality Assurance

**Current state:** 34 pytest tests (auth/MFA, upload and download policy, sharing access control, admin settings, and the new upload sessions) plus 14 Node crypto tests (round-trips, tampering, legacy format, CLI↔browser compatibility). All pass. There's no CI, no linting, no type checking, no browser end-to-end tests, no S3 tests and no concurrency tests.

### TEST-001 [P0] Test that the passphrase never reaches the server

**Category:** Testing. **Confidence:** High.

**Affected files:** new tests in `tests/js/` and an end-to-end browser test.

**Problem:** SEC-001 went unnoticed because nothing asserts the zero-knowledge property.

**Recommendation:** Intercept every request made by the upload and download flows and assert that the passphrase, the raw key and the filename appear in no request body, header or URL path.

**Validation:** The test fails on the current code and passes after SEC-001.

**Complexity:** Small–Medium. **Dependencies:** SEC-001, TEST-004.

### TEST-002 [P1] Concurrency regression tests

**Category:** Testing. **Confidence:** High.

**Recommendation:** Promote `repro_live.py` [A] and [B] into pytest with a live-uvicorn fixture: the burn race (exactly one success), the lockout race (at most `max` attempts), and parallel `/complete` (BUG-009).

**Complexity:** Small. **Dependencies:** BUG-001, SEC-005.

### TEST-003 [P2] Tighten weak assertions in existing tests

**Category:** Testing. **Confidence:** High.

**Affected files:** `tests/test_upload_download.py` (`test_secondary_password_lockout` accepts `401 or 423` for every attempt).

**Problem:** That test would still pass if the lockout triggered on the first attempt.

**Recommendation:** Assert exactly `max-1` 401 responses, then 423.

**Complexity:** Small.

### TEST-004 [P2] Browser end-to-end tests

**Category:** Testing. **Confidence:** High.

**Problem:** There's no real-browser coverage of the upload → link → download → decrypt flow. This session's streaming upload and download code has only been verified in Node, not in a browser.

**Recommendation:** Playwright tests for single and batch upload, passphrase mode, burn, a missing fragment, EXIF stripping (SEC-008) and zero CSP violations (SEC-009).

**Complexity:** Medium. **Dependencies:** none.

### TEST-005 [P2] S3 backend tests

**Category:** Testing. **Confidence:** High. Would have caught BUG-005.

**Recommendation:** Run the existing suite with the `moto` mock S3 (or a MinIO container) as a second backend, including the cleanup and factory-reset paths.

**Complexity:** Small.

### TEST-006 [P2] Privacy-mode tests

**Category:** Testing. **Confidence:** High. Would have caught SEC-002 and SEC-003.

**Recommendation:** With zero-log on and IP level "none", run every endpoint and then assert the audit and files tables contain no IPs, user agents, user IDs, actor tokens or typed identifiers.

**Complexity:** Small.

### TEST-007 [P2] CI with static analysis and dependency scanning

**Category:** Testing. **Confidence:** High.

**Recommendation:** A GitHub Actions or equivalent pipeline running `ruff`, `mypy` on `app/`, `pip-audit`, `bandit`, `node --test`, and `eslint` with a security plugin. None of these could be run during this audit.

**Complexity:** Small. **Dependencies:** SEC-013.

### TEST-008 [P2] Settings validation and multi-process propagation tests

**Category:** Testing. **Confidence:** High.

**Recommendation:** Bounds tests (BUG-004) and a two-process propagation test (BUG-002).

**Complexity:** Small.

### TEST-009 [P2] Policy-matrix tests for session issuance

**Category:** Testing. **Confidence:** High.

**Recommendation:** For each of {register, login, mfa-verify, enforce-confirm} × {MFA enforced or not, login allowed or not, admin or not}, assert the expected outcome (catches SEC-007).

**Complexity:** Small.

---

## Prioritized Backlog

| # | ID | Pri | Short description | Rationale | Complexity | Depends on | Expected outcome |
|---|---|---|---|---|---|---|---|
| 1 | SEC-001 | P0 | Send a derived verifier instead of the passphrase | Core promise broken | M | — | Server never sees the passphrase |
| 2 | TEST-001 | P0 | Zero-knowledge network assertions | Lock in SEC-001 | S–M | SEC-001 | Regression-proof |
| 3 | SEC-002 | P1 | Stop storing the actor in zero-log mode | Privacy promise inverted | S | — | Zero-log means zero log |
| 4 | BUG-001 | P1 | Atomic download claim | Single-use links consumed several times | S | — | Exactly-once burn |
| 5 | SEC-005 | P1 | Atomic attempt reservation | Lockout bypass | S | — | Limits hold under concurrency |
| 6 | SEC-004 | P1 | Streamed, bounded chunk bodies | Unauthenticated memory DoS | S | — | Flat memory |
| 7 | SEC-007 | P1 | Shared session-issuance policy | MFA bypass | S | ARCH-003 | Policy enforced everywhere |
| 8 | SEC-013 | P1 | Upgrade Starlette/FastAPI, python-jose (or move to PyJWT), cryptography | Public CVEs | S–M | — | Clean pip-audit |
| 9 | SEC-006 | P1 | Proof-of-key download token; time-limited lockout | Key-less griefing | M | SEC-001 | Only key holders can consume |
| 10 | SEC-008 | P1 | Fail-closed, lossless metadata stripping | Location leaks | M | UI-004 | No silent GPS leaks |
| 11 | BUG-005 | P1 | Cleanup through the storage backend | S3 never purged | S | — | Retention honoured |
| 12 | BUG-002 / ARCH-001 | P1 | Versioned settings; single cleanup leader | Multi-process correctness | S–M | — | Policies consistent |
| 13 | TEST-002 | P1 | Concurrency tests | Lock in the fixes above | S | 4, 5 | Regression-proof |
| 14 | SEC-009 | P2 | CSP and HSTS | Defence in depth for key material | S | (ARCH-008) | XSS can't exfiltrate keys |
| 15 | SEC-010 | P2 | Lock down `storage_path` | Arbitrary deletion | S | — | Safe reset |
| 16 | SEC-015 | P2 | Audited, bounded prune | Accountability | S | — | Tamper-evident log |
| 17 | BUG-004 | P2 | Bound numeric settings | Self-inflicted outages | S | — | No endless upload loop |
| 18 | BUG-003 | P2 | Last-admin guard | Admin lockout | S | ARCH-003 | Always ≥ 1 admin |
| 19 | BUG-008 | P2 | Offset-addressed chunks | Silent corruption | M | — | Retry-safe uploads |
| 20 | SEC-011 / SEC-012 | P2 | Rate limits; reservation-aware capacity | Anonymous DoS | M | PERF-001 | Bounded abuse |
| 21 | PERF-001 / PERF-002 / PERF-009 | P2 | DB usage counter, SQL cleanup off the event loop, WAL | Latency at scale | S | BUG-005 | O(1) init; no stalls |
| 22 | SEC-003 | P2 | Drop the persistent uploader link | Linkability | S | SEC-002 | Unlinkable anonymous uploads |
| 23 | ARCH-003 | P2 | Shared domain services | Root cause of BUG-003, SEC-007, SEC-018 | M | — | One source of truth |
| 24 | ARCH-002 / BUG-007 | P2 | Alembic; wider identity columns | Upgrade safety | M | — | Real migrations |
| 25 | ARCH-005 | P2 | Container hardening; remove apscheduler | Operational security | S | — | Non-root image |
| 26 | COMP-007 | P2 | Rename the project | Trust and legal risk | S | — | No FPF confusion |
| 27 | UI-001 / UI-003 / UI-004 | P2 | Download progress, burn confirmation, strip status | Destructive or opaque UX | S | SEC-006, SEC-008 | Fewer lost files |
| 28 | UI-002 / FEAT-004 | P2–P3 | Cancel, retry and resume | Large-file reliability | M | BUG-008 | Uploads survive flaky networks |
| 29 | PERF-005 / FEAT-005 | P2–P3 | Stream downloads to disk | Large-file memory | M | — | Flat memory |
| 30 | TEST-003…009 | P2 | Test gaps | Quality | S–M | — | Coverage of critical paths |
| 31 | SEC-014 / 016 / 017 / 018 / 019 / 020 | P3 | Lower-severity hardening | Defence in depth | S | various | — |
| 32 | BUG-006 / 009 / 010 | P3 | Edge-case bugs | Polish | S | — | — |
| 33 | PERF-003 / 004 / 006 / 007 / 008 / 010 | P3 | Smaller optimisations | Scale and UX | S–M | — | — |
| 34 | UI-005 / 006 / 007 | P3 | Accessibility and feedback | Usability | S | — | axe-clean |
| 35 | ARCH-004 / 006 / 007 / 008 | P3 | Maintainability | — | S–M | — | — |
| 36 | FEAT-006 / 007 / 011 / 009 / 008 / 003 | P3 | Quick-win features | Competitiveness | S–M | — | Parity with Send, Bitwarden, PrivateBin |
| 37 | FEAT-001 / 002 / 010 / 012, SEC-021 | P4 | Strategic features | Differentiation | L | SEC-001, ARCH-003 | A leading self-hosted E2EE drop |

---

## Implementation Roadmap

**Stage 1: Restore the core promises (P0/P1 security).**
- **Findings:** SEC-001, TEST-001, SEC-002, SEC-003, SEC-007, SEC-013.
- **Files:** `upload.js`, `download-common.js`, `share.js`, `crypto.js` (verifier derivation), `app/api/upload.py`, `files.py`, `auth.py`, `models/file.py` (`verifier_version`), `requirements.txt`.
- **Regression risks:** existing passphrase files must keep working (versioned verifier), and FastAPI/Starlette upgrades can change behaviour, so run the full suite.
- **Done when:** TEST-001 and the privacy tests are green, `pip-audit` is clean, and an old passphrase file still downloads.

**Stage 2: Concurrency and abuse resistance.**
- **Findings:** BUG-001, SEC-005, SEC-006, SEC-004, BUG-009, TEST-002, SEC-011, SEC-012, BUG-004, SEC-010, SEC-015, BUG-003.
- **Files:** `files.py`, `auth.py`, `upload.py`, `schemas/settings.py`, `storage_service.py`, `admin_audit.py`. Introduce `services/lockout.py` and `services/files.py` here (the start of ARCH-003).
- **Regression risks:** the download-token change touches both the share and portal flows. Keep accepting downloads without a token only for files uploaded before the change.
- **Done when:** the [A], [B] and [C] reproductions show exactly-once behaviour, the attempt limit holds, and memory stays flat.

**Stage 3: Multi-process readiness, storage and performance.**
- **Findings:** BUG-002, ARCH-001, BUG-005, ARCH-007, PERF-001, PERF-002, PERF-009, PERF-003, PERF-004, TEST-005, TEST-008.
- **Files:** `dynamic_settings.py`, `cleanup.py`, `storage_service.py`, `database.py`, `admin_files.py`, `sharing.py`.
- **Done when:** the two-process test is green, the S3 tests are green, and `/init` time doesn't depend on the number of stored files.

**Stage 4: Maintainability and upgrade safety.**
- **Findings:** ARCH-003 (finished), ARCH-002, BUG-007, ARCH-004, ARCH-005, ARCH-006, ARCH-008, SEC-009, TEST-007.
- **Done when:** Alembic is at its baseline, CI runs lint, types, audit and tests, and every page works under a strict CSP.

**Stage 5: UX.**
- **Findings:** SEC-008 together with UI-004, UI-001, UI-003, BUG-008 with UI-002, PERF-005, PERF-006, PERF-007, UI-005, UI-006, UI-007, BUG-006.
- **Done when:** TEST-004's Playwright suite passes, axe reports no serious issues, and a 4 GB download keeps memory flat.

**Stage 6: Features and positioning.**
- **Findings:** COMP-007 (rename), FEAT-006, FEAT-007, FEAT-011, FEAT-009, FEAT-008 and FEAT-003 first, then FEAT-004, FEAT-001, FEAT-002, FEAT-012 and FEAT-010.
- **Done when:** each feature's acceptance criteria pass, plus a final full regression run.

---

## Verification Results

All commands were run from the project root during this audit. Throwaway instances used scratchpad directories, never the real database.

| Check | Command | Result |
|---|---|---|
| Python tests | `.venv/bin/python -m pytest -q` | **34 passed** (87 deprecation warnings from python-jose's `utcnow`) |
| JS crypto tests | `node --test tests/js/` | **14/14 passed** (including CLI↔browser compatibility) |
| Python compile | `python -m compileall -q app cli` | OK |
| JS syntax | `node --check` on all 23 JS files | OK |
| In-process reproductions | `scratchpad/audit/repro_inproc.py` | 7 reproduced: SEC-002, SEC-007, BUG-003, SEC-006 (lockout), BUG-004, BUG-006, SEC-015. 1 control passed (the upload-only API key scope is enforced). 1 hypothesis refuted. |
| Live reproductions | `scratchpad/audit/repro_live.py` | [A] BUG-001: 3 of 8 admitted. [B] SEC-005: 32 of 32 checked against a limit of 5. [C] SEC-004: RSS 116 → 926 MiB. [D] with `--workers 2`: inconclusive on macOS. |
| Two-process settings test | two uvicorn processes on :8801/:8802 sharing one DB | BUG-002 reproduced: B returned 200 after anonymous uploads were disabled through A |
| Dependency versions | `uv pip list --python .venv/bin/python` | starlette 0.41.3, python-jose 3.3.0, cryptography 44.0.0, ecdsa 0.19.2 (pulled in by jose) |

**Not run (limitations):**
- **Linters and scanners:** ruff, mypy, eslint, pip-audit, bandit and semgrep aren't installed, and installing them wasn't allowed.
- **Browser checks:** Playwright needs Chrome, which isn't installed, so no screenshots, Core Web Vitals, Lighthouse or axe runs. The UI findings are based on code.
- **Other gaps:** no load or throughput benchmarks beyond the memory measurement in [C], and no S3 testing (BUG-005 is code-verified only).

---

## Final Assessment

**Biggest weaknesses:**
1. The passphrase mode leaks the passphrase (SEC-001), and zero-log mode is inverted (SEC-002). The product's two strongest promises are the ones most broken.
2. Every counter-based safety feature (burn, download limits, lockouts) has a race condition.
3. The app works correctly only as a single process with local storage. It looks multi-process-ready and S3-ready, but isn't.

**Most important opportunities:**
- Adopt the auth-key design Send already solved (COMP-001). One derivation scheme fixes SEC-001, SEC-006 and UI-003 together.
- Reverse shares (FEAT-001) would make this the only self-hosted, E2EE, policy-managed drop box among the apps reviewed.

**Highest-impact fixes, by value per effort:**
1. SEC-002: a one-line inversion.
2. BUG-001 together with SEC-005: atomic `UPDATE`s, about 30 lines.
3. SEC-004: streamed bodies.
4. SEC-007: share one policy function between register and login.
5. SEC-013: dependency bumps.

**Features most likely to improve competitiveness:** FEAT-001 (reverse shares), FEAT-006 (text sends), FEAT-007 (manage links after creation), FEAT-011 (CLI download) and FEAT-005 (stream to disk). The rename in COMP-007 should happen before any public launch.

**What to implement first:** Stage 1 (SEC-001, TEST-001, SEC-002, SEC-007, SEC-013), then Stage 2's atomic-counter work.
