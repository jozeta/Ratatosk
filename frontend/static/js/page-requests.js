// Owner side of upload request links (FEAT-001).
(function () {
  if (!window.SDApi.isLoggedIn()) { window.location.href = "/login"; return; }
  const $ = (id) => document.getElementById(id);
  const h = window.SDKeysUI.h;
  const humanSize = (b) => window.SDUtil.humanSize(b);
  const when = (iso) => new Date(iso).toLocaleString();
  let cfg = null;

  function linkFor(r) {
    // The fingerprint in the #fragment lets the sender's browser check that
    // the key the server hands out really is yours.
    return `${location.origin}/r/${r.id}#${r.fingerprint}`;
  }

  async function openInbox(r) {
    $("inboxCard").hidden = false;
    $("inboxTitle").textContent = `Received: ${r.label || "(no description)"}`;
    const body = $("inboxBody");
    body.replaceChildren();
    const files = await window.SDApi.get(`/api/requests/${r.id}/files`);
    $("inboxEmpty").hidden = files.length > 0;
    for (const f of files) {
      const btn = h("button", { type: "button", className: "btn btn-primary btn-sm" }, "Decrypt & download");
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          const key = await window.SDKeysUI.openSecret(f.wrapped_key, f.ephemeral_public_key);
          const result = await window.SDDownload.fetchAndDecrypt(f.file_id, null, key, {
            onProgress: (p) => { btn.textContent = `Downloading ${Math.round(p * 100)}%`; },
          });
          window.SDDownload.saveDecrypted(result);
          btn.textContent = `Saved "${result.name}"`;
        } catch (e) {
          window.SDToast.danger(e.message);
          btn.textContent = "Decrypt & download";
        } finally {
          btn.disabled = false;
        }
      });
      body.appendChild(h("tr", {}, h("td", {}, when(f.created_at)), h("td", {}, humanSize(f.size_bytes)),
        h("td", {}, when(f.expires_at)), h("td", {}, btn)));
    }
    $("inboxCard").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function actionBtn(label, cls, fn) {
    const b = h("button", { type: "button", className: `btn ${cls} btn-sm` }, label);
    b.addEventListener("click", async () => { b.disabled = true; try { await fn(b); } catch (e) { window.SDToast.danger(e.message); } finally { b.disabled = false; } });
    return b;
  }

  async function load() {
    const rows = await window.SDApi.get("/api/requests");
    $("listCard").hidden = false;
    $("emptyState").hidden = rows.length > 0;
    const body = $("requestsBody");
    body.replaceChildren();
    for (const r of rows) {
      const actions = h("td", { className: "row-actions" },
        actionBtn("Copy link", "btn-outline", (b) => window.SDUtil.copyText(linkFor(r), b)),
        actionBtn("Received files", "btn-outline", () => openInbox(r)),
        r.open ? actionBtn("Close", "btn-outline", async () => { await window.SDApi.post(`/api/requests/${r.id}/close`, {}); load(); }) : null,
        actionBtn("Delete", "btn-danger", async () => {
          if (!confirm("Delete this link and every file received through it?")) return;
          await window.SDApi.del(`/api/requests/${r.id}`);
          $("inboxCard").hidden = true;
          load();
        }));
      body.appendChild(h("tr", {},
        h("td", {}, r.label || "(no description)"),
        h("td", {}, when(r.expires_at)),
        h("td", {}, `${r.upload_count}${r.max_uploads ? " / " + r.max_uploads : ""}`),
        h("td", {}, h("span", { className: `badge ${r.open ? "badge-ok" : "badge-muted"}` }, r.open ? "open" : "closed")),
        actions));
    }
  }

  $("createForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await window.SDApi.post("/api/requests", {
        label: $("reqLabel").value,
        expires_in: $("reqExpires").value,
        max_uploads: parseInt($("reqMaxUploads").value, 10) || 0,
        max_file_size_mb: parseInt($("reqMaxSize").value, 10) || null,
        file_ttl: $("reqRetention").value,
      });
      await window.SDUtil.copyText(linkFor(r));
      window.SDToast.show("Request link created and copied. Send it to whoever should send you files.", "success");
      $("reqLabel").value = "";
      load();
    } catch (err) {
      window.SDToast.danger(err.message);
    }
  });

  (async () => {
    cfg = await window.SDApi.config();
    if (!cfg.enable_upload_requests) {
      $("noKeysNotice").hidden = false;
      $("noKeysNotice").textContent = "Request links are disabled on this site.";
      return;
    }
    const retention = $("reqRetention");
    for (const code of cfg.allowed_ttl_presets.split(",").map((s) => s.trim()).filter(Boolean)) {
      retention.appendChild(h("option", { value: code, selected: code === cfg.default_ttl }, code));
    }
    $("reqMaxSize").value = cfg.max_file_size_mb;
    $("reqMaxSize").max = cfg.max_file_size_mb;
    try {
      await window.SDKeysUI.myMaterial(true);
      $("createForm").hidden = false;
    } catch (e) {
      $("noKeysNotice").hidden = false;
    }
    load().catch((e) => window.SDToast.danger(e.message));
  })();
})();
