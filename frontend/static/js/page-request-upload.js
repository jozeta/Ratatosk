// Sender side of an upload request link (FEAT-001). No account needed.
(function () {
  const $ = (id) => document.getElementById(id);
  const requestId = location.pathname.split("/").filter(Boolean).pop();
  const expectedFingerprint = (location.hash || "").slice(1).toLowerCase();
  let req = null;

  function li(text, cls) {
    const item = document.createElement("li");
    item.className = "file-queue-item";
    const name = document.createElement("span");
    name.className = "file-queue-name";
    name.textContent = text;
    const status = document.createElement("span");
    status.className = `file-queue-status ${cls || ""}`;
    item.append(name, status);
    $("sentList").appendChild(item);
    return status;
  }

  function closed(message) {
    $("reqClosed").hidden = false;
    $("reqClosed").textContent = message;
    $("sendPanel").hidden = true;
  }

  async function init() {
    try {
      req = await window.SDApi.get(`/api/requests/${encodeURIComponent(requestId)}/public`);
    } catch (e) {
      $("reqInfo").textContent = "This request link doesn't exist.";
      return;
    }
    // The link's #fragment carries the owner's key fingerprint. If the key
    // the server gave us doesn't match, the server (or someone in between)
    // swapped it - refuse to encrypt anything to it.
    const actual = await window.SDKeys.fingerprint(req.public_key);
    if (!expectedFingerprint || actual !== expectedFingerprint || actual !== req.fingerprint) {
      $("reqInfo").textContent = "";
      closed(expectedFingerprint
        ? "Security check failed: the encryption key for this link doesn't match the link itself. Nothing was sent. Ask the person who sent you the link for a new one."
        : "This link is incomplete (the part after # is missing). Ask the person who sent it for the complete link.");
      return;
    }
    $("reqInfo").textContent = `Open until ${new Date(req.expires_at).toLocaleString()}` +
      (req.uploads_left != null ? ` · ${req.uploads_left} file(s) left` : "");
    if (req.label) { $("reqLabel").hidden = false; $("reqLabel").textContent = `For: ${req.label}`; }
    if (!req.open) return closed("This request link is closed - it expired, was closed by its owner, or is full.");
    $("maxSizeHint").textContent = `Max ${req.max_file_size_mb} MB per file`;
    $("sendPanel").hidden = false;
  }

  async function sendOne(file) {
    const status = li(file.name);
    if (file.size > req.max_file_size_mb * 1024 * 1024) { status.textContent = "too large"; status.classList.add("status-error"); return; }
    try {
      status.textContent = "Removing metadata…";
      const stripped = await window.SDExif.stripImageMetadata(file);
      if ((stripped.status === "unsupported" || stripped.status === "failed") &&
          !confirm(`Metadata such as location or author could NOT be removed from "${file.name}". Send it anyway?`)) {
        status.textContent = "skipped";
        return;
      }
      status.textContent = "Encrypting…";
      const enc = await window.SDCrypto.createEncryptor(stripped.file, file.name, file.type || "application/octet-stream", null);
      // Wrap this file's secret to the request owner's public key: only
      // their private key can unwrap it.
      const wrapped = await window.SDKeys.wrapSecret(window.SDCrypto.b64urlDecode(enc.urlKey), req.public_key);
      const init = await window.SDApi.post("/api/uploads/init", {
        total_size_bytes: enc.size, extension: (file.name.split(".").pop() || "").toLowerCase() || null, request_id: requestId,
      });
      await window.SDUploadEngine.streamUpload(init.upload_id, enc, init.chunk_size_bytes, 0,
        (f) => { status.textContent = `Sending ${Math.round(f * 100)}%`; });
      await window.SDApi.post(`/api/uploads/${init.upload_id}/complete`, {
        ttl: "1h", download_token_hash: enc.tokenHash, ...wrapped,
      });
      status.textContent = "Sent ✓";
      status.classList.add("status-done");
    } catch (e) {
      status.textContent = e.message || "Failed";
      status.classList.add("status-error");
      if (e.status === 410) closed("This request link just closed - it's full or expired.");
    }
  }

  async function sendAll(files) {
    for (const f of Array.from(files)) await sendOne(f);
  }

  const dropzone = $("dropzone");
  const input = $("fileInput");
  dropzone.addEventListener("click", () => input.click());
  dropzone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => { e.preventDefault(); dropzone.classList.remove("dragover"); sendAll(e.dataTransfer.files); });
  input.addEventListener("change", () => { sendAll(input.files); input.value = ""; });

  init();
})();
