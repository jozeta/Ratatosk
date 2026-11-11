#!/usr/bin/env python3
"""Ratatosk command-line client.

Encrypts and decrypts on your machine with the same format the browser uses,
so the server never sees plaintext, filenames, keys or passphrases.

Upload (needs an API key - create one at /account):
    ratatosk upload --server https://drop.example.com --api-key sdk_... report.pdf
    export RATATOSK_API_KEY=sdk_...
    ratatosk upload --server https://drop.example.com --ttl 7d --burn report.pdf
    tar cz project/ | ratatosk upload --server ... --stdin --name project.tgz

Download (no account needed if anonymous downloads are allowed):
    ratatosk download 'https://drop.example.com/share/<id>#<key>'
    ratatosk download 'https://drop.example.com/share/<id>' --password '...' -o out.pdf

Verify that a server runs an unmodified release of the web app:
    ratatosk verify https://drop.example.com --expect <release digest from CHANGELOG.md>

Add --json to any command for machine-readable output.

Requires: pip install cryptography
"""
import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:
    print("error: this script needs the 'cryptography' package: pip install cryptography", file=sys.stderr)
    sys.exit(1)

# Must match frontend/static/js/crypto.js - see the format comment there.
FLAG_V3_RANDOM_KEY = 0x05
FLAG_V3_PASSPHRASE = 0x06
LEGACY_STREAM_FLAGS = {0x03: False, 0x04: True}  # flag -> is passphrase mode
PBKDF2_ITERATIONS = 600000
SEGMENT_SIZE = 1024 * 1024
GCM_TAG_BYTES = 16
ENC_INFO = b"ratatosk-enc-v1"
DL_INFO = b"ratatosk-dl-v1"
__version__ = "2.2.0"  # keep equal to app/version.py (tests/test_version.py checks)
USER_AGENT = f"ratatosk-cli/{__version__}"


class CliError(Exception):
    pass


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(secret: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(secret)


def _pbkdf2(password: str, salt: bytes, iterations: int) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations).derive(password.encode("utf-8"))


def derive_from_secret(secret: bytes) -> tuple[bytes, str]:
    """(AES file key, download token) - independent HKDF outputs."""
    return _hkdf(secret, ENC_INFO), b64url_encode(_hkdf(secret, DL_INFO))


class StreamEncryptor:
    """Segmented AES-256-GCM (STREAM construction), byte-for-byte the format
    crypto.js's createEncryptor writes. Reads the input one segment at a time,
    so memory use stays flat regardless of size. Ciphertext is deterministic
    given the parameters, so chunks(offset) can resume anywhere."""

    def __init__(self, path: str, name: str, mime_type: str, password: str | None):
        self.path = path
        file_size = os.path.getsize(path)
        meta = json.dumps({"name": name, "type": mime_type, "size": file_size}, ensure_ascii=False).encode("utf-8")
        self._prefix = len(meta).to_bytes(4, "little") + meta
        self._nonce_prefix = secrets.token_bytes(8)
        tail = SEGMENT_SIZE.to_bytes(4, "little") + self._nonce_prefix

        self.kdf_salt: str | None = None
        self.kdf_iterations: int | None = None
        if password:
            salt = secrets.token_bytes(16)
            secret = _pbkdf2(password, salt, PBKDF2_ITERATIONS)
            self.header = bytes([FLAG_V3_PASSPHRASE]) + salt + PBKDF2_ITERATIONS.to_bytes(4, "little") + tail
            self.url_key = None
            self.kdf_salt, self.kdf_iterations = b64url_encode(salt), PBKDF2_ITERATIONS
        else:
            secret = secrets.token_bytes(32)
            self.header = bytes([FLAG_V3_RANDOM_KEY]) + tail
            self.url_key = b64url_encode(secret)
        key, self.download_token = derive_from_secret(secret)
        self.token_hash = hashlib.sha256(self.download_token.encode()).hexdigest()
        self._aead = AESGCM(key)

        plaintext_len = len(self._prefix) + file_size
        self._segments = max(1, -(-plaintext_len // SEGMENT_SIZE))
        self.size = len(self.header) + plaintext_len + self._segments * GCM_TAG_BYTES

    def _segment(self, fh, i: int) -> bytes:
        start = i * SEGMENT_SIZE
        end = start + SEGMENT_SIZE
        out = b""
        plen = len(self._prefix)
        if start < plen:
            out += self._prefix[start:min(end, plen)]
        fstart = max(0, start - plen)
        fend = end - plen
        if fend > 0:
            fh.seek(fstart)
            out += fh.read(fend - fstart)
        is_final = i == self._segments - 1
        iv = self._nonce_prefix + i.to_bytes(4, "big")
        return self._aead.encrypt(iv, out, self.header + bytes([1 if is_final else 0]))

    def chunks(self, from_offset: int = 0):
        pos = from_offset
        if pos < len(self.header):
            yield self.header[pos:]
            pos = len(self.header)
        sealed = SEGMENT_SIZE + GCM_TAG_BYTES
        i, skip = divmod(pos - len(self.header), sealed)
        with open(self.path, "rb") as fh:
            for idx in range(i, self._segments):
                seg = self._segment(fh, idx)
                yield seg[skip:] if skip else seg
                skip = 0


def iter_upload_chunks(pieces, chunk_size: int, start_offset: int = 0):
    """Regroups ciphertext pieces into (offset, bytes) uploads of chunk_size."""
    buf = bytearray()
    offset = start_offset
    for piece in pieces:
        buf += piece
        while len(buf) >= chunk_size:
            yield offset, bytes(buf[:chunk_size])
            offset += chunk_size
            del buf[:chunk_size]
    if buf:
        yield offset, bytes(buf)


class StreamDecryptor:
    """Incremental decryption of the segmented formats (0x03-0x06)."""

    def __init__(self, url_key: str | None, password: str | None):
        self.url_key, self.password = url_key, password
        self.buf = bytearray()
        self.header: bytes | None = None
        self.meta: dict | None = None
        self.index = 0
        self.out = None
        self._pending_plain = bytearray()

    def _setup(self) -> bool:
        flag = self.buf[0]
        if flag not in (FLAG_V3_RANDOM_KEY, FLAG_V3_PASSPHRASE, *LEGACY_STREAM_FLAGS):
            raise CliError("Unsupported or legacy single-shot file format - download it in the browser instead")
        is_pass = flag in (FLAG_V3_PASSPHRASE, 0x04)
        hlen = 1 + (20 if is_pass else 0) + 12
        if len(self.buf) < hlen:
            return False
        header = bytes(self.buf[:hlen])
        del self.buf[:hlen]
        off = 1
        if is_pass:
            if not self.password:
                raise CliError("This file needs a passphrase (--password)")
            salt, iters = header[1:17], int.from_bytes(header[17:21], "little")
            secret = _pbkdf2(self.password, salt, iters)
            off = 21
        else:
            if not self.url_key:
                raise CliError("The link is missing its #key part")
            secret = b64url_decode(self.url_key)
        key = derive_from_secret(secret)[0] if flag in (FLAG_V3_RANDOM_KEY, FLAG_V3_PASSPHRASE) else secret
        self.seg = int.from_bytes(header[off:off + 4], "little")
        self.nonce = header[off + 4:off + 12]
        self.aead = AESGCM(key)
        self.header = header
        return True

    def _open(self, sealed: bytes, final: bool) -> bytes:
        if self.header is None:
            raise CliError("Decryption failed - the file is corrupted")
        iv = self.nonce + self.index.to_bytes(4, "big")
        try:
            plain = self.aead.decrypt(iv, sealed, self.header + bytes([1 if final else 0]))
        except Exception:
            raise CliError("Decryption failed - wrong key/passphrase, or the file is corrupted") from None
        self.index += 1
        return plain

    def feed(self, data: bytes, final: bool = False):
        """Yields plaintext envelope bytes."""
        self.buf += data
        if self.header is None:
            if not self.buf or not self._setup():
                return
        sealed = self.seg + GCM_TAG_BYTES
        while len(self.buf) > sealed:
            yield self._open(bytes(self.buf[:sealed]), False)
            del self.buf[:sealed]
        if final:
            yield self._open(bytes(self.buf), True)
            self.buf.clear()


def api_request(server: str, path: str, api_key: str | None, method: str = "GET", data=None, raw: bool = False,
                headers: dict | None = None, retries: int = 3, stream: bool = False):
    if urllib.parse.urlsplit(server).scheme not in ("http", "https"):
        raise CliError(f"server must be an http(s) URL, got {server!r}")
    url = server.rstrip("/") + path
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    if api_key:
        hdrs["Authorization"] = f"Bearer {api_key}"
    body = None
    if data is not None:
        if raw:
            body = data
            hdrs["Content-Type"] = "application/octet-stream"
        else:
            body = json.dumps(data).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=120)  # nosec B310 - scheme checked above
            if stream:
                return resp
            with resp:
                raw_body = resp.read()
                return json.loads(raw_body) if raw_body else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except ValueError:
                pass
            # Chunk PUTs are offset-addressed, so retrying them is safe.
            if e.code in (429, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise CliError(f"{method} {path} -> HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise CliError(f"could not reach {server}: {e.reason}") from None


def cmd_upload(args) -> dict:
    if not args.api_key:
        raise CliError("an API key is required (--api-key or RATATOSK_API_KEY)")
    tmp = None
    if args.stdin:
        name = args.name or "stdin.bin"
        fd, tmp = tempfile.mkstemp(prefix="ratatosk-")
        with os.fdopen(fd, "wb") as out:
            while True:
                block = sys.stdin.buffer.read(1024 * 1024)
                if not block:
                    break
                out.write(block)
        path = tmp
    else:
        if not args.file or not os.path.isfile(args.file):
            raise CliError(f"no such file: {args.file}")
        path, name = args.file, args.name or os.path.basename(args.file)
    try:
        enc = StreamEncryptor(path, name, "application/octet-stream", args.password)
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else None
        init = api_request(args.server, "/api/uploads/init", args.api_key, "POST", {"total_size_bytes": enc.size, "extension": ext})
        upload_id, chunk_size = init["upload_id"], init["chunk_size_bytes"]
        if not args.json:
            print(f"Encrypting and uploading {name} ({enc.size:,} bytes encrypted)...", file=sys.stderr)
        for offset, chunk in iter_upload_chunks(enc.chunks(), chunk_size):
            api_request(args.server, f"/api/uploads/{upload_id}/chunk", args.api_key, "PUT", chunk, raw=True,
                        headers={"Upload-Offset": str(offset)})
        complete = api_request(args.server, f"/api/uploads/{upload_id}/complete", args.api_key, "POST", {
            "ttl": args.ttl,
            "burn_after_download": args.burn,
            "max_downloads": args.max_downloads,
            "download_token_hash": enc.token_hash,
            "passphrase_protected": bool(args.password),
            "kdf_salt": enc.kdf_salt,
            "kdf_iterations": enc.kdf_iterations,
        })
    finally:
        if tmp:
            os.remove(tmp)
    link = f"{args.server.rstrip('/')}/share/{complete['file_id']}"
    if enc.url_key:
        link += f"#{enc.url_key}"
    return {"file_id": complete["file_id"], "link": link, "expires_at": complete["expires_at"], "passphrase": bool(args.password)}


def cmd_download(args) -> dict:
    parsed = urllib.parse.urlsplit(args.link)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[-2] != "share":
        raise CliError("expected a share link like https://host/share/<id>#<key>")
    server = f"{parsed.scheme}://{parsed.netloc}"
    file_id, url_key = parts[-1], (parsed.fragment or None)
    meta = api_request(server, f"/api/files/{file_id}/meta", args.api_key)
    headers = {}
    if meta["auth_scheme"] == "token":
        if meta.get("requires_password"):
            if not args.password:
                raise CliError("this file needs a passphrase (--password)")
            secret = _pbkdf2(args.password, b64url_decode(meta["kdf_salt"]), meta["kdf_iterations"])
        else:
            if not url_key:
                raise CliError("the link is missing its #key part")
            secret = b64url_decode(url_key)
        token = derive_from_secret(secret)[1]
        # Check the key before downloading, so a wrong one never burns the file.
        api_request(server, f"/api/files/{file_id}/verify-token", args.api_key, "POST", {"token": token})
        headers["X-Download-Token"] = token
    elif meta["auth_scheme"] == "legacy_password":
        raise CliError("this is an older passphrase file - download it in the browser")

    resp = api_request(server, f"/api/files/{file_id}/blob", args.api_key, headers=headers, stream=True)
    dec = StreamDecryptor(url_key, args.password)
    envelope = bytearray()
    meta_out: dict | None = None
    out_fh = None
    out_path = args.output
    written = 0

    def handle(plain: bytes):
        nonlocal meta_out, out_fh, out_path, written
        if meta_out is None:
            envelope.extend(plain)
            if len(envelope) < 4:
                return
            jlen = int.from_bytes(envelope[:4], "little")
            if len(envelope) < 4 + jlen:
                return
            meta_out = json.loads(envelope[4:4 + jlen])
            out_path = out_path or os.path.basename(meta_out.get("name") or f"{file_id}.bin")
            if out_path == "-":
                out_fh = sys.stdout.buffer
            else:
                if os.path.exists(out_path) and not args.force:
                    raise CliError(f"{out_path} exists (use --force to overwrite)")
                out_fh = open(out_path + ".part", "wb")
            rest = bytes(envelope[4 + jlen:])
            envelope.clear()
            if rest:
                out_fh.write(rest)
                written += len(rest)
            return
        if out_fh is None:
            raise CliError("Decryption failed - the file is corrupted")
        out_fh.write(plain)
        written += len(plain)

    try:
        with resp:
            while True:
                block = resp.read(1024 * 1024)
                if not block:
                    break
                for plain in dec.feed(block):
                    handle(plain)
            for plain in dec.feed(b"", final=True):
                handle(plain)
        if out_fh is None:
            raise CliError("Decryption failed - the file is corrupted")
    except BaseException:
        if out_fh not in (None, sys.stdout.buffer):
            out_fh.close()
            os.remove(out_path + ".part")
        raise
    if out_fh is not sys.stdout.buffer:
        out_fh.close()
        os.replace(out_path + ".part", out_path)
    name = (meta_out or {}).get("name")
    return {"file_id": file_id, "name": name, "saved_to": out_path, "bytes": written}


def _sri(data: bytes) -> str:
    return "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode()


def verify_manifest(manifest: dict, fetch, expect_digest: str | None) -> dict:
    """Check a server's frontend against its published release (FEAT-012).

    `fetch(path) -> bytes` downloads what the server really serves. Passes
    only if every file matches the manifest *and* the manifest's digest
    equals the one published for that release - the server can't satisfy
    both while serving modified code."""
    files = manifest.get("files") or {}
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    mismatched = []
    for path, expected in sorted(files.items()):
        url_path = path.replace("/share/_", "/share/00000000-0000-0000-0000-000000000000").replace("/r/_", "/r/00000000-0000-0000-0000-000000000000")
        try:
            actual = _sri(fetch(url_path))
        except CliError as e:
            mismatched.append(f"{path} (unreachable: {e})")
            continue
        if actual != expected:
            mismatched.append(path)
    digest_ok = expect_digest is None or digest == expect_digest.strip().lower()
    return {
        "version": manifest.get("version"),
        "release_digest": digest,
        "files_checked": len(files),
        "mismatched": mismatched,
        "digest_matches_published": digest_ok if expect_digest else None,
        "ok": not mismatched and digest_ok and bool(files),
    }


def cmd_verify(args) -> dict:
    server = args.url.rstrip("/")
    manifest = api_request(server, "/api/integrity", None)

    def fetch(path: str) -> bytes:
        if urllib.parse.urlsplit(server).scheme not in ("http", "https"):
            raise CliError("server must be an http(s) URL")
        req = urllib.request.Request(server + path, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310 - scheme checked above
                return resp.read()
        except urllib.error.URLError as e:
            raise CliError(str(e)) from None

    result = verify_manifest(manifest, fetch, args.expect)
    if not args.expect and not args.json:
        print("note: without --expect this only proves the server is self-consistent; pass the release digest "
              "published for this version (CHANGELOG.md) to prove it serves the genuine release.", file=sys.stderr)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ratatosk", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"ratatosk {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("upload", help="encrypt and upload a file")
    up.add_argument("file", nargs="?", help="file to upload (omit with --stdin)")
    up.add_argument("--server", required=True, help="base URL, e.g. https://drop.example.com")
    up.add_argument("--api-key", default=os.environ.get("RATATOSK_API_KEY") or os.environ.get("SECUREDROP_API_KEY"))
    up.add_argument("--ttl", default="24h", help="expiry preset, e.g. 10m/1h/24h/7d/30d (must be allowed by the server)")
    up.add_argument("--password", default=None, help="derive the key from a passphrase instead of putting it in the link")
    up.add_argument("--max-downloads", type=int, default=0, help="0 = unlimited")
    up.add_argument("--burn", action="store_true", help="delete immediately after the first download")
    up.add_argument("--stdin", action="store_true", help="read the data from standard input")
    up.add_argument("--name", help="filename the recipient sees (defaults to the file's name)")
    up.add_argument("--json", action="store_true", help="print the result as JSON")

    down = sub.add_parser("download", help="download and decrypt a share link")
    down.add_argument("link", help="share link, including its #key part unless passphrase-protected")
    down.add_argument("--password", default=None, help="passphrase for passphrase-protected files")
    down.add_argument("-o", "--output", help="where to save (default: original filename; '-' for stdout)")
    down.add_argument("--force", action="store_true", help="overwrite an existing output file")
    down.add_argument("--api-key", default=os.environ.get("RATATOSK_API_KEY") or os.environ.get("SECUREDROP_API_KEY"),
                      help="only needed if the server disallows anonymous downloads")
    down.add_argument("--json", action="store_true", help="print the result as JSON")

    ver = sub.add_parser("verify", help="check that a server serves an unmodified release of the web app")
    ver.add_argument("url", help="base URL of the server, e.g. https://drop.example.com")
    ver.add_argument("--expect", help="release digest published for this version (see CHANGELOG.md)")
    ver.add_argument("--json", action="store_true", help="print the result as JSON")

    args = parser.parse_args(argv)
    try:
        if args.command == "upload":
            result = cmd_upload(args)
        elif args.command == "download":
            result = cmd_download(args)
        else:
            result = cmd_verify(args)
    except CliError as e:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(e)}))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result))
    elif args.command == "verify":
        if result["ok"]:
            print(f"OK: {result['files_checked']} files match release {result['version']} (digest {result['release_digest']})")
        else:
            for path in result["mismatched"]:
                print(f"MODIFIED: {path}")
            if result["digest_matches_published"] is False:
                print(f"DIGEST MISMATCH: server's manifest digest is {result['release_digest']}, not the published one")
    elif args.command == "upload":
        print(f"Done. Expires: {result['expires_at']}")
        print(f"Share link: {result['link']}")
        if result["passphrase"]:
            print("This file needs the passphrase you chose - share it with the recipient separately from the link.")
    else:
        print(f"Saved {result['name']!r} to {result['saved_to']} ({result['bytes']:,} bytes)", file=sys.stderr)
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
