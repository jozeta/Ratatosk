/*
 * SDQRCode - minimal dependency-free QR Code encoder (ISO/IEC 18004).
 * Byte-mode only, error-correction level M, versions 1-10.
 * Self-hosted so the app never has to call an external service or CDN to
 * render a share-link QR code (which would leak the decryption key in the
 * URL fragment to that third party).
 */
(function () {
  "use strict";

  // ---- GF(256) tables (primitive polynomial 0x11D, generator 2) ----
  const GF_EXP = new Array(512);
  const GF_LOG = new Array(256);
  (function buildGF() {
    let x = 1;
    for (let i = 0; i < 255; i++) {
      GF_EXP[i] = x;
      GF_LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11d;
    }
    for (let i = 255; i < 512; i++) GF_EXP[i] = GF_EXP[i - 255];
  })();

  function gfMul(a, b) {
    if (a === 0 || b === 0) return 0;
    return GF_EXP[GF_LOG[a] + GF_LOG[b]];
  }

  // Reed-Solomon generator polynomial for `degree` EC codewords, coefficients high->low.
  function rsGeneratorPoly(degree) {
    let poly = [1];
    for (let i = 0; i < degree; i++) {
      const next = new Array(poly.length + 1).fill(0);
      for (let j = 0; j < poly.length; j++) {
        next[j] ^= gfMul(poly[j], 1); // * x term (multiply by (x - a^i)) below
      }
      for (let j = 0; j < poly.length; j++) {
        next[j + 1] ^= gfMul(poly[j], GF_EXP[i]);
      }
      poly = next;
    }
    return poly; // length degree+1
  }

  function rsEncode(dataCodewords, ecCount) {
    const gen = rsGeneratorPoly(ecCount);
    const res = dataCodewords.concat(new Array(ecCount).fill(0));
    for (let i = 0; i < dataCodewords.length; i++) {
      const coef = res[i];
      if (coef === 0) continue;
      for (let j = 0; j < gen.length; j++) {
        res[i + j] ^= gfMul(gen[j], coef);
      }
    }
    return res.slice(dataCodewords.length);
  }

  // ---- Version capacity table, EC level M, versions 1-10 ----
  // groups: list of [blockCount, dataCodewordsPerBlock]
  const VERSION_TABLE = {
    1: { ec: 10, groups: [[1, 16]] },
    2: { ec: 16, groups: [[1, 28]] },
    3: { ec: 26, groups: [[1, 44]] },
    4: { ec: 18, groups: [[2, 32]] },
    5: { ec: 24, groups: [[2, 43]] },
    6: { ec: 16, groups: [[4, 27]] },
    7: { ec: 18, groups: [[4, 31]] },
    8: { ec: 22, groups: [[2, 38], [2, 39]] },
    9: { ec: 22, groups: [[3, 36], [2, 37]] },
    10: { ec: 26, groups: [[4, 43], [1, 44]] },
  };
  const REMAINDER_BITS = { 1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0 };
  const ALIGNMENT_COORDS = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
  };

  function totalDataCodewords(v) {
    return VERSION_TABLE[v].groups.reduce((s, [n, cw]) => s + n * cw, 0);
  }

  function charCountBits(version) {
    return version <= 9 ? 8 : 16; // byte mode
  }

  function byteCapacity(version) {
    const total = totalDataCodewords(version);
    const headerBits = 4 + charCountBits(version);
    return Math.floor((total * 8 - headerBits) / 8);
  }

  function chooseVersion(byteLen) {
    for (let v = 1; v <= 10; v++) {
      if (byteLen <= byteCapacity(v)) return v;
    }
    throw new Error("SDQRCode: input too large (max ~" + byteCapacity(10) + " bytes at version 10)");
  }

  // ---- Bit buffer ----
  class BitBuffer {
    constructor() { this.bits = []; }
    put(value, length) {
      for (let i = length - 1; i >= 0; i--) this.bits.push((value >>> i) & 1);
    }
    get length() { return this.bits.length; }
    toBytes() {
      const bytes = [];
      for (let i = 0; i < this.bits.length; i += 8) {
        let b = 0;
        for (let j = 0; j < 8; j++) b = (b << 1) | (this.bits[i + j] || 0);
        bytes.push(b);
      }
      return bytes;
    }
  }

  function utf8Bytes(str) {
    return Array.from(new TextEncoder().encode(str));
  }

  function buildDataCodewords(version, dataBytes) {
    const buf = new BitBuffer();
    buf.put(0b0100, 4); // byte mode indicator
    buf.put(dataBytes.length, charCountBits(version));
    for (const b of dataBytes) buf.put(b, 8);

    const totalBits = totalDataCodewords(version) * 8;
    // terminator (up to 4 bits)
    const termLen = Math.min(4, totalBits - buf.length);
    if (termLen > 0) buf.put(0, termLen);
    // pad to byte boundary
    while (buf.length % 8 !== 0) buf.put(0, 1);
    // pad codewords
    const padBytes = [0xec, 0x11];
    let pi = 0;
    while (buf.length < totalBits) {
      buf.put(padBytes[pi % 2], 8);
      pi++;
    }
    return buf.toBytes();
  }

  function interleave(version, dataCodewords) {
    const groups = VERSION_TABLE[version].groups;
    const ecCount = VERSION_TABLE[version].ec;
    const blocks = []; // { data: [...], ec: [...] }
    let offset = 0;
    for (const [blockCount, cwPerBlock] of groups) {
      for (let i = 0; i < blockCount; i++) {
        const data = dataCodewords.slice(offset, offset + cwPerBlock);
        offset += cwPerBlock;
        const ec = rsEncode(data, ecCount);
        blocks.push({ data, ec });
      }
    }
    const maxData = Math.max(...blocks.map((b) => b.data.length));
    const out = [];
    for (let i = 0; i < maxData; i++) {
      for (const b of blocks) if (i < b.data.length) out.push(b.data[i]);
    }
    const maxEc = Math.max(...blocks.map((b) => b.ec.length));
    for (let i = 0; i < maxEc; i++) {
      for (const b of blocks) if (i < b.ec.length) out.push(b.ec[i]);
    }
    return out;
  }

  // ---- Format / version info (BCH) ----
  const G15 = 0x537;
  const G15_MASK = 0x5412;
  const G18 = 0x1f25;

  function bchDigitCount(x) {
    let d = 0;
    while (x !== 0) { d++; x >>>= 1; }
    return d;
  }
  function bchRemainder(data, generator) {
    let d = data;
    const genDigits = bchDigitCount(generator);
    while (bchDigitCount(d) >= genDigits) {
      d ^= generator << (bchDigitCount(d) - genDigits);
    }
    return d;
  }
  function formatBits(maskPattern) {
    const ecIndicator = 0b00; // level M
    const data = (ecIndicator << 3) | maskPattern; // 5 bits
    const d = data << 10;
    const rem = bchRemainder(d, G15);
    return (d | rem) ^ G15_MASK;
  }
  function versionInfoBits(version) {
    const d = version << 12;
    const rem = bchRemainder(d, G18);
    return d | rem;
  }

  // ---- Matrix construction ----
  function newMatrix(size) {
    const m = [];
    for (let i = 0; i < size; i++) m.push(new Array(size).fill(null));
    return m;
  }

  function isFinderZone(r, c, size) {
    return (r < 9 && c < 9) || (r < 9 && c > size - 9) || (r > size - 9 && c < 9);
  }

  function placeFinder(m, top, left) {
    for (let r = -1; r <= 7; r++) {
      for (let c = -1; c <= 7; c++) {
        const rr = top + r, cc = left + c;
        if (rr < 0 || cc < 0 || rr >= m.length || cc >= m.length) continue;
        const inRing = r === -1 || r === 7 || c === -1 || c === 7;
        const inOuter = r >= 0 && r <= 6 && c >= 0 && c <= 6 && (r === 0 || r === 6 || c === 0 || c === 6);
        const inCenter = r >= 2 && r <= 4 && c >= 2 && c <= 4;
        m[rr][cc] = inOuter || inCenter ? 1 : 0;
      }
    }
  }

  function placeAlignment(m, r, c) {
    for (let dr = -2; dr <= 2; dr++) {
      for (let dc = -2; dc <= 2; dc++) {
        const rr = r + dr, cc = c + dc;
        const ring = Math.max(Math.abs(dr), Math.abs(dc));
        m[rr][cc] = ring === 1 ? 0 : 1;
      }
    }
  }

  function buildFunctionMatrix(version, size) {
    const m = newMatrix(size);
    placeFinder(m, 0, 0);
    placeFinder(m, 0, size - 7);
    placeFinder(m, size - 7, 0);

    // timing patterns
    for (let i = 8; i < size - 8; i++) {
      if (m[6][i] === null) m[6][i] = i % 2 === 0 ? 1 : 0;
      if (m[i][6] === null) m[i][6] = i % 2 === 0 ? 1 : 0;
    }

    // alignment patterns
    const coords = ALIGNMENT_COORDS[version];
    for (const r of coords) {
      for (const c of coords) {
        if (isFinderZone(r, c, size)) continue;
        placeAlignment(m, r, c);
      }
    }

    // dark module
    m[size - 8][8] = 1;

    // reserve format info areas (value filled in later)
    for (let i = 0; i < 9; i++) {
      if (m[8][i] === null) m[8][i] = -1; // reserved marker
      if (m[i][8] === null) m[i][8] = -1;
    }
    for (let i = 0; i < 8; i++) {
      if (m[8][size - 1 - i] === null) m[8][size - 1 - i] = -1;
      if (m[size - 1 - i][8] === null) m[size - 1 - i][8] = -1;
    }

    // reserve version info areas (version >= 7)
    if (version >= 7) {
      for (let r = 0; r < 6; r++) {
        for (let c = 0; c < 3; c++) {
          m[r][size - 11 + c] = -1;
          m[size - 11 + c][r] = -1;
        }
      }
    }

    return m;
  }

  function isFunctionModule(m, r, c) {
    return m[r][c] !== null;
  }

  function applyMask(m, size, maskPattern, funcMask) {
    const out = newMatrix(size);
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        let v = m[r][c];
        if (!funcMask[r][c]) {
          let flip;
          switch (maskPattern) {
            case 0: flip = (r + c) % 2 === 0; break;
            case 1: flip = r % 2 === 0; break;
            case 2: flip = c % 3 === 0; break;
            case 3: flip = (r + c) % 3 === 0; break;
            case 4: flip = (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0; break;
            case 5: flip = ((r * c) % 2) + ((r * c) % 3) === 0; break;
            case 6: flip = (((r * c) % 2) + ((r * c) % 3)) % 2 === 0; break;
            case 7: flip = (((r + c) % 2) + ((r * c) % 3)) % 2 === 0; break;
          }
          if (flip) v = v ^ 1;
        }
        out[r][c] = v;
      }
    }
    return out;
  }

  function penalty(m, size) {
    let total = 0;
    // Rule 1: runs of 5+ same color, rows then cols
    for (let r = 0; r < size; r++) {
      let run = 1;
      for (let c = 1; c < size; c++) {
        if (m[r][c] === m[r][c - 1]) run++;
        else { if (run >= 5) total += 3 + (run - 5); run = 1; }
      }
      if (run >= 5) total += 3 + (run - 5);
    }
    for (let c = 0; c < size; c++) {
      let run = 1;
      for (let r = 1; r < size; r++) {
        if (m[r][c] === m[r - 1][c]) run++;
        else { if (run >= 5) total += 3 + (run - 5); run = 1; }
      }
      if (run >= 5) total += 3 + (run - 5);
    }
    // Rule 2: 2x2 blocks
    for (let r = 0; r < size - 1; r++) {
      for (let c = 0; c < size - 1; c++) {
        const v = m[r][c];
        if (v === m[r][c + 1] && v === m[r + 1][c] && v === m[r + 1][c + 1]) total += 3;
      }
    }
    // Rule 3: 1:1:3:1:1 finder-like pattern with 4-module light run on either side
    const pat1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0];
    const pat2 = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1];
    function matchesAt(arr, idx, pat) {
      for (let i = 0; i < pat.length; i++) if (arr[idx + i] !== pat[i]) return false;
      return true;
    }
    for (let r = 0; r < size; r++) {
      const row = m[r];
      for (let c = 0; c <= size - 11; c++) {
        if (matchesAt(row, c, pat1) || matchesAt(row, c, pat2)) total += 40;
      }
    }
    for (let c = 0; c < size; c++) {
      const col = [];
      for (let r = 0; r < size; r++) col.push(m[r][c]);
      for (let r = 0; r <= size - 11; r++) {
        if (matchesAt(col, r, pat1) || matchesAt(col, r, pat2)) total += 40;
      }
    }
    // Rule 4: dark ratio
    let dark = 0;
    for (let r = 0; r < size; r++) for (let c = 0; c < size; c++) if (m[r][c]) dark++;
    const percent = (dark * 100) / (size * size);
    const prev5 = Math.floor(percent / 5) * 5;
    const next5 = prev5 + 5;
    total += Math.min(Math.abs(prev5 - 50) / 5, Math.abs(next5 - 50) / 5) * 10;
    return total;
  }

  function generateMatrix(text) {
    const dataBytes = utf8Bytes(text);
    const version = chooseVersion(dataBytes.length);
    const size = 17 + 4 * version;

    const dataCodewords = buildDataCodewords(version, dataBytes);
    const interleaved = interleave(version, dataCodewords);
    const remainder = REMAINDER_BITS[version];

    const funcTemplate = buildFunctionMatrix(version, size);
    const funcMask = funcTemplate.map((row) => row.map((v) => v !== null));

    const dataMatrix = funcTemplate.map((row) => row.slice());
    placeDataWithRemainder(dataMatrix, size, interleaved, remainder);

    let best = null, bestPenalty = Infinity, bestMask = 0;
    for (let mp = 0; mp < 8; mp++) {
      const masked = applyMask(dataMatrix, size, mp, funcMask);
      writeFormatInfo(masked, size, version, mp);
      const p = penalty(masked, size);
      if (p < bestPenalty) { bestPenalty = p; best = masked; bestMask = mp; }
    }

    const modules = best.map((row) => row.map((v) => (v ? 1 : 0)));
    return { size, modules, version, maskPattern: bestMask };
  }

  function placeDataWithRemainder(m, size, dataCodewords, remainderBits) {
    // Same zigzag as placeData, but codewords + remainder bits together as a bitstream.
    const bits = [];
    for (const byte of dataCodewords) for (let i = 7; i >= 0; i--) bits.push((byte >> i) & 1);
    for (let i = 0; i < remainderBits; i++) bits.push(0);
    let bitIndex = 0;
    let upward = true;
    let col = size - 1;
    while (col > 0) {
      if (col === 6) col--;
      for (let i = 0; i < size; i++) {
        const row = upward ? size - 1 - i : i;
        for (const c of [col, col - 1]) {
          if (m[row][c] === null) {
            m[row][c] = bitIndex < bits.length ? bits[bitIndex] : 0;
            bitIndex++;
          }
        }
      }
      upward = !upward;
      col -= 2;
    }
  }

  function writeFormatInfo(m, size, version, maskPattern) {
    const bits = formatBits(maskPattern);
    const get = (i) => (bits >> i) & 1;

    // Format info is duplicated (two copies) for redundancy, per spec.
    // Vertical strip (column 8): bits 0-5 near top-left, bit6/7 continue
    // down, bits 8-14 reappear near the bottom-left finder.
    for (let i = 0; i < 15; i++) {
      const v = get(i);
      if (i < 6) m[i][8] = v;
      else if (i < 8) m[i + 1][8] = v;
      else m[size - 15 + i][8] = v;
    }
    // Horizontal strip (row 8): bits 0-7 near top-right, bits 8-14 near top-left.
    for (let i = 0; i < 15; i++) {
      const v = get(i);
      if (i < 8) m[8][size - i - 1] = v;
      else if (i < 9) m[8][15 - i] = v; // i==8 -> col 7
      else m[8][14 - i] = v; // i=9..14 -> cols 5..0
    }

    if (version >= 7) {
      const vbits = versionInfoBits(version);
      const vget = (i) => (vbits >> i) & 1;
      for (let i = 0; i < 18; i++) {
        const v = vget(i);
        const rowMajorR = Math.floor(i / 3), rowMajorC = (i % 3) + (size - 11);
        m[rowMajorR][rowMajorC] = v;
        const colMajorR = (i % 3) + (size - 11), colMajorC = Math.floor(i / 3);
        m[colMajorR][colMajorC] = v;
      }
    }
  }

  function renderToCanvas(canvas, text, options) {
    const opts = options || {};
    const { size, modules } = generateMatrix(text);
    const border = 4;
    const totalModules = size + border * 2;
    const px = canvas.width;
    const scale = px / totalModules;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = opts.light || "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = opts.dark || "#000000";
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        if (modules[r][c]) {
          ctx.fillRect((c + border) * scale, (r + border) * scale, Math.ceil(scale), Math.ceil(scale));
        }
      }
    }
  }

  window.SDQRCode = { generateMatrix, renderToCanvas };
})();
