(function () {
  // Files larger than this are streamed straight to disk through the service
  // worker (when available) instead of being assembled in memory (PERF-005).
  const STREAM_THRESHOLD = 64 * 1024 * 1024;

  const humanSize = (b) => window.SDUtil.humanSize(b);

  function timeRemaining(expiresAtIso) {
    const diffMs = new Date(expiresAtIso).getTime() - Date.now();
    if (diffMs <= 0) return "expired";
    const mins = Math.floor(diffMs / 60000);
    if (mins < 60) return `${mins}m remaining`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h remaining`;
    return `${Math.floor(hrs / 24)}d remaining`;
  }

  function fetchMeta(fileId) {
    return window.SDApi.get(`/api/files/${encodeURIComponent(fileId)}/meta`);
  }

  /**
   * Work out the headers that prove we hold the key, and check them with the
   * server *before* downloading - so a wrong passphrase or a truncated link
   * fails cleanly instead of consuming (or burning) the file (UI-003).
   */
  async function authorize(fileId, meta, urlKey, password) {
    if (meta.auth_scheme === "token") {
      const token = await window.SDCrypto.deriveDownloadToken({
        urlKey, password: meta.requires_password ? password : null,
        kdfSalt: meta.kdf_salt, kdfIterations: meta.kdf_iterations,
      });
      await window.SDApi.post(`/api/files/${encodeURIComponent(fileId)}/verify-token`, { token });
      return { "X-Download-Token": token };
    }
    if (meta.auth_scheme === "legacy_password") {
      // Files uploaded before the token scheme: the server checks the
      // passphrase itself. New uploads never send it (SEC-001).
      await window.SDApi.post(`/api/files/${encodeURIComponent(fileId)}/verify-password`, { password });
      return { "X-Secondary-Password": password };
    }
    return {};
  }

  // ---- stream-to-disk via service worker --------------------------------
  let swReady = null;
  function serviceWorker() {
    if (!swReady) {
      swReady = (async () => {
        if (!("serviceWorker" in navigator) || !window.isSecureContext || !window.ReadableStream) return null;
        try {
          await navigator.serviceWorker.register("/sw.js", { scope: "/" });
          const reg = await navigator.serviceWorker.ready;
          return reg.active || null;
        } catch (e) {
          return null;
        }
      })();
    }
    return swReady;
  }

  /** A sink whose bytes flow to a file download, with backpressure. */
  async function openDiskSink(meta, size) {
    const sw = await serviceWorker();
    if (!sw) return null;
    const id = Math.random().toString(36).slice(2) + Date.now().toString(36);
    const channel = new MessageChannel();
    let credits = 0, waiter = null, failed = null;
    channel.port1.onmessage = (e) => {
      if (e.data.type === "pull") { credits += 1; if (waiter) { waiter(); waiter = null; } }
      if (e.data.type === "cancel") { failed = new Error("Download cancelled."); if (waiter) { waiter(); waiter = null; } }
    };
    const opened = new Promise((resolve) => {
      const onOpen = (e) => { if (e.data.type === "opened") { channel.port1.removeEventListener("message", onOpen); resolve(); } };
      channel.port1.addEventListener("message", onOpen);
    });
    channel.port1.start();
    sw.postMessage({ type: "open", id, name: meta.name || "download", mime: meta.type, size }, [channel.port2]);
    await opened;
    const frame = document.createElement("iframe");
    frame.hidden = true;
    frame.src = `/__ratatosk_dl/${id}`;
    document.body.appendChild(frame);
    setTimeout(() => frame.remove(), 60 * 60 * 1000);
    return {
      async write(u8) {
        while (credits <= 0 && !failed) await new Promise((r) => { waiter = r; });
        if (failed) throw failed;
        credits -= 1;
        const copy = u8.slice();
        channel.port1.postMessage({ type: "chunk", chunk: copy }, [copy.buffer]);
      },
      async close() { channel.port1.postMessage({ type: "done" }); },
      async abort() { channel.port1.postMessage({ type: "abort" }); },
    };
  }

  /**
   * Download and decrypt. Returns { name, type, size, kind, streamed, blob }.
   * opts: { meta, onProgress(fraction), forceMemory }
   */
  async function fetchAndDecrypt(fileId, password, urlKey, opts) {
    opts = opts || {};
    const meta = opts.meta || await fetchMeta(fileId);
    const headers = await authorize(fileId, meta, urlKey, password);
    // The session (if any) travels in the HttpOnly cookie.
    const res = await fetch(`/api/files/${encodeURIComponent(fileId)}/blob`, { headers, credentials: "same-origin" });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    const total = meta.size_bytes || Number(res.headers.get("content-length")) || 0;
    const decryptOpts = {
      onProgress: (n) => { if (opts.onProgress && total) opts.onProgress(Math.min(n / total, 1)); },
      onMeta: async (m) => {
        // Text and bundle manifests are always small and shown in the page.
        // Read at call time so it can be tuned (and tests can force the path).
        if (opts.forceMemory || m.kind || total < window.SDDownload.STREAM_THRESHOLD) return null;
        return openDiskSink(m, m.size);
      },
    };
    if (res.body && res.body.getReader) {
      return window.SDCrypto.decryptStream(window.SDCrypto.readableToIterator(res.body), urlKey, password, decryptOpts);
    }
    return window.SDCrypto.decryptDownload(await res.arrayBuffer(), urlKey, password, decryptOpts);
  }

  function saveDecrypted(result) {
    if (result.streamed) return; // already written to disk by the service worker
    const url = URL.createObjectURL(result.blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = result.name || "download";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  /** For burn-after-download / last-download files: make the loss explicit. */
  function confirmDestructive(meta) {
    const last = meta.burn_after_download || (meta.max_downloads && meta.download_count + 1 >= meta.max_downloads);
    if (!last) return true;
    return window.confirm(
      "This file will be permanently deleted after this download.\n\n" +
      "Make sure you can save it now - it can't be downloaded again. Continue?"
    );
  }

  /** Text sends (FEAT-006) are shown in the page instead of downloaded. */
  async function renderText(result, container) {
    const text = await result.blob.text();
    container.textContent = "";
    const pre = document.createElement("pre");
    pre.className = "text-view";
    pre.textContent = text;
    pre.tabIndex = 0;
    pre.setAttribute("aria-label", "Decrypted message");
    const copy = document.createElement("button");
    copy.className = "btn btn-outline btn-sm mt-1";
    copy.type = "button";
    copy.textContent = "Copy text";
    copy.addEventListener("click", () => window.SDUtil.copyText(text, copy));
    container.appendChild(pre);
    container.appendChild(copy);
    container.hidden = false;
  }

  /** Bundles (FEAT-003): list member files, each downloadable on its own. */
  async function renderBundle(result, container, opts) {
    const manifest = JSON.parse(await result.blob.text());
    container.textContent = "";
    const heading = document.createElement("h3");
    heading.className = "mt-0";
    heading.textContent = `${manifest.files.length} file(s)`;
    container.appendChild(heading);
    const list = document.createElement("ul");
    list.className = "bundle-list";
    const buttons = [];
    for (const item of manifest.files) {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = `${item.name} (${humanSize(item.size)})`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-outline btn-sm";
      btn.textContent = "Download";
      const download = async () => {
        if (btn.disabled) return;
        btn.disabled = true;
        try {
          const r = await fetchAndDecrypt(item.id, null, item.key, {});
          saveDecrypted(r);
          btn.textContent = "Saved ✓";
        } catch (e) {
          btn.disabled = false;
          window.SDToast.show(`${item.name}: ${e.message}`, "danger");
        }
      };
      btn.addEventListener("click", download);
      buttons.push(download);
      li.appendChild(label);
      li.appendChild(btn);
      list.appendChild(li);
    }
    container.appendChild(list);
    const all = document.createElement("button");
    all.type = "button";
    all.className = "btn btn-primary btn-block mt-2";
    all.textContent = "Download all";
    all.addEventListener("click", async () => {
      all.disabled = true;
      for (const download of buttons) await download();
      all.disabled = false;
    });
    container.appendChild(all);
    container.hidden = false;
    if (opts && opts.onRendered) opts.onRendered();
  }

  async function guardAnonymousDownload() {
    if (window.SDApi.isLoggedIn()) return false;
    try {
      const cfg = await window.SDApi.config();
      if (!cfg.allow_anonymous_download) {
        window.location.href = "/login";
        return true;
      }
    } catch (e) { /* config fetch failing shouldn't block the page */ }
    return false;
  }

  window.SDDownload = {
    STREAM_THRESHOLD, humanSize, timeRemaining, fetchMeta, fetchAndDecrypt, saveDecrypted,
    confirmDestructive, renderText, renderBundle, guardAnonymousDownload,
  };
})();
