// Tests for frontend/static/js/exif-strip.js (SEC-008): lossless, fail-closed
// metadata removal. Run with: node --test tests/js/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ctx = { Blob, File, Uint8Array, DataView, String, Date, Error };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(readFileSync(path.join(ROOT, "frontend/static/js/exif-strip.js"), "utf8"), ctx);
const X = ctx.window.SDExif;

const ascii = (s) => Uint8Array.from(s, (c) => c.charCodeAt(0));
const cat = (...parts) => { const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out; };
const u16be = (n) => new Uint8Array([n >> 8, n & 0xff]);
const u32be = (n) => new Uint8Array([n >>> 24, (n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff]);
const u32le = (n) => new Uint8Array([n & 0xff, (n >> 8) & 0xff, (n >> 16) & 0xff, n >>> 24]);
const has = (hay, needle) => Buffer.from(hay).includes(Buffer.from(needle));

function seg(marker, payload) { return cat(new Uint8Array([0xff, marker]), u16be(payload.length + 2), payload); }

function exifPayload(orientation) {
  // big-endian TIFF, IFD0: Orientation + a GPS IFD pointer, plus a GPS marker string
  const ifd = cat(u16be(2), u16be(0x0112), u16be(3), u32be(1), u16be(orientation), u16be(0),
    u16be(0x8825), u16be(4), u32be(1), u32be(38), u32be(0));
  return cat(ascii("Exif\0\0"), ascii("MM"), u16be(42), u32be(8), ifd, ascii("GPS 59.3293N 18.0686E"));
}

const SCAN = cat(new Uint8Array([0xff, 0xda]), u16be(8), new Uint8Array([1, 1, 0, 0, 0x3f, 0]), Uint8Array.from({ length: 300 }, (_, i) => i % 251), new Uint8Array([0xff, 0xd9]));

function jpeg(...segments) { return cat(new Uint8Array([0xff, 0xd8]), ...segments, SCAN); }

async function strip(bytes, name, type) {
  return X.stripImageMetadata(new File([bytes], name, { type }));
}
const bytesOf = async (f) => new Uint8Array(await f.arrayBuffer());

test("JPEG: GPS/EXIF, XMP, IPTC and comments removed; image data untouched", async () => {
  const input = jpeg(
    seg(0xe0, cat(ascii("JFIF\0"), new Uint8Array([1, 1, 0, 0, 1, 0, 1, 0, 0]))),
    seg(0xe1, exifPayload(1)),
    seg(0xe1, ascii("http://ns.adobe.com/xap/1.0/\0<x:xmpmeta>author: Jane</x:xmpmeta>")),
    seg(0xed, ascii("Photoshop 3.0\0IPTC by-line Jane")),
    seg(0xfe, ascii("shot at home")),
  );
  const res = await strip(input, "p.jpg", "image/jpeg");
  assert.equal(res.status, "stripped");
  const out = await bytesOf(res.file);
  for (const secret of ["GPS 59.3293N", "xmpmeta", "IPTC", "shot at home"]) assert.ok(!has(out, ascii(secret)), secret);
  assert.ok(has(out, ascii("JFIF")));
  assert.deepEqual(out.subarray(out.length - SCAN.length), SCAN, "entropy-coded data must be byte-identical");
});

test("JPEG: rotation survives as a minimal Orientation-only EXIF block", async () => {
  const res = await strip(jpeg(seg(0xe1, exifPayload(6))), "r.jpg", "image/jpeg");
  const out = await bytesOf(res.file);
  assert.ok(!has(out, ascii("GPS")));
  assert.equal(X._internals.exifOrientation(out.subarray(6, out.length)), 6);
});

test("JPEG: ICC colour profile is kept", async () => {
  const icc = seg(0xe2, cat(ascii("ICC_PROFILE\0"), new Uint8Array([1, 1]), ascii("sRGB profile data")));
  const out = await bytesOf((await strip(jpeg(icc, seg(0xfe, ascii("c"))), "c.jpg", "image/jpeg")).file);
  assert.ok(has(out, ascii("ICC_PROFILE")) && has(out, ascii("sRGB profile data")));
});

test("JPEG without metadata is reported clean and left alone", async () => {
  const input = jpeg(seg(0xe0, ascii("JFIF\0\x01\x01\0\0\x01\0\x01\0\0")));
  const res = await strip(input, "clean.jpg", "image/jpeg");
  assert.equal(res.status, "clean");
  assert.deepEqual(await bytesOf(res.file), input);
});

function pngChunk(type, data) {
  return cat(u32be(data.length), ascii(type), data, new Uint8Array(4));
}

test("PNG: text, eXIf and tIME chunks removed, pixels kept", async () => {
  const sig = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const idat = pngChunk("IDAT", ascii("compressed-pixels"));
  const input = cat(sig, pngChunk("IHDR", new Uint8Array(13)), pngChunk("tEXt", ascii("Author\0Jane")),
    pngChunk("eXIf", ascii("MM\0*GPS")), pngChunk("tIME", new Uint8Array(7)), idat, pngChunk("IEND", new Uint8Array(0)));
  const res = await strip(input, "i.png", "image/png");
  assert.equal(res.status, "stripped");
  const out = await bytesOf(res.file);
  for (const t of ["tEXt", "eXIf", "tIME", "Jane"]) assert.ok(!has(out, ascii(t)), t);
  assert.ok(has(out, idat));
});

test("WebP: EXIF and XMP chunks removed, VP8X flags and RIFF size fixed", async () => {
  const vp8x = cat(ascii("VP8X"), u32le(10), new Uint8Array([0x0c, 0, 0, 0, 1, 0, 0, 1, 0, 0]));
  const exif = cat(ascii("EXIF"), u32le(8), ascii("GPSGPSGP"));
  const xmp = cat(ascii("XMP "), u32le(4), ascii("Jane"));
  const img = cat(ascii("VP8 "), u32le(4), ascii("data"));
  const body = cat(ascii("WEBP"), vp8x, img, exif, xmp);
  const input = cat(ascii("RIFF"), u32le(body.length), body);
  const res = await strip(input, "w.webp", "image/webp");
  assert.equal(res.status, "stripped");
  const out = await bytesOf(res.file);
  assert.ok(!has(out, ascii("GPS")) && !has(out, ascii("Jane")));
  assert.equal(out[20] & 0x0c, 0, "EXIF/XMP flags cleared");
  assert.equal(new DataView(out.buffer).getUint32(4, true), out.length - 8, "RIFF size updated");
});

test("formats that can't be stripped are flagged, not silently passed", async () => {
  for (const [name, type] of [["IMG_1.heic", "image/heic"], ["clip.mp4", "video/mp4"], ["doc.pdf", "application/pdf"],
    ["memo.docx", ""], ["anim.gif", "image/gif"]]) {
    assert.equal((await strip(new Uint8Array(20), name, type)).status, "unsupported", name);
  }
  assert.equal((await strip(new Uint8Array(20), "notes.txt", "text/plain")).status, "none");
});

test("an unreadable image fails closed: original returned, status failed", async () => {
  const garbage = new Uint8Array([0xff, 0xd8, 0x12, 0x34, 0x56]);
  const res = await strip(garbage, "broken.jpg", "image/jpeg");
  assert.equal(res.status, "failed");
  assert.deepEqual(await bytesOf(res.file), garbage);
});
