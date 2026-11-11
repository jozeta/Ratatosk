/* Låda Glass 2.0.0: behaviour for lada-glass.css (tools/design). Generated from design/js/ by build.py; do not edit. */
// Opens the wrapper that 99-foot.js closes. build.py concatenates design/js/*.js in name order
// into lada-glass.js; every part in between is plain statements that attach to LG.
(function (root) {
"use strict";

const LG = {};
LG.version = "2.0.0";            // build.py: design/VERSION
LG.tokens = {"accents": [{"name": "fjord", "d": "#5A93C4", "l": "#2B5B84"}, {"name": "arctic-teal", "d": "#459AA3", "l": "#216B73"}, {"name": "slate-steel", "d": "#7D91A8", "l": "#415164"}, {"name": "frost-cyan", "d": "#88C0D0", "l": "#2A7288"}, {"name": "aurora-green", "d": "#A3BE8C", "l": "#45763E"}, {"name": "aurora-violet", "d": "#B48EAD", "l": "#714D88"}, {"name": "lingonberry", "d": "#D96E75", "l": "#A83541"}, {"name": "cloudberry", "d": "#E0915C", "l": "#AD591D"}, {"name": "birch-gold", "d": "#E1BC6D", "l": "#8C6A16"}, {"name": "midnight-indigo", "d": "#8D95E3", "l": "#41479C"}]};       // build.py: { accents: [{name, d, l}, …] } from tokens.json, in its order
LG._added = [];                      // functions called with each element added to the document (one shared MutationObserver, set up in 04-stepper.js)
LG._init = [];                       // parts push setup functions (delegated listeners); 99-foot.js runs them once the DOM is ready

// --- Shared utilities (LadaGlass.util) ---------------------------------------------------------
const SVG_NS = "http://www.w3.org/2000/svg";
let uidCount = 0;

// Attributes are set with setAttribute; inline handlers (on*) are refused, so app data passed as
// attributes can never become script.
function setAttrs(node, attrs) {
  for (const k of Object.keys(attrs || {})) {
    if (/^on/i.test(k)) throw new Error(`LadaGlass: refusing inline handler attribute ${k}`);
    node.setAttribute(k, String(attrs[k]));
  }
}

function append(node, children) {
  for (const c of children || []) {
    if (c === null || c === undefined || c === false) continue;
    node.append(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
}

LG.util = {
  // el(tag, {class, text, attrs}, children?): an element; text goes in as textContent only, and
  // string children become text nodes.
  el(tag, opts, children) {
    const o = opts || {};
    const node = document.createElement(tag);
    if (o.class) node.className = o.class;
    if (o.text !== undefined && o.text !== null) node.textContent = String(o.text);
    setAttrs(node, o.attrs);
    append(node, children);
    return node;
  },

  // svg(tag, attrs, children?): an SVG element. A non-finite number (NaN, ±Infinity) throws, so a
  // bad chart value never reaches an attribute.
  svg(tag, attrs, children) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const k of Object.keys(attrs || {})) {
      const v = attrs[k];
      if (typeof v === "number" && !Number.isFinite(v)) throw new Error(`LadaGlass: non-finite ${k}=${v} on <${tag}>`);
    }
    setAttrs(node, attrs);
    append(node, children);
    return node;
  },

  // focusables(root): the elements Tab can reach inside root, in document order.
  focusables(root) {
    const sel = 'a[href], area[href], button, input, select, textarea, iframe, summary, audio[controls], video[controls], [contenteditable]:not([contenteditable="false"]), [tabindex]';
    return Array.from(root.querySelectorAll(sel)).filter((e) =>
      !e.disabled && e.getAttribute("tabindex") !== "-1" && !(e.type === "hidden" && e.tagName === "INPUT") &&
      !e.closest("[hidden], [inert]") && e.getClientRects().length > 0);
  },

  reducedMotion() {
    return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  },

  // onKey(el, {"Escape": fn, "Shift+Tab": fn, "Mod+k": fn}): keydown shortcuts on el. Mod is Meta
  // on Apple platforms and Ctrl elsewhere; modifiers must match exactly; letters ignore case.
  // fn gets the event (call preventDefault there if needed). Returns a function that removes it.
  onKey(el, map) {
    const handler = (e) => {
      const k = e.key || "";   // Chrome's autofill fires keydown events without a key
      const mac = /^(Mac|iP)/.test((typeof navigator !== "undefined" && navigator.platform) || "");
      for (const combo of Object.keys(map)) {
        const parts = combo.split("+");
        const key = parts.pop();
        const want = { ctrl: false, meta: false, alt: false, shift: false };
        for (const m of parts) {
          const n = m.toLowerCase();
          if (n === "mod") want[mac ? "meta" : "ctrl"] = true;
          else if (n in want) want[n] = true;
        }
        const keyOk = key.length === 1 ? k.toLowerCase() === key.toLowerCase() : k === key;
        if (keyOk && !!e.ctrlKey === want.ctrl && !!e.metaKey === want.meta && !!e.altKey === want.alt && !!e.shiftKey === want.shift) {
          map[combo](e);
          return;
        }
      }
    };
    el.addEventListener("keydown", handler);
    return () => el.removeEventListener("keydown", handler);
  },

  // uid(prefix): a unique id for aria-* wiring, never one already used in the page.
  uid(prefix) {
    let id;
    do { id = `${prefix || "lg"}-${++uidCount}`; } while (typeof document !== "undefined" && document.getElementById(id));
    return id;
  },
};

// Overlay core (LadaGlass.overlay), shared by modals, the drawer, the palette and later overlays.
// Built on the native <dialog>: showModal() gives the focus trap, the top layer and ::backdrop.
//   open(dialog, {trigger, modal = true, onClose})  show it, remember the trigger (default: the
//                                                   focused element) and add it to the stack
//   close(dialog, returnValue?)                     play the close animation, close it, and put
//                                                   focus back on its trigger
//   stack()                                         the open overlays, newest last
// Esc closes only the newest overlay. A click on a modal's backdrop closes it unless the dialog has
// data-lg-static. A <button type="button" data-lg-close value="…"> closes its dialog with that
// value and skips form validation (use it for Cancel, so Enter in a field never means Cancel). A
// <form method="dialog"> inside closes it through close(), with the submit button's value. However a dialog closes (even dialog.close() from the app), the stack, the focus
// and onClose are settled once: at once for close(), and otherwise when its open attribute goes
// (a MutationObserver, which unlike the "close" event doesn't wait for a rendered frame). Each
// opening has its own generation, so a late close event, animationend or timer from an earlier
// opening never settles a reopened dialog. An open overlay removed from the document without being
// closed is pruned (settled, onClose called) before the stack is used.
// LG._overlayChange: functions called after an overlay enters or leaves the stack (the toaster
// follows the newest modal with it).
const overlayStack = [];
const overlayState = new WeakMap();   // dialog -> {gen, trigger, modal, onClose, closing, timer, onEnd}
const overlayWired = new WeakSet();
let overlayGen = 0;
LG._overlayChange = [];

function overlayChanged() {
  for (const fn of LG._overlayChange) {
    try { fn(); } catch (e) { console.error("LadaGlass overlay change:", e); }
  }
}

function overlayIsDialog(d) {
  return typeof HTMLDialogElement === "function" && d instanceof HTMLDialogElement;
}

// The close animation is whatever the CSS gives [data-lg-closing]; none (or reduced motion) closes at once.
function overlayAnimates(d) {
  if (LG.util.reducedMotion()) return false;
  const cs = getComputedStyle(d);
  return cs.animationName !== "none" && parseFloat(cs.animationDuration) > 0;
}

// overlayFinish(d, gen?): settle the opening `gen` (default: the current one) once.
function overlayFinish(d, gen) {
  const st = overlayState.get(d);
  const i = overlayStack.indexOf(d);
  if (!st || i < 0) return;                         // not ours, or already settled
  if (gen !== undefined && gen !== st.gen) return;  // an earlier opening's late signal
  const wasTop = i === overlayStack.length - 1;
  overlayStack.splice(i, 1);
  clearTimeout(st.timer);
  if (st.onEnd) d.removeEventListener("animationend", st.onEnd);
  d.removeAttribute("data-lg-closing");
  overlayState.delete(d);
  // Only the newest overlay hands focus back: an older one closing underneath leaves it where it is.
  // A removed dialog only does so when focus was lost with it (it can't hold focus any more).
  const lost = !document.activeElement || document.activeElement === document.body;
  if (wasTop && (d.isConnected || lost)) {
    const t = overlayReturnTarget(st.trigger);
    if (t) t.focus();
  }
  overlayChanged();
  if (typeof st.onClose === "function") st.onClose(d.returnValue);
}

// Where focus goes back to: the trigger, or when it can't take focus any more (removed, or hidden like
// the item of a menu that closed when this overlay opened over it) the trigger of the floating panel
// that held it (LG._float, following its returnTo chain), else the first control of the overlay now
// on top. Null when there is nowhere sensible.
function overlayReturnTarget(trigger) {
  const ok = (x) => !!x && x.isConnected && typeof x.focus === "function" && x.getClientRects().length > 0;
  let t = trigger;
  for (let n = 0; t && !ok(t) && n < 10; n++) t = LG._float ? LG._float.backFor(t) : null;
  if (ok(t)) return t;
  const top = overlayStack[overlayStack.length - 1];
  return top ? LG.util.focusables(top).find(ok) || null : null;
}

// Settle open overlays that were removed from the document without being closed.
function overlayPrune() {
  for (const d of overlayStack.slice().reverse()) if (!d.isConnected) overlayFinish(d);
}

function overlayWire(d) {
  if (overlayWired.has(d)) return;
  overlayWired.add(d);
  // Both only count while the dialog is closed: by the time a queued close event (or the record of
  // open() dropping an app-set open attribute) arrives, the dialog may be open again.
  d.addEventListener("close", () => { if (!d.open) overlayFinish(d); });
  if (typeof MutationObserver === "function") {
    new MutationObserver(() => { if (!d.open) overlayFinish(d); }).observe(d, { attributes: true, attributeFilter: ["open"] });
  }
  // The browser's Esc (close request) on a modal: run it through close() so it animates.
  d.addEventListener("cancel", (e) => {
    if (!overlayState.has(d)) return;
    e.preventDefault();
    LG.overlay.close(d, "");
  });
  // Backdrop: the press and the click both land on the dialog itself, outside its box. (A drag
  // that starts inside and ends outside doesn't count.)
  let downOutside = false;
  const outside = (e) => {
    if (e.target !== d) return false;
    const r = d.getBoundingClientRect();
    return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
  };
  d.addEventListener("pointerdown", (e) => { downOutside = outside(e); });
  d.addEventListener("click", (e) => {
    const st = overlayState.get(d);
    const hit = downOutside && outside(e);
    downOutside = false;
    if (hit && st && st.modal && !d.hasAttribute("data-lg-static")) LG.overlay.close(d, "");
  });
}

LG.overlay = {
  open(d, opts) {
    if (!overlayIsDialog(d)) throw new TypeError("LadaGlass.overlay.open: expected a <dialog> element");
    const o = opts || {};
    overlayPrune();
    if (overlayState.has(d)) return;   // already open
    overlayWire(d);
    const trigger = o.trigger || (document.activeElement !== document.body ? document.activeElement : null);
    d.removeAttribute("data-lg-closing");
    // Opened outside the overlay core (an open attribute): drop it without a close event, then reopen properly.
    if (d.open) d.removeAttribute("open");
    // Shown first, so a dialog the browser refuses (e.g. not in the document) never enters the stack.
    if (o.modal === false) d.show(); else d.showModal();
    overlayState.set(d, { gen: ++overlayGen, trigger, modal: o.modal !== false, onClose: o.onClose, closing: false, timer: 0, onEnd: null });
    overlayStack.push(d);
    overlayChanged();
  },

  close(d, returnValue) {
    const st = overlayState.get(d);
    if (!st) { if (overlayIsDialog(d) && d.open) d.close(returnValue); return; }
    if (st.closing) return;
    st.closing = true;
    const gen = st.gen;
    const done = () => {
      const cur = overlayState.get(d);
      if (!cur || cur.gen !== gen) return;   // settled already, maybe reopened since
      if (d.open) d.close(returnValue === undefined ? "" : String(returnValue));
      overlayFinish(d, gen);
    };
    d.setAttribute("data-lg-closing", "");
    if (!overlayAnimates(d)) { done(); return; }
    st.onEnd = (e) => { if (e.target === d) done(); };
    d.addEventListener("animationend", st.onEnd);
    st.timer = setTimeout(done, 600);   // in case animationend never comes
  },

  stack() {
    overlayPrune();
    return overlayStack.slice();
  },
};

LG._init.push(() => {
  // Esc closes the newest overlay only. Bubble phase, so a widget inside that handles Esc itself
  // (and calls preventDefault) wins; preventDefault here also stops the browser closing a lower modal.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented || e.isComposing) return;
    overlayPrune();
    if (!overlayStack.length) return;
    e.preventDefault();
    LG.overlay.close(overlayStack[overlayStack.length - 1], "");
  });
  document.addEventListener("click", (e) => {
    const t = e.target;
    const b = t && typeof t.closest === "function" ? t.closest("[data-lg-close]") : null;
    const d = b ? b.closest("dialog") : null;
    if (!d || !overlayState.has(d)) return;
    e.preventDefault();
    LG.overlay.close(d, b.value !== undefined ? b.value : "");
  });
  // <form method="dialog"> in an open overlay: close through close() (animated) with the
  // submitter's value, instead of the browser's instant close.
  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (!f || f.method !== "dialog" || e.defaultPrevented) return;
    const d = f.closest("dialog");
    if (!d || !overlayState.has(d)) return;
    e.preventDefault();
    LG.overlay.close(d, e.submitter && e.submitter.value !== undefined ? e.submitter.value : "");
  });
});

// Placement (LadaGlass.place) and the floating-panel core shared by the tooltip, popover, menus and
// combobox (later the chart tooltip).
//   place(anchorRect, floatSize, viewport, side = "bottom", gap = 6) → {top, left, side}
//     puts the float on `side` of the anchor (centred along it), flips to the opposite side when it
//     doesn't fit but the opposite does, then clamps it inside the viewport with an 8 px margin. Pure.
const PLACE_MARGIN = 8;
const PLACE_OPPOSITE = { top: "bottom", bottom: "top", left: "right", right: "left" };

LG.place = (a, f, vp, side, gap) => {
  const s0 = PLACE_OPPOSITE[side] ? side : "bottom";
  const g = gap === undefined ? 6 : gap;
  const fits = (s) => (s === "bottom" ? a.bottom + g + f.height <= vp.height - PLACE_MARGIN
    : s === "top" ? a.top - g - f.height >= PLACE_MARGIN
      : s === "right" ? a.right + g + f.width <= vp.width - PLACE_MARGIN
        : a.left - g - f.width >= PLACE_MARGIN);
  const s = !fits(s0) && fits(PLACE_OPPOSITE[s0]) ? PLACE_OPPOSITE[s0] : s0;
  let top, left;
  if (s === "bottom" || s === "top") {
    top = s === "bottom" ? a.bottom + g : a.top - g - f.height;
    left = a.left + (a.right - a.left) / 2 - f.width / 2;
  } else {
    left = s === "right" ? a.right + g : a.left - g - f.width;
    top = a.top + (a.bottom - a.top) / 2 - f.height / 2;
  }
  const clamp = (v, size, room) => Math.max(PLACE_MARGIN, Math.min(v, room - PLACE_MARGIN - size));
  return { top: clamp(top, f.height, vp.height), left: clamp(left, f.width, vp.width), side: s };
};

// Floating panels (LG._float, internal). A shown panel is a manual popover where supported: the top
// layer keeps it above everything at viewport coordinates (a dialog's transform, backdrop-filter or
// overflow would otherwise move or clip it). A modal dialog makes the rest of the page inert, so a
// panel whose host (its trigger) is inside an open dialog is moved into that dialog while shown, and
// put back where it was when hidden (one the script made, never placed before, goes to body). It is
// placed with place() and follows scroll and resize.
//   show(el, {anchor(size) → rect, side, gap, host}) / hide(el) / update(el) / shown(el)
//   open(el, {…show options, trigger, returnTo, onClose}) / close(el, {focus}) / isOpen(el) / backFor(node)
//     open() also adds it to the dismiss stack: Esc closes the newest (focus back on returnTo or the
//     trigger, and the Esc never reaches an enclosing modal); a click or focus outside the panel and
//     its trigger closes it; so does a modal opening over it or its dialog closing.
const floatCan = typeof HTMLElement !== "undefined" && typeof HTMLElement.prototype.showPopover === "function";
const floatShown = new Map();   // el -> {anchor, side, gap}
const floatHome = new WeakMap(); // el -> placeholder comment where it came from, or "body"
const floatLayers = [];         // newest last: {el, trigger, returnTo, onClose}
const floatBack = new WeakMap(); // el -> where its focus goes back to (returnTo or trigger), kept after it closes

function floatPosition(el) {
  const st = floatShown.get(el);
  if (!st) return;
  const size = { width: el.offsetWidth, height: el.offsetHeight };   // layout size: the open animation's scale doesn't count
  const p = LG.place(st.anchor(size), size, { width: document.documentElement.clientWidth, height: window.innerHeight }, st.side, st.gap);
  el.style.setProperty("top", `${Math.round(p.top)}px`);     // whole pixels keep the text crisp
  el.style.setProperty("left", `${Math.round(p.left)}px`);
  el.setAttribute("data-lg-side", p.side);
}

function floatLayerClose(L, focus) {
  const i = floatLayers.indexOf(L);
  if (i < 0) return;
  floatLayers.splice(i, 1);
  LG._float.hide(L.el);
  // Esc always hands focus back; an outside click or focus only when focus was in the panel (or lost).
  const back = L.returnTo || L.trigger;
  const lost = !document.activeElement || document.activeElement === document.body || L.el.contains(document.activeElement);
  if ((focus || lost) && back && back.isConnected && typeof back.focus === "function") back.focus();
  if (typeof L.onClose === "function") L.onClose();
}

// Close the newest panels down to the first one that holds `target` (a click or focus outside).
function floatOutside(target) {
  for (const L of floatLayers.slice().reverse()) {
    if (target && (L.el.contains(target) || (L.trigger && L.trigger.contains(target)))) return;
    floatLayerClose(L, false);
  }
}

LG._float = {
  show(el, opts) {
    const o = opts || {};
    const dlg = o.host && typeof o.host.closest === "function" ? o.host.closest("dialog[open]") : null;
    if (dlg && !dlg.contains(el)) {
      if (!floatHome.has(el)) {
        // Where to go back to: a placeholder where it was, or body for one made by the script.
        let home = "body";
        if (el.isConnected) { home = document.createComment("lg-float"); el.before(home); }
        floatHome.set(el, home);
      }
      dlg.append(el);
    } else if (!el.isConnected) {
      document.body.append(el);
    }
    el.setAttribute("data-lg-open", "");
    if (floatCan) {
      if (!el.hasAttribute("popover")) el.setAttribute("popover", "manual");
      if (!el.matches(":popover-open")) { try { el.showPopover(); } catch (_) { /* not in a document */ } }
    }
    floatShown.set(el, { anchor: o.anchor, side: o.side || "bottom", gap: o.gap });
    floatPosition(el);
  },
  hide(el) {
    if (!floatShown.has(el)) return;
    floatShown.delete(el);
    if (floatCan && el.matches(":popover-open")) { try { el.hidePopover(); } catch (_) { /* already gone */ } }
    el.removeAttribute("data-lg-open");
    const home = floatHome.get(el);
    if (home) {
      floatHome.delete(el);
      if (home === "body") document.body.append(el);
      else if (home.isConnected) home.replaceWith(el);
      else home.remove();
    }
  },
  update(el) { floatPosition(el); },
  shown(el) { return floatShown.has(el); },
  open(el, opts) {
    const o = opts || {};
    if (LG._float.isOpen(el)) return;
    LG._float.show(el, o);
    floatLayers.push({ el, trigger: o.trigger || null, returnTo: o.returnTo || null, onClose: o.onClose });
    if (o.returnTo || o.trigger) floatBack.set(el, o.returnTo || o.trigger); else floatBack.delete(el);
  },
  close(el, opts) {
    const L = floatLayers.find((x) => x.el === el);
    if (L) floatLayerClose(L, !!(opts && opts.focus));
  },
  isOpen(el) { return floatLayers.some((x) => x.el === el); },
  // backFor(node): returnTo or the trigger of the panel (open or closed since) that holds node, or null.
  backFor(node) {
    for (let n = node; n; n = n.parentElement) if (floatBack.has(n)) return floatBack.get(n);
    return null;
  },
};

LG._overlayChange.push(() => {
  const modals = LG.overlay.stack().filter((d) => d.open);
  const newest = modals[modals.length - 1];
  for (const L of floatLayers.slice().reverse()) {
    const d = L.el.closest("dialog");
    if ((d && !d.open) || (newest && !newest.contains(L.el))) floatLayerClose(L, false);
  }
});

LG._init.push(() => {
  // Capture phase, so Esc closes the newest panel before any widget or the overlay core sees it;
  // preventDefault keeps the overlay core (and the browser's dialog cancel) from also closing a modal.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented || e.isComposing || !floatLayers.length) return;
    e.preventDefault();
    floatLayerClose(floatLayers[floatLayers.length - 1], true);
  }, true);
  document.addEventListener("click", (e) => { if (floatLayers.length) floatOutside(e.target); });
  document.addEventListener("focusin", (e) => { if (floatLayers.length) floatOutside(e.target); });
  const follow = () => { for (const el of floatShown.keys()) floatPosition(el); };
  document.addEventListener("scroll", follow, { capture: true, passive: true });
  window.addEventListener("resize", follow);
});

// Spotlight hover (.lg-spotlight): one delegated pointermove listener keeps --lg-x and --lg-y (px,
// relative to the element) up to date; the CSS draws the light there. Under reduced motion the CSS
// hides the light, so updating the two properties costs nothing visible.
LG._init.push(() => {
  document.addEventListener("pointermove", (e) => {
    const t = e.target;
    const el = t && typeof t.closest === "function" ? t.closest(".lg-spotlight") : null;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--lg-x", `${e.clientX - r.left}px`);
    el.style.setProperty("--lg-y", `${e.clientY - r.top}px`);
  }, { passive: true });
});

// Number stepper (.lg-stepper with <button data-lg-step="-1|1"> around <input type="number">) and
// the slider fill (.lg-slider keeps --lg-fill, the filled share of the track, up to date). Both use
// delegated listeners and a MutationObserver, so controls added later work without any setup. The
// fill also re-syncs on focus, pointer press, change and form reset, so a script setting `value`
// (which fires no event) is corrected as soon as the slider is used.
function decimals(n) {
  const s = String(n);
  const i = s.indexOf(".");
  return i < 0 ? 0 : s.length - i - 1;
}

function stepInput(input, dir) {
  if (input.disabled || input.readOnly) return;
  const num = (v) => (v === "" || v === null || v === undefined ? NaN : Number(v));
  const min = num(input.min), max = num(input.max);
  const stepAttr = num(input.step);
  const step = Number.isFinite(stepAttr) && stepAttr > 0 ? stepAttr : 1;
  const cur = num(input.value);
  const base = Number.isFinite(cur) ? cur : (Number.isFinite(min) ? min : 0);
  let next = base + dir * step;
  next = Number(next.toFixed(Math.max(decimals(step), decimals(base))));   // 0.1 + 0.2 stays 0.3
  if (Number.isFinite(max) && next > max) next = max;
  if (Number.isFinite(min) && next < min) next = min;
  if (String(next) === input.value) return;
  input.value = String(next);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function syncSlider(r) {
  const min = Number(r.min === "" ? 0 : r.min), max = Number(r.max === "" ? 100 : r.max);
  const span = max - min;
  const pct = span > 0 ? Math.min(100, Math.max(0, ((Number(r.value) - min) / span) * 100)) : 0;
  r.style.setProperty("--lg-fill", `${Number(pct.toFixed(2))}%`);
}

// syncSliders(root?): set the fill on every slider under root (default: the document).
LG.syncSliders = (root) => {
  for (const r of (root || document).querySelectorAll(".lg-slider")) syncSlider(r);
};

LG._init.push(() => {
  document.addEventListener("click", (e) => {
    const t = e.target;
    const b = t && typeof t.closest === "function" ? t.closest("[data-lg-step]") : null;
    if (!b) return;
    e.preventDefault();   // a step button without type="button" would otherwise submit its form
    const dir = Number(b.getAttribute("data-lg-step")) < 0 ? -1 : 1;
    const wrap = b.closest(".lg-stepper");
    const input = wrap ? wrap.querySelector('input[type="number"]') : null;
    if (input) stepInput(input, dir);
  });
  document.addEventListener("input", (e) => {
    const t = e.target;
    if (t && t.classList && t.classList.contains("lg-slider")) syncSlider(t);
  });
  const resync = (e) => {
    const t = e.target;
    if (t && t.classList && t.classList.contains("lg-slider")) syncSlider(t);
  };
  for (const type of ["focusin", "pointerdown", "change"]) document.addEventListener(type, resync);
  // A reset restores values after the event, so look again once it has applied.
  document.addEventListener("reset", (e) => {
    const f = e.target;
    if (f && typeof f.querySelectorAll === "function") setTimeout(() => LG.syncSliders(f), 0);
  });
  if (typeof MutationObserver === "function") {
    new MutationObserver((records) => {
      for (const rec of records) {
        for (const n of rec.addedNodes) {
          if (n.nodeType !== 1) continue;
          if (n.classList.contains("lg-slider")) syncSlider(n);
          LG.syncSliders(n);
          for (const fn of LG._added) fn(n);
        }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
  LG.syncSliders();
});

// Fuzzy matching (LadaGlass.fuzzy), used by the command palette and the combobox.
//   fuzzy(query, text) → number | null   case-insensitive subsequence match; null when the query's
//                                         characters don't all appear in order, 0 for an empty query.
// Higher is better: +3 for each matched character at a word start, +2 for each one right after the
// previous match, +5 when the text starts with the query. Each place the first character occurs is
// tried as a start (the rest matched leftmost from there) and the best score wins. Pure.
const fuzzyWordStart = (t, i) => i === 0 || /[^\p{L}\p{N}]/u.test(t[i - 1]);

LG.fuzzy = (query, text) => {
  const q = String(query === null || query === undefined ? "" : query).toLowerCase();
  const t = String(text === null || text === undefined ? "" : text).toLowerCase();
  if (!q) return 0;
  let best = null;
  for (let start = t.indexOf(q[0]); start >= 0; start = t.indexOf(q[0], start + 1)) {
    let score = fuzzyWordStart(t, start) ? 3 : 0;
    let prev = start;
    for (let j = 1; j < q.length && score !== null; j++) {
      const i = t.indexOf(q[j], prev + 1);
      if (i < 0) { score = null; break; }
      if (fuzzyWordStart(t, i)) score += 3;
      if (i === prev + 1) score += 2;
      prev = i;
    }
    if (score === null) break;   // a later start can't match what an earlier one couldn't
    if (best === null || score > best) best = score;
  }
  if (best !== null && t.startsWith(q)) best += 5;
  return best;
};

// Modals (LadaGlass.modal, LadaGlass.confirm) on the overlay core, and form-dialog validation.
//   modal.open(dialog, {trigger})   a <dialog class="lg-modal"> as a modal overlay
//   modal.close(dialog, value?)     close it (animated), focus back on the trigger
//   confirm({title, body, confirmLabel = "OK", cancelLabel = "Cancel", danger = false}) → Promise<boolean>
//                                   builds its own dialog (all text via textContent), resolves true
//                                   only for the confirm button, and removes the dialog after closing
// Form dialogs: when a form inside an .lg-modal fails validation on submit, each invalid field gets
// aria-invalid="true" and a sibling .lg-field-error with the browser's message (instead of the
// browser's bubble), focus goes to the first one, and the dialog stays open. Editing a field until
// it is valid clears both.
LG.modal = {
  open(d, opts) {
    if (typeof HTMLDialogElement !== "function" || !(d instanceof HTMLDialogElement)) {
      throw new TypeError("LadaGlass.modal.open: expected a <dialog> element");
    }
    LG.overlay.open(d, { trigger: (opts || {}).trigger, modal: true });
  },
  close(d, value) {
    LG.overlay.close(d, value);
  },
};

LG.confirm = (opts) => {
  const o = opts || {};
  const { el, uid } = LG.util;
  const trigger = document.activeElement !== document.body ? document.activeElement : null;
  const titleId = uid("lg-confirm-title"), bodyId = uid("lg-confirm-body");
  const cancel = el("button", { class: "lg-btn", text: o.cancelLabel || "Cancel", attrs: { type: "button", value: "cancel", "data-lg-close": "" } });
  const ok = el("button", { class: `lg-btn ${o.danger ? "lg-btn-danger" : "lg-btn-primary"}`, text: o.confirmLabel || "OK", attrs: { type: "submit", value: "confirm" } });
  const hasBody = o.body !== undefined && o.body !== null && o.body !== "";
  const attrs = { "aria-labelledby": titleId };
  if (hasBody) attrs["aria-describedby"] = bodyId;
  const d = el("dialog", { class: "lg-modal lg-confirm", attrs }, [
    el("form", { attrs: { method: "dialog" } }, [
      el("h2", { class: "lg-modal-title", text: o.title === undefined ? "" : o.title, attrs: { id: titleId } }),
      hasBody ? el("p", { class: "lg-modal-body", text: o.body, attrs: { id: bodyId } }) : null,
      el("div", { class: "lg-modal-actions" }, [cancel, ok]),
    ]),
  ]);
  document.body.append(d);
  return new Promise((resolve) => {
    LG.overlay.open(d, {
      trigger,
      modal: true,
      onClose: (value) => { d.remove(); resolve(value === "confirm"); },
    });
    // A destructive action starts on Cancel, so a stray Enter doesn't delete anything.
    (o.danger ? cancel : ok).focus();
  });
};

function modalFieldError(field) {
  const next = field.nextElementSibling;
  if (next && next.classList.contains("lg-field-error")) return next;
  const err = LG.util.el("p", { class: "lg-field-error", attrs: { id: LG.util.uid("lg-err"), "data-lg-auto": "" } });
  field.after(err);
  return err;
}

function modalDescribedBy(field, id, add) {
  const ids = (field.getAttribute("aria-describedby") || "").split(/\s+/).filter((x) => x && x !== id);
  if (add) ids.push(id);
  if (ids.length) field.setAttribute("aria-describedby", ids.join(" "));
  else field.removeAttribute("aria-describedby");
}

LG._init.push(() => {
  const pendingFocus = new WeakSet();
  // "invalid" doesn't bubble, so listen in the capture phase.
  document.addEventListener("invalid", (e) => {
    const field = e.target;
    const form = field && field.form;
    if (!form || !form.closest(".lg-modal")) return;
    e.preventDefault();   // our message instead of the browser's bubble
    field.setAttribute("aria-invalid", "true");
    const err = modalFieldError(field);
    err.textContent = field.validationMessage;
    if (!err.id) err.id = LG.util.uid("lg-err");
    modalDescribedBy(field, err.id, true);
    // Every invalid field fires in one go; focus the first once they all have.
    if (!pendingFocus.has(form)) {
      pendingFocus.add(form);
      queueMicrotask(() => {
        pendingFocus.delete(form);
        const first = form.querySelector('[aria-invalid="true"]');
        if (first) first.focus();
      });
    }
  }, true);

  const clear = (e) => {
    const field = e.target;
    if (!field || !field.validity || !field.closest || !field.closest(".lg-modal")) return;
    if (field.getAttribute("aria-invalid") !== "true" || !field.validity.valid) return;
    field.removeAttribute("aria-invalid");
    const next = field.nextElementSibling;
    if (next && next.classList.contains("lg-field-error")) {
      modalDescribedBy(field, next.id, false);
      if (next.hasAttribute("data-lg-auto")) next.remove(); else next.textContent = "";
    }
  };
  document.addEventListener("input", clear);
  document.addEventListener("change", clear);
});

// Drawer / sheet (LadaGlass.drawer) on the overlay core: a <dialog class="lg-drawer">. A side sheet
// from the right on wide screens, a bottom sheet with a drag handle (.lg-drawer-handle) at 760 px
// and narrower (layout is pure CSS).
//   drawer.open(dialog, {trigger})   open it as a modal overlay
//   drawer.close(dialog)             close it (animated), focus back on the trigger
//   drawer.shouldDismiss(dy, velocity)   pure: true when dy >= 80 px, or dy > 20 px and velocity > 0.5 px/ms
// Dragging the handle down moves the sheet (inline transform); letting go either closes it (the
// closing animation starts at the dragged offset, --lg-drag-y) or lets it spring back (a transition),
// and the inline transform is always removed again.
LG.drawer = {
  open(d, opts) {
    if (typeof HTMLDialogElement !== "function" || !(d instanceof HTMLDialogElement)) {
      throw new TypeError("LadaGlass.drawer.open: expected a <dialog> element");
    }
    d.style.removeProperty("--lg-drag-y");
    LG.overlay.open(d, { trigger: (opts || {}).trigger, modal: true });
  },
  close(d) {
    LG.overlay.close(d);
  },
  shouldDismiss(dy, velocity) {
    return dy >= 80 || (dy > 20 && velocity > 0.5);
  },
};

LG._init.push(() => {
  let drag = null;   // {d, id, y0, samples: [{y, t}]}
  const end = (e, cancelled) => {
    if (!drag || e.pointerId !== drag.id) return;
    const { d, y0, samples } = drag;
    drag = null;
    const dy = Math.max(0, e.clientY - y0);
    const now = performance.now();
    // Speed over the last 100 ms of movement (at least 16 ms, so one jittery sample isn't a flick).
    const ref = samples.find((s) => now - s.t <= 100) || samples[samples.length - 1];
    const velocity = ref ? (e.clientY - ref.y) / Math.max(16, now - ref.t) : 0;
    const dismiss = !cancelled && LG.drawer.shouldDismiss(dy, velocity);
    // The closing keyframe starts from the dragged offset, so the sheet slides on from where the
    // finger left it; a spring-back is a CSS transition from the inline transform to none.
    if (dismiss) d.style.setProperty("--lg-drag-y", dy + "px");
    d.style.transform = "";
    if (dismiss) LG.drawer.close(d);
    d.removeAttribute("data-lg-dragging");
  };
  document.addEventListener("pointerdown", (e) => {
    const h = e.target && typeof e.target.closest === "function" ? e.target.closest(".lg-drawer-handle") : null;
    const d = h ? h.closest("dialog.lg-drawer") : null;
    if (!d || !d.open || drag) return;
    drag = { d, id: e.pointerId, y0: e.clientY, samples: [{ y: e.clientY, t: performance.now() }] };
    d.setAttribute("data-lg-dragging", "");
    try { h.setPointerCapture(e.pointerId); } catch (_) { /* synthetic pointer ids can't be captured */ }
  });
  document.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    drag.samples.push({ y: e.clientY, t: performance.now() });
    if (drag.samples.length > 20) drag.samples.shift();
    drag.d.style.transform = `translateY(${Math.max(0, e.clientY - drag.y0)}px)`;
  });
  document.addEventListener("pointerup", (e) => end(e, false));
  document.addEventListener("pointercancel", (e) => end(e, true));
});

// Toasts (LadaGlass.toast), Sonner-style: stacked in the bottom-right corner, fanned out while the
// pointer or focus is on them (which also pauses their timers), dismissed by × or a drag right. A ×
// pressed from the keyboard hands focus to the next toast's ×, or back to where it was before.
//   toast(title, {type: "info"|"ok"|"bad"|"loading", description, duration = 4000}) → {update(title, opts), dismiss()}
//     duration 0 or type "loading": stays until updated or dismissed. update() changes the toast in
//     place and restarts its timer with the new type's duration.
//   toast.promise(promise, {loading, success, error}) → promise: a loading toast that turns ok or bad;
//     success and error are strings or functions of the value / reason.
//   toast.offsets(count, expanded, height = 60) → [{y, scale, opacity}], newest last (pure).
// The toaster is a lazily made <section class="lg-toaster" aria-live="polite">; bad toasts get
// role="alert". All text goes in as textContent. A modal dialog makes the rest of the page inert and
// covers it, so while one is open the toaster lives inside the newest modal overlay, and back in
// body when the last closes. It is a manual popover where supported: the top layer keeps it above
// the dialog and at the viewport's corner (a dialog's transform or backdrop-filter would otherwise
// become its containing block, and its overflow would clip it).
(function () {
  const TYPES = ["info", "ok", "bad", "loading"];
  const VISIBLE = 3, SWIPE = 90, GAP = 8, LEAVE_MS = 320;   // LEAVE_MS: --lg-dur-standard
  const el = LG.util.el;
  const icon = (paths, circle) => LG.util.svg("svg", { class: "lg-icon", viewBox: "0 0 24 24", "aria-hidden": "true" },
    (circle ? [LG.util.svg("circle", { cx: 12, cy: 12, r: 9 })] : []).concat(paths.map((d) => LG.util.svg("path", { d }))));
  const ICONS = {
    ok: () => icon(["M8 12.5l3 3 5-6"], true),
    bad: () => icon(["M12 7.5v5.5M12 16.5v.01"], true),
    info: () => icon(["M12 11v5.5M12 7.5v.01"], true),
    loading: () => el("span", { class: "lg-spinner" }),
  };

  let toaster = null, toasts = [], hovered = false, focused = false;
  let before = null;   // what had focus before focus moved into the toaster
  const expanded = () => hovered || focused;
  const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

  function offsets(count, isExpanded, height) {
    const h = height === undefined ? 60 : height;
    const out = [];
    for (let i = 0; i < count; i++) {
      const k = count - 1 - i;
      const step = isExpanded ? h + GAP : 10;
      out.push({ y: k === 0 ? 0 : -k * step, scale: isExpanded ? 1 : Math.round((1 - k * 0.05) * 1000) / 1000, opacity: k >= VISIBLE ? 0 : 1 });
    }
    return out;
  }

  function layout() {
    if (!toaster) return;
    const ex = expanded();
    const shown = toasts.slice(-VISIBLE);
    // Full height from scrollHeight (plus the borders), so it holds while a toast is clamped to the front one's height.
    const full = (n) => n.scrollHeight + n.offsetHeight - n.clientHeight;
    const h = Math.max(0, ...shown.map((r) => full(r.el))) || 60;
    const front = toasts.length ? full(toasts[toasts.length - 1].el) : 0;
    offsets(toasts.length, ex, h).forEach((o, i) => {
      const r = toasts[i];
      r.base = `translateY(${o.y}px) scale(${o.scale})`;
      // Collapsed, the toasts behind take the front one's height, so only their 10 px edge peeks out.
      // Their content fades out (data-lg-behind) so it doesn't show through the front toast's glass.
      const behind = !ex && i < toasts.length - 1;
      if (behind) r.el.style.height = front + "px"; else r.el.style.removeProperty("height");
      if (behind) r.el.setAttribute("data-lg-behind", ""); else r.el.removeAttribute("data-lg-behind");
      r.el.style.zIndex = String(i + 1);
      if (o.opacity) r.el.removeAttribute("inert"); else r.el.setAttribute("inert", "");
      if (r.drag) return;
      r.el.style.transform = r.base;
      r.el.style.opacity = String(o.opacity);
    });
    // While fanned out the toaster covers the stack, so the gaps between toasts don't end the hover.
    if (ex && toasts.length) toaster.style.height = Math.min(toasts.length, VISIBLE) * (h + GAP) + "px";
    else toaster.style.removeProperty("height");
    if (ex) toaster.setAttribute("data-lg-expanded", ""); else toaster.removeAttribute("data-lg-expanded");
  }

  function startTimer(r) {
    clearTimeout(r.timer);
    r.timer = null;
    if (expanded() || !(r.remaining > 0) || r.remaining === Infinity) return;
    r.started = now();
    r.timer = setTimeout(() => dismiss(r), r.remaining);
  }
  function pauseTimer(r) {
    if (!r.timer) return;
    clearTimeout(r.timer);
    r.timer = null;
    r.remaining = Math.max(0, r.remaining - (now() - r.started));
  }
  function setExpanded(fn) {
    const was = expanded();
    fn();
    if (was === expanded()) return;
    for (const r of toasts) { if (expanded()) pauseTimer(r); else startTimer(r); }
    layout();
  }

  const canPopover = typeof HTMLElement !== "undefined" && typeof HTMLElement.prototype.showPopover === "function";
  const isModal = (d) => { try { return d.matches(":modal"); } catch (_) { return true; } };

  // place(): the toaster into the newest open modal overlay (or body), shown in the top layer.
  // Moving it keeps its toasts, their timers and the stack; a moved popover is hidden, so show it again.
  function place() {
    if (!toaster) return;
    const modals = LG.overlay ? LG.overlay.stack().filter((d) => d.open && d.isConnected && isModal(d)) : [];
    const host = modals.length ? modals[modals.length - 1] : document.body;
    if (toaster.parentNode !== host) {
      const had = toaster.contains(document.activeElement);
      host.append(toaster);
      if (had) setExpanded(() => { focused = false; });   // moving it drops the focus without a focusout
    }
    if (canPopover && !toaster.matches(":popover-open")) {
      try { toaster.showPopover(); } catch (_) { /* not in a document */ }
    }
    layout();
  }
  LG._overlayChange.push(place);

  function ensureToaster() {
    if (toaster) { place(); return toaster; }
    toaster = el("section", { class: "lg-toaster", attrs: { "aria-live": "polite", "aria-label": "Notifications" } });
    if (canPopover) toaster.setAttribute("popover", "manual");
    toaster.addEventListener("pointerenter", () => setExpanded(() => { hovered = true; }));
    toaster.addEventListener("pointerleave", () => setExpanded(() => { hovered = false; }));
    toaster.addEventListener("focusin", (e) => {
      if (!toaster.contains(e.relatedTarget)) before = e.relatedTarget || null;
      setExpanded(() => { focused = true; });
    });
    toaster.addEventListener("focusout", (e) => {
      if (!toaster.contains(e.relatedTarget)) setExpanded(() => { focused = false; });
    });
    place();
    return toaster;
  }

  function dismiss(r, swiped) {
    const i = toasts.indexOf(r);
    if (i < 0) return;
    const hadFocus = r.el.contains(document.activeElement);   // checked before it turns inert
    toasts.splice(i, 1);
    clearTimeout(r.timer);
    r.drag = null;
    // Keyboard dismiss (focus was in it): before it goes inert or is removed, focus moves to the × of
    // the toast that takes its place among the visible ones, or with none left back where it was
    // before the toaster got it.
    if (hadFocus) {
      layout();   // a toast that moves into the visible three loses inert first
      const shown = toasts.slice(-VISIBLE);
      const next = shown.length ? shown[Math.min(Math.max(i - (toasts.length - shown.length), 0), shown.length - 1)] : null;
      const x = next ? next.el.querySelector(".lg-toast-close") : null;
      if (x) x.focus();
      else if (before && before.isConnected && typeof before.focus === "function") before.focus();
    }
    r.el.setAttribute("data-lg-removing", "");
    r.el.setAttribute("inert", "");
    r.el.removeAttribute("data-lg-dragging");
    r.el.style.transform = swiped ? `translateX(110%) ${r.base}` : `${r.base} translateY(16px) scale(0.95)`;
    r.el.style.opacity = "0";
    // Removed by a timer, not transitionend (which may never fire); at once under reduced motion.
    if (LG.util.reducedMotion()) r.el.remove(); else setTimeout(() => r.el.remove(), LEAVE_MS);
    if (!toasts.length) { hovered = false; focused = false; }
    if (!expanded()) for (const t of toasts) if (!t.timer) startTimer(t);
    layout();
  }

  function apply(r, title, opts) {
    const o = opts || {};
    const type = TYPES.includes(o.type) ? o.type : "info";
    r.el.className = "lg-toast lg-" + type;
    if (type === "bad") r.el.setAttribute("role", "alert"); else r.el.removeAttribute("role");
    r.icon.replaceChildren(ICONS[type]());
    r.title.textContent = title === undefined || title === null ? "" : String(title);
    const desc = o.description === undefined || o.description === null ? "" : String(o.description);
    r.desc.textContent = desc;
    r.desc.hidden = !desc;
    const d = typeof o.duration === "number" && o.duration >= 0 ? o.duration : 4000;
    r.remaining = type === "loading" || d === 0 ? Infinity : d;
    startTimer(r);
  }

  function attachDrag(r) {
    const n = r.el;
    const end = (e, cancelled) => {
      if (!r.drag || e.pointerId !== r.drag.id) return;
      const dx = Math.max(0, e.clientX - r.drag.x0);
      r.drag = null;
      n.removeAttribute("data-lg-dragging");
      if (!cancelled && dx >= SWIPE) dismiss(r, true); else layout();
    };
    n.addEventListener("pointerdown", (e) => {
      if (r.drag || !toasts.includes(r) || (e.button !== undefined && e.button !== 0)) return;
      if (e.target && typeof e.target.closest === "function" && e.target.closest("button")) return;
      r.drag = { id: e.pointerId, x0: e.clientX };
      n.setAttribute("data-lg-dragging", "");
      try { n.setPointerCapture(e.pointerId); } catch (_) { /* synthetic pointer ids can't be captured */ }
    });
    n.addEventListener("pointermove", (e) => {
      if (!r.drag || e.pointerId !== r.drag.id) return;
      const dx = Math.max(0, e.clientX - r.drag.x0);
      n.style.transform = `translateX(${dx}px) ${r.base}`;
      n.style.opacity = String(Math.max(0, 1 - dx / 250));
    });
    n.addEventListener("pointerup", (e) => end(e, false));
    n.addEventListener("pointercancel", (e) => end(e, true));
  }

  LG.toast = function toast(title, opts) {
    const host = ensureToaster();
    const r = { timer: null, remaining: 0, started: 0, base: "", drag: null };
    r.icon = el("span", { class: "lg-toast-icon", attrs: { "aria-hidden": "true" } });
    r.title = el("strong", { class: "lg-toast-title" });
    r.desc = el("span", { class: "lg-toast-description lg-muted" });
    const close = el("button", { class: "lg-toast-close", attrs: { type: "button", "aria-label": "Dismiss" } },
      [icon(["M6 6l12 12M18 6L6 18"])]);
    r.el = el("div", { class: "lg-toast" }, [r.icon, el("div", { class: "lg-toast-body" }, [r.title, r.desc]), close]);
    close.addEventListener("click", () => dismiss(r));
    attachDrag(r);
    toasts.push(r);
    host.append(r.el);
    apply(r, title, opts);
    layout();
    return {
      update(t, o) { if (toasts.includes(r)) apply(r, t, o); },
      dismiss() { dismiss(r); },
    };
  };

  LG.toast.offsets = offsets;

  LG.toast.promise = function (promise, msgs) {
    const m = msgs || {};
    const text = (v, x) => (typeof v === "function" ? v(x) : v);
    const t = LG.toast(m.loading === undefined ? "Loading…" : m.loading, { type: "loading" });
    Promise.resolve(promise).then(
      (v) => { if (m.success === undefined) t.dismiss(); else t.update(text(m.success, v), { type: "ok" }); },
      (e) => t.update(m.error === undefined ? (e && e.message) || "Failed" : text(m.error, e), { type: "bad" }),
    ).catch((err) => { t.dismiss(); console.error("LadaGlass.toast.promise:", err); });
    return promise;
  };
})();

// Command palette (LadaGlass.palette) on the overlay core: a <dialog class="lg-palette"> about 70 px
// from the top with a search field and a grouped, fuzzy-filtered list of commands.
//   palette({commands, placeholder = "Type a command or search…", shortcut = true}) → {open(), close(), setCommands(list)}
//   command: {group?, label, keywords?: [], shortcut?: "⌘E", run()}
// With shortcut, Mod+K (Meta on Apple platforms, Ctrl elsewhere) toggles it from anywhere. Groups
// keep the order they first appear in; inside a group the best LG.fuzzy score over the label and
// keywords comes first, then the original order. The field is an ARIA combobox (aria-controls,
// aria-expanded, aria-activedescendant) over a listbox of options; ↑↓ wrap, Enter or a click runs a
// command, Esc closes (the overlay core's Esc). A command runs after the palette has closed and
// focus is back on its trigger, so it can open another overlay. All text goes in as textContent.
// The ARIA combobox/listbox pattern, shared by the palette and the combobox (12-combobox.js):
//   _option(cls, children, onHover, onPick) → a role="option" element with an id; pointermove calls
//     onHover, a click onPick, and a press never takes focus from the field.
//   _activeOption(input, options, i): marks option i aria-selected, points the field's
//     aria-activedescendant at it and scrolls it into view (-1 or out of range: none).
LG._option = (cls, children, onHover, onPick) => {
  const opt = LG.util.el("div", { class: cls, attrs: { role: "option", id: LG.util.uid(cls), "aria-selected": "false" } }, children);
  opt.addEventListener("pointermove", onHover);
  opt.addEventListener("mousedown", (e) => e.preventDefault());   // keep focus in the field
  opt.addEventListener("click", onPick);
  return opt;
};
LG._activeOption = (input, options, i) => {
  options.forEach((o, j) => o.setAttribute("aria-selected", j === i ? "true" : "false"));
  const cur = options[i];
  if (!cur) { input.removeAttribute("aria-activedescendant"); return; }
  input.setAttribute("aria-activedescendant", cur.id);
  if (typeof cur.scrollIntoView === "function") cur.scrollIntoView({ block: "nearest" });
};

LG.palette = (opts) => {
  const o = opts || {};
  const { el, uid } = LG.util;
  let commands = [];
  let shown = [];     // [{cmd, opt}] in display order
  let sel = 0;
  let pending = null; // the command to run once closed

  const listId = uid("lg-palette-list");
  const input = el("input", { class: "lg-palette-input", attrs: {
    type: "text", role: "combobox", "aria-expanded": "false", "aria-controls": listId, "aria-autocomplete": "list",
    "aria-label": "Command", autocomplete: "off", spellcheck: "false",
    placeholder: o.placeholder === undefined ? "Type a command or search…" : o.placeholder,
  } });
  const list = el("div", { class: "lg-palette-list", attrs: { id: listId, role: "listbox", "aria-label": "Commands" } });
  const empty = el("p", { class: "lg-palette-empty", attrs: { role: "status" } });
  const d = el("dialog", { class: "lg-palette", attrs: { "aria-label": "Command palette" } }, [input, list, empty]);

  const isOpen = () => LG.overlay.stack().includes(d);

  function select(i) {
    sel = i;
    LG._activeOption(input, shown.map((s) => s.opt), i);
  }

  function render() {
    const q = input.value.trim();
    const groups = [];   // [{name, items: [{cmd, score, i}]}] in first-appearance order
    commands.forEach((cmd, i) => {
      const name = cmd.group === undefined || cmd.group === null ? "" : String(cmd.group);
      let g = groups.find((x) => x.name === name);
      if (!g) { g = { name, items: [] }; groups.push(g); }
      let score = null;
      for (const t of [cmd.label].concat(cmd.keywords || [])) {
        const s = LG.fuzzy(q, t);
        if (s !== null && (score === null || s > score)) score = s;
      }
      if (score !== null) g.items.push({ cmd, score, i });
    });
    shown = [];
    list.replaceChildren();
    for (const g of groups) {
      if (!g.items.length) continue;
      g.items.sort((a, b) => b.score - a.score || a.i - b.i);
      let box = list;
      if (g.name) {
        const hid = uid("lg-palette-group");
        box = el("div", { class: "lg-palette-group", attrs: { role: "group", "aria-labelledby": hid } }, [
          el("div", { class: "lg-palette-heading", text: g.name, attrs: { id: hid, role: "presentation" } }),
        ]);
        list.append(box);
      }
      for (const it of g.items) {
        const n = shown.length;
        const opt = LG._option("lg-palette-item", [
          el("span", { class: "lg-palette-label", text: it.cmd.label }),
          it.cmd.shortcut ? el("kbd", { class: "lg-kbd", text: it.cmd.shortcut }) : null,
        ], () => { if (sel !== n) select(n); }, () => runAt(n));
        shown.push({ cmd: it.cmd, opt });
        box.append(opt);
      }
    }
    empty.textContent = shown.length ? "" : "No results";
    input.setAttribute("aria-expanded", shown.length ? "true" : "false");
    select(shown.length ? Math.min(Math.max(sel, 0), shown.length - 1) : -1);
  }

  function runAt(i) {
    const s = shown[i];
    if (!s) return;
    pending = s.cmd;
    api.close();
  }

  LG.util.onKey(input, {
    ArrowDown: (e) => { e.preventDefault(); if (shown.length) select((sel + 1) % shown.length); },
    ArrowUp: (e) => { e.preventDefault(); if (shown.length) select((sel - 1 + shown.length) % shown.length); },
    Enter: (e) => { e.preventDefault(); if (!e.isComposing) runAt(sel); },
  });
  input.addEventListener("input", () => { sel = 0; render(); });

  const api = {
    open() {
      if (isOpen()) return;
      pending = null;
      input.value = "";
      sel = 0;
      render();
      if (!d.isConnected) document.body.append(d);
      LG.overlay.open(d, {
        modal: true,
        onClose: () => {
          d.remove();
          const c = pending;
          pending = null;
          if (c && typeof c.run === "function") c.run();
        },
      });
      input.focus();
    },
    close() {
      if (isOpen()) LG.overlay.close(d);
    },
    setCommands(listIn) {
      commands = Array.isArray(listIn) ? listIn.slice() : [];
      render();
    },
  };
  api.setCommands(o.commands);

  if (o.shortcut !== false && typeof document !== "undefined") {
    LG.util.onKey(document, {
      "Mod+k": (e) => {
        e.preventDefault();
        if (isOpen()) api.close(); else api.open();
      },
    });
  }
  return api;
};

// Tooltips: [data-lg-tooltip="text"], with an optional data-lg-shortcut="⌘E" shown as a keycap.
// One shared <div class="lg-tooltip" role="tooltip">, linked from the trigger with aria-describedby
// while it shows. It shows 400 ms after a mouse or pen hovers the trigger, at once on keyboard focus
// (:focus-visible), above the trigger (below when there is no room), and hides on leave, blur, a
// press, or Esc (that Esc goes no further, so it never also closes an enclosing modal). Delegated
// listeners, so triggers added later work. Text goes in as textContent.
(function () {
  const DELAY = 400;
  const { el, uid } = LG.util;
  let tip = null, current = null, pending = null, timer = 0;

  const triggerOf = (t) => (t && typeof t.closest === "function" ? t.closest("[data-lg-tooltip]") : null);
  const focusVisible = (t) => { try { return t.matches(":focus-visible"); } catch (_) { return true; } };

  function cancel() { clearTimeout(timer); timer = 0; pending = null; }

  function hide() {
    cancel();
    if (!current) return;
    const ids = (current.getAttribute("aria-describedby") || "").split(/\s+/).filter((x) => x && x !== tip.id);
    if (ids.length) current.setAttribute("aria-describedby", ids.join(" ")); else current.removeAttribute("aria-describedby");
    current = null;
    LG._float.hide(tip);
  }

  function show(t) {
    cancel();
    if (current === t) return;
    hide();
    const text = t.getAttribute("data-lg-tooltip");
    if (!text || !t.isConnected) return;
    if (!tip) tip = el("div", { class: "lg-tooltip", attrs: { role: "tooltip", id: uid("lg-tooltip") } });
    const sc = t.getAttribute("data-lg-shortcut");
    tip.replaceChildren(el("span", { text }));
    if (sc) tip.append(el("kbd", { class: "lg-kbd", text: sc }));
    current = t;
    const ids = (t.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
    t.setAttribute("aria-describedby", ids.concat(tip.id).join(" "));
    LG._float.show(tip, { anchor: () => t.getBoundingClientRect(), side: "top", host: t });
  }

  // Its modal closed (or was removed) while it showed: hide it, so it goes back to body and the
  // trigger loses aria-describedby.
  LG._overlayChange.push(() => {
    const d = tip && current ? tip.closest("dialog") : null;
    if (current && (!tip.isConnected || (d && !d.open))) hide();
  });

  LG._init.push(() => {
    document.addEventListener("pointerover", (e) => {
      if (current && !current.isConnected) hide();
      if (e.pointerType === "touch") return;
      const t = triggerOf(e.target);
      if (!t || t === current || t === pending) return;
      cancel();
      pending = t;
      timer = setTimeout(() => show(t), DELAY);
    });
    document.addEventListener("pointerout", (e) => {
      const t = triggerOf(e.target);
      if (!t || t.contains(e.relatedTarget)) return;
      if (t === pending) cancel();
      if (t === current) hide();
    });
    document.addEventListener("pointerdown", hide, true);
    document.addEventListener("focusin", (e) => {
      const t = triggerOf(e.target);
      if (t && focusVisible(e.target)) show(t);
      else if (current && !(t && t === current)) hide();
    });
    document.addEventListener("focusout", (e) => {
      if (current && current.contains(e.target) && !current.contains(e.relatedTarget)) hide();
    });
    // Capture on window, so this Esc is handled before everything on document: the floating panels
    // (popover, menus), widgets and the overlay core. One layer per Esc: the tooltip goes first.
    window.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || !current || e.isComposing || e.defaultPrevented) return;
      e.preventDefault();
      hide();
    }, true);
  });
})();

// Popovers, dropdown menus and context menus, on the floating-panel core (02-place.js). None of them
// is a modal dialog: Esc, a click outside or focus moving away closes them.
//   [data-lg-popover="<id>"]  toggles the .lg-popover with that id below the trigger; focus moves to
//                             its first control, and Esc (or a click outside while focus was inside)
//                             puts it back on the trigger.
//   [data-lg-menu="<id>"]     opens <div class="lg-menu" role="menu" id> below the trigger, focus on its
//                             first item (↓ on the trigger: first, ↑: last). Items are role="menuitem"
//                             (disabled or aria-disabled ones are skipped); .lg-menu-sep separates;
//                             data-danger marks a danger item. ↑↓ wrap, Home, End, a letter jumps to
//                             the next item starting with it, Enter/Space or a click activates, Tab and
//                             Esc close. Activating closes the menu, puts focus back on the trigger, then
//                             dispatches "lg-select" on the menu with detail {value: data-value, item}.
//   contextMenu(target, menu) → remove()   opens the menu at the pointer on contextmenu (the
//                             browser's menu is suppressed) and at the target on Shift+F10.
// Triggers present at start-up get aria-haspopup/aria-expanded/aria-controls; later ones get them
// when first opened.
(function () {
  const ITEM = '[role="menuitem"]';
  const wired = new WeakSet();

  const itemsOf = (m) => Array.from(m.querySelectorAll(ITEM)).filter((i) =>
    !i.disabled && i.getAttribute("aria-disabled") !== "true" && !i.closest("[hidden]"));
  const labelOf = (i) => (i.querySelector(".lg-menu-label") || i).textContent.trim().toLowerCase();
  const rectOf = (node) => () => node.getBoundingClientRect();

  function prepare(trigger, kind, id) {
    if (kind === "menu") trigger.setAttribute("aria-haspopup", "menu");
    trigger.setAttribute("aria-controls", id);
    if (!trigger.hasAttribute("aria-expanded")) trigger.setAttribute("aria-expanded", "false");
  }

  function activate(m, item) {
    if (!item || !itemsOf(m).includes(item)) return;
    LG._float.close(m, { focus: true });
    m.dispatchEvent(new CustomEvent("lg-select", { bubbles: true, detail: { value: item.getAttribute("data-value"), item } }));
  }

  function wire(m) {
    if (wired.has(m)) return;
    wired.add(m);
    m.addEventListener("keydown", (e) => {
      if (e.isComposing || e.defaultPrevented || !LG._float.isOpen(m)) return;
      const items = itemsOf(m);
      const cur = items.indexOf(e.target.closest(ITEM));
      const go = (i) => { e.preventDefault(); if (items[i]) items[i].focus(); };
      const k = e.key || "";
      if (k === "ArrowDown") go(cur < 0 ? 0 : (cur + 1) % items.length);
      else if (k === "ArrowUp") go(cur < 0 ? items.length - 1 : (cur - 1 + items.length) % items.length);
      else if (k === "Home") go(0);
      else if (k === "End") go(items.length - 1);
      // Through click(), so keyboard and pointer activate the same way (a link item navigates).
      else if (k === "Enter" || k === " ") { e.preventDefault(); if (!e.repeat && items[cur]) items[cur].click(); }
      else if (k === "Tab") LG._float.close(m, { focus: true });   // the Tab then moves on from the trigger
      else if (k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const ch = k.toLowerCase();
        for (let n = 1; n <= items.length; n++) {
          const i = (cur + n) % items.length;
          if (labelOf(items[i]).startsWith(ch)) { go(i); break; }
        }
      }
    });
    m.addEventListener("click", (e) => {
      const item = e.target.closest(ITEM);
      if (item && m.contains(item)) activate(m, item);
    });
    m.addEventListener("pointermove", (e) => {
      const item = e.target.closest(ITEM);
      if (item && itemsOf(m).includes(item) && document.activeElement !== item) item.focus({ preventScroll: true });
    });
  }

  // openMenu(m, {trigger, returnTo, anchor, gap, focus: "first" | "last"})
  function openMenu(m, o) {
    wire(m);
    for (const i of m.querySelectorAll(ITEM)) i.setAttribute("tabindex", "-1");
    const t = o.trigger;
    LG._float.open(m, { anchor: o.anchor, side: "bottom", gap: o.gap, host: t || o.returnTo, trigger: t, returnTo: o.returnTo,
      onClose: () => { if (t) t.setAttribute("aria-expanded", "false"); } });
    if (t) t.setAttribute("aria-expanded", "true");
    const items = itemsOf(m);
    const first = o.focus === "last" ? items[items.length - 1] : items[0];
    if (first) first.focus();
  }

  function togglePopover(t, p) {
    if (LG._float.isOpen(p)) { LG._float.close(p, { focus: true }); return; }
    prepare(t, "popover", p.id);
    LG._float.open(p, { anchor: rectOf(t), side: "bottom", host: t, trigger: t,
      onClose: () => t.setAttribute("aria-expanded", "false") });
    t.setAttribute("aria-expanded", "true");
    const first = LG.util.focusables(p)[0];
    if (first) first.focus();
  }

  function menuTrigger(t, focus) {
    const m = document.getElementById(t.getAttribute("data-lg-menu"));
    if (!m) return;
    if (LG._float.isOpen(m)) { LG._float.close(m, { focus: true }); return; }
    prepare(t, "menu", m.id);
    openMenu(m, { trigger: t, anchor: rectOf(t), focus });
  }

  LG.contextMenu = (target, m) => {
    // A zero-height anchor as wide as the menu, so the centred placement puts its left edge at x.
    const at = (x, y) => {
      const a = document.activeElement;
      const back = a && a !== document.body && !m.contains(a) ? a : target;
      if (LG._float.isOpen(m)) LG._float.close(m);
      openMenu(m, { returnTo: back, gap: 0, anchor: (size) => ({ left: x, right: x + size.width, width: size.width, top: y, bottom: y, height: 0 }) });
    };
    const onMenu = (e) => { e.preventDefault(); at(e.clientX, e.clientY); };
    target.addEventListener("contextmenu", onMenu);
    const offKey = LG.util.onKey(target, {
      "Shift+F10": (e) => { e.preventDefault(); const r = target.getBoundingClientRect(); at(r.left, r.bottom); },
    });
    return () => { target.removeEventListener("contextmenu", onMenu); offKey(); };
  };

  LG._init.push(() => {
    for (const t of document.querySelectorAll("[data-lg-menu]")) prepare(t, "menu", t.getAttribute("data-lg-menu"));
    for (const t of document.querySelectorAll("[data-lg-popover]")) prepare(t, "popover", t.getAttribute("data-lg-popover"));
    document.addEventListener("click", (e) => {
      const t = e.target && typeof e.target.closest === "function" ? e.target.closest("[data-lg-menu], [data-lg-popover]") : null;
      if (!t || t.disabled) return;
      if (t.hasAttribute("data-lg-menu")) { menuTrigger(t, "first"); return; }
      const p = document.getElementById(t.getAttribute("data-lg-popover"));
      if (p) togglePopover(t, p);
    });
    document.addEventListener("keydown", (e) => {
      const t = e.target && typeof e.target.matches === "function" && e.target.matches("[data-lg-menu], [data-lg-popover]") ? e.target : null;
      if (!t || e.isComposing) return;
      // A held Enter or Space would toggle it on every repeat.
      if (e.repeat && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); return; }
      if (t.hasAttribute("data-lg-menu") && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        const m = document.getElementById(t.getAttribute("data-lg-menu"));
        if (m && !LG._float.isOpen(m)) menuTrigger(t, e.key === "ArrowUp" ? "last" : "first");
      }
    });
  });
})();

// Combobox (LadaGlass.combobox): type-to-search over a long list, on a text input.
//   combobox(input, {options: [{value, label}], onSelect(value, option)}) → {setOptions(list), close()}
// The input becomes an ARIA combobox (as in the palette: aria-expanded, aria-controls,
// aria-activedescendant) over a <div class="lg-combobox" role="listbox"> placed right after it and
// shown below it on the floating-panel core. Typing filters with LG.fuzzy (best score first, then
// the original order); ↓ (or typing) opens it, ↑↓ wrap, Enter or a click picks: the input gets the
// label and onSelect gets the value. Esc, a click outside or leaving the field closes the list.
// Keys during IME composition are left alone. Labels go in as textContent. Label the input with
// <label for> or aria-label, not a wrapping <label> (the list would become part of its name).
LG.combobox = (input, opts) => {
  const o = opts || {};
  const { el, uid } = LG.util;
  let options = [];
  let shown = [];   // [{option, opt}]
  let sel = 0;

  const listId = uid("lg-combobox");
  const list = el("div", { class: "lg-combobox", attrs: { id: listId, role: "listbox" } });
  const label = input.getAttribute("aria-label");
  if (label) list.setAttribute("aria-label", label);
  for (const [k, v] of [["role", "combobox"], ["aria-autocomplete", "list"], ["aria-expanded", "false"], ["aria-controls", listId], ["autocomplete", "off"]]) {
    input.setAttribute(k, v);
  }
  input.after(list);

  const isOpen = () => LG._float.isOpen(list);
  const select = (i) => { sel = i; LG._activeOption(input, shown.map((s) => s.opt), i); };

  function render() {
    const q = input.value.trim();
    const hits = [];
    options.forEach((option, i) => {
      const score = LG.fuzzy(q, option.label);
      if (score !== null) hits.push({ option, score, i });
    });
    hits.sort((a, b) => b.score - a.score || a.i - b.i);
    shown = hits.map((h, n) => ({
      option: h.option,
      opt: LG._option("lg-combobox-option", [String(h.option.label)], () => { if (sel !== n) select(n); }, () => pick(n)),
    }));
    list.replaceChildren(...shown.map((s) => s.opt));
  }

  function open() {
    render();
    if (!shown.length) { close(); return; }
    list.style.setProperty("min-width", `${input.getBoundingClientRect().width}px`);
    if (isOpen()) LG._float.update(list);
    else {
      LG._float.open(list, { anchor: () => input.getBoundingClientRect(), side: "bottom", gap: 4, host: input, trigger: input,
        onClose: () => { input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant"); } });
    }
    input.setAttribute("aria-expanded", "true");
    select(Math.min(Math.max(sel, 0), shown.length - 1));
  }

  function close() { if (isOpen()) LG._float.close(list); }

  function pick(n) {
    const s = shown[n];
    if (!s) return;
    input.value = String(s.option.label);
    close();
    if (typeof o.onSelect === "function") o.onSelect(s.option.value, s.option);
  }

  const move = (d) => (e) => {
    if (e.isComposing) return;
    e.preventDefault();
    if (!isOpen()) { sel = d > 0 ? 0 : -1; open(); if (sel < 0) select(shown.length - 1); return; }
    select((sel + d + shown.length) % shown.length);
  };
  LG.util.onKey(input, {
    ArrowDown: move(1),
    ArrowUp: move(-1),
    "Alt+ArrowDown": (e) => { if (!e.isComposing && !isOpen()) { e.preventDefault(); sel = 0; open(); } },
    Enter: (e) => { if (e.isComposing || !isOpen()) return; e.preventDefault(); pick(sel); },
  });
  input.addEventListener("input", () => { sel = 0; open(); });
  input.addEventListener("blur", (e) => { if (!list.contains(e.relatedTarget)) close(); });

  const api = {
    setOptions(listIn) {
      options = Array.isArray(listIn) ? listIn.slice() : [];
      if (isOpen()) open();
    },
    close,
  };
  api.setOptions(o.options);
  return api;
};

// Animated numbers (NumberFlow-style): LadaGlass.number(el, value, {locale, format, delta}) shows
// Intl.NumberFormat(locale, format).format(value) with one rolling column per ASCII digit; other
// characters (separators, signs, units) are static. el gets the formatted value as its aria-label
// (and role="img" on a span or div without a role, so the label is read); everything inside is aria-hidden.
// Columns are matched from the right, so a ones column stays the ones column and rolls when the
// value changes. Elements with [data-lg-number="<value>"] are drawn by auto-init and redrawn when
// the attribute changes. Under reduced motion the change is instant (CSS drops the transition).
const numberState = new WeakMap();   // el -> { value }

function digitColumn() {
  const col = LG.util.el("span", { class: "lg-digit-col" });
  for (let i = 0; i <= 9; i++) col.append(LG.util.el("span", { text: i }));
  return LG.util.el("span", { class: "lg-digit", attrs: { "aria-hidden": "true" } }, [col]);
}

LG.number = (el, value, opts) => {
  const o = opts || {};
  const fmt = Object.assign({}, o.format || {});
  const nf = new Intl.NumberFormat(o.locale || "en-US", fmt);
  const text = nf.format(value);
  const state = numberState.get(el);
  if (!state) el.replaceChildren();                       // drop fallback text written in the HTML
  el.classList.add("lg-number");
  el.setAttribute("aria-label", text);
  // Only a generic span/div needs a role for its label to be read; a cell, heading, link or output
  // keeps its own (implicit) role.
  if (!el.hasAttribute("role") && (el.localName === "span" || el.localName === "div")) el.setAttribute("role", "img");

  // Pair new characters with the current children from the right; reuse a child of the same kind.
  const chars = Array.from(text);
  const old = Array.from(el.children);
  const next = new Array(chars.length);
  let j = old.length - 1;
  for (let i = chars.length - 1; i >= 0; i--, j--) {
    const isDigit = /^[0-9]$/.test(chars[i]);
    const cand = j >= 0 ? old[j] : null;
    if (cand && cand.classList.contains(isDigit ? "lg-digit" : "lg-number-sym")) next[i] = cand;
  }
  // Remove what isn't reused, then insert new nodes around the kept ones without moving them
  // (a moved node loses its running transition).
  for (const c of old) if (!next.includes(c)) c.remove();
  const fresh = [];
  for (let i = 0; i < chars.length; i++) {
    let node = next[i];
    if (!node) {
      node = /^[0-9]$/.test(chars[i]) ? digitColumn() : LG.util.el("span", { class: "lg-number-sym", attrs: { "aria-hidden": "true" } });
      if (node.classList.contains("lg-digit")) { node.style.setProperty("--lg-d", "0"); fresh.push(node); }
      el.insertBefore(node, el.children[i] || null);
    }
  }
  // New columns start at 0 and roll to their digit: let the browser see the 0 first.
  if (fresh.length && el.isConnected && !LG.util.reducedMotion()) el.getBoundingClientRect();
  chars.forEach((ch, i) => {
    const node = el.children[i];
    if (node.classList.contains("lg-digit")) node.style.setProperty("--lg-d", ch);
    else node.textContent = ch === "-" ? "−" : ch;   // a real minus sign
  });

  if (o.delta && state && Number.isFinite(state.value) && Number.isFinite(value)) {
    const diff = value - state.value;
    let badge = el.nextElementSibling;
    if (!badge || !badge.classList.contains("lg-delta")) {
      badge = LG.util.el("span", { class: "lg-delta" });
      el.after(badge);
    }
    const abs = new Intl.NumberFormat(o.locale || "en-US", Object.assign({}, fmt, { signDisplay: "auto" })).format(Math.abs(diff));
    badge.textContent = diff > 0 ? `+${abs}` : diff < 0 ? `−${abs}` : abs;
    badge.classList.toggle("lg-delta-up", diff > 0);
    badge.classList.toggle("lg-delta-down", diff < 0);
  }
  numberState.set(el, { value });
};

function initNumber(el) {
  const raw = (el.getAttribute("data-lg-number") || "").trim();
  const v = raw === "" ? NaN : Number(raw);
  if (!Number.isFinite(v)) return;
  const s = numberState.get(el);
  if (s && s.value === v) return;
  LG.number(el, v);
}

LG._init.push(() => {
  for (const el of document.querySelectorAll("[data-lg-number]")) initNumber(el);
  if (typeof MutationObserver !== "function") return;
  new MutationObserver((records) => {
    for (const rec of records) {
      if (rec.type === "attributes") { initNumber(rec.target); continue; }
      for (const n of rec.addedNodes) {
        if (n.nodeType !== 1) continue;
        if (n.hasAttribute("data-lg-number")) initNumber(n);
        for (const d of n.querySelectorAll("[data-lg-number]")) initNumber(d);
      }
    }
  }).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-lg-number"] });
});

// Chart core (LadaGlass.chart): pure helpers the charts build on, plus colors(), which reads the
// series colours from computed CSS. Nothing here ever returns NaN; non-finite input gives an empty
// result instead.
const fin = Number.isFinite;
const round2 = (x) => { const r = Math.round(x * 100) / 100; return Object.is(r, -0) ? 0 : r; };

LG.chart = {
  // niceTicks(min, max, count = 5): ticks at 1, 2 or 5 × 10ⁿ steps covering [min, max]; a flat
  // range widens to [min − 1, max + 1]. count is capped at 100. Non-finite input, or a span too wide
  // for a double, gives []; a tick that would overflow is dropped, so nothing is ever NaN.
  niceTicks(min, max, count) {
    if (!fin(min) || !fin(max)) return [];
    let lo = Math.min(min, max), hi = Math.max(min, max);
    if (lo === hi) { lo -= 1; hi += 1; }
    const n = fin(count) && count >= 1 ? Math.min(100, Math.round(count)) : 5;
    const raw = (hi - lo) / n;
    if (!fin(raw) || raw <= 0) return [];
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm <= 1 + 1e-9 ? 1 : norm <= 2 + 1e-9 ? 2 : norm <= 5 + 1e-9 ? 5 : 10) * mag;
    if (!fin(step) || step <= 0) return [];
    const start = Math.floor(lo / step + 1e-9), end = Math.ceil(hi / step - 1e-9);
    const out = [];
    for (let i = start; i <= end; i++) {
      const v = Number((i * step).toPrecision(12));   // 12 significant digits: no 0.6000000000000001
      if (fin(v)) out.push(Object.is(v, -0) ? 0 : v);
    }
    return out;
  },

  // scale([d0, d1], [r0, r1]): linear map; a zero-width domain maps everything to the midpoint.
  scale(domain, range) {
    const [d0, d1] = domain, [r0, r1] = range;
    if (!(fin(d0) && fin(d1)) || d0 === d1) return () => (r0 + r1) / 2;
    return (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
  },

  // linePath([[x, y]…]): "M x,y L x,y …" (2 decimals), "" for no points; non-finite points are skipped.
  linePath(points) {
    return (points || []).filter((p) => p && fin(p[0]) && fin(p[1]))
      .map((p, i) => `${i ? "L" : "M"}${round2(p[0])},${round2(p[1])}`).join("");
  },

  // arcPath(cx, cy, r, inner, a0, a1): an annular sector (a pie slice when inner is 0). Angles in
  // radians, 0 at twelve o'clock, clockwise. An empty span gives ""; a full turn draws a ring.
  arcPath(cx, cy, r, inner, a0, a1) {
    if (![cx, cy, r, inner, a0, a1].every(fin)) return "";
    const R = Math.max(0, r), ri = Math.min(Math.max(0, inner), R);
    const from = Math.min(a0, a1), span = Math.abs(a1 - a0);
    if (span <= 0 || R <= 0) return "";
    const pt = (a, rad) => `${round2(cx + rad * Math.sin(a))},${round2(cy - rad * Math.cos(a))}`;
    if (span >= 2 * Math.PI - 1e-9) {
      // Two half arcs each way; the inner circle runs the other way, so it is a hole (nonzero fill).
      const ring = (rad, sweep) => `M${pt(0, rad)}A${round2(rad)},${round2(rad)} 0 0 ${sweep} ${pt(Math.PI, rad)}` +
                                   `A${round2(rad)},${round2(rad)} 0 0 ${sweep} ${pt(0, rad)}Z`;
      return ring(R, 1) + (ri > 0 ? ring(ri, 0) : "");
    }
    const to = from + span, large = span > Math.PI ? 1 : 0;
    let d = `M${pt(from, R)}A${round2(R)},${round2(R)} 0 ${large} 1 ${pt(to, R)}`;
    d += ri > 0 ? `L${pt(to, ri)}A${round2(ri)},${round2(ri)} 0 ${large} 0 ${pt(from, ri)}Z` : `L${round2(cx)},${round2(cy)}Z`;
    return d;
  },

  // colors(el): series colours for el: its computed --lg-accent and --lg-accent-2, then the other
  // accent presets (tokens.json order) in the active theme's variant, skipping those two.
  colors(el) {
    const cs = getComputedStyle(el);
    const get = (n) => cs.getPropertyValue(n).trim();
    const accent = get("--lg-accent"), accent2 = get("--lg-accent-2");
    const light = get("--lg-text").toUpperCase() !== get("--lg-text-d").toUpperCase();
    const taken = [accent.toUpperCase(), accent2.toUpperCase()];
    const out = [accent, accent2];
    for (const a of (LG.tokens && LG.tokens.accents) || []) {
      const c = light ? a.l : a.d;
      if (!taken.includes(c.toUpperCase())) out.push(c);
    }
    return out;
  },
};

// Sparklines: LadaGlass.chart.sparkline(el, values, {area = true}) draws a small SVG line (and a
// soft area under it) in --lg-accent, with no axes. Non-finite values are skipped; fewer than 2
// finite values draw nothing and set data-lg-empty. The SVG is aria-hidden: the number beside it
// carries the meaning, so label el yourself if the trend matters on its own.
LG.chart.sparkline = (el, values, opts) => {
  const o = opts || {};
  const W = 100, H = 32, PAD = 2;
  el.classList.add("lg-sparkline");
  const pts = [];
  (values || []).forEach((v, i) => { if (typeof v === "number" && Number.isFinite(v)) pts.push([i, v]); });
  if (pts.length < 2) {
    el.replaceChildren();
    el.setAttribute("data-lg-empty", "");
    return;
  }
  el.removeAttribute("data-lg-empty");
  const ys = pts.map((p) => p[1]);
  const x = LG.chart.scale([pts[0][0], pts[pts.length - 1][0]], [0, W]);
  const y = LG.chart.scale([Math.min(...ys), Math.max(...ys)], [H - PAD, PAD]);
  const xy = pts.map((p) => [x(p[0]), y(p[1])]);
  const line = LG.chart.linePath(xy);
  const kids = [];
  if (o.area !== false) {
    kids.push(LG.util.svg("path", { class: "lg-sparkline-area", d: `${line}L${W},${H}L0,${H}Z` }));
  }
  kids.push(LG.util.svg("path", { class: "lg-sparkline-line", d: line, "vector-effect": "non-scaling-stroke" }));
  el.replaceChildren(LG.util.svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false" }, kids));
};

// Charts (LadaGlass.chart.line / bar / donut / meter): hand-made SVG on the chart core.
//   line(el, {label, series: [{name, points: [[x, y]…]}], area = false, x: {type: "linear"|"time", format}, y: {format}})
//   bar(el, {label, categories: [string], series: [{name, values: [number]}], stacked = false, horizontal = false})
//   donut(el, {label, parts: [{label, value}], center})
//   meter(el, {label, value, max = 100})
// Each returns {update(data), destroy()}; update() merges data into the options and redraws into the
// same root <svg class="lg-chart-svg">. el gets .lg-chart, role="img" and an aria-label that
// summarises the data ("Findings per host: example.se 3, test.local 12"; label is the prefix). It
// redraws when el resizes (ResizeObserver). Without a finite value it shows .lg-chart-empty "No data"
// and sets data-lg-empty. Every label goes in with textContent. Colours come from chart.colors(el),
// one per series (part) in order, and never carry identity alone: two or more series get a legend
// (real text), lines get dash patterns (and end labels when they don't collide), bar series after the
// first get a hatch or dot pattern, and so do donut parts, which are also listed with their values. Line, bar and donut
// charts are focusable: hovering, or the arrow keys (Home, End; Esc hides), show a tooltip
// (.lg-tooltip.lg-chart-tip, placed by LadaGlass.place) with the x value or category and every
// series' value; a crosshair (line), band (bar) or segment highlight (donut) marks it.
// Time x values are milliseconds. Missing or non-finite values are skipped, never drawn as 0.
(function () {
  const { el: h, svg: s, uid } = LG.util;
  const C = LG.chart;
  const R = round2;
  const CH = 6.5;                                   // estimated px per character of 11 px chart text
  const DASH = ["", "6 4", "2 3", "8 3 2 3"];       // line series: solid, dashed, dotted, dash-dot
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const short = (t, n) => (t.length > n ? `${t.slice(0, Math.max(1, n - 1))}…` : t);
  const numFmt = (o) => { try { return new Intl.NumberFormat(undefined, o); } catch (_) { return { format: String }; } };
  const fullNum = numFmt({ maximumFractionDigits: 2 });
  const compactNum = numFmt({ notation: "compact", maximumFractionDigits: 1 });
  const userFmt = (f, dflt) => (typeof f === "function" ? (v) => String(f(v)) : dflt);
  const nameOf = (x, i, what) => (x && x.name !== undefined && x.name !== null ? String(x.name) : `${what} ${i + 1}`);
  const finite = (v) => (typeof v === "number" && fin(v) ? v : null);

  // barPath(x, y, w, h, r, end): a bar with its data end ("top", "bottom", "left", "right") rounded
  // by r (at most half the thickness and the whole length) and square corners at the baseline.
  C.barPath = (x, y, w, hgt, r, end) => {
    if (![x, y, w, hgt, r].every(fin) || w <= 0 || hgt <= 0) return "";
    const vert = end === "top" || end === "bottom";
    const rr = Math.max(0, Math.min(r, vert ? w / 2 : hgt / 2, vert ? hgt : w));
    const x2 = x + w, y2 = y + hgt;
    if (!rr) return `M${R(x)},${R(y)}H${R(x2)}V${R(y2)}H${R(x)}Z`;
    const a = (px, py) => `A${R(rr)},${R(rr)} 0 0 1 ${R(px)},${R(py)}`;
    if (end === "bottom") return `M${R(x2)},${R(y)}V${R(y2 - rr)}${a(x2 - rr, y2)}H${R(x + rr)}${a(x, y2 - rr)}V${R(y)}Z`;
    if (end === "right") return `M${R(x)},${R(y)}H${R(x2 - rr)}${a(x2, y + rr)}V${R(y2 - rr)}${a(x2 - rr, y2)}H${R(x)}Z`;
    if (end === "left") return `M${R(x2)},${R(y2)}H${R(x + rr)}${a(x, y2 - rr)}V${R(y + rr)}${a(x + rr, y)}H${R(x2)}Z`;
    return `M${R(x)},${R(y2)}V${R(y + rr)}${a(x + rr, y)}H${R(x2 - rr)}${a(x2, y + rr)}V${R(y2)}Z`;
  };

  // nearest(sorted, v): the index of the value closest to v (the lower one on a tie), -1 for none.
  C.nearest = (list, v) => {
    if (!list || !list.length || !fin(v)) return -1;
    let lo = 0, hi = list.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (list[m] <= v) lo = m; else hi = m; }
    return Math.abs(v - list[lo]) <= Math.abs(list[hi] - v) ? lo : hi;
  };

  // --- shared pieces ----------------------------------------------------------------------------
  const swatchLine = (color, dash) => s("svg", { class: "lg-chart-swatch", viewBox: "0 0 16 10", "aria-hidden": "true", focusable: "false" },
    [s("line", Object.assign({ x1: 1, y1: 5, x2: 15, y2: 5, stroke: color, "stroke-width": 2, "stroke-linecap": "round" }, dash ? { "stroke-dasharray": dash } : {}))]);
  const swatchRect = (fill) => s("svg", { class: "lg-chart-swatch", viewBox: "0 0 16 10", "aria-hidden": "true", focusable: "false" },
    [s("rect", { x: 2, y: 0, width: 12, height: 10, rx: 3, fill })]);
  const tick = (cls, x, y, anchor, text) => s("text", { class: `lg-chart-tick ${cls}`, x: R(x), y: R(y), "text-anchor": anchor }, [text]);
  const emptyView = (label) => ({ empty: true, nodes: [], legend: null, items: null, label: `${label}: no data` });

  // Value axis: ticks from niceTicks over [min, max] widened to include 0; compact labels from 10,000.
  function valueAxis(lo, hi, len, fmt) {
    let t = C.niceTicks(Math.min(0, lo), Math.max(0, hi), clamp(Math.round(len / 45), 2, 8));
    if (t.length < 2) t = [Math.min(0, lo), Math.max(0, hi, lo + 1)];
    const big = Math.max(Math.abs(t[0]), Math.abs(t[t.length - 1])) >= 10000;
    const label = fmt || ((v) => (big ? compactNum : fullNum).format(v));
    return { ticks: t, lo: t[0], hi: t[t.length - 1], labels: t.map(label) };
  }

  // Bar series after the first get a pattern (hatch 45°, hatch 135°, cross-hatch, dots) over their colour.
  function pattern(id, color, si) {
    const kind = (si - 1) % 4;
    const kids = [s("rect", { width: 6, height: 6, fill: color })];
    if (kind === 3) kids.push(s("circle", { class: "lg-chart-hatch-dot", cx: 3, cy: 3, r: 1.2 }));
    else {
      kids.push(s("line", { class: "lg-chart-hatch", x1: 0, y1: 0, x2: 0, y2: 6 }));
      if (kind === 2) kids.push(s("line", { class: "lg-chart-hatch", x1: 0, y1: 3, x2: 6, y2: 3 }));
    }
    return s("pattern", { id, width: 6, height: 6, patternUnits: "userSpaceOnUse",
                          patternTransform: kind === 1 ? "rotate(-45)" : kind === 3 ? "rotate(0)" : "rotate(45)" }, kids);
  }

  // --- the chart frame: root svg, legend, empty state, tooltip, keyboard and pointer --------------
  function makeChart(el, kind, opts, render) {
    let o = Object.assign({}, opts);
    const id = uid("lg-chart");
    const svg = s("svg", { class: "lg-chart-svg", focusable: "false" });
    const legend = h("div", { class: "lg-chart-legend" });
    const empty = h("div", { class: "lg-chart-empty", text: "No data" });
    const tip = h("div", { class: "lg-tooltip lg-chart-tip", attrs: { role: "tooltip", "aria-live": "polite", id: `${id}-tip` } });
    const interactive = kind !== "meter";
    let view = null, active = -1, anchor = { x: 0, y: 0 }, measured = "";
    el.classList.add("lg-chart", `lg-chart-${kind}`);
    el.setAttribute("role", "img");
    el.replaceChildren(svg);

    const box = () => { const r = svg.getBoundingClientRect(); return { w: Math.round(r.width) || 320, h: Math.round(r.height) || 200 }; };

    function redraw() {
      let b = box();
      const colors = C.colors(el).map((c) => c || "currentColor");
      view = render(o, { W: b.w, H: b.h, colors, id });
      if (view.height && view.height !== b.h) {
        svg.style.setProperty("height", `${view.height}px`);
        b = { w: b.w, h: view.height };
      }
      svg.setAttribute("viewBox", `0 0 ${b.w} ${b.h}`);
      svg.replaceChildren(...view.nodes);
      measured = `${b.w}x${b.h}`;
      if (view.legend && view.legend.length) {
        legend.replaceChildren(...view.legend.map((k) => h("span", { class: "lg-chart-key" }, [k.swatch,
          h("span", { class: "lg-chart-key-label", text: k.label }), k.value ? h("span", { class: "lg-chart-key-value", text: k.value }) : null])));
        if (view.legendAfter) svg.after(legend); else svg.before(legend);
      } else legend.remove();
      if (view.empty) { el.append(empty); el.setAttribute("data-lg-empty", ""); } else { empty.remove(); el.removeAttribute("data-lg-empty"); }
      el.setAttribute("aria-label", view.label);
      if (interactive && !view.empty) el.setAttribute("tabindex", "0"); else el.removeAttribute("tabindex");
      if (active >= 0) { if (view.items && active < view.items.count) show(active); else hide(); }
    }

    function show(i) {
      const it = view && view.items;
      if (!it || !it.count) { hide(); return; }
      active = clamp(i, 0, it.count - 1);
      const d = it.at(active);
      anchor = { x: d.x, y: d.y };
      tip.replaceChildren(h("div", { class: "lg-chart-tip-x", text: d.title }), ...d.rows.map((r) => h("div", { class: "lg-chart-tip-row" },
        [r.swatch, h("span", { class: "lg-chart-tip-value", text: r.value }), h("span", { class: "lg-chart-tip-name", text: r.name })])));
      it.mark(active);
      const ids = (el.getAttribute("aria-describedby") || "").split(/\s+/).filter((x) => x && x !== tip.id);
      el.setAttribute("aria-describedby", ids.concat(tip.id).join(" "));
      LG._float.show(tip, { side: "top", gap: 10, host: el, anchor: () => {
        const r = svg.getBoundingClientRect(), [W, H] = measured.split("x").map(Number);
        const x = r.left + anchor.x * (r.width / W || 1), y = r.top + anchor.y * (r.height / H || 1);
        return { left: x, right: x, top: y, bottom: y, width: 0, height: 0 };
      } });
    }

    function hide() {
      if (view && view.items) view.items.mark(-1);
      active = -1;
      LG._float.hide(tip);
      const ids = (el.getAttribute("aria-describedby") || "").split(/\s+/).filter((x) => x && x !== tip.id);
      if (ids.length) el.setAttribute("aria-describedby", ids.join(" ")); else el.removeAttribute("aria-describedby");
    }

    const local = (e) => {
      const r = svg.getBoundingClientRect(), [W, H] = measured.split("x").map(Number);
      return { x: (e.clientX - r.left) * (W / r.width || 1), y: (e.clientY - r.top) * (H / r.height || 1) };
    };
    const onMove = (e) => {
      if (!view || !view.items) return;
      const p = local(e), i = view.items.hit(p.x, p.y);
      if (i < 0) hide(); else if (i !== active) show(i);
    };
    const onLeave = () => { if (document.activeElement !== el) hide(); };
    const onFocus = () => { if (view && view.items) show(active >= 0 ? active : 0); };
    const onBlur = () => hide();
    const onKeyDown = (e) => {
      if (!view || !view.items || e.altKey || e.ctrlKey || e.metaKey) return;
      const n = view.items.count, k = e.key;
      let to = null;
      if (k === "ArrowRight" || k === "ArrowDown") to = active + 1;
      else if (k === "ArrowLeft" || k === "ArrowUp") to = Math.max(0, active - 1);
      else if (k === "Home") to = 0;
      else if (k === "End") to = n - 1;
      else if (k === "Escape" && active >= 0) { e.preventDefault(); e.stopPropagation(); hide(); return; }
      if (to === null) return;
      e.preventDefault();
      show(clamp(to, 0, n - 1));
    };
    if (interactive) {
      svg.addEventListener("pointermove", onMove);
      svg.addEventListener("pointerleave", onLeave);
      el.addEventListener("focus", onFocus);
      el.addEventListener("blur", onBlur);
      el.addEventListener("keydown", onKeyDown);
    }
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => {
      const b = box();
      if (`${b.w}x${b.h}` !== measured) redraw();
    }) : null;

    redraw();
    if (ro) ro.observe(el);

    return {
      update(data) { o = Object.assign({}, o, data); redraw(); },
      destroy() {
        if (ro) ro.disconnect();
        hide();
        tip.remove();
        svg.removeEventListener("pointermove", onMove);
        svg.removeEventListener("pointerleave", onLeave);
        el.removeEventListener("focus", onFocus);
        el.removeEventListener("blur", onBlur);
        el.removeEventListener("keydown", onKeyDown);
        el.replaceChildren();
        for (const a of ["role", "aria-label", "tabindex", "data-lg-empty"]) el.removeAttribute(a);
        el.classList.remove("lg-chart", `lg-chart-${kind}`);
      },
    };
  }

  // --- line / area -------------------------------------------------------------------------------
  function renderLine(o, { W, H, colors }) {
    const label = o.label ? String(o.label) : "Line chart";
    const time = !!(o.x && o.x.type === "time");
    const series = (o.series || []).map((sr, si) => ({
      name: nameOf(sr, si, "Series"), si, color: colors[si % colors.length], dash: DASH[si % DASH.length],
      pts: ((sr && sr.points) || []).filter((p) => Array.isArray(p) && fin(p[0]) && fin(p[1])).map((p) => [p[0], p[1]]).sort((a, b) => a[0] - b[0]),
    }));
    const all = [].concat(...series.map((x) => x.pts));
    if (!all.length) return emptyView(label);
    const xs = Array.from(new Set(all.map((p) => p[0]))).sort((a, b) => a - b);
    const span = xs[xs.length - 1] - xs[0];
    let fx = userFmt(o.x && o.x.format, null);
    if (!fx) {
      if (time) {
        const df = new Intl.DateTimeFormat(undefined, span <= 2 * 864e5 ? { hour: "2-digit", minute: "2-digit" } : { month: "short", day: "numeric" });
        fx = (v) => df.format(new Date(v));
      } else fx = (v) => fullNum.format(v);
    }
    const fy = userFmt(o.y && o.y.format, (v) => fullNum.format(v));
    const ys = all.map((p) => p[1]);
    const top = 10, bottom = 24;
    const ax = valueAxis(Math.min(...ys), Math.max(...ys), H - top - bottom, userFmt(o.y && o.y.format, null));
    const y = C.scale([ax.lo, ax.hi], [H - bottom, top]);
    const left = Math.max(...ax.labels.map((t) => t.length)) * CH + 12;

    // End labels: 2–4 series whose last points are at least 14 px apart; otherwise the legend and dashes carry identity.
    const drawn = series.filter((x) => x.pts.length);
    let ends = drawn.length >= 2 && drawn.length <= 4 ? drawn.map((x) => ({ x, y: y(x.pts[x.pts.length - 1][1]), text: short(x.name, 18) })) : [];
    const ey = ends.map((e) => e.y).sort((a, b) => a - b);
    if (ey.some((v, i) => i && v - ey[i - 1] < 14)) ends = [];
    const right = ends.length ? Math.max(...ends.map((e) => e.text.length)) * CH + 14 : 16;
    const x0 = left, x1 = Math.max(left + 20, W - right);
    const x = C.scale([xs[0], xs[xs.length - 1]], [x0, x1]);
    const px = xs.map(x);

    const nodes = [];
    ax.ticks.forEach((t, i) => {
      nodes.push(s("line", { class: t === 0 ? "lg-chart-zero" : "lg-chart-gridline", x1: R(x0), x2: R(x1), y1: R(y(t)), y2: R(y(t)) }));
      nodes.push(tick("lg-chart-ytick", x0 - 8, y(t) + 4, "end", ax.labels[i]));
    });
    const maxT = Math.max(2, Math.floor((x1 - x0) / 80));
    let xt;
    if (xs.length === 1) xt = xs;
    else if (time) {
      const step = Math.ceil((xs.length - 1) / (maxT - 1));
      xt = xs.filter((_, i) => i % step === 0);
    } else xt = C.niceTicks(xs[0], xs[xs.length - 1], maxT).filter((v) => v >= xs[0] - 1e-9 * Math.abs(span) && v <= xs[xs.length - 1] + 1e-9 * Math.abs(span));
    for (const v of xt) nodes.push(tick("lg-chart-xtick", x(v), H - 6, "middle", fx(v)));

    const base = y(clamp(0, ax.lo, ax.hi));
    for (const sr of series) {
      const pts = sr.pts.map((p) => [x(p[0]), y(p[1])]);
      if (pts.length >= 2) {
        const d = C.linePath(pts);
        if (o.area) nodes.push(s("path", { class: "lg-chart-area", fill: sr.color, d: `${d}L${R(pts[pts.length - 1][0])},${R(base)}L${R(pts[0][0])},${R(base)}Z` }));
        nodes.push(s("path", Object.assign({ class: "lg-chart-line", d, stroke: sr.color, fill: "none", "data-lg-series": sr.si }, sr.dash ? { "stroke-dasharray": sr.dash } : {})));
      } else if (pts.length === 1) {
        nodes.push(s("circle", { class: "lg-chart-marker", cx: R(pts[0][0]), cy: R(pts[0][1]), r: 4, fill: sr.color, "data-lg-series": sr.si }));
      }
    }
    for (const e of ends) {
      const last = e.x.pts[e.x.pts.length - 1];
      nodes.push(s("text", { class: "lg-chart-endlabel", x: R(x(last[0]) + 8), y: R(e.y + 4) }, [e.text]));
    }

    // Hover layer: the crosshair and a dot per series at the active x.
    const cross = s("line", { class: "lg-chart-cross", y1: R(top), y2: R(H - bottom), x1: 0, x2: 0, visibility: "hidden" });
    const dots = series.map((sr) => s("circle", { class: "lg-chart-dot", r: 4, cx: 0, cy: 0, fill: sr.color, visibility: "hidden" }));
    nodes.push(s("g", { class: "lg-chart-hover" }, [cross].concat(dots)));

    const valueAt = (sr, xv) => { const p = sr.pts.find((q) => q[0] === xv); return p ? p[1] : null; };
    const summary = drawn.map((sr) => {
      const v = sr.pts.map((p) => p[1]);
      return v.length === 1 ? `${sr.name} ${fy(v[0])}` :
        `${sr.name} ${fy(v[0])} to ${fy(v[v.length - 1])} (low ${fy(Math.min(...v))}, high ${fy(Math.max(...v))})`;
    }).join("; ");
    return {
      nodes,
      label: `${label}: ${xs.length > 1 ? `${fx(xs[0])} to ${fx(xs[xs.length - 1])}. ` : ""}${summary}`,
      legend: series.length >= 2 ? series.map((sr) => ({ label: sr.name, swatch: swatchLine(sr.color, sr.dash) })) : null,
      items: {
        count: xs.length,
        hit: (pxv) => C.nearest(px, pxv),
        at(i) {
          const vals = series.map((sr) => valueAt(sr, xs[i]));
          const fy0 = vals.filter((v) => v !== null);
          return { title: fx(xs[i]), x: px[i], y: fy0.length ? y(Math.max(...fy0)) : top,
                   rows: series.map((sr, k) => ({ name: sr.name, value: vals[k] === null ? "–" : fy(vals[k]), swatch: swatchLine(sr.color, sr.dash) })) };
        },
        mark(i) {
          const on = i >= 0;
          cross.setAttribute("visibility", on ? "visible" : "hidden");
          if (on) { cross.setAttribute("x1", R(px[i])); cross.setAttribute("x2", R(px[i])); }
          series.forEach((sr, k) => {
            const v = on ? valueAt(sr, xs[i]) : null;
            dots[k].setAttribute("visibility", v === null ? "hidden" : "visible");
            if (v !== null) { dots[k].setAttribute("cx", R(px[i])); dots[k].setAttribute("cy", R(y(v))); }
          });
        },
      },
    };
  }

  // --- bar (grouped or stacked, vertical or horizontal) ------------------------------------------
  function renderBar(o, { W, H, colors, id }) {
    const label = o.label ? String(o.label) : "Bar chart";
    const cats = (o.categories || []).map(String);
    const series = (o.series || []).map((sr, si) => ({
      name: nameOf(sr, si, "Series"), si, color: colors[si % colors.length],
      fill: si === 0 ? colors[0] : `url(#${id}-p${si})`,
      vals: cats.map((_, ci) => finite(sr && sr.values ? sr.values[ci] : undefined)),
    }));
    const any = series.some((sr) => sr.vals.some((v) => v !== null));
    if (!cats.length || !any) return emptyView(label);
    const fv = (v) => fullNum.format(v);
    const stacked = !!o.stacked, horiz = !!o.horizontal;
    let lo = 0, hi = 0;
    cats.forEach((_, ci) => {
      let pos = 0, neg = 0;
      for (const sr of series) {
        const v = sr.vals[ci];
        if (v === null) continue;
        if (stacked) { if (v >= 0) pos += v; else neg += v; } else { pos = Math.max(pos, v); neg = Math.min(neg, v); }
      }
      hi = Math.max(hi, pos); lo = Math.min(lo, neg);
    });
    const k = stacked ? 1 : series.length;
    const labelled = !stacked;
    const valueLen = Math.max(...series.map((sr) => Math.max(...sr.vals.map((v) => (v === null ? 0 : fv(v).length)))));

    let x0, x1, y0, y1, height, ax;
    if (horiz) {
      const band = Math.max(28, k * 14 + 12);
      x0 = Math.min(W * 0.4, Math.max(...cats.map((c) => short(c, 24).length)) * CH + 12);
      x1 = Math.max(x0 + 20, W - 10 - (labelled ? valueLen * CH + 6 : 0));
      y0 = 8; y1 = y0 + band * cats.length;
      height = y1 + 24;
      ax = valueAxis(lo, hi, x1 - x0);
    } else {
      y0 = labelled ? 18 : 10; y1 = H - 24;
      ax = valueAxis(lo, hi, y1 - y0);
      x0 = Math.max(...ax.labels.map((t) => t.length)) * CH + 12;
      x1 = W - 8;
    }
    const v = horiz ? C.scale([ax.lo, ax.hi], [x0, x1]) : C.scale([ax.lo, ax.hi], [y1, y0]);
    const bandStart = horiz ? y0 : x0, bandLen = (horiz ? y1 - y0 : x1 - x0) / cats.length;
    const barT = clamp((bandLen * 0.7 - (k - 1) * 2) / k, 1, 24);
    const groupT = k * barT + (k - 1) * 2;

    const nodes = [s("defs", {}, series.filter((sr) => sr.si > 0).map((sr) => pattern(`${id}-p${sr.si}`, sr.color, sr.si)))];
    const band = s("rect", { class: "lg-chart-band", x: 0, y: 0, width: 0, height: 0, rx: 4, visibility: "hidden" });
    nodes.push(band);
    ax.ticks.forEach((t, i) => {
      const p = R(v(t)), cls = t === 0 ? "lg-chart-zero" : "lg-chart-gridline";
      if (horiz) {
        nodes.push(s("line", { class: cls, x1: p, x2: p, y1: R(y0), y2: R(y1) }));
        nodes.push(tick("lg-chart-xtick", v(t), height - 6, "middle", ax.labels[i]));
      } else {
        nodes.push(s("line", { class: cls, x1: R(x0), x2: R(x1), y1: p, y2: p }));
        nodes.push(tick("lg-chart-ytick", x0 - 8, v(t) + 4, "end", ax.labels[i]));
      }
    });
    const tops = [];   // per category: the anchor point for the tooltip
    cats.forEach((c, ci) => {
      const b0 = bandStart + ci * bandLen, g0 = b0 + (bandLen - groupT) / 2;
      if (horiz) nodes.push(tick("lg-chart-cat", x0 - 8, b0 + bandLen / 2 + 4, "end", short(c, 24)));
      else nodes.push(tick("lg-chart-cat lg-chart-xtick", b0 + bandLen / 2, y1 + 18, "middle", short(c, Math.max(3, Math.floor(bandLen / CH)))));
      let pos = 0, neg = 0, reach = v(0);
      const present = series.filter((sr) => sr.vals[ci] !== null && sr.vals[ci] !== 0);
      const lastPos = present.filter((sr) => sr.vals[ci] > 0).pop(), lastNeg = present.filter((sr) => sr.vals[ci] < 0).pop();
      series.forEach((sr, si) => {
        const val = sr.vals[ci];
        if (val === null || val === 0) return;
        let a, b, outer = true;
        if (stacked) {
          if (val > 0) { a = pos; b = pos += val; outer = sr === lastPos; } else { a = neg; b = neg += val; outer = sr === lastNeg; }
        } else { a = 0; b = val; }
        let pa = v(a), pb = v(b);
        if (!outer) pb += (pb > pa ? -1 : 1) * Math.min(2, Math.abs(pb - pa));   // the 2 px gap between stacked segments
        const t0 = stacked ? g0 : g0 + si * (barT + 2);
        const lo2 = Math.min(pa, pb), len = Math.abs(pb - pa);
        const end = horiz ? (val > 0 ? "right" : "left") : (val > 0 ? "top" : "bottom");
        const d = horiz ? C.barPath(lo2, t0, len, barT, outer ? 4 : 0, end) : C.barPath(t0, lo2, barT, len, outer ? 4 : 0, end);
        if (d) nodes.push(s("path", { class: "lg-chart-bar", d, fill: sr.fill, "data-lg-series": si, "data-lg-index": ci }));
        reach = horiz ? Math.max(reach, pb) : Math.min(reach, pb);
        if (labelled) {
          const text = fv(val), w = text.length * CH;
          if (horiz) nodes.push(s("text", { class: "lg-chart-value", x: R(val > 0 ? pb + 5 : pb - 5), y: R(t0 + barT / 2 + 4), "text-anchor": val > 0 ? "start" : "end" }, [text]));
          else if (w <= bandLen / k) nodes.push(s("text", { class: "lg-chart-value", x: R(t0 + barT / 2), y: R(val > 0 ? pb - 5 : pb + 13), "text-anchor": "middle" }, [text]));
        }
      });
      tops.push(horiz ? { x: reach, y: b0 + bandLen / 2 } : { x: b0 + bandLen / 2, y: reach });
    });

    const multi = series.length >= 2;
    const summary = cats.map((c, ci) => (multi
      ? `${c} (${series.map((sr) => `${sr.name} ${sr.vals[ci] === null ? "no value" : fv(sr.vals[ci])}`).join(", ")})`
      : `${c} ${series[0].vals[ci] === null ? "no value" : fv(series[0].vals[ci])}`)).join(multi ? "; " : ", ");
    return {
      nodes, height: horiz ? Math.round(height) : 0,
      label: `${label}: ${summary}`,
      legend: multi ? series.map((sr) => ({ label: sr.name, swatch: swatchRect(sr.fill) })) : null,
      items: {
        count: cats.length,
        hit(px, py) {
          const p = horiz ? py : px, i = Math.floor((p - bandStart) / bandLen);
          return i >= 0 && i < cats.length ? i : -1;
        },
        at: (ci) => ({ title: cats[ci], x: tops[ci].x, y: tops[ci].y,
                       rows: series.map((sr) => ({ name: sr.name, value: sr.vals[ci] === null ? "–" : fv(sr.vals[ci]), swatch: swatchRect(sr.fill) })) }),
        mark(ci) {
          band.setAttribute("visibility", ci >= 0 ? "visible" : "hidden");
          if (ci < 0) return;
          const b0 = bandStart + ci * bandLen;
          const r = horiz ? [x0, b0, x1 - x0, bandLen] : [b0, y0, bandLen, y1 - y0];
          ["x", "y", "width", "height"].forEach((a, i) => band.setAttribute(a, R(r[i])));
        },
      },
    };
  }

  // --- donut -------------------------------------------------------------------------------------
  function renderDonut(o, { W, H, colors, id }) {
    const label = o.label ? String(o.label) : "Donut chart";
    const parts = (o.parts || []).map((p, i) => ({ label: p && p.label !== undefined && p.label !== null ? String(p.label) : `Part ${i + 1}`,
                                                  value: Math.max(0, finite(p && p.value) || 0), color: colors[i % colors.length],
                                                  fill: i === 0 ? colors[0] : `url(#${id}-p${i})` }));
    const total = parts.reduce((a, p) => a + p.value, 0);
    if (!(total > 0) || !fin(total)) return emptyView(label);
    const fv = (v) => fullNum.format(v);
    const pct = (v) => `${Math.round((v / total) * 100)}%`;
    const size = Math.min(W, H), cx = W / 2, cy = H / 2, r = Math.max(4, size / 2 - 2), inner = r * 0.64;
    const live = parts.filter((p) => p.value > 0);
    const pad = live.length > 1 ? 1 / r : 0;
    let acc = 0;
    const segs = [];
    for (const p of live) {
      const a0 = (acc / total) * 2 * Math.PI, a1 = ((acc += p.value) / total) * 2 * Math.PI;
      const d = C.arcPath(cx, cy, r, inner, a0 + pad, Math.max(a0 + pad, a1 - pad));
      segs.push({ p, a0, a1, node: d ? s("path", { class: "lg-chart-seg", d, fill: p.fill }) : null });
    }
    const g = s("g", { class: "lg-chart-segs" }, segs.map((x) => x.node));
    const nodes = [s("defs", {}, parts.slice(1).map((p, k) => pattern(`${id}-p${k + 1}`, p.color, k + 1))), g];
    if (o.center !== undefined && o.center !== null && o.center !== "") {
      nodes.push(s("text", { class: "lg-chart-center", x: R(cx), y: R(cy + 6), "text-anchor": "middle" }, [String(o.center)]));
    }
    return {
      nodes, legendAfter: true,
      label: `${label}: ${parts.map((p) => `${p.label} ${fv(p.value)} (${pct(p.value)})`).join(", ")}`,
      legend: parts.map((p) => ({ label: p.label, value: `${fv(p.value)} · ${pct(p.value)}`, swatch: swatchRect(p.fill) })),
      items: {
        count: segs.length,
        hit(px, py) {
          const dx = px - cx, dy = py - cy, dist = Math.hypot(dx, dy);
          if (dist < inner - 4 || dist > r + 4) return -1;
          let a = Math.atan2(dx, -dy);
          if (a < 0) a += 2 * Math.PI;
          return segs.findIndex((x) => a >= x.a0 && a < x.a1);
        },
        at(i) {
          const x = segs[i], m = (x.a0 + x.a1) / 2, rm = (r + inner) / 2;
          return { title: x.p.label, x: cx + rm * Math.sin(m), y: cy - rm * Math.cos(m),
                   rows: [{ name: pct(x.p.value), value: fv(x.p.value), swatch: swatchRect(x.p.fill) }] };
        },
        mark(i) {
          if (i >= 0) g.setAttribute("data-lg-hover", ""); else g.removeAttribute("data-lg-hover");
          segs.forEach((x, k) => { if (x.node) { if (k === i) x.node.setAttribute("data-lg-active", ""); else x.node.removeAttribute("data-lg-active"); } });
        },
      },
    };
  }

  // --- meter: a half-ring gauge -------------------------------------------------------------------
  function renderMeter(o, { W, H, colors }) {
    const label = o.label ? String(o.label) : "Meter";
    const max = o.max === undefined || o.max === null ? 100 : o.max;
    const val = finite(o.value);
    if (val === null || !fin(max) || max <= 0) return emptyView(label);
    const fv = (v) => fullNum.format(v);
    const frac = clamp(val / max, 0, 1);
    const r = Math.max(10, Math.min(W / 2 - 4, H - 30)), inner = r - Math.max(6, r * 0.2);
    const cx = W / 2, cy = r + 4;
    const nodes = [s("path", { class: "lg-chart-track", d: C.arcPath(cx, cy, r, inner, -Math.PI / 2, Math.PI / 2) })];
    const d = C.arcPath(cx, cy, r, inner, -Math.PI / 2, -Math.PI / 2 + Math.PI * frac);
    if (d) nodes.push(s("path", { class: "lg-chart-fill", d, fill: colors[0] }));
    nodes.push(s("text", { class: "lg-chart-meter-value", x: R(cx), y: R(cy - 4), "text-anchor": "middle" }, [fv(val)]));
    nodes.push(s("text", { class: "lg-chart-meter-label", x: R(cx), y: R(cy + 18), "text-anchor": "middle" }, [label]));
    return { nodes, label: `${label}: ${fv(val)} of ${fv(max)}`, legend: null, items: null };
  }

  C.line = (el, opts) => makeChart(el, "line", opts, renderLine);
  C.bar = (el, opts) => makeChart(el, "bar", opts, renderBar);
  C.donut = (el, opts) => makeChart(el, "donut", opts, renderDonut);
  C.meter = (el, opts) => makeChart(el, "meter", opts, renderMeter);
})();

// Table extras. Sorting: <th data-lg-sort> in a .lg-table. A click (or Enter/Space on the button
// that auto-init puts inside the header, the keyboard-operable pattern) cycles aria-sort through
// ascending, descending and none, and sorts the tbody rows by that column; "none" restores the
// original order. A cell's key is its data-value, else its text. Rows with .lg-table-empty stay last.
// Selection: <input type="checkbox" data-lg-select-all> in the header and data-lg-select in rows;
// the header box shows checked / unchecked / indeterminate, selected rows get data-lg-selected (the
// CSS hook; the checkbox is the accessible state, aria-selected is only valid in grids), and the
// table fires a bubbling "lg-selection" event with detail.count.
// LG.table.compare(a, b): numbers numerically, otherwise natural, case-insensitive localeCompare. Pure.
LG.table = {
  compare(a, b) {
    const na = typeof a === "number" ? a : (String(a).trim() === "" ? NaN : Number(a));
    const nb = typeof b === "number" ? b : (String(b).trim() === "" ? NaN : Number(b));
    if (Number.isFinite(na) && Number.isFinite(nb)) return na < nb ? -1 : na > nb ? 1 : 0;
    return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  },
};

const tableOrder = new WeakMap();   // tbody -> its rows in the original order

function sortKey(row, col) {
  const cell = row.cells[col];
  if (!cell) return "";
  return cell.hasAttribute("data-value") ? cell.getAttribute("data-value") : cell.textContent.trim();
}

// Wrap a sortable header's content in a <button> so Tab, Enter and Space work natively.
function prepareSortHeader(th) {
  if (th.querySelector("button.lg-sort-btn")) return;
  const btn = LG.util.el("button", { class: "lg-sort-btn", attrs: { type: "button" } });
  btn.append(...Array.from(th.childNodes));
  th.append(btn);
  if (!th.hasAttribute("aria-sort")) th.setAttribute("aria-sort", "none");
}

function applySort(th) {
  const table = th.closest("table");
  const body = table && table.tBodies[0];
  if (!body) return;
  if (!tableOrder.has(body)) tableOrder.set(body, Array.from(body.rows));
  const cur = th.getAttribute("aria-sort");
  const next = cur === "ascending" ? "descending" : cur === "descending" ? "none" : "ascending";
  for (const h of table.querySelectorAll("th[data-lg-sort]")) { prepareSortHeader(h); h.setAttribute("aria-sort", "none"); }
  th.setAttribute("aria-sort", next);
  const col = th.cellIndex;
  const original = tableOrder.get(body).filter((r) => r.parentNode === body);
  const known = new Set(original);
  const extra = Array.from(body.rows).filter((r) => !known.has(r));   // rows added after the first sort
  let rows = original.concat(extra);
  const empty = rows.filter((r) => r.classList.contains("lg-table-empty"));
  rows = rows.filter((r) => !r.classList.contains("lg-table-empty"));
  if (next !== "none") {
    const dir = next === "ascending" ? 1 : -1;
    rows = rows.map((r, i) => ({ r, i, k: sortKey(r, col) }))
      .sort((x, y) => dir * LG.table.compare(x.k, y.k) || x.i - y.i).map((x) => x.r);
  }
  body.append(...rows, ...empty);
}

function syncSelection(table) {
  const boxes = Array.from(table.querySelectorAll("[data-lg-select]"));
  let count = 0;
  for (const b of boxes) {
    const tr = b.closest("tr");
    if (b.checked) count++;
    if (tr) tr.toggleAttribute("data-lg-selected", b.checked);
  }
  for (const all of table.querySelectorAll("[data-lg-select-all]")) {
    all.checked = boxes.length > 0 && count === boxes.length;
    all.indeterminate = count > 0 && count < boxes.length;
  }
  table.dispatchEvent(new CustomEvent("lg-selection", { bubbles: true, detail: { count } }));
}

// Headers rendered after init (tables built on fetch) are prepared by the shared observer.
LG._added.push((n) => {
  if (n.matches("th[data-lg-sort]")) prepareSortHeader(n);
  for (const th of n.querySelectorAll("th[data-lg-sort]")) prepareSortHeader(th);
});

LG._init.push(() => {
  for (const th of document.querySelectorAll("th[data-lg-sort]")) prepareSortHeader(th);
  for (const t of document.querySelectorAll("table")) {
    if (t.querySelector("[data-lg-select]")) syncSelection(t);
  }
  document.addEventListener("click", (e) => {
    const th = e.target && typeof e.target.closest === "function" ? e.target.closest("th[data-lg-sort]") : null;
    if (th) applySort(th);
  });
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (!t || typeof t.matches !== "function") return;
    const table = t.closest("table");
    if (!table) return;
    if (t.matches("[data-lg-select-all]")) {
      for (const b of table.querySelectorAll("[data-lg-select]")) if (!b.disabled) b.checked = t.checked;
      syncSelection(table);
    } else if (t.matches("[data-lg-select]")) {
      syncSelection(table);
    }
  });
});

// Closes the wrapper opened in 00-head.js: Node gets the object from require(); browsers get the
// global LadaGlass and the auto-init (every LG._init function, once the DOM is ready).
if (typeof module === "object" && module && module.exports) {
  module.exports = LG;
} else {
  root.LadaGlass = LG;
}

if (typeof document !== "undefined") {
  const runInit = () => {
    for (const fn of LG._init) {
      try { fn(); } catch (e) { console.error("LadaGlass init:", e); }   // one broken part doesn't stop the others
    }
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", runInit, { once: true });
  else runInit();
}
})(typeof globalThis !== "undefined" ? globalThis : this);
