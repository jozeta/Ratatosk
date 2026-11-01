"""Emits CLI-encrypted blobs as JSON for crypto.test.mjs to decrypt with the
browser code - proves cli/securedrop_upload.py and crypto.js agree on the
wire format. Not a pytest module (no test_ prefix)."""
import base64
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "cli"))
from ratatosk import SEGMENT_SIZE, StreamEncryptor  # noqa: E402


def case(data: bytes, name: str, password):
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(data)
    try:
        enc = StreamEncryptor(f.name, name, "application/octet-stream", password)
        blob = b"".join(enc.chunks())
        assert len(blob) == enc.size, (len(blob), enc.size)
    finally:
        os.unlink(f.name)
    return {
        "name": name,
        "password": password,
        "url_key": enc.url_key,
        "blob_b64": base64.b64encode(blob).decode(),
        "download_token": enc.download_token,
        "kdf_salt": enc.kdf_salt,
        "kdf_iterations": enc.kdf_iterations,
        "plain_b64": base64.b64encode(data).decode(),
    }


def boundary_size(name: str) -> int:
    """File size that makes the plaintext envelope end exactly on a segment
    boundary - the edge case where an off-by-one would add an empty segment."""
    meta = json.dumps({"name": name, "type": "application/octet-stream", "size": 0}).encode()
    for size in range(2 * SEGMENT_SIZE - len(meta) - 64, 2 * SEGMENT_SIZE):
        m = json.dumps({"name": name, "type": "application/octet-stream", "size": size}).encode()
        if 4 + len(m) + size == 2 * SEGMENT_SIZE:
            return size
    raise RuntimeError("no boundary size found")


rnd = os.urandom
cases = [
    case(b"", "empty.txt", None),
    case(rnd(1000), "small.bin", None),
    case(rnd(boundary_size("edge.bin")), "edge.bin", None),
    case(rnd(int(3.5 * SEGMENT_SIZE)), "räksmörgås.bin", None),
    case(rnd(SEGMENT_SIZE + 7), "pw.bin", "hunter2-but-longer"),
]
json.dump(cases, sys.stdout)
