/*
 * Ratatosk client-side crypto module.
 *
 * Zero-knowledge design: plaintext, filenames, keys and passphrases never
 * leave the browser. AES-256-GCM (WebCrypto) encrypts a small envelope
 * (filename + mime type + file bytes) so the server learns none of them.
 *
 * Key handling (current format, flags 0x05/0x06)
 * ----------------------------------------------
 * One secret per file:
 *   - link mode:       a random 256-bit secret S, carried in the URL #fragment
 *                      (browsers never send the fragment to the server);
 *   - passphrase mode: S = PBKDF2-SHA256(passphrase, salt, iterations).
 * HKDF-SHA256 then derives two independent values from S:
 *   - the AES-GCM file key          (info "ratatosk-enc-v1"), never leaves here;
 *   - a download token              (info "ratatosk-dl-v1").
 * The server stores SHA-256(token) and requires the token to serve the
 * ciphertext. Knowing the token reveals nothing about the file key (HKDF
 * outputs are independent), so the server can check that a downloader holds
 * the secret without ever being able to decrypt. This replaced sending the
 * passphrase itself to the server (SEC-001), and stops anyone who only knows
 * a file id from consuming, burning or locking it (SEC-006). It follows the
 * design Firefox Send used (separate encryption and auth keys from one secret).
 *
 * Blob wire format (segmented STREAM construction)
 * ------------------------------------------------
 *   [1 byte flag]  0x05 = link mode, 0x06 = passphrase mode
 *   if passphrase: [16 bytes PBKDF2 salt][4 bytes LE iteration count]
 *   [4 bytes LE segment size S][8 bytes random nonce prefix]
 *   then the plaintext envelope cut into S-byte segments (last may be
 *   shorter), each sealed separately with AES-GCM:
 *     IV  = nonce prefix || 4-byte BE segment index
 *     AAD = full header bytes || 1 byte (1 if final segment, else 0)
 *   The counter stops segments being reordered, the final-segment flag stops
 *   trailing segments being dropped, and binding the header stops it being
 *   swapped. Segments let both sides work in bounded memory, and let an
 *   interrupted upload resume from any offset (the ciphertext is a pure
 *   function of key, nonce prefix and plaintext).
 *
 * Older formats, still decrypted, never written:
 *   0x03/0x04  same segmented layout, AES key = S directly (no token)
 *   0x01/0x02  single-shot: [flag][salt+iters if 0x02][12-byte IV][ciphertext]
 *
 * Plaintext envelope:
 *   [4 bytes LE JSON length][JSON {name, type, size, kind?}][raw file bytes]
 *   kind: "text" marks a text send (FEAT-006), "bundle" a multi-file manifest.
 */
(function () {
  // OWASP's current minimum for PBKDF2-HMAC-SHA256. Stored per file, so
  // raising it only affects new uploads.
  const PBKDF2_ITERATIONS = 600000;
  const FLAG_RANDOM_KEY = 0x01; // legacy, decrypt-only
  const FLAG_PASSPHRASE = 0x02; // legacy, decrypt-only
  const FLAG_STREAM_RANDOM_KEY = 0x03; // legacy, decrypt-only
  const FLAG_STREAM_PASSPHRASE = 0x04; // legacy, decrypt-only
  const FLAG_V3_RANDOM_KEY = 0x05;
  const FLAG_V3_PASSPHRASE = 0x06;
  // 1 MiB plaintext per segment: large enough that per-call WebCrypto
  // overhead is negligible, small enough to keep memory use flat.
  const SEGMENT_SIZE = 1024 * 1024;
  const GCM_TAG_BYTES = 16;
  const ENC_INFO = new TextEncoder().encode("ratatosk-enc-v1");
  const DL_INFO = new TextEncoder().encode("ratatosk-dl-v1");
  const EMPTY = new Uint8Array(0);

  function b64urlEncode(buf) {
    const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function b64urlDecode(str) {
    let s = String(str).replace(/-/g, "+").replace(/_/g, "/");
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

  async function sha256Hex(text) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function importRawAesKey(rawBytes) {
    return crypto.subtle.importKey("raw", rawBytes, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
  }

  async function pbkdf2Bits(password, salt, iterations) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits", "deriveKey"]);
    return new Uint8Array(await crypto.subtle.deriveBits({ name: "PBKDF2", salt, iterations, hash: "SHA-256" }, base, 256));
  }

  // Legacy 0x02/0x04: the passphrase-derived key *was* the AES key.
  async function deriveLegacyPasswordKey(password, salt, iterations) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations, hash: "SHA-256" }, base,
      { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  }

  /** From the 32-byte file secret S: { encKey, token } (see header comment). */
  async function deriveFromSecret(secretBytes) {
    const ikm = await crypto.subtle.importKey("raw", secretBytes, "HKDF", false, ["deriveKey", "deriveBits"]);
    const encKey = await crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: EMPTY, info: ENC_INFO }, ikm,
      { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
    const tokenBits = await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt: EMPTY, info: DL_INFO }, ikm, 256);
    return { encKey, token: b64urlEncode(tokenBits) };
  }

  /**
   * The download token a recipient presents, derived from what they hold.
   * @param {{urlKey?: string, password?: string, kdfSalt?: string, kdfIterations?: number}} p
   */
  async function deriveDownloadToken(p) {
    if (p.password) {
      if (!p.kdfSalt || !p.kdfIterations) throw new Error("Missing passphrase parameters.");
      const secret = await pbkdf2Bits(p.password, b64urlDecode(p.kdfSalt), p.kdfIterations);
      return (await deriveFromSecret(secret)).token;
    }
    if (!p.urlKey) throw new Error("Missing decryption key.");
    return (await deriveFromSecret(b64urlDecode(p.urlKey))).token;
  }

  function buildEnvelopePrefix(name, type, size, kind) {
    const meta = { name, type, size };
    if (kind) meta.kind = kind;
    const jsonBytes = new TextEncoder().encode(JSON.stringify(meta));
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
   * Prepare a file for streaming encryption. Nothing is read yet; call
   * `chunks(fromOffset)` to pull ciphertext a segment at a time.
   *
   * @param {Blob} file - the (already metadata-stripped) file
   * @param {string} name
   * @param {string} type
   * @param {string|null} password - passphrase mode if set
   * @param {object} [opts] - { kind, resume } where resume is a previous
   *   encryptor's `resumeState`, to regenerate byte-identical ciphertext.
   * @returns {Promise<{size, urlKey, downloadToken, tokenHash, kdfSalt, kdfIterations, resumeState, chunks}>}
   */
  async function createEncryptor(file, name, type, password, opts) {
    opts = opts || {};
    const resume = opts.resume || null;
    const noncePrefix = resume ? b64urlDecode(resume.noncePrefix) : randomBytes(8);
    const segSizeBytes = new Uint8Array(4);
    new DataView(segSizeBytes.buffer).setUint32(0, SEGMENT_SIZE, true);
    let header, urlKey = null, secret, salt = null, iterations = null;

    if (password) {
      salt = resume ? b64urlDecode(resume.kdfSalt) : randomBytes(16);
      iterations = resume ? resume.kdfIterations : PBKDF2_ITERATIONS;
      secret = await pbkdf2Bits(password, salt, iterations);
      const iterBytes = new Uint8Array(4);
      new DataView(iterBytes.buffer).setUint32(0, iterations, true);
      header = concatBuffers([new Uint8Array([FLAG_V3_PASSPHRASE]), salt, iterBytes, segSizeBytes, noncePrefix]);
    } else {
      secret = resume ? b64urlDecode(resume.urlKey) : randomBytes(32);
      header = concatBuffers([new Uint8Array([FLAG_V3_RANDOM_KEY]), segSizeBytes, noncePrefix]);
      urlKey = b64urlEncode(secret);
    }
    const { encKey, token } = await deriveFromSecret(secret);

    // A Blob of [prefix, file] is lazy - slicing it reads from the file on
    // demand rather than copying the whole thing into memory.
    const plaintext = new Blob([buildEnvelopePrefix(name, type, file.size, opts.kind), file]);
    const segmentCount = Math.max(1, Math.ceil(plaintext.size / SEGMENT_SIZE));
    const sealedSize = SEGMENT_SIZE + GCM_TAG_BYTES;
    const size = header.byteLength + plaintext.size + segmentCount * GCM_TAG_BYTES;

    async function sealSegment(i) {
      const isFinal = i === segmentCount - 1;
      const part = await plaintext.slice(i * SEGMENT_SIZE, (i + 1) * SEGMENT_SIZE).arrayBuffer();
      const sealed = await crypto.subtle.encrypt(
        { name: "AES-GCM", iv: segmentIv(noncePrefix, i), additionalData: segmentAad(header, isFinal) }, encKey, part);
      return new Uint8Array(sealed);
    }

    /** Ciphertext from byte `fromOffset` (0 = start) to the end. */
    async function* chunks(fromOffset) {
      let pos = fromOffset || 0;
      if (pos < header.byteLength) {
        yield header.subarray(pos);
        pos = header.byteLength;
      }
      let i = Math.floor((pos - header.byteLength) / sealedSize);
      let skip = (pos - header.byteLength) - i * sealedSize;
      for (; i < segmentCount; i++) {
        const sealed = await sealSegment(i);
        yield skip ? sealed.subarray(skip) : sealed;
        skip = 0;
      }
    }

    return {
      size,
      urlKey,
      downloadToken: token,
      tokenHash: await sha256Hex(token),
      kdfSalt: salt ? b64urlEncode(salt) : null,
      kdfIterations: iterations,
      // Enough to regenerate identical ciphertext later (FEAT-004). For
      // passphrase mode the passphrase itself is NOT included - it must be
      // re-entered to resume.
      resumeState: {
        mode: password ? "passphrase" : "link",
        urlKey,
        noncePrefix: b64urlEncode(noncePrefix),
        kdfSalt: salt ? b64urlEncode(salt) : null,
        kdfIterations: iterations,
      },
      chunks,
    };
  }

  /** Small/test convenience: whole ciphertext as one Blob. */
  async function encryptForUpload(fileBytes, name, type, password, opts) {
    const enc = await createEncryptor(new Blob([fileBytes]), name, type, password, opts);
    const parts = [];
    for await (const c of enc.chunks(0)) parts.push(c);
    return { blob: new Blob(parts, { type: "application/octet-stream" }), urlKey: enc.urlKey, encryptor: enc };
  }

  // Accumulates incoming byte chunks and hands out exact-length reads.
  class ByteQueue {
    constructor() { this.parts = []; this.length = 0; }
    push(u8) { if (u8.byteLength) { this.parts.push(u8); this.length += u8.byteLength; } }
    peekByte() { return this.parts.length ? this.parts[0][0] : undefined; }
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

  // Turns decrypted envelope bytes back into metadata + file bytes, writing
  // the bytes either to a sink (stream to disk) or into memory parts.
  class EnvelopeReader {
    constructor(onMeta) { this.pending = new ByteQueue(); this.meta = null; this.parts = []; this.sink = null; this.onMeta = onMeta; }
    async push(u8) {
      if (this.meta) return this._emit(u8);
      this.pending.push(u8);
      if (this.pending.length < 4) return;
      const lenBytes = this.pending.take(4);
      const jsonLen = new DataView(lenBytes.buffer).getUint32(0, true);
      if (this.pending.length < jsonLen) {
        const rest = this.pending.take(this.pending.length);
        this.pending.push(lenBytes);
        this.pending.push(rest);
        return;
      }
      this.meta = JSON.parse(new TextDecoder().decode(this.pending.take(jsonLen)));
      this.meta.type = this.meta.type || "application/octet-stream";
      if (this.onMeta) this.sink = (await this.onMeta(this.meta)) || null;
      if (this.pending.length) await this._emit(this.pending.take(this.pending.length));
    }
    async _emit(u8) {
      if (this.sink) await this.sink.write(u8);
      else this.parts.push(u8);
    }
    async finish() {
      if (!this.meta) throw new Error("Decryption failed - the file is corrupted.");
      const m = this.meta;
      if (this.sink) {
        await this.sink.close();
        return { name: m.name, type: m.type, size: m.size, kind: m.kind || null, streamed: true, blob: null };
      }
      return { name: m.name, type: m.type, size: m.size, kind: m.kind || null, streamed: false, blob: new Blob(this.parts, { type: m.type }) };
    }
    async abort(err) { if (this.sink && this.sink.abort) await this.sink.abort(err); }
  }

  async function* singleChunk(buf) {
    yield buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  }

  /**
   * Decrypt a download as it arrives, a segment at a time.
   * @param {AsyncIterable<Uint8Array>} source
   * @param {string|null} urlKey - base64url secret (link mode)
   * @param {string|null} password - passphrase (passphrase mode)
   * @param {object} [opts] - { onMeta(meta) -> sink|null, onProgress(bytesIn) }
   * @returns {Promise<{name, type, size, kind, streamed, blob}>}
   */
  async function decryptStream(source, urlKey, password, opts) {
    opts = opts || {};
    const q = new ByteQueue();
    const it = source[Symbol.asyncIterator]();
    let done = false, bytesIn = 0;
    async function fill(n) {
      while (!done && q.length < n) {
        const r = await it.next();
        if (r.done) done = true;
        else {
          q.push(r.value);
          bytesIn += r.value.byteLength;
          if (opts.onProgress) opts.onProgress(bytesIn);
        }
      }
      return q.length >= n;
    }

    if (!(await fill(1))) throw new Error("Unrecognized file format.");
    const flag = q.peekByte();

    if (flag === FLAG_RANDOM_KEY || flag === FLAG_PASSPHRASE) {
      // Legacy single-shot blob: one GCM tag over everything - buffer it all.
      await fill(Infinity);
      const legacy = await decryptLegacy(q.take(q.length), urlKey, password);
      const reader = new EnvelopeReader(opts.onMeta);
      await reader.push(legacy);
      return reader.finish();
    }
    const passphraseFlags = [FLAG_STREAM_PASSPHRASE, FLAG_V3_PASSPHRASE];
    const knownFlags = [FLAG_STREAM_RANDOM_KEY, FLAG_V3_RANDOM_KEY, ...passphraseFlags];
    if (!knownFlags.includes(flag)) throw new Error("Unrecognized file format.");

    const isPass = passphraseFlags.includes(flag);
    const headerLen = isPass ? 1 + 16 + 4 + 4 + 8 : 1 + 4 + 8;
    if (!(await fill(headerLen))) throw new Error("Decryption failed - the file is corrupted.");
    const header = q.take(headerLen);
    const hv = new DataView(header.buffer);
    let key, off = 1;
    if (isPass) {
      if (!password) throw new Error("This file requires a passphrase to decrypt.");
      const salt = header.slice(off, off + 16);
      const iterations = hv.getUint32(off + 16, true);
      off += 20;
      key = flag === FLAG_V3_PASSPHRASE
        ? (await deriveFromSecret(await pbkdf2Bits(password, salt, iterations))).encKey
        : await deriveLegacyPasswordKey(password, salt, iterations);
    } else {
      if (!urlKey) throw new Error("Missing decryption key.");
      const secret = b64urlDecode(urlKey);
      key = flag === FLAG_V3_RANDOM_KEY ? (await deriveFromSecret(secret)).encKey : await importRawAesKey(secret);
    }
    const segSize = hv.getUint32(off, true);
    const noncePrefix = header.slice(off + 4, off + 12);
    if (segSize === 0 || segSize > 64 * 1024 * 1024) throw new Error("Decryption failed - the file is corrupted.");
    const sealedSize = segSize + GCM_TAG_BYTES;

    const out = new EnvelopeReader(opts.onMeta);
    try {
      for (let i = 0; ; i++) {
        // A segment is final iff nothing follows it - read one byte past a
        // full sealed segment to find out which case we're in.
        await fill(sealedSize + 1);
        const isFinal = q.length <= sealedSize;
        if (q.length < GCM_TAG_BYTES) throw new Error("Decryption failed - the file is corrupted.");
        const sealed = q.take(isFinal ? q.length : sealedSize);
        let plain;
        try {
          plain = await crypto.subtle.decrypt(
            { name: "AES-GCM", iv: segmentIv(noncePrefix, i), additionalData: segmentAad(header, isFinal) }, key, sealed);
        } catch (e) {
          throw new Error("Decryption failed - wrong key/passphrase, or the file is corrupted.");
        }
        await out.push(new Uint8Array(plain));
        if (isFinal) break;
      }
    } catch (e) {
      await out.abort(e);
      throw e;
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

  /** Decrypt an already-downloaded blob (any format). */
  function decryptDownload(blobBuf, urlKey, password, opts) {
    return decryptStream(singleChunk(blobBuf), urlKey, password, opts);
  }

  // Legacy 0x01/0x02 single-shot format. Returns the plaintext envelope.
  async function decryptLegacy(bytes, urlKey, password) {
    const flag = bytes[0];
    let offset = 1, key;
    if (flag === FLAG_PASSPHRASE) {
      if (!password) throw new Error("This file requires a passphrase to decrypt.");
      const salt = bytes.slice(offset, offset + 16);
      offset += 16;
      const iterations = new DataView(bytes.buffer, bytes.byteOffset + offset, 4).getUint32(0, true);
      offset += 4;
      key = await deriveLegacyPasswordKey(password, salt, iterations);
    } else {
      if (!urlKey) throw new Error("Missing decryption key.");
      key = await importRawAesKey(b64urlDecode(urlKey));
    }
    const iv = bytes.slice(offset, offset + 12);
    try {
      return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, bytes.slice(offset + 12)));
    } catch (e) {
      throw new Error("Decryption failed - wrong key/passphrase, or the file is corrupted.");
    }
  }

  window.SDCrypto = {
    PBKDF2_ITERATIONS,
    SEGMENT_SIZE,
    b64urlEncode,
    b64urlDecode,
    randomBytes,
    sha256Hex,
    createEncryptor,
    encryptForUpload,
    deriveDownloadToken,
    decryptStream,
    decryptDownload,
    readableToIterator,
  };
})();
