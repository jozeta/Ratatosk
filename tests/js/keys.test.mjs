// Tests for frontend/static/js/keys.js (FEAT-001/FEAT-002).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ctx = { crypto: globalThis.crypto, Blob, TextEncoder, TextDecoder, btoa, atob, Uint8Array, DataView };
ctx.window = ctx;
vm.createContext(ctx);
for (const f of ["crypto.js", "keys.js"]) vm.runInContext(readFileSync(path.join(ROOT, "frontend/static/js", f), "utf8"), ctx);
const K = ctx.window.SDKeys;
const C = ctx.window.SDCrypto;

test("keypair round trip: wrap a file secret to a recipient and unwrap it", async () => {
  const alice = await K.generate("alice's long passphrase");
  assert.match(alice.fingerprint, /^[0-9a-f]{64}$/);
  assert.equal(alice.fingerprint, await K.fingerprint(alice.material.public_key));

  const secret = C.randomBytes(32);
  const wrapped = await K.wrapSecret(secret, alice.material.public_key);
  const unlocked = await K.unlock(alice.material, "alice's long passphrase");
  const out = await K.unwrapSecret(wrapped.wrapped_key, wrapped.ephemeral_public_key, unlocked, alice.material.public_key);
  assert.deepEqual(out, secret);
});

test("the unlocked private key can't be exported", async () => {
  const alice = await K.generate("pw pw pw pw");
  const key = await K.unlock(alice.material, "pw pw pw pw");
  assert.equal(key.extractable, false);
  await assert.rejects(crypto.subtle.exportKey("pkcs8", key));
});

test("wrong passphrase is rejected", async () => {
  const alice = await K.generate("right passphrase");
  await assert.rejects(K.unlock(alice.material, "wrong passphrase"), /Wrong encryption passphrase/);
});

test("another user's key can't unwrap, and tampering is detected", async () => {
  const alice = await K.generate("alice pass 1");
  const mallory = await K.generate("mallory pass 1");
  const wrapped = await K.wrapSecret(C.randomBytes(32), alice.material.public_key);
  const malKey = await K.unlock(mallory.material, "mallory pass 1");
  await assert.rejects(K.unwrapSecret(wrapped.wrapped_key, wrapped.ephemeral_public_key, malKey, mallory.material.public_key));

  const aliceKey = await K.unlock(alice.material, "alice pass 1");
  const bytes = C.b64urlDecode(wrapped.wrapped_key);
  bytes[20] ^= 1;
  await assert.rejects(K.unwrapSecret(C.b64urlEncode(bytes), wrapped.ephemeral_public_key, aliceKey, alice.material.public_key));
});

test("wraps are bound to the recipient key (no cross-recipient replay)", async () => {
  const alice = await K.generate("alice pass 2");
  const bob = await K.generate("bob pass 2");
  const wrapped = await K.wrapSecret(C.randomBytes(32), alice.material.public_key);
  const aliceKey = await K.unlock(alice.material, "alice pass 2");
  // Same private key, but claiming Bob's public key as "ours" changes the KEK.
  await assert.rejects(K.unwrapSecret(wrapped.wrapped_key, wrapped.ephemeral_public_key, aliceKey, bob.material.public_key));
});

test("changing the passphrase keeps the keypair", async () => {
  const alice = await K.generate("old passphrase!");
  const wrapped = await K.wrapSecret(C.randomBytes(32), alice.material.public_key);
  const rewrapped = await K.rewrap(alice.material, "old passphrase!", "new passphrase!");
  assert.equal(rewrapped.public_key, alice.material.public_key);
  await assert.rejects(K.unlock(rewrapped, "old passphrase!"));
  const key = await K.unlock(rewrapped, "new passphrase!");
  assert.equal((await K.unwrapSecret(wrapped.wrapped_key, wrapped.ephemeral_public_key, key, alice.material.public_key)).length, 32);
});
