/*
 * Client-side metadata stripping, lossless and fail-closed (SEC-008).
 *
 * The old version re-encoded JPEG/PNG/WebP through a <canvas>: lossy
 * (quality 0.95 on every photo, colour profiles dropped), and on any failure -
 * or for any other format, including iPhone HEIC photos - it silently
 * uploaded the original, GPS and all.
 *
 * Now the image *containers* are edited directly, so pixels are untouched:
 *   JPEG: drop APP1 (EXIF/XMP), APP13 (IPTC/Photoshop), COM and other
 *         application segments; keep JFIF (APP0), ICC colour (APP2
 *         ICC_PROFILE) and Adobe (APP14). If EXIF said the photo is rotated,
 *         a minimal EXIF block holding only the Orientation tag is put back,
 *         so the image still displays the right way up.
 *   PNG:  drop tEXt/zTXt/iTXt (text, often XMP), eXIf and tIME chunks.
 *   WebP: drop EXIF and XMP chunks and clear their VP8X flags.
 * Everything else gets an explicit status, so the UI can warn about formats
 * that may carry metadata this code can't remove (HEIC, video, PDF, Office).
 *
 * Result: { file, status, note } with status one of
 *   "stripped"    - metadata found and removed
 *   "clean"       - supported format, nothing to remove
 *   "unsupported" - may contain metadata that can't be removed here
 *   "none"        - format with no known embedded metadata
 *   "failed"      - couldn't parse; the ORIGINAL is returned, caller must ask
 */
(function () {
  const MAY_HAVE_METADATA = [
    /^image\/(heic|heif|avif|tiff|gif)$/, /^video\//, /^audio\//, /^application\/pdf$/,
    /^application\/(msword|vnd\.openxmlformats-officedocument\..*|vnd\.oasis\.opendocument\..*|vnd\.ms-.*)$/,
  ];
  const EXT_TYPES = {
    jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", heic: "image/heic", heif: "image/heif",
    avif: "image/avif", tif: "image/tiff", tiff: "image/tiff", gif: "image/gif", mp4: "video/mp4", mov: "video/quicktime",
    m4a: "audio/mp4", mp3: "audio/mpeg", pdf: "application/pdf", doc: "application/msword",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    odt: "application/vnd.oasis.opendocument.text",
  };

  function typeOf(file) {
    if (file.type) return file.type.toLowerCase();
    const ext = (file.name || "").split(".").pop().toLowerCase();
    return EXT_TYPES[ext] || "";
  }

  function concat(parts) {
    const total = parts.reduce((n, p) => n + p.byteLength, 0);
    const out = new Uint8Array(total);
    let off = 0;
    for (const p of parts) { out.set(p, off); off += p.byteLength; }
    return out;
  }

  function startsWith(bytes, offset, ascii) {
    for (let i = 0; i < ascii.length; i++) if (bytes[offset + i] !== ascii.charCodeAt(i)) return false;
    return true;
  }

  // ---- JPEG ---------------------------------------------------------------
  function exifOrientation(seg) {
    // seg = APP1 payload starting with "Exif\0\0"
    if (!startsWith(seg, 0, "Exif\0\0")) return 1;
    const t = 6;
    const le = seg[t] === 0x49;
    const dv = new DataView(seg.buffer, seg.byteOffset, seg.byteLength);
    const u16 = (o) => dv.getUint16(t + o, le);
    const u32 = (o) => dv.getUint32(t + o, le);
    const ifd = u32(4);
    const n = u16(ifd);
    for (let i = 0; i < n; i++) {
      const e = ifd + 2 + i * 12;
      if (u16(e) === 0x0112) return u16(e + 8) || 1;
    }
    return 1;
  }

  function minimalExifOrientation(orientation) {
    // APP1: "Exif\0\0" + big-endian TIFF with one IFD0 entry (Orientation).
    const payload = new Uint8Array([
      0x45, 0x78, 0x69, 0x66, 0, 0,
      0x4d, 0x4d, 0, 0x2a, 0, 0, 0, 8,
      0, 1,
      0x01, 0x12, 0, 3, 0, 0, 0, 1, 0, orientation, 0, 0,
      0, 0, 0, 0,
    ]);
    const len = payload.length + 2;
    return concat([new Uint8Array([0xff, 0xe1, len >> 8, len & 0xff]), payload]);
  }

  function stripJpeg(b) {
    if (b[0] !== 0xff || b[1] !== 0xd8) throw new Error("not a JPEG");
    const keep = [b.subarray(0, 2)];
    let i = 2, removed = false, orientation = 1;
    while (i < b.length) {
      if (b[i] !== 0xff) throw new Error("bad marker");
      const marker = b[i + 1];
      if (marker === 0xff) { i += 1; continue; } // fill byte
      if (marker === 0xda) { keep.push(b.subarray(i)); break; } // SOS: image data follows
      if ((marker >= 0xd0 && marker <= 0xd7) || marker === 0x01) { keep.push(b.subarray(i, i + 2)); i += 2; continue; }
      const len = (b[i + 2] << 8) | b[i + 3];
      if (len < 2 || i + 2 + len > b.length) throw new Error("bad segment length");
      const seg = b.subarray(i, i + 2 + len);
      const payload = b.subarray(i + 4, i + 2 + len);
      const isApp = marker >= 0xe0 && marker <= 0xef;
      let drop = false;
      if (marker === 0xfe) drop = true; // COM
      else if (isApp) {
        if (marker === 0xe0) drop = false; // JFIF/JFXX
        else if (marker === 0xe2) drop = !startsWith(payload, 0, "ICC_PROFILE\0");
        else if (marker === 0xee) drop = !startsWith(payload, 0, "Adobe");
        else drop = true; // APP1 EXIF/XMP, APP13 IPTC, everything else
        if (marker === 0xe1 && startsWith(payload, 0, "Exif\0\0")) {
          try { orientation = exifOrientation(payload); } catch (e) { orientation = 1; }
        }
      }
      if (drop) removed = true;
      else keep.push(seg);
      i += 2 + len;
    }
    if (!removed) return null;
    if (orientation > 1 && orientation <= 8) keep.splice(1, 0, minimalExifOrientation(orientation));
    return concat(keep);
  }

  // ---- PNG ----------------------------------------------------------------
  const PNG_DROP = new Set(["tEXt", "zTXt", "iTXt", "eXIf", "tIME"]);
  function stripPng(b) {
    const sig = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
    if (!sig.every((v, k) => b[k] === v)) throw new Error("not a PNG");
    const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
    const keep = [b.subarray(0, 8)];
    let i = 8, removed = false;
    while (i < b.length) {
      const len = dv.getUint32(i);
      const type = String.fromCharCode(b[i + 4], b[i + 5], b[i + 6], b[i + 7]);
      const end = i + 12 + len;
      if (end > b.length) throw new Error("bad chunk length");
      if (PNG_DROP.has(type)) removed = true;
      else keep.push(b.subarray(i, end));
      i = end;
      if (type === "IEND") break;
    }
    return removed ? concat(keep) : null;
  }

  // ---- WebP ---------------------------------------------------------------
  function stripWebp(b) {
    if (!startsWith(b, 0, "RIFF") || !startsWith(b, 8, "WEBP")) throw new Error("not a WebP");
    const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
    const chunks = [];
    let i = 12, removed = false;
    while (i + 8 <= b.length) {
      const fourcc = String.fromCharCode(b[i], b[i + 1], b[i + 2], b[i + 3]);
      const size = dv.getUint32(i + 4, true);
      const end = i + 8 + size + (size & 1);
      if (end > b.length + 1) throw new Error("bad chunk size");
      if (fourcc === "EXIF" || fourcc === "XMP ") removed = true;
      else chunks.push(b.slice(i, Math.min(end, b.length)));
      i = end;
    }
    if (!removed) return null;
    for (const c of chunks) {
      if (startsWith(c, 0, "VP8X")) c[8] &= ~(0x08 | 0x04); // clear EXIF + XMP flags
    }
    const body = concat(chunks);
    const header = new Uint8Array(12);
    header.set(b.subarray(0, 12));
    new DataView(header.buffer).setUint32(4, body.byteLength + 4, true);
    return concat([header, body]);
  }

  const STRIPPERS = { "image/jpeg": stripJpeg, "image/png": stripPng, "image/webp": stripWebp };

  async function stripImageMetadata(file) {
    const type = typeOf(file);
    const stripper = STRIPPERS[type];
    if (!stripper) {
      if (MAY_HAVE_METADATA.some((re) => re.test(type))) {
        return { file, status: "unsupported", note: "May contain metadata (e.g. location or author) that can't be removed in the browser" };
      }
      return { file, status: "none", note: "" };
    }
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const out = stripper(bytes);
      if (!out) return { file, status: "clean", note: "No metadata found" };
      const clean = new File([out], file.name, { type: file.type || type, lastModified: Date.now() });
      return { file: clean, status: "stripped", note: "Metadata removed" };
    } catch (e) {
      return { file, status: "failed", note: "Couldn't read this image to remove its metadata" };
    }
  }

  window.SDExif = { stripImageMetadata, typeOf, _internals: { stripJpeg, stripPng, stripWebp, exifOrientation } };
})();
