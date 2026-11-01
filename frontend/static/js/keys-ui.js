/*
 * UI helpers around SDKeys: unlock your encryption key (from this device's
 * memory or by asking for the passphrase in an accessible dialog), and turn
 * a wrapped file key into the URL-key form the download code uses.
 */
(function () {
  let material = null; // { public_key, wrapped_private_key, kdf_salt, kdf_iterations, fingerprint }
  let unlocked = null;

  async function myMaterial(force) {
    if (!material || force) material = await window.SDApi.get("/api/account/keys");
    return material;
  }

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k === "className") el.className = v; else el.setAttribute(k, v === true ? "" : v);
    }
    kids.flat().forEach((c) => c != null && el.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
    return el;
  }

  /**
   * Accessible passphrase dialog. Resolves { passphrase, remember } or null.
   * opts: { title, message, confirm (ask twice), remember (show checkbox), submitLabel }
   */
  function askPassphrase(opts) {
    return new Promise((resolve) => {
      const previous = document.activeElement;
      const input = h("input", { type: "password", id: "sdk-pass", autocomplete: "off", minlength: "10", required: true });
      const input2 = opts.confirm ? h("input", { type: "password", id: "sdk-pass2", autocomplete: "off", required: true }) : null;
      const remember = opts.remember ? h("input", { type: "checkbox", id: "sdk-remember" }) : null;
      const error = h("div", { className: "small text-danger mt-1", role: "alert" });
      const cancel = h("button", { type: "button", className: "btn btn-outline" }, "Cancel");
      const form = h("form", { className: "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "sdk-title" },
        h("h3", { className: "mt-0", id: "sdk-title" }, opts.title || "Encryption passphrase"),
        opts.message ? h("p", { className: "small text-muted" }, opts.message) : null,
        h("div", { className: "form-group" }, h("label", { for: "sdk-pass" }, "Passphrase"), input),
        input2 ? h("div", { className: "form-group" }, h("label", { for: "sdk-pass2" }, "Repeat passphrase"), input2) : null,
        remember ? h("label", { className: "small" }, remember, " Remember on this device until I log out") : null,
        error,
        h("div", { className: "row-actions mt-2" }, h("button", { type: "submit", className: "btn btn-primary" }, opts.submitLabel || "Unlock"), cancel));
      const backdrop = h("div", { className: "modal-backdrop" }, form);
      function close(value) {
        backdrop.remove();
        document.removeEventListener("keydown", onKey);
        if (previous && previous.focus) previous.focus();
        resolve(value);
      }
      function onKey(e) { if (e.key === "Escape") close(null); }
      cancel.addEventListener("click", () => close(null));
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        if (opts.confirm && input.value.length < 10) { error.textContent = "Use at least 10 characters."; return; }
        if (input2 && input.value !== input2.value) { error.textContent = "The passphrases don't match."; return; }
        close({ passphrase: input.value, remember: !!(remember && remember.checked) });
      });
      document.addEventListener("keydown", onKey);
      document.body.appendChild(backdrop);
      input.focus();
    });
  }

  /** The unlocked private key, asking for the passphrase if needed. */
  async function unlockPrivateKey() {
    const m = await myMaterial();
    if (unlocked && unlocked.fingerprint === m.fingerprint) return unlocked.key;
    const user = window.SDApi.getUser();
    const cached = user ? await window.SDKeys.recall(user.id) : null;
    if (cached && cached.fingerprint === m.fingerprint) {
      unlocked = { key: cached.key, fingerprint: m.fingerprint };
      return cached.key;
    }
    for (;;) {
      const answer = await askPassphrase({
        title: "Unlock your encryption key",
        message: "Files shared with you end-to-end can only be opened with your encryption passphrase. It never leaves this browser.",
        remember: true,
      });
      if (!answer) throw new Error("Cancelled.");
      try {
        const key = await window.SDKeys.unlock(m, answer.passphrase);
        unlocked = { key, fingerprint: m.fingerprint };
        if (answer.remember && user) await window.SDKeys.remember(user.id, m.fingerprint, key);
        return key;
      } catch (e) {
        window.SDToast.show(e.message, "danger");
      }
    }
  }

  /** Wrapped file secret -> base64url key usable as a link key. */
  async function openSecret(wrappedKey, ephemeralPublicKey) {
    const m = await myMaterial();
    const key = await unlockPrivateKey();
    const secret = await window.SDKeys.unwrapSecret(wrappedKey, ephemeralPublicKey, key, m.public_key);
    return window.SDCrypto.b64urlEncode(secret);
  }

  window.SDKeysUI = { askPassphrase, myMaterial, unlockPrivateKey, openSecret, h };
})();
