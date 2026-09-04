#!/usr/bin/env python3
"""SecureDrop CLI uploader.

Encrypts a file client-side (same AES-256-GCM wire format the browser
produces) and uploads it via a SecureDrop API key, without ever sending
plaintext or the decryption key to the server.

Usage:
    python cli/securedrop_upload.py --server https://drop.example.com \\
        --api-key sdk_... --ttl 24h path/to/file.pdf

    # or set the key once:
    export SECUREDROP_API_KEY=sdk_...
    python cli/securedrop_upload.py --server https://drop.example.com report.pdf

Create an API key from the web UI at /account, or:
    curl -X POST https://drop.example.com/api/account/api-keys \\
        -H "Authorization: Bearer <your session token>" \\
        -H "Content-Type: application/json" -d '{"name": "my-laptop"}'

Requires: pip install cryptography
"""
import argparse
import base64
import json
import os
import secrets
import sys
import urllib.error
import urllib.request

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:
    print("error: this script needs the 'cryptography' package: pip install cryptography", file=sys.stderr)
    sys.exit(1)

FLAG_RANDOM_KEY = 0x01
FLAG_PASSPHRASE = 0x02
PBKDF2_ITERATIONS = 250000


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_envelope(file_bytes: bytes, name: str, mime_type: str) -> bytes:
    """[4-byte LE JSON length][JSON {name,type,size}][raw file bytes] - must
    match frontend/static/js/crypto.js's buildPlaintextEnvelope exactly."""
    meta = json.dumps({"name": name, "type": mime_type, "size": len(file_bytes)}).encode("utf-8")
    return len(meta).to_bytes(4, "little") + meta + file_bytes


def encrypt_for_upload(file_bytes: bytes, name: str, mime_type: str, password: str | None):
    """Returns (blob_bytes, url_key_or_None). Wire format must match
    crypto.js's encryptForUpload exactly: [flag][salt+iters if passphrase][12-byte IV][ciphertext]."""
    envelope = build_envelope(file_bytes, name, mime_type)
    iv = secrets.token_bytes(12)

    if password:
        salt = secrets.token_bytes(16)
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
        key = kdf.derive(password.encode("utf-8"))
        header = bytes([FLAG_PASSPHRASE]) + salt + PBKDF2_ITERATIONS.to_bytes(4, "little")
        url_key = None
    else:
        key = secrets.token_bytes(32)
        header = bytes([FLAG_RANDOM_KEY])
        url_key = b64url_encode(key)

    ciphertext = AESGCM(key).encrypt(iv, envelope, None)
    return header + iv + ciphertext, url_key


def api_request(server: str, path: str, api_key: str, method: str = "GET", data=None, raw: bool = False):
    url = server.rstrip("/") + path
    headers = {"Authorization": f"Bearer {api_key}"}
    body = None
    if data is not None:
        if raw:
            body = data
            headers["Content-Type"] = "application/octet-stream"
        else:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw_body = resp.read()
            return json.loads(raw_body) if raw_body else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"error: {method} {path} -> HTTP {e.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"error: could not reach {server}: {e.reason}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="Path to the file to upload")
    parser.add_argument("--server", required=True, help="Base URL, e.g. https://drop.example.com")
    parser.add_argument("--api-key", default=os.environ.get("SECUREDROP_API_KEY"), help="API key (or set SECUREDROP_API_KEY)")
    parser.add_argument("--ttl", default="24h", help="Expiration preset, e.g. 10m/1h/24h/7d/30d (must be allowed by server policy)")
    parser.add_argument("--password", default=None, help="Optional secondary passphrase - the key is derived from it instead of a random link key")
    parser.add_argument("--max-downloads", type=int, default=0, help="0 = unlimited")
    parser.add_argument("--burn", action="store_true", help="Delete immediately after the first download")
    args = parser.parse_args()

    if not args.api_key:
        print("error: an API key is required (--api-key or SECUREDROP_API_KEY)", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(args.file):
        print(f"error: no such file: {args.file}", file=sys.stderr)
        sys.exit(1)

    name = os.path.basename(args.file)
    with open(args.file, "rb") as f:
        file_bytes = f.read()

    print(f"Encrypting {name} ({len(file_bytes):,} bytes)...")
    blob, url_key = encrypt_for_upload(file_bytes, name, "application/octet-stream", args.password)

    ext = name.rsplit(".", 1)[-1].lower() if "." in name else None
    init = api_request(args.server, "/api/uploads/init", args.api_key, "POST", {
        "total_size_bytes": len(blob), "extension": ext,
    })
    upload_id = init["upload_id"]
    chunk_size = init["chunk_size_bytes"]

    print(f"Uploading ({len(blob):,} bytes encrypted)...")
    offset = 0
    while offset < len(blob):
        chunk = blob[offset: offset + chunk_size]
        api_request(args.server, f"/api/uploads/{upload_id}/chunk", args.api_key, "PUT", chunk, raw=True)
        offset += len(chunk)

    complete = api_request(args.server, f"/api/uploads/{upload_id}/complete", args.api_key, "POST", {
        "ttl": args.ttl,
        "burn_after_download": args.burn,
        "max_downloads": args.max_downloads,
        "password": args.password,
    })

    link = f"{args.server.rstrip('/')}/share/{complete['file_id']}"
    if url_key:
        link += f"#{url_key}"

    print()
    print(f"Done. Expires: {complete['expires_at']}")
    print(f"Share link: {link}")
    if args.password:
        print("This file requires the passphrase you supplied - share it with the recipient separately from the link.")


if __name__ == "__main__":
    main()
