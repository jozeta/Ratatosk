// Frozen copy of the first segmented crypto.js (flags 0x03/0x04, AES key = secret,
// no download token), kept only so tests prove those files still decrypt.
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
 * Blob wire format, segmented (written by all current uploads):
 *   [1 byte flag]  0x03 = random-key mode, 0x04 = passphrase mode
 *   if flag == 0x04: [16 bytes PBKDF2 salt][4 bytes LE iteration count]
 *   [4 bytes LE segment size S][8 bytes random nonce prefix]
 *   then the plaintext envelope, cut into S-byte segments (last may be
 *   shorter), each sealed separately with AES-GCM:
 *     IV  = nonce prefix || 4-byte BE segment index
 *     AAD = full header bytes || 1 byte (1 if final segment, else 0)
 *   so every segment is S+16 bytes on the wire except the final one.
 *   This is the STREAM construction: the counter in the IV stops segments
 *   being reordered, the final-segment flag stops trailing segments being
 *   silently dropped, and binding the header stops it being swapped out.
 *   Segmenting lets both sides work in bounded memory instead of holding
 *   the whole file (plus copies) in RAM at once.
 *
 * Legacy single-shot format (still decrypted, no longer written):
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
  const FLAG_RANDOM_KEY = 0x01; // legacy, decrypt-only
  const FLAG_PASSPHRASE = 0x02; // legacy, decrypt-only
  const FLAG_STREAM_RANDOM_KEY = 0x03;
  const FLAG_STREAM_PASSPHRASE = 0x04;
  // 1 MiB plaintext per segment: large enough that per-call WebCrypto
  // overhead is negligible, small enough to keep memory use flat. Stored in
  // the header, so it can change later without breaking existing files.
  const SEGMENT_SIZE = 1024 * 1024;
  const GCM_TAG_BYTES = 16;

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

  function parsePlaintextEnvelope(buf) {
    const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    const jsonLen = view.getUint32(0, true);
    const jsonBytes = buf.slice(4, 4 + jsonLen);
    const meta = JSON.parse(new TextDecoder().decode(jsonBytes));
    const fileBytes = buf.slice(4 + jsonLen);
    return { name: meta.name, type: meta.type, size: meta.size, fileBytes };
  }

  function buildEnvelopePrefix(name, type, size) {
    const jsonBytes = new TextEncoder().encode(JSON.stringify({ name, type, size }));
    const lenPrefix = new Uint8Array(4);
    new DataView(lenPrefix.buffer).setUint32(0, jsonBytes.length, true);
    return concatBuffers([lenPrefix, jsonBytes]);
  }

  function segmentIv(noncePrefix, index) {
    const iv = new Uint8Array(12);
    iv.set(noncePrefix, 0);
    new DataView(iv.buffer).setUint32(8, index, false);
    return iv;
  }

  function segmentAad(header, isFinal) {
    return concatBuffers([header, new Uint8Array([isFinal ? 1 : 0])]);
  }

  /**
   * Prepare a file for streaming encryption. Nothing is read from the file
   * yet; call `chunks()` to pull ciphertext a segment at a time.
   * @param {Blob} file - the (already metadata-stripped) file
   * @param {string} name
   * @param {string} type
   * @param {string|null} password - if provided, passphrase-derived key mode
   * @returns {Promise<{size: number, urlKey: string|null, chunks: () => AsyncGenerator<Uint8Array>}>}
   *   `size` is the exact total ciphertext length, known up front so the
   *   upload can be declared to the server before any encryption happens.
   */
  async function createEncryptor(file, name, type, password) {
    const noncePrefix = randomBytes(8);
    const segSizeBytes = new Uint8Array(4);
    new DataView(segSizeBytes.buffer).setUint32(0, SEGMENT_SIZE, true);
    let key, header, urlKey;

    if (password) {
      const salt = randomBytes(16);
      key = await deriveKeyFromPassword(password, salt, PBKDF2_ITERATIONS);
      const iterBytes = new Uint8Array(4);
      new DataView(iterBytes.buffer).setUint32(0, PBKDF2_ITERATIONS, true);
      header = concatBuffers([new Uint8Array([FLAG_STREAM_PASSPHRASE]), salt, iterBytes, segSizeBytes, noncePrefix]);
      urlKey = null;
    } else {
      const rawKey = randomBytes(32);
      key = await importRawAesKey(rawKey);
      header = concatBuffers([new Uint8Array([FLAG_STREAM_RANDOM_KEY]), segSizeBytes, noncePrefix]);
      urlKey = b64urlEncode(rawKey);
    }

    // A Blob of [prefix, file] is lazy - slicing it reads from the file on
    // demand rather than copying the whole thing into memory.
    const plaintext = new Blob([buildEnvelopePrefix(name, type, file.size), file]);
    const segmentCount = Math.max(1, Math.ceil(plaintext.size / SEGMENT_SIZE));
    const size = header.byteLength + plaintext.size + segmentCount * GCM_TAG_BYTES;

    async function* chunks() {
      yield header;
      for (let i = 0; i < segmentCount; i++) {
        const isFinal = i === segmentCount - 1;
        const part = await plaintext.slice(i * SEGMENT_SIZE, (i + 1) * SEGMENT_SIZE).arrayBuffer();
        const sealed = await crypto.subtle.encrypt(
          { name: "AES-GCM", iv: segmentIv(noncePrefix, i), additionalData: segmentAad(header, isFinal) },
          key,
          part
        );
        yield new Uint8Array(sealed);
      }
    }

    return { size, urlKey, chunks };
  }

  /**
   * Convenience wrapper: encrypt the whole file into a single Blob. Only for
   * small inputs/tests - uploads should stream from createEncryptor().
   */
  async function encryptForUpload(fileBytes, name, type, password) {
    const enc = await createEncryptor(new Blob([fileBytes]), name, type, password);
    const parts = [];
    for await (const c of enc.chunks()) parts.push(c);
    return { blob: new Blob(parts, { type: "application/octet-stream" }), urlKey: enc.urlKey };
  }

  // Accumulates incoming byte chunks and hands out exact-length reads,
  // without re-copying the whole buffer on every append.
  class ByteQueue {
    constructor() { this.parts = []; this.length = 0; }
    push(u8) { if (u8.byteLength) { this.parts.push(u8); this.length += u8.byteLength; } }
    take(n) {
      const out = new Uint8Array(n);
      let filled = 0;
      while (filled < n) {
        const head = this.parts[0];
        const need = n - filled;
        if (head.byteLength <= need) {
          out.set(head, filled);
          filled += head.byteLength;
          this.parts.shift();
        } else {
          out.set(head.subarray(0, need), filled);
          this.parts[0] = head.subarray(need);
          filled += need;
        }
      }
      this.length -= n;
      return out;
    }
  }

  // Turns decrypted envelope bytes back into {name, type, size} + file parts.
  class EnvelopeReader {
    constructor() { this.pending = new ByteQueue(); this.meta = null; this.fileParts = []; }
    push(u8) {
      if (this.meta) { this.fileParts.push(u8); return; }
      this.pending.push(u8);
      if (this.pending.length < 4) return;
      const lenBytes = this.pending.take(4);
      const jsonLen = new DataView(lenBytes.buffer).getUint32(0, true);
      if (this.pending.length < jsonLen) {
        // JSON straddles a segment boundary (only possible with absurd
        // filenames) - put the length back and wait for more.
        const rest = this.pending.take(this.pending.length);
        this.pending.push(lenBytes);
        this.pending.push(rest);
        return;
      }
      this.meta = JSON.parse(new TextDecoder().decode(this.pending.take(jsonLen)));
      if (this.pending.length) this.fileParts.push(this.pending.take(this.pending.length));
    }
    finish() {
      if (!this.meta) throw new Error("Decryption failed - the file is corrupted.");
      const type = this.meta.type || "application/octet-stream";
      return { name: this.meta.name, type, size: this.meta.size, blob: new Blob(this.fileParts, { type }) };
    }
  }

  async function* singleChunk(buf) {
    yield buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  }

  /**
   * Decrypt a download as it arrives, a segment at a time.
   * @param {AsyncIterable<Uint8Array>} source - e.g. from readableToIterator(res.body)
   * @param {string|null} urlKey - base64url raw key (random-key mode)
   * @param {string|null} password - passphrase (passphrase mode)
   * @returns {Promise<{name: string, type: string, size: number, blob: Blob}>}
   */
  async function decryptStream(source, urlKey, password) {
    const q = new ByteQueue();
    const it = source[Symbol.asyncIterator]();
    let done = false;
    async function fill(n) {
      while (!done && q.length < n) {
        const r = await it.next();
        if (r.done) done = true;
        else q.push(r.value);
      }
      return q.length >= n;
    }

    if (!(await fill(1))) throw new Error("Unrecognized file format.");
    const flag = q.parts[0][0];

    if (flag === FLAG_RANDOM_KEY || flag === FLAG_PASSPHRASE) {
      // Legacy single-shot blob: one GCM tag over everything, so there's no
      // way to verify it incrementally - buffer it all, as before.
      await fill(Infinity);
      const legacy = await decryptLegacy(q.take(q.length), urlKey, password);
      return { name: legacy.name, type: legacy.type, size: legacy.size, blob: new Blob([legacy.fileBytes], { type: legacy.type }) };
    }
    if (flag !== FLAG_STREAM_RANDOM_KEY && flag !== FLAG_STREAM_PASSPHRASE) {
      throw new Error("Unrecognized file format.");
    }

    const headerLen = flag === FLAG_STREAM_PASSPHRASE ? 1 + 16 + 4 + 4 + 8 : 1 + 4 + 8;
    if (!(await fill(headerLen))) throw new Error("Decryption failed - the file is corrupted.");
    const header = q.take(headerLen);
    const hv = new DataView(header.buffer);
    let key, off = 1;
    if (flag === FLAG_STREAM_PASSPHRASE) {
      if (!password) throw new Error("This file requires a passphrase to decrypt.");
      const salt = header.slice(off, off + 16);
      const iterations = hv.getUint32(off + 16, true);
      off += 20;
      key = await deriveKeyFromPassword(password, salt, iterations);
    } else {
      if (!urlKey) throw new Error("Missing decryption key.");
      key = await importRawAesKey(b64urlDecode(urlKey));
    }
    const segSize = hv.getUint32(off, true);
    const noncePrefix = header.slice(off + 4, off + 12);
    if (segSize === 0 || segSize > 64 * 1024 * 1024) throw new Error("Decryption failed - the file is corrupted.");
    const sealedSize = segSize + GCM_TAG_BYTES;

    const out = new EnvelopeReader();
    for (let i = 0; ; i++) {
      // A segment is final iff nothing follows it - so read one byte past a
      // full sealed segment to find out which case we're in.
      await fill(sealedSize + 1);
      const isFinal = q.length <= sealedSize;
      if (q.length < GCM_TAG_BYTES) throw new Error("Decryption failed - the file is corrupted.");
      const sealed = q.take(isFinal ? q.length : sealedSize);
      let plain;
      try {
        plain = await crypto.subtle.decrypt(
          { name: "AES-GCM", iv: segmentIv(noncePrefix, i), additionalData: segmentAad(header, isFinal) },
          key,
          sealed
        );
      } catch (e) {
        throw new Error("Decryption failed - wrong key/passphrase, or the file is corrupted.");
      }
      out.push(new Uint8Array(plain));
      if (isFinal) break;
    }
    return out.finish();
  }

  async function* readableToIterator(stream) {
    const reader = stream.getReader();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) return;
        yield value;
      }
    } finally {
      reader.releaseLock();
    }
  }

  /**
   * Decrypt an already-fully-downloaded blob (any format version).
   * @param {ArrayBuffer|Uint8Array} blobBuf
   * @returns {Promise<{name, type, size, blob}>}
   */
  function decryptDownload(blobBuf, urlKey, password) {
    return decryptStream(singleChunk(blobBuf), urlKey, password);
  }

  // Legacy (flag 0x01/0x02) single-shot format.
  async function decryptLegacy(blobBuf, urlKey, password) {
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
    createEncryptor,
    encryptForUpload,
    decryptStream,
    decryptDownload,
    readableToIterator,
  };
})();
