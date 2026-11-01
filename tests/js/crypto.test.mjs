// Tests for frontend/static/js/crypto.js, run with: node --test tests/js/
// Node's built-in WebCrypto/Blob are the same APIs the browser exposes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function loadCrypto(file) {
  const ctx = { crypto: globalThis.crypto, Blob, TextEncoder, TextDecoder, btoa, atob, Uint8Array, DataView };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(readFileSync(file, "utf8"), ctx);
  return ctx.window.SDCrypto;
}

const SD = loadCrypto(path.join(ROOT, "frontend/static/js/crypto.js"));
const SEG = 1024 * 1024;

function bytes(n, seed = 7) {
  const out = new Uint8Array(n);
  let x = seed;
  for (let i = 0; i < n; i++) { x = (x * 1103515245 + 12345) >>> 0; out[i] = x >>> 24; }
  return out;
}

async function encrypt(data, password = null, name = "f.bin") {
  const enc = await SD.createEncryptor(new Blob([data]), name, "application/x-test", password);
  const parts = [];
  for await (const c of enc.chunks(0)) parts.push(c);
  const blob = new Uint8Array(await new Blob(parts).arrayBuffer());
  assert.equal(blob.byteLength, enc.size, "declared size must match actual ciphertext size");
  return { blob, urlKey: enc.urlKey, enc };
}

// Feed ciphertext in arbitrary-sized pieces, like a network stream would.
async function* pieces(u8, size) {
  for (let i = 0; i < u8.byteLength; i += size) yield u8.subarray(i, i + size);
}

async function plainOf(result) {
  return new Uint8Array(await result.blob.arrayBuffer());
}

for (const n of [0, 1, SEG - 40, SEG, 2 * SEG, Math.floor(3.5 * SEG)]) {
  test(`random-key round trip, ${n} bytes`, async () => {
    const data = bytes(n);
    const { blob, urlKey } = await encrypt(data);
    const res = await SD.decryptStream(pieces(blob, 65537), urlKey, null);
    assert.equal(res.name, "f.bin");
    assert.equal(res.type, "application/x-test");
    assert.equal(res.size, n);
    assert.deepEqual(await plainOf(res), data);
  });
}

test("passphrase round trip, and wrong passphrase fails", async () => {
  const data = bytes(SEG + 123);
  const { blob, urlKey } = await encrypt(data, "correct horse");
  assert.equal(urlKey, null);
  const res = await SD.decryptDownload(blob, null, "correct horse");
  assert.deepEqual(await plainOf(res), data);
  await assert.rejects(SD.decryptDownload(blob, null, "wrong"), /Decryption failed/);
  await assert.rejects(SD.decryptDownload(blob, null, null), /requires a passphrase/);
});

test("unicode filename survives", async () => {
  const { blob, urlKey } = await encrypt(bytes(10), null, "räksmörgås 📄.pdf");
  assert.equal((await SD.decryptDownload(blob, urlKey, null)).name, "räksmörgås 📄.pdf");
});

const HEADER = 1 + 4 + 8; // link-mode header (flag 0x05)
const SEALED = SEG + 16;

test("truncating trailing segments is detected", async () => {
  const { blob, urlKey } = await encrypt(bytes(3 * SEG));
  // Drop the final segment: the new last one was sealed as non-final.
  const truncated = blob.subarray(0, HEADER + 3 * SEALED);
  await assert.rejects(SD.decryptDownload(truncated, urlKey, null), /Decryption failed/);
});

test("reordering segments is detected", async () => {
  const { blob, urlKey } = await encrypt(bytes(3 * SEG));
  const swapped = new Uint8Array(blob);
  swapped.set(blob.subarray(HEADER + SEALED, HEADER + 2 * SEALED), HEADER);
  swapped.set(blob.subarray(HEADER, HEADER + SEALED), HEADER + SEALED);
  await assert.rejects(SD.decryptDownload(swapped, urlKey, null), /Decryption failed/);
});

test("tampering with the header is detected", async () => {
  const { blob, urlKey } = await encrypt(bytes(100));
  const tampered = new Uint8Array(blob);
  tampered[HEADER - 1] ^= 1; // flip a nonce-prefix bit
  await assert.rejects(SD.decryptDownload(tampered, urlKey, null), /Decryption failed/);
});

test("flipping a ciphertext bit is detected", async () => {
  const { blob, urlKey } = await encrypt(bytes(100));
  const tampered = new Uint8Array(blob);
  tampered[HEADER + 5] ^= 1;
  await assert.rejects(SD.decryptDownload(tampered, urlKey, null), /Decryption failed/);
});

test("files written by the first segmented format (0x03/0x04) still decrypt", async () => {
  const v2 = loadCrypto(path.join(ROOT, "tests/js/fixtures/crypto_v2.js"));
  const data = bytes(2 * SEG + 9);
  for (const pw of [null, "v2-pass"]) {
    const { blob, urlKey } = await v2.encryptForUpload(data.buffer, "v2.bin", "application/x-v2", pw);
    const buf = new Uint8Array(await blob.arrayBuffer());
    assert.equal(buf[0], pw ? 0x04 : 0x03);
    const res = await SD.decryptStream(pieces(buf, 70000), urlKey, pw);
    assert.equal(res.name, "v2.bin");
    assert.deepEqual(await plainOf(res), data);
  }
});

test("new uploads use the HKDF format and a download token unrelated to the key", async () => {
  const { blob, urlKey, enc } = await encrypt(bytes(10));
  assert.equal(blob[0], 0x05);
  assert.notEqual(enc.downloadToken, urlKey);
  assert.equal(await SD.deriveDownloadToken({ urlKey }), enc.downloadToken);
  assert.equal(enc.tokenHash, await SD.sha256Hex(enc.downloadToken));

  const p = await encrypt(bytes(10), "pass phrase");
  assert.equal(p.blob[0], 0x06);
  assert.equal(p.urlKey, null);
  const token = await SD.deriveDownloadToken({ password: "pass phrase", kdfSalt: p.enc.kdfSalt, kdfIterations: p.enc.kdfIterations });
  assert.equal(token, p.enc.downloadToken);
  const wrong = await SD.deriveDownloadToken({ password: "wrong", kdfSalt: p.enc.kdfSalt, kdfIterations: p.enc.kdfIterations });
  assert.notEqual(wrong, p.enc.downloadToken);
});

test("encryption can resume at any byte offset with identical ciphertext", async () => {
  const data = bytes(3 * SEG + 777);
  const { blob, enc } = await encrypt(data);
  const again = await SD.createEncryptor(new Blob([data]), "f.bin", "application/x-test", null, { resume: enc.resumeState });
  for (const offset of [0, 5, 13, 14, SEG, SEG + 13 + 16, 2 * (SEG + 16) + 13 + 100, blob.byteLength - 1]) {
    const parts = [];
    for await (const c of again.chunks(offset)) parts.push(c);
    const tail = new Uint8Array(await new Blob(parts).arrayBuffer());
    assert.deepEqual(tail, blob.subarray(offset), `resume at ${offset}`);
  }
  assert.equal(again.downloadToken, enc.downloadToken);
});

test("passphrase uploads resume too (passphrase re-entered)", async () => {
  const data = bytes(SEG + 50);
  const { blob, enc } = await encrypt(data, "resume me");
  const again = await SD.createEncryptor(new Blob([data]), "f.bin", "application/x-test", "resume me", { resume: enc.resumeState });
  const parts = [];
  for await (const c of again.chunks(SEG)) parts.push(c);
  assert.deepEqual(new Uint8Array(await new Blob(parts).arrayBuffer()), blob.subarray(SEG));
});

test("text sends carry kind=text", async () => {
  const enc = await SD.createEncryptor(new Blob(["hej då"]), "message.txt", "text/plain", null, { kind: "text" });
  const parts = [];
  for await (const c of enc.chunks(0)) parts.push(c);
  const res = await SD.decryptDownload(new Uint8Array(await new Blob(parts).arrayBuffer()), enc.urlKey, null);
  assert.equal(res.kind, "text");
  assert.equal(await res.blob.text(), "hej då");
});

test("decrypted bytes can stream to a sink instead of memory", async () => {
  const data = bytes(2 * SEG + 3);
  const { blob, urlKey } = await encrypt(data);
  const got = [];
  let closed = false, seenMeta = null;
  const res = await SD.decryptStream(pieces(blob, 50000), urlKey, null, {
    onMeta: (m) => { seenMeta = m; return { write: (u8) => { got.push(u8.slice()); }, close: () => { closed = true; } }; },
  });
  assert.equal(res.streamed, true);
  assert.equal(res.blob, null);
  assert.equal(seenMeta.name, "f.bin");
  assert.ok(closed);
  assert.deepEqual(new Uint8Array(await new Blob(got).arrayBuffer()), data);
});

test("files written by the previous (single-shot) format still decrypt", async () => {
  // The original single-shot crypto.js is preserved here as a fixture.
  const legacy = loadCrypto(path.join(ROOT, "tests/js/fixtures/crypto_v1.js"));
  const data = bytes(2 * SEG + 5);
  for (const pw of [null, "legacy-pass"]) {
    const { blob, urlKey } = await legacy.encryptForUpload(data.buffer, "old.txt", "text/plain", pw);
    const buf = new Uint8Array(await blob.arrayBuffer());
    const res = await SD.decryptStream(pieces(buf, 4096), urlKey, pw);
    assert.equal(res.name, "old.txt");
    assert.deepEqual(await plainOf(res), data);
  }
});

test("blobs produced by the Python CLI decrypt in the browser code", async (t) => {
  const py = path.join(ROOT, ".venv/bin/python");
  let out;
  try {
    out = execFileSync(py, ["-I", path.join(ROOT, "tests/js/cli_encrypt_fixture.py")], { maxBuffer: 64 << 20 });
  } catch {
    t.skip("project .venv with 'cryptography' not available");
    return;
  }
  for (const c of JSON.parse(out)) {
    const blob = Uint8Array.from(Buffer.from(c.blob_b64, "base64"));
    const res = await SD.decryptDownload(blob, c.url_key, c.password);
    assert.equal(res.name, c.name);
    // Both clients must derive the same download token from the same secret.
    const token = await SD.deriveDownloadToken({ urlKey: c.url_key, password: c.password, kdfSalt: c.kdf_salt, kdfIterations: c.kdf_iterations });
    assert.equal(token, c.download_token);
    assert.deepEqual(await plainOf(res), Uint8Array.from(Buffer.from(c.plain_b64, "base64")));
  }
});
