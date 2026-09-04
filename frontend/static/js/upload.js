(function () {
  let cfg = null;
  let queue = []; // { id, file, status: pending|encrypting|uploading|done|error, progress, link, key, error }

  const dropzone = document.getElementById("dropzone");
  const dropzoneText = document.getElementById("dropzoneText");
  const fileInput = document.getElementById("fileInput");
  const folderInput = document.getElementById("folderInput");
  const folderPickerRow = document.getElementById("folderPickerRow");
  const folderPickerLink = document.getElementById("folderPickerLink");
  const fileQueueEl = document.getElementById("fileQueue");
  const uploadBtn = document.getElementById("uploadBtn");
  const ttlMaxDownloadsRow = document.getElementById("ttlMaxDownloadsRow");
  const ttlGroup = document.getElementById("ttlGroup");
  const ttlSelect = document.getElementById("ttlSelect");
  const maxDownloadsGroup = document.getElementById("maxDownloadsGroup");
  const maxDownloadsInput = document.getElementById("maxDownloads");
  const burnRow = document.getElementById("burnRow");
  const burnCheckbox = document.getElementById("burnAfterDownload");
  const notifyRow = document.getElementById("notifyRow");
  const notifyCheckbox = document.getElementById("notifyOnDownload");
  const passwordGroup = document.getElementById("passwordGroup");
  const passwordInput = document.getElementById("secondaryPassword");
  const passwordOptionalLabel = document.getElementById("passwordOptionalLabel");
  const progressWrap = document.getElementById("progressWrap");
  const progressBar = document.getElementById("progressBar");
  const progressLabel = document.getElementById("progressLabel");
  const maxSizeHint = document.getElementById("maxSizeHint");

  const resultModal = document.getElementById("resultModal");
  const resultLink = document.getElementById("resultLink");
  const resultKeyGroup = document.getElementById("resultKeyGroup");
  const resultKey = document.getElementById("resultKey");
  const shareWithUsersSection = document.getElementById("shareWithUsersSection");
  const userPickerList = document.getElementById("userPickerList");
  const shareWithUsersBtn = document.getElementById("shareWithUsersBtn");
  const shareStatus = document.getElementById("shareStatus");

  const batchResultModal = document.getElementById("batchResultModal");
  const batchResultsBody = document.getElementById("batchResultsBody");

  function showAlert(message, type = "danger") {
    window.SDToast.show(message, type);
  }

  function humanSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    const units = ["KB", "MB", "GB"];
    let val = bytes;
    for (const u of units) {
      val /= 1024;
      if (val < 1024) return val.toFixed(1) + " " + u;
    }
    return val.toFixed(1) + " TB";
  }

  const TTL_LABELS = { m: "minute(s)", h: "hour(s)", d: "day(s)" };
  function ttlLabel(code) {
    const amount = code.slice(0, -1);
    const unit = code.slice(-1);
    return `${amount} ${TTL_LABELS[unit] || unit}`;
  }

  async function loadConfig() {
    cfg = await window.SDApi.get("/api/config");

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

    if (!cfg.allow_anonymous_upload && !window.SDApi.isLoggedIn()) {
      window.location.href = "/login";
      return;
    }
  }

  // ---- File queue management ----
  let nextId = 1;

  function addFiles(files) {
    const list = Array.from(files);
    if (!list.length) return;
    if (!cfg.enable_multi_file_upload) {
      queue = [{ id: nextId++, file: list[0], status: "pending", progress: 0 }];
    } else {
      for (const file of list) {
        queue.push({ id: nextId++, file, status: "pending", progress: 0 });
      }
    }
    renderQueue();
  }

  function removeFromQueue(id) {
    queue = queue.filter((item) => item.id !== id);
    renderQueue();
  }

  function renderQueue() {
    fileQueueEl.innerHTML = "";
    fileQueueEl.style.display = queue.length ? "" : "none";
    uploadBtn.disabled = queue.length === 0;
    uploadBtn.textContent = queue.length > 1 ? `Encrypt & Upload ${queue.length} files` : "Encrypt & Upload";

    if (!queue.length) return;

    const list = document.createElement("div");
    list.className = "file-queue";
    for (const item of queue) {
      const row = document.createElement("div");
      row.className = "file-queue-item";

      const name = document.createElement("span");
      name.className = "file-queue-name";
      name.textContent = item.file.name;
      name.title = item.file.name;

      const size = document.createElement("span");
      size.className = "file-queue-size";
      size.textContent = humanSize(item.file.size);

      row.appendChild(name);
      row.appendChild(size);

      if (item.status === "pending") {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "file-queue-remove";
        remove.textContent = "×";
        remove.title = "Remove";
        remove.addEventListener("click", () => removeFromQueue(item.id));
        row.appendChild(remove);
      } else if (item.status === "encrypting" || item.status === "uploading") {
        const bar = document.createElement("div");
        bar.className = "file-queue-mini-bar";
        const fill = document.createElement("div");
        fill.className = "file-queue-mini-bar-fill";
        fill.style.width = `${Math.round(item.progress * 100)}%`;
        bar.appendChild(fill);
        row.appendChild(bar);
        const status = document.createElement("span");
        status.className = "file-queue-status";
        status.textContent = item.status === "encrypting" ? "Encrypting…" : `${Math.round(item.progress * 100)}%`;
        row.appendChild(status);
      } else if (item.status === "done") {
        const status = document.createElement("span");
        status.className = "file-queue-status status-done";
        status.textContent = "Done";
        row.appendChild(status);
      } else if (item.status === "error") {
        const status = document.createElement("span");
        status.className = "file-queue-status status-error";
        status.textContent = item.error || "Failed";
        row.appendChild(status);
      }

      list.appendChild(row);
    }
    fileQueueEl.appendChild(list);
  }

  // ---- Drag & drop, including folders ----
  async function collectFilesFromDataTransfer(dataTransfer) {
    const items = dataTransfer.items;
    if (!items || !items.length || !items[0].webkitGetAsEntry) {
      return Array.from(dataTransfer.files || []);
    }
    const entries = Array.from(items).map((i) => i.webkitGetAsEntry()).filter(Boolean);
    const files = [];
    async function walk(entry) {
      if (entry.isFile) {
        await new Promise((resolve) => entry.file((f) => { files.push(f); resolve(); }));
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        const entriesInDir = await new Promise((resolve) => {
          const all = [];
          function readBatch() {
            reader.readEntries((batch) => {
              if (!batch.length) { resolve(all); return; }
              all.push(...batch);
              readBatch();
            });
          }
          readBatch();
        });
        for (const child of entriesInDir) await walk(child);
      }
    }
    for (const entry of entries) await walk(entry);
    return files;
  }

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", async (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    const files = await collectFilesFromDataTransfer(e.dataTransfer);
    if (files.length) addFiles(files);
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) addFiles(fileInput.files);
    fileInput.value = "";
  });
  folderPickerLink.addEventListener("click", (e) => {
    e.preventDefault();
    folderInput.click();
  });
  folderInput.addEventListener("change", () => {
    if (folderInput.files.length) addFiles(folderInput.files);
    folderInput.value = "";
  });

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

  async function uploadInChunks(uploadId, blob, chunkSize, onProgress) {
    let offset = 0;
    const total = blob.size;
    while (offset < total) {
      const chunk = blob.slice(offset, offset + chunkSize);
      await window.SDApi.raw(`/api/uploads/${uploadId}/chunk`, {
        method: "PUT",
        headers: { "Content-Type": "application/octet-stream" },
        body: chunk,
      });
      offset += chunk.size;
      onProgress(Math.min(offset / total, 1));
    }
  }

  // Encrypts and uploads a single File, driving the given item's status via onProgress.
  async function encryptAndUploadOne(file, password, onProgress) {
    onProgress("encrypting", 0);
    const strippedFile = file.type.startsWith("image/")
      ? await window.SDExif.stripImageMetadata(file)
      : file;
    const fileBytes = await strippedFile.arrayBuffer();
    const { blob: encryptedBlob, urlKey } = await window.SDCrypto.encryptForUpload(
      fileBytes, file.name, file.type || "application/octet-stream", password
    );

    const ext = getExtension(file.name);
    const initRes = await window.SDApi.post("/api/uploads/init", {
      total_size_bytes: encryptedBlob.size,
      extension: ext || null,
    });

    onProgress("uploading", 0);
    await uploadInChunks(initRes.upload_id, encryptedBlob, initRes.chunk_size_bytes, (frac) => {
      onProgress("uploading", frac);
    });

    const completeRes = await window.SDApi.post(`/api/uploads/${initRes.upload_id}/complete`, {
      ttl: cfg.allow_custom_ttl ? ttlSelect.value : cfg.default_ttl,
      burn_after_download: burnCheckbox.checked,
      max_downloads: cfg.allow_custom_max_downloads ? (parseInt(maxDownloadsInput.value, 10) || 0) : 0,
      password: password,
      notify_on_download: notifyRow.style.display !== "none" && notifyCheckbox.checked,
    });

    return { fileId: completeRes.file_id, urlKey };
  }

  uploadBtn.addEventListener("click", async () => {
    if (!queue.length) return;

    for (const item of queue) {
      if (item.file.size > cfg.max_file_size_mb * 1024 * 1024) {
        showAlert(`"${item.file.name}" exceeds the ${cfg.max_file_size_mb}MB limit.`);
        return;
      }
      if (!validateExtension(item.file.name)) {
        showAlert(`"${item.file.name}" is not a permitted file type.`);
        return;
      }
    }
    if (cfg.allow_secondary_password && cfg.enforce_secondary_password && !passwordInput.value) {
      showAlert("A secondary passphrase is required.");
      return;
    }

    uploadBtn.disabled = true;
    const password = (cfg.allow_secondary_password && passwordInput.value) || null;

    if (queue.length === 1) {
      // Single file: keep the rich single-result experience (QR, share-with-users).
      const item = queue[0];
      progressWrap.style.display = "";
      try {
        const { fileId, urlKey } = await encryptAndUploadOne(item.file, password, (status, frac) => {
          item.status = status;
          item.progress = frac;
          const pct = status === "encrypting" ? 8 : 10 + frac * 88;
          progressBar.style.width = pct + "%";
          progressLabel.textContent = status === "encrypting" ? "Encrypting..." : `Uploading... ${Math.round(frac * 100)}%`;
        });
        progressBar.style.width = "100%";
        showResult(fileId, urlKey);
        queue = [];
        renderQueue();
      } catch (e) {
        showAlert(e.message || "Upload failed.");
      } finally {
        uploadBtn.disabled = false;
        progressWrap.style.display = "none";
        progressBar.style.width = "0%";
      }
      return;
    }

    // Batch: upload sequentially, respecting the server's concurrent-upload limit implicitly.
    const results = [];
    for (const item of queue) {
      item.status = "encrypting";
      item.progress = 0;
      renderQueue();
      try {
        const { fileId, urlKey } = await encryptAndUploadOne(item.file, password, (status, frac) => {
          item.status = status;
          item.progress = frac;
          renderQueue();
        });
        item.status = "done";
        const base = `${location.origin}/share/${fileId}`;
        results.push({ name: item.file.name, link: urlKey ? `${base}#${urlKey}` : base });
      } catch (e) {
        item.status = "error";
        item.error = e.message || "Failed";
      }
      renderQueue();
    }

    uploadBtn.disabled = false;
    if (results.length) showBatchResults(results);
    const failedCount = queue.length - results.length;
    if (failedCount > 0) showAlert(`${failedCount} file(s) failed to upload - see the list above.`);
    queue = queue.filter((item) => item.status === "error");
    renderQueue();
  });

  function showResult(fileId, urlKey) {
    const base = `${location.origin}/share/${fileId}`;
    const link = urlKey ? `${base}#${urlKey}` : base;
    resultLink.value = link;
    if (urlKey) {
      resultKeyGroup.style.display = "";
      resultKey.value = urlKey;
    } else {
      resultKeyGroup.style.display = "none";
    }
    resultModal.hidden = false;

    if (window.SDQRCode) {
      const canvas = document.getElementById("qrCanvas");
      try { window.SDQRCode.renderToCanvas(canvas, link); } catch (e) { /* QR is a convenience, non-fatal */ }
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
      copyBtn.textContent = "Copy";
      copyBtn.addEventListener("click", () => navigator.clipboard.writeText(r.link));
      actionCell.appendChild(copyBtn);
      row.appendChild(nameCell);
      row.appendChild(linkCell);
      row.appendChild(actionCell);
      batchResultsBody.appendChild(row);
    }
    batchResultModal.hidden = false;
  }

  async function setUpShareSection(fileId, urlKey) {
    shareStatus.textContent = "";
    shareWithUsersSection.style.display = "none";
    if (!urlKey || !cfg.enable_user_sharing || !window.SDApi.isLoggedIn()) return;

    let users;
    try {
      users = await window.SDApi.get("/api/users/list");
    } catch (e) {
      return; // feature disabled server-side, or nothing to show - fail quietly here
    }
    if (!users.length) return;

    userPickerList.innerHTML = "";
    for (const u of users) {
      const row = document.createElement("div");
      row.className = "user-picker-row";
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = u.id;
      label.appendChild(checkbox);
      label.appendChild(document.createTextNode(u.username));
      row.appendChild(label);
      userPickerList.appendChild(row);
    }
    shareWithUsersSection.style.display = "";

    shareWithUsersBtn.onclick = async () => {
      const selected = Array.from(userPickerList.querySelectorAll("input:checked")).map((el) => el.value);
      if (!selected.length) {
        shareStatus.textContent = "Select at least one user.";
        return;
      }
      shareWithUsersBtn.disabled = true;
      try {
        const res = await window.SDApi.post(`/api/files/${fileId}/share`, { user_ids: selected, key: urlKey });
        shareStatus.textContent = `Shared with: ${res.shared_with.join(", ")}`;
      } catch (e) {
        shareStatus.textContent = e.message || "Sharing failed.";
      } finally {
        shareWithUsersBtn.disabled = false;
      }
    };
  }

  document.getElementById("copyLinkBtn").addEventListener("click", () => {
    navigator.clipboard.writeText(resultLink.value);
  });
  document.getElementById("copyKeyBtn").addEventListener("click", () => {
    navigator.clipboard.writeText(resultKey.value);
  });
  document.getElementById("uploadAnotherBtn").addEventListener("click", () => {
    resultModal.hidden = true;
    passwordInput.value = "";
    shareWithUsersSection.style.display = "none";
  });
  document.getElementById("closeModalXBtn").addEventListener("click", () => {
    resultModal.hidden = true;
  });
  document.getElementById("batchUploadAnotherBtn").addEventListener("click", () => {
    batchResultModal.hidden = true;
    passwordInput.value = "";
  });
  document.getElementById("closeBatchModalXBtn").addEventListener("click", () => {
    batchResultModal.hidden = true;
  });

  loadConfig().catch((e) => showAlert("Failed to load server configuration: " + e.message));
})();
