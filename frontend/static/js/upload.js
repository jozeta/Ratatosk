(function () {
  let cfg = null;
  // { id, file, status: pending|encrypting|uploading|done|error, progress, error, strip: {status, note} }
  let queue = [];
  let mode = "file"; // "file" | "text"
  let activeAbort = null;

  const RESUME_TTL_MS = 60 * 60 * 1000; // matches the server's idle timeout

  const $ = (id) => document.getElementById(id);
  const dropzone = $("dropzone");
  const dropzoneText = $("dropzoneText");
  const fileInput = $("fileInput");
  const folderInput = $("folderInput");
  const folderPickerRow = $("folderPickerRow");
  const folderPickerLink = $("folderPickerLink");
  const fileQueueEl = $("fileQueue");
  const uploadBtn = $("uploadBtn");
  const cancelBtn = $("cancelBtn");
  const ttlMaxDownloadsRow = $("ttlMaxDownloadsRow");
  const ttlGroup = $("ttlGroup");
  const ttlSelect = $("ttlSelect");
  const maxDownloadsGroup = $("maxDownloadsGroup");
  const maxDownloadsInput = $("maxDownloads");
  const burnRow = $("burnRow");
  const burnCheckbox = $("burnAfterDownload");
  const notifyRow = $("notifyRow");
  const notifyCheckbox = $("notifyOnDownload");
  const bundleRow = $("bundleRow");
  const bundleCheckbox = $("bundleFiles");
  const passwordGroup = $("passwordGroup");
  const passwordInput = $("secondaryPassword");
  const passwordOptionalLabel = $("passwordOptionalLabel");
  const progressWrap = $("progressWrap");
  const progressBar = $("progressBar");
  const progressLabel = $("progressLabel");
  const maxSizeHint = $("maxSizeHint");
  const fileModePanel = $("fileModePanel");
  const textModePanel = $("textModePanel");
  const textInput = $("textInput");
  const resumeBanner = $("resumeBanner");

  const resultModal = $("resultModal");
  const resultTitle = $("resultTitle");
  const resultLink = $("resultLink");
  const resultKeyGroup = $("resultKeyGroup");
  const resultKey = $("resultKey");
  const shareWithUsersSection = $("shareWithUsersSection");
  const userPickerList = $("userPickerList");
  const shareLookupInput = $("shareLookupInput");
  const shareLookupBtn = $("shareLookupBtn");
  const shareWithUsersBtn = $("shareWithUsersBtn");
  const shareStatus = $("shareStatus");
  const batchResultModal = $("batchResultModal");
  const batchResultsBody = $("batchResultsBody");

  const humanSize = (b) => window.SDUtil.humanSize(b);
  const showAlert = (message, type = "danger") => window.SDToast.show(message, type);

  const TTL_LABELS = { m: "minute(s)", h: "hour(s)", d: "day(s)" };
  function ttlLabel(code) {
    return `${code.slice(0, -1)} ${TTL_LABELS[code.slice(-1)] || code.slice(-1)}`;
  }

  async function loadConfig() {
    cfg = await window.SDApi.config();
    if (!cfg.allow_anonymous_upload && !window.SDApi.isLoggedIn()) {
      window.location.href = "/login";
      return;
    }

    ttlSelect.innerHTML = "";
    cfg.allowed_ttl_presets.split(",").map((s) => s.trim()).filter(Boolean).forEach((code) => {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = ttlLabel(code);
      if (code === cfg.default_ttl) opt.selected = true;
      ttlSelect.appendChild(opt);
    });
    ttlGroup.style.display = cfg.allow_custom_ttl ? "" : "none";
    maxSizeHint.textContent = `Max file size: ${cfg.max_file_size_mb} MB`;

    burnRow.style.display = cfg.allow_burn_after_download ? "" : "none";
    notifyRow.style.display = (cfg.enable_download_notifications && cfg.password_reset_enabled && window.SDApi.isLoggedIn()) ? "" : "none";
    if (cfg.force_burn_after_download) {
      burnCheckbox.checked = true;
      burnCheckbox.disabled = true;
    }
    maxDownloadsInput.value = cfg.default_max_downloads || 0;
    maxDownloadsGroup.style.display = cfg.allow_custom_max_downloads ? "" : "none";
    if (!cfg.allow_custom_ttl && !cfg.allow_custom_max_downloads) ttlMaxDownloadsRow.style.display = "none";

    passwordGroup.style.display = cfg.allow_secondary_password ? "" : "none";
    if (cfg.allow_secondary_password && cfg.enforce_secondary_password) {
      passwordOptionalLabel.textContent = "(required)";
      passwordInput.required = true;
    }
    if (cfg.enable_multi_file_upload) {
      fileInput.multiple = true;
      folderPickerRow.style.display = "";
      dropzoneText.textContent = "Drag & drop files or a folder here, or click to browse";
    }
    showResumableUploads();
  }

  // ---- mode switch (file / text) -----------------------------------------
  document.querySelectorAll("[data-mode]").forEach((tab) => {
    tab.addEventListener("click", () => {
      mode = tab.dataset.mode;
      document.querySelectorAll("[data-mode]").forEach((t) => t.setAttribute("aria-selected", t === tab ? "true" : "false"));
      fileModePanel.hidden = mode !== "file";
      textModePanel.hidden = mode !== "text";
      updateUploadButton();
    });
  });
  textInput.addEventListener("input", updateUploadButton);

  function updateUploadButton() {
    if (mode === "text") {
      uploadBtn.disabled = !textInput.value.trim();
      uploadBtn.textContent = "Encrypt & Share Text";
      return;
    }
    uploadBtn.disabled = queue.length === 0;
    uploadBtn.textContent = queue.length > 1 ? `Encrypt & Upload ${queue.length} files` : "Encrypt & Upload";
    bundleRow.style.display = queue.length > 1 ? "" : "none";
  }

  // ---- file queue ----------------------------------------------------------
  let nextId = 1;
  const rowEls = new Map(); // item id -> { row, fill, status }

  function addFiles(files) {
    const list = Array.from(files);
    if (!list.length) return;
    const items = list.map((file) => ({ id: nextId++, file, status: "pending", progress: 0, strip: null }));
    queue = cfg.enable_multi_file_upload ? queue.concat(items) : items.slice(0, 1);
    renderQueue();
    // Strip metadata up front so the user sees, per file, what happened (UI-004).
    for (const item of queue) {
      if (item.strip) continue;
      item.strip = { status: "checking", note: "Checking metadata…" };
      window.SDExif.stripImageMetadata(item.file).then((res) => {
        item.file = res.file;
        item.strip = { status: res.status, note: res.note };
        renderQueue();
      });
    }
  }

  function removeFromQueue(id) {
    queue = queue.filter((item) => item.id !== id);
    renderQueue();
  }

  const STRIP_LABELS = {
    checking: ["…", "badge-muted"], stripped: ["metadata removed", "badge-ok"], clean: ["no metadata", "badge-ok"],
    unsupported: ["metadata NOT removed", "badge-warn"], failed: ["metadata NOT removed", "badge-warn"], none: ["", ""],
  };

  // Rebuilds the list; called only when items are added/removed/finish -
  // progress ticks go through updateRowProgress instead (PERF-006).
  function renderQueue() {
    fileQueueEl.innerHTML = "";
    rowEls.clear();
    fileQueueEl.style.display = queue.length ? "" : "none";
    updateUploadButton();
    if (!queue.length) return;

    const list = document.createElement("ul");
    list.className = "file-queue";
    list.setAttribute("aria-label", "Files to upload");
    for (const item of queue) {
      const row = document.createElement("li");
      row.className = "file-queue-item";

      const name = document.createElement("span");
      name.className = "file-queue-name";
      name.textContent = item.file.name;
      name.title = item.file.name;
      row.appendChild(name);

      if (item.strip && STRIP_LABELS[item.strip.status] && STRIP_LABELS[item.strip.status][0]) {
        const [label, cls] = STRIP_LABELS[item.strip.status];
        const badge = document.createElement("span");
        badge.className = `badge ${cls}`;
        badge.textContent = label;
        badge.title = item.strip.note;
        row.appendChild(badge);
      }

      const size = document.createElement("span");
      size.className = "file-queue-size";
      size.textContent = humanSize(item.file.size);
      row.appendChild(size);

      const refs = { row };
      if (item.status === "pending") {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "file-queue-remove";
        remove.textContent = "×";
        remove.title = "Remove";
        remove.setAttribute("aria-label", `Remove ${item.file.name}`);
        remove.addEventListener("click", () => removeFromQueue(item.id));
        row.appendChild(remove);
      } else {
        const bar = document.createElement("div");
        bar.className = "file-queue-mini-bar";
        const fill = document.createElement("div");
        fill.className = "file-queue-mini-bar-fill";
        bar.appendChild(fill);
        const status = document.createElement("span");
        status.className = "file-queue-status";
        if (item.status === "done") { status.classList.add("status-done"); status.textContent = "Done"; bar.hidden = true; }
        if (item.status === "error") { status.classList.add("status-error"); status.textContent = item.error || "Failed"; bar.hidden = true; }
        row.appendChild(bar);
        row.appendChild(status);
        Object.assign(refs, { fill, status });
      }
      rowEls.set(item.id, refs);
      list.appendChild(row);
    }
    fileQueueEl.appendChild(list);
    queue.forEach(updateRowProgress);
  }

  let rafPending = new Set();
  function updateRowProgress(item) {
    rafPending.add(item);
    if (rafPending.size > 1) return;
    requestAnimationFrame(() => {
      for (const it of rafPending) {
        const refs = rowEls.get(it.id);
        if (!refs || !refs.fill) continue;
        refs.fill.style.width = `${Math.round(it.progress * 100)}%`;
        if (it.status === "encrypting") refs.status.textContent = "Encrypting…";
        else if (it.status === "uploading") refs.status.textContent = `${Math.round(it.progress * 100)}%`;
      }
      rafPending = new Set();
    });
  }

  // ---- drag & drop, including folders --------------------------------------
  async function collectFilesFromDataTransfer(dataTransfer) {
    const items = dataTransfer.items;
    if (!items || !items.length || !items[0].webkitGetAsEntry) return Array.from(dataTransfer.files || []);
    const entries = Array.from(items).map((i) => i.webkitGetAsEntry()).filter(Boolean);
    const files = [];
    async function walk(entry) {
      if (entry.isFile) {
        await new Promise((resolve) => entry.file((f) => { files.push(f); resolve(); }, resolve));
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        const all = await new Promise((resolve) => {
          const acc = [];
          (function readBatch() {
            reader.readEntries((batch) => { if (!batch.length) return resolve(acc); acc.push(...batch); readBatch(); }, () => resolve(acc));
          })();
        });
        for (const child of all) await walk(child);
      }
    }
    for (const entry of entries) await walk(entry);
    return files;
  }

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } });
  dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", async (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    const files = await collectFilesFromDataTransfer(e.dataTransfer);
    if (files.length) addFiles(files);
  });
  fileInput.addEventListener("change", () => { if (fileInput.files.length) addFiles(fileInput.files); fileInput.value = ""; });
  folderPickerLink.addEventListener("click", (e) => { e.preventDefault(); folderInput.click(); });
  folderInput.addEventListener("change", () => { if (folderInput.files.length) addFiles(folderInput.files); folderInput.value = ""; });

  function getExtension(filename) {
    const idx = filename.lastIndexOf(".");
    return idx >= 0 ? filename.slice(idx + 1).toLowerCase() : "";
  }

  function validateExtension(filename) {
    const ext = getExtension(filename);
    if (!ext) return true;
    const listed = cfg.extension_list.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
    if (cfg.extension_rule_mode === "whitelist") return listed.includes(ext);
    return !listed.includes(ext);
  }

  // ---- resumable state (FEAT-004) ------------------------------------------
  // An interrupted upload can be resumed after a reload: the File handle and
  // the parameters needed to regenerate identical ciphertext are kept in
  // IndexedDB until the upload finishes (or after an hour, when the server
  // forgets it anyway). Link-mode entries hold the file's key, so they exist
  // only for unfinished uploads and are deleted as soon as each one ends;
  // passphrase-mode entries never store the passphrase.
  const DB_NAME = "ratatosk-uploads";
  function idb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore("pending", { keyPath: "uploadId" });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  async function idbDo(modeRW, fn) {
    try {
      const db = await idb();
      return await new Promise((resolve, reject) => {
        const tx = db.transaction("pending", modeRW);
        const out = fn(tx.objectStore("pending"));
        tx.oncomplete = () => resolve(out && out.result);
        tx.onerror = () => reject(tx.error);
      });
    } catch (e) { return null; }
  }
  const savePending = (entry) => idbDo("readwrite", (s) => s.put(entry));
  const dropPending = (uploadId) => idbDo("readwrite", (s) => s.delete(uploadId));
  const listPending = () => idbDo("readonly", (s) => s.getAll());

  async function showResumableUploads() {
    const entries = (await listPending()) || [];
    const fresh = [];
    for (const e of entries) {
      if (Date.now() - e.createdAt > RESUME_TTL_MS) dropPending(e.uploadId);
      else fresh.push(e);
    }
    resumeBanner.innerHTML = "";
    resumeBanner.hidden = !fresh.length;
    for (const entry of fresh) {
      const row = document.createElement("div");
      row.className = "resume-row";
      const text = document.createElement("span");
      text.textContent = `Unfinished upload: ${entry.name} (${humanSize(entry.size)})`;
      const resume = document.createElement("button");
      resume.type = "button";
      resume.className = "btn btn-primary btn-sm";
      resume.textContent = "Resume";
      resume.addEventListener("click", () => resumeUpload(entry));
      const discard = document.createElement("button");
      discard.type = "button";
      discard.className = "btn btn-outline btn-sm";
      discard.textContent = "Discard";
      discard.addEventListener("click", async () => {
        try { await window.SDApi.del(`/api/uploads/${entry.uploadId}`); } catch (e) { /* already gone */ }
        await dropPending(entry.uploadId);
        showResumableUploads();
      });
      row.append(text, resume, discard);
      resumeBanner.appendChild(row);
    }
  }

  async function resumeUpload(entry) {
    let password = null;
    if (entry.resume.mode === "passphrase") {
      password = window.prompt(`Re-enter the passphrase used for "${entry.name}" to resume:`);
      if (!password) return;
    }
    progressWrap.style.display = "";
    try {
      const status = await window.SDApi.get(`/api/uploads/${entry.uploadId}`);
      const encryptor = await window.SDCrypto.createEncryptor(entry.file, entry.name, entry.type, password,
        { resume: entry.resume, kind: entry.kind || undefined });
      if (encryptor.size !== status.declared_size) throw new Error("The file has changed since the upload started.");
      setSingleProgress(status.resume_offset / encryptor.size, "Resuming...");
      setBusy(true);
      activeAbort = new AbortController();
      await streamUpload(entry.uploadId, encryptor, entry.chunkSize, status.resume_offset,
        (f) => setSingleProgress(f, `Uploading... ${Math.round(f * 100)}%`), activeAbort.signal);
      const res = await completeUpload(entry.uploadId, encryptor, entry.options, []);
      await dropPending(entry.uploadId);
      showResult(res.file_id, encryptor.urlKey, entry.kind === "text" ? "Message encrypted" : "File uploaded");
    } catch (e) {
      if (e.status === 404) {
        await dropPending(entry.uploadId);
        showAlert("That upload expired on the server - please start it again.");
      } else if (e.name !== "AbortError") showAlert(e.message || "Resume failed.");
    } finally {
      setBusy(false);
      progressWrap.style.display = "none";
      showResumableUploads();
    }
  }

  // ---- upload engine ---------------------------------------------------------
  function setBusy(busy) {
    uploadBtn.disabled = busy;
    cancelBtn.hidden = !busy;
    if (!busy) { activeAbort = null; updateUploadButton(); }
  }
  cancelBtn.addEventListener("click", () => { if (activeAbort) activeAbort.abort(); });

  // Chunked, parallel, retrying upload of an encryptor's output - shared
  // with the request-link page (upload-engine.js).
  const streamUpload = window.SDUploadEngine.streamUpload;

  function uploadOptions() {
    return {
      ttl: cfg.allow_custom_ttl ? ttlSelect.value : cfg.default_ttl,
      burn_after_download: burnCheckbox.checked,
      max_downloads: cfg.allow_custom_max_downloads ? (parseInt(maxDownloadsInput.value, 10) || 0) : 0,
      notify_on_download: notifyRow.style.display !== "none" && notifyCheckbox.checked,
    };
  }

  function completeUpload(uploadId, encryptor, options, bundleMemberIds, isBundle) {
    // The passphrase itself is never sent - only the hash of a token
    // derived from it, plus the (non-secret) KDF parameters (SEC-001).
    return window.SDApi.post(`/api/uploads/${uploadId}/complete`, {
      ...options,
      download_token_hash: encryptor.tokenHash,
      passphrase_protected: encryptor.resumeState.mode === "passphrase",
      kdf_salt: encryptor.kdfSalt,
      kdf_iterations: encryptor.kdfIterations,
      is_bundle: !!isBundle,
      bundle_member_ids: bundleMemberIds || [],
    });
  }

  /** Encrypt + upload one Blob. Returns { fileId, urlKey }. */
  async function encryptAndUpload(blob, name, type, password, opts, onProgress, signal) {
    onProgress("encrypting", 0);
    const encryptor = await window.SDCrypto.createEncryptor(blob, name, type, password, { kind: opts.kind });
    const initRes = await window.SDApi.post("/api/uploads/init", {
      total_size_bytes: encryptor.size,
      extension: opts.kind ? null : (getExtension(name) || null),
    });
    const uploadId = initRes.upload_id;
    const options = opts.options || uploadOptions();
    const canResume = blob instanceof File || opts.kind === "text";
    if (canResume) {
      await savePending({
        uploadId, file: blob, name, type, size: blob.size, kind: opts.kind || null, chunkSize: initRes.chunk_size_bytes,
        resume: encryptor.resumeState, options, createdAt: Date.now(),
      });
    }
    try {
      onProgress("uploading", 0);
      await streamUpload(uploadId, encryptor, initRes.chunk_size_bytes, 0, (f) => onProgress("uploading", f), signal);
      const res = await completeUpload(uploadId, encryptor, options, opts.bundleMemberIds, opts.isBundle);
      await dropPending(uploadId);
      return { fileId: res.file_id, urlKey: encryptor.urlKey };
    } catch (e) {
      if (e.name === "AbortError") {
        try { await window.SDApi.del(`/api/uploads/${uploadId}`); } catch (err) { /* ignore */ }
        await dropPending(uploadId);
      } else if (canResume) {
        e.message = `${e.message || "Upload failed"} - you can resume it from this page.`;
        showResumableUploads();
      }
      throw e;
    }
  }

  function setSingleProgress(frac, label) {
    progressBar.style.width = `${Math.max(2, Math.round(frac * 100))}%`;
    progressBar.setAttribute("aria-valuenow", String(Math.round(frac * 100)));
    progressLabel.textContent = label;
  }

  async function confirmMetadataWarnings() {
    const risky = queue.filter((i) => i.strip && (i.strip.status === "unsupported" || i.strip.status === "failed"));
    const checking = queue.some((i) => i.strip && i.strip.status === "checking");
    if (checking) { showAlert("Still checking files for metadata - try again in a moment.", "info"); return false; }
    if (!risky.length) return true;
    const names = risky.slice(0, 5).map((i) => `• ${i.file.name}`).join("\n") + (risky.length > 5 ? `\n…and ${risky.length - 5} more` : "");
    // Fail closed (SEC-008): the user decides, explicitly.
    return window.confirm(
      `Metadata such as location or author could NOT be removed from:\n\n${names}\n\n` +
      "The recipient may be able to see it. Upload anyway?"
    );
  }

  uploadBtn.addEventListener("click", async () => {
    if (cfg.allow_secondary_password && cfg.enforce_secondary_password && !passwordInput.value) {
      showAlert("A secondary passphrase is required.");
      return;
    }
    const password = (cfg.allow_secondary_password && passwordInput.value) || null;
    activeAbort = new AbortController();
    const signal = activeAbort.signal;

    if (mode === "text") {
      const blob = new Blob([textInput.value], { type: "text/plain" });
      setBusy(true);
      progressWrap.style.display = "";
      try {
        const { fileId, urlKey } = await encryptAndUpload(blob, "message.txt", "text/plain", password, { kind: "text" },
          (st, f) => setSingleProgress(st === "encrypting" ? 0.05 : f, st === "encrypting" ? "Encrypting..." : "Uploading..."), signal);
        textInput.value = "";
        showResult(fileId, urlKey, "Message encrypted");
      } catch (e) {
        if (e.name !== "AbortError") showAlert(e.message || "Upload failed.");
      } finally {
        setBusy(false);
        progressWrap.style.display = "none";
      }
      return;
    }

    if (!queue.length) return;
    for (const item of queue) {
      if (item.file.size > cfg.max_file_size_mb * 1024 * 1024) return showAlert(`"${item.file.name}" exceeds the ${cfg.max_file_size_mb}MB limit.`);
      if (!validateExtension(item.file.name)) return showAlert(`"${item.file.name}" is not a permitted file type.`);
    }
    if (!(await confirmMetadataWarnings())) return;
    setBusy(true);

    if (queue.length === 1) {
      const item = queue[0];
      progressWrap.style.display = "";
      try {
        const { fileId, urlKey } = await encryptAndUpload(item.file, item.file.name, item.file.type || "application/octet-stream", password, {},
          (status, frac) => setSingleProgress(status === "encrypting" ? 0.05 : 0.08 + frac * 0.9,
            status === "encrypting" ? "Encrypting..." : `Uploading... ${Math.round(frac * 100)}%`), signal);
        setSingleProgress(1, "Done");
        queue = [];
        renderQueue();
        showResult(fileId, urlKey, "File uploaded");
      } catch (e) {
        if (e.name === "AbortError") showAlert("Upload cancelled.", "info");
        else showAlert(e.message || "Upload failed.");
      } finally {
        setBusy(false);
        progressWrap.style.display = "none";
        progressBar.style.width = "0%";
      }
      return;
    }

    // Batch: sequential, each file its own session. As a bundle, members get
    // random keys listed in an encrypted manifest that is the one shared link.
    const asBundle = bundleCheckbox.checked;
    const options = uploadOptions();
    const results = [];
    for (const item of queue) {
      if (signal.aborted) break;
      item.status = "encrypting";
      item.progress = 0;
      renderQueue();
      try {
        const { fileId, urlKey } = await encryptAndUpload(
          item.file, item.file.name, item.file.type || "application/octet-stream", asBundle ? null : password,
          { options: asBundle ? { ...options, notify_on_download: false } : options },
          (status, frac) => { item.status = status; item.progress = frac; updateRowProgress(item); }, signal);
        item.status = "done";
        results.push({ item, fileId, urlKey });
      } catch (e) {
        item.status = "error";
        item.error = e.name === "AbortError" ? "Cancelled" : (e.message || "Failed");
      }
      renderQueue();
    }

    try {
      if (asBundle && results.length && !signal.aborted) {
        const manifest = {
          files: results.map((r) => ({ id: r.fileId, key: r.urlKey, name: r.item.file.name, size: r.item.file.size, type: r.item.file.type })),
        };
        const blob = new Blob([JSON.stringify(manifest)], { type: "application/json" });
        progressWrap.style.display = "";
        const { fileId, urlKey } = await encryptAndUpload(blob, "bundle.json", "application/json", password,
          { kind: "bundle", isBundle: true, bundleMemberIds: results.map((r) => r.fileId), options },
          (st, f) => setSingleProgress(f, "Finishing bundle..."), signal);
        showResult(fileId, urlKey, `${results.length} files uploaded as one link`);
      } else if (results.length) {
        showBatchResults(results.map((r) => {
          const base = `${location.origin}/share/${r.fileId}`;
          return { name: r.item.file.name, link: r.urlKey ? `${base}#${r.urlKey}` : base };
        }));
      }
    } catch (e) {
      showAlert(e.message || "Couldn't create the bundle.");
    } finally {
      setBusy(false);
      progressWrap.style.display = "none";
    }
    const failedCount = queue.filter((i) => i.status === "error").length;
    if (failedCount > 0) showAlert(`${failedCount} file(s) failed to upload - see the list above.`);
    queue = queue.filter((item) => item.status === "error");
    renderQueue();
  });

  // ---- results ----------------------------------------------------------------
  function showResult(fileId, urlKey, title) {
    const base = `${location.origin}/share/${fileId}`;
    const link = urlKey ? `${base}#${urlKey}` : base;
    resultTitle.textContent = title || "File uploaded";
    resultLink.value = link;
    resultKeyGroup.style.display = urlKey ? "" : "none";
    resultKey.value = urlKey || "";
    resultModal.hidden = false;
    resultLink.focus();
    resultLink.select();
    if (window.SDQRCode) {
      try { window.SDQRCode.renderToCanvas($("qrCanvas"), link); } catch (e) { /* QR is a convenience */ }
    }
    setUpShareSection(fileId, urlKey);
  }

  function showBatchResults(results) {
    batchResultsBody.innerHTML = "";
    for (const r of results) {
      const row = document.createElement("tr");
      const nameCell = document.createElement("td");
      nameCell.textContent = r.name;
      const linkCell = document.createElement("td");
      const code = document.createElement("code");
      code.textContent = r.link;
      code.style.wordBreak = "break-all";
      linkCell.appendChild(code);
      const actionCell = document.createElement("td");
      const copyBtn = document.createElement("button");
      copyBtn.className = "btn btn-outline btn-sm";
      copyBtn.type = "button";
      copyBtn.textContent = "Copy";
      copyBtn.addEventListener("click", () => window.SDUtil.copyText(r.link, copyBtn));
      actionCell.appendChild(copyBtn);
      row.append(nameCell, linkCell, actionCell);
      batchResultsBody.appendChild(row);
    }
    batchResultModal.hidden = false;
  }

  function addPickerUser(u, checked) {
    if (userPickerList.querySelector(`input[value="${CSS.escape(u.id)}"]`)) return;
    const row = document.createElement("div");
    row.className = "user-picker-row";
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = u.id;
    checkbox.checked = !!checked;
    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(" " + u.username));
    row.appendChild(label);
    userPickerList.appendChild(row);
    userPickerList.hidden = false;
  }

  async function setUpShareSection(fileId, urlKey) {
    shareStatus.textContent = "";
    shareWithUsersSection.style.display = "none";
    userPickerList.innerHTML = "";
    // An empty bordered list looks broken - hide it until someone is in it
    // (people who opted into the directory, or added by exact username).
    userPickerList.hidden = true;
    if (!urlKey || !cfg.enable_user_sharing || !window.SDApi.isLoggedIn()) return;
    try {
      // Only users who chose to be discoverable are listed (SEC-020);
      // anyone else can be added by exact username below.
      (await window.SDApi.get("/api/users/list")).forEach((u) => addPickerUser(u, false));
    } catch (e) {
      return; // sharing disabled server-side
    }
    shareWithUsersSection.style.display = "";

    shareLookupBtn.onclick = async () => {
      const username = shareLookupInput.value.trim();
      if (!username) return;
      try {
        const u = await window.SDApi.get(`/api/users/lookup?username=${encodeURIComponent(username)}`);
        addPickerUser(u, true);
        shareLookupInput.value = "";
      } catch (e) {
        shareStatus.textContent = e.status === 404 ? `No user named "${username}".` : e.message;
      }
    };
    shareWithUsersBtn.onclick = async () => {
      const selected = Array.from(userPickerList.querySelectorAll("input:checked")).map((el) => el.value);
      if (!selected.length) { shareStatus.textContent = "Select at least one user."; return; }
      shareWithUsersBtn.disabled = true;
      try {
        // Recipients with encryption keys get the file key wrapped to their
        // own public key - end-to-end, the server can't open it (FEAT-002).
        const recipients = [];
        const withoutKeys = [];
        const secret = window.SDCrypto.b64urlDecode(urlKey);
        for (const id of selected) {
          try {
            const pk = await window.SDApi.get(`/api/users/${encodeURIComponent(id)}/public-key`);
            recipients.push({ user_id: id, ...(await window.SDKeys.wrapSecret(secret, pk.public_key)) });
          } catch (e) {
            if (e.status !== 404) throw e;
            withoutKeys.push(id);
          }
        }
        if (withoutKeys.length && !cfg.allow_server_held_share_keys) {
          throw new Error(`${withoutKeys.length} recipient(s) haven't set up encryption keys yet, so they can't receive files.`);
        }
        if (withoutKeys.length && !confirm(`${withoutKeys.length} recipient(s) haven't set up encryption keys. For them, this server will hold the file's key (not end-to-end). Continue?`)) return;
        const res = await window.SDApi.post(`/api/files/${fileId}/share`,
          { recipients, user_ids: withoutKeys, key: withoutKeys.length ? urlKey : null });
        shareStatus.textContent = `Shared with: ${res.shared_with.join(", ")}` + (withoutKeys.length ? "" : " (end-to-end)");
      } catch (e) {
        shareStatus.textContent = e.message || "Sharing failed.";
      } finally {
        shareWithUsersBtn.disabled = false;
      }
    };
  }

  $("copyLinkBtn").addEventListener("click", (e) => window.SDUtil.copyText(resultLink.value, e.currentTarget, resultLink));
  $("copyKeyBtn").addEventListener("click", (e) => window.SDUtil.copyText(resultKey.value, e.currentTarget, resultKey));
  $("uploadAnotherBtn").addEventListener("click", () => {
    resultModal.hidden = true;
    passwordInput.value = "";
    shareWithUsersSection.style.display = "none";
  });
  $("closeModalXBtn").addEventListener("click", () => { resultModal.hidden = true; });
  $("batchUploadAnotherBtn").addEventListener("click", () => { batchResultModal.hidden = true; passwordInput.value = ""; });
  $("closeBatchModalXBtn").addEventListener("click", () => { batchResultModal.hidden = true; });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { resultModal.hidden = true; batchResultModal.hidden = true; }
  });

  loadConfig().catch((e) => showAlert("Failed to load server configuration: " + e.message));
})();
