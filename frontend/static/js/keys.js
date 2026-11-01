/*
 * Ratatosk account encryption keys (FEAT-001 / FEAT-002).
 *
 * Each account can have an ECDH P-256 keypair. The private key is encrypted
 * ("wrapped") here in the browser with AES-GCM under a key derived by
 * PBKDF2-SHA256 (600,000 iterations) from the user's *encryption
 * passphrase*. That passphrase never leaves the browser - deliberately not
 * the login password, which the server sees when you sign in. The server
 * stores the public key and the wrapped private key; it can't open either
 * for anyone.
 *
 * File secrets are wrapped to a recipient with ECDH-ES:
 *   ephemeral keypair E;  Z = ECDH(E.private, recipient.public)
 *   KEK = HKDF-SHA256(Z, salt = empty, info = "ratatosk-wrap-v1" || E.public || recipient.public)
 *   wrapped = iv(12) || AES-GCM(KEK, iv, secret)
 * Binding both public keys into the KEK means a wrapped key can't be
 * replayed against a different recipient or ephemeral key.
 *
 * Unlocked private keys can optionally be remembered on this device, as a
 * *non-extractable* CryptoKey in IndexedDB: usable for unwrapping, but not
 * exportable even by the page's own scripts. Logging out forgets them.
 */
(function () {
  const ITERATIONS = 600000;
  const WRAP_INFO = new TextEncoder().encode("ratatosk-wrap-v1");
  const EC = { name: "ECDH", namedCurve: "P-256" };
  const DB_NAME = "ratatosk-keys";

  const enc = (b) => window.SDCrypto.b64urlEncode(b);
  const dec = (s) => window.SDCrypto.b64urlDecode(s);
  const rnd = (n) => crypto.getRandomValues(new Uint8Array(n));

  function concat(...parts) {
    const out = new Uint8Array(parts.reduce((n, p) => n + p.byteLength, 0));
    let o = 0;
    for (const p of parts) { out.set(new Uint8Array(p), o); o += p.byteLength; }
    return out;
  }

  async function passphraseKey(passphrase, salt, iterations) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(passphrase), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations, hash: "SHA-256" }, base,
      { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  }

  async function fingerprint(publicKeyB64) {
    const digest = await crypto.subtle.digest("SHA-256", dec(publicKeyB64));
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function wrapPrivate(pkcs8, passphrase) {
    const salt = rnd(16);
    const key = await passphraseKey(passphrase, salt, ITERATIONS);
    const iv = rnd(12);
    const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, pkcs8);
    return { wrapped_private_key: enc(concat(iv, ct)), kdf_salt: enc(salt), kdf_iterations: ITERATIONS };
  }

  async function importPrivate(pkcs8) {
    return crypto.subtle.importKey("pkcs8", pkcs8, EC, false, ["deriveBits"]);
  }

  /** New keypair, wrapped with `passphrase`. Returns the material to store
   * on the server plus the unlocked (non-extractable) private key. */
  async function generate(passphrase) {
    const pair = await crypto.subtle.generateKey(EC, true, ["deriveBits"]);
    const spki = new Uint8Array(await crypto.subtle.exportKey("spki", pair.publicKey));
    const pkcs8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
    const wrapped = await wrapPrivate(pkcs8, passphrase);
    const public_key = enc(spki);
    const privateKey = await importPrivate(pkcs8);
    pkcs8.fill(0);
    return { material: { public_key, ...wrapped }, fingerprint: await fingerprint(public_key), privateKey };
  }

  async function decryptPkcs8(material, passphrase) {
    const blob = dec(material.wrapped_private_key);
    const key = await passphraseKey(passphrase, dec(material.kdf_salt), material.kdf_iterations);
    try {
      return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: blob.slice(0, 12) }, key, blob.slice(12)));
    } catch (e) {
      throw new Error("Wrong encryption passphrase.");
    }
  }

  /** Unlock the stored private key with the passphrase. */
  async function unlock(material, passphrase) {
    const pkcs8 = await decryptPkcs8(material, passphrase);
    const key = await importPrivate(pkcs8);
    pkcs8.fill(0);
    return key;
  }

  /** Same keypair, new passphrase. */
  async function rewrap(material, oldPassphrase, newPassphrase) {
    const pkcs8 = await decryptPkcs8(material, oldPassphrase);
    const wrapped = await wrapPrivate(pkcs8, newPassphrase);
    pkcs8.fill(0);
    return { public_key: material.public_key, ...wrapped };
  }

  async function kek(privateKey, peerPublic, ephSpki, recipientSpki) {
    const bits = await crypto.subtle.deriveBits({ name: "ECDH", public: peerPublic }, privateKey, 256);
    const ikm = await crypto.subtle.importKey("raw", bits, "HKDF", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: new Uint8Array(0), info: concat(WRAP_INFO, ephSpki, recipientSpki) },
      ikm, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  }

  /** Wrap a file secret (Uint8Array) to a recipient's public key. */
  async function wrapSecret(secret, recipientPublicB64) {
    const recipientSpki = dec(recipientPublicB64);
    const recipient = await crypto.subtle.importKey("spki", recipientSpki, EC, false, []);
    const eph = await crypto.subtle.generateKey(EC, true, ["deriveBits"]);
    const ephSpki = new Uint8Array(await crypto.subtle.exportKey("spki", eph.publicKey));
    const key = await kek(eph.privateKey, recipient, ephSpki, recipientSpki);
    const iv = rnd(12);
    const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, secret);
    return { wrapped_key: enc(concat(iv, ct)), ephemeral_public_key: enc(ephSpki) };
  }

  /** Unwrap a file secret with our private key. */
  async function unwrapSecret(wrappedB64, ephemeralPublicB64, privateKey, ownPublicB64) {
    const ephSpki = dec(ephemeralPublicB64);
    const eph = await crypto.subtle.importKey("spki", ephSpki, EC, false, []);
    const key = await kek(privateKey, eph, ephSpki, dec(ownPublicB64));
    const blob = dec(wrappedB64);
    try {
      return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: blob.slice(0, 12) }, key, blob.slice(12)));
    } catch (e) {
      throw new Error("This file's key couldn't be unlocked with your keys.");
    }
  }

  // ---- per-device cache of unlocked (non-extractable) keys ---------------
  function idb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore("keys");
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  async function store(mode, fn) {
    try {
      const db = await idb();
      return await new Promise((resolve, reject) => {
        const tx = db.transaction("keys", mode);
        const r = fn(tx.objectStore("keys"));
        tx.oncomplete = () => resolve(r && r.result);
        tx.onerror = () => reject(tx.error);
      });
    } catch (e) { return null; }
  }
  const remember = (userId, fingerprintHex, key) => store("readwrite", (s) => s.put({ key, fingerprint: fingerprintHex }, userId));
  const recall = (userId) => store("readonly", (s) => s.get(userId));
  const forgetAll = () => store("readwrite", (s) => s.clear());

  window.SDKeys = { ITERATIONS, generate, unlock, rewrap, wrapSecret, unwrapSecret, fingerprint, remember, recall, forgetAll };
})();
