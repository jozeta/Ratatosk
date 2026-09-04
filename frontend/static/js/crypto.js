/*
 * SecureDrop client-side crypto module.
 *
 * Zero-knowledge design: plaintext and decryption keys never leave the
 * browser. AES-256-GCM (Web Crypto SubtleCrypto) encrypts a small envelope
 * (original filename + mime type + file bytes) as a single unit, so the
 * server never learns the filename either.
 *
 * Two key-transport modes:
 *  - Direct-link mode: a random 256-bit key is generated, never sent to the
 *    server, and base64url-encoded into the URL hash fragment. Whoever holds
 *    the full link can decrypt; the server (which never sees the fragment)
 *    cannot.
 *  - Secondary-passphrase mode: the AES key itself is derived from a
 *    human-chosen passphrase via PBKDF2 (client-side). The URL fragment
 *    carries nothing secret; the recipient must separately be told the
 *    passphrase. The server additionally stores a bcrypt hash of the
 *    passphrase purely to rate-limit/lock out online guessing attempts
 *    against the download endpoint - it never learns the passphrase itself,
 *    and the bcrypt hash cannot be used to derive the encryption key.
 *
 * Blob wire format (what actually gets uploaded/stored/downloaded):
 *   [1 byte flag]  0x01 = random-key mode, 0x02 = passphrase mode
 *   if flag == 0x02: [16 bytes PBKDF2 salt][4 bytes LE iteration count]
 *   [12 bytes AES-GCM IV]
 *   [ciphertext ... ] (AES-GCM tag is appended by SubtleCrypto automatically)
 *
 * Plaintext envelope (before encryption):
 *   [4 bytes LE JSON length][JSON bytes: {name, type, size}][raw file bytes]
 */
(function () {
  // OWASP's current minimum for PBKDF2-HMAC-SHA256. Stored per-file in the
  // blob header (see format above), so raising this only affects new
  // uploads - existing files keep decrypting with whatever count they were
  // written with.
  const PBKDF2_ITERATIONS = 600000;
  const FLAG_RANDOM_KEY = 0x01;
  const FLAG_PASSPHRASE = 0x02;

  function b64urlEncode(buf) {
    const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function b64urlDecode(str) {
    let s = str.replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    const bin = atob(s);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  }

  function randomBytes(n) {
    return crypto.getRandomValues(new Uint8Array(n));
  }

  function concatBuffers(parts) {
    const total = parts.reduce((sum, p) => sum + p.byteLength, 0);
    const out = new Uint8Array(total);
    let offset = 0;
    for (const p of parts) {
      out.set(p instanceof Uint8Array ? p : new Uint8Array(p), offset);
      offset += p.byteLength;
    }
    return out;
  }

  async function importRawAesKey(rawBytes) {
    return crypto.subtle.importKey("raw", rawBytes, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
  }

  async function deriveKeyFromPassword(password, salt, iterations) {
    const baseKey = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(password),
      "PBKDF2",
      false,
      ["deriveKey"]
    );
    return crypto.subtle.deriveKey(
      { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
      baseKey,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"]
    );
  }

  function buildPlaintextEnvelope(fileBytes, name, type) {
    const json = JSON.stringify({ name, type, size: fileBytes.byteLength });
    const jsonBytes = new TextEncoder().encode(json);
    const lenPrefix = new Uint8Array(4);
    new DataView(lenPrefix.buffer).setUint32(0, jsonBytes.length, true);
    return concatBuffers([lenPrefix, jsonBytes, fileBytes]);
  }

  function parsePlaintextEnvelope(buf) {
    const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    const jsonLen = view.getUint32(0, true);
    const jsonBytes = buf.slice(4, 4 + jsonLen);
    const meta = JSON.parse(new TextDecoder().decode(jsonBytes));
    const fileBytes = buf.slice(4 + jsonLen);
    return { name: meta.name, type: meta.type, size: meta.size, fileBytes };
  }

  /**
   * Encrypt a file for upload.
   * @param {ArrayBuffer} fileBytes
   * @param {string} name
   * @param {string} type
   * @param {string|null} password - if provided, passphrase-derived key mode
   * @returns {Promise<{blob: Blob, urlKey: string|null}>}
   */
  async function encryptForUpload(fileBytes, name, type, password) {
    const envelope = buildPlaintextEnvelope(new Uint8Array(fileBytes), name, type);
    const iv = randomBytes(12);
    let key, header, urlKey;

    if (password) {
      const salt = randomBytes(16);
      key = await deriveKeyFromPassword(password, salt, PBKDF2_ITERATIONS);
      const iterBytes = new Uint8Array(4);
      new DataView(iterBytes.buffer).setUint32(0, PBKDF2_ITERATIONS, true);
      header = concatBuffers([new Uint8Array([FLAG_PASSPHRASE]), salt, iterBytes]);
      urlKey = null;
    } else {
      const rawKey = randomBytes(32);
      key = await importRawAesKey(rawKey);
      header = new Uint8Array([FLAG_RANDOM_KEY]);
      urlKey = b64urlEncode(rawKey);
    }

    const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, envelope);
    const blob = new Blob([header, iv, new Uint8Array(ciphertext)], { type: "application/octet-stream" });
    return { blob, urlKey };
  }

  /**
   * Decrypt a downloaded blob.
   * @param {ArrayBuffer} blobBuf
   * @param {string|null} urlKey - base64url raw key (random-key mode)
   * @param {string|null} password - passphrase (passphrase mode)
   */
  async function decryptDownload(blobBuf, urlKey, password) {
    const bytes = new Uint8Array(blobBuf);
    const flag = bytes[0];
    let offset = 1;
    let key;

    if (flag === FLAG_PASSPHRASE) {
      if (!password) throw new Error("This file requires a passphrase to decrypt.");
      const salt = bytes.slice(offset, offset + 16);
      offset += 16;
      const iterations = new DataView(bytes.buffer, bytes.byteOffset + offset, 4).getUint32(0, true);
      offset += 4;
      key = await deriveKeyFromPassword(password, salt, iterations);
    } else if (flag === FLAG_RANDOM_KEY) {
      if (!urlKey) throw new Error("Missing decryption key.");
      key = await importRawAesKey(b64urlDecode(urlKey));
    } else {
      throw new Error("Unrecognized file format.");
    }

    const iv = bytes.slice(offset, offset + 12);
    offset += 12;
    const ciphertext = bytes.slice(offset);

    let plaintext;
    try {
      plaintext = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ciphertext);
    } catch (e) {
      throw new Error("Decryption failed - wrong key/passphrase, or the file is corrupted.");
    }
    return parsePlaintextEnvelope(new Uint8Array(plaintext));
  }

  window.SDCrypto = {
    b64urlEncode,
    b64urlDecode,
    randomBytes,
    encryptForUpload,
    decryptDownload,
  };
})();
