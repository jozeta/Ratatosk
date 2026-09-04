(function () {
  if (!window.SDApi.isAdmin()) {
    window.location.href = "/login";
    return;
  }

  const tbody = document.getElementById("auditTableBody");
  const resultCount = document.getElementById("resultCount");
  const pageLabel = document.getElementById("pageLabel");
  const PAGE_SIZE = 50;
  let page = 1;

  function showAlert(message, type = "danger") {
    window.SDToast.show(message, type);
  }

  function currentFilters() {
    const params = new URLSearchParams();
    const eventType = document.getElementById("filterEventType").value;
    const fileId = document.getElementById("filterFileId").value.trim();
    const search = document.getElementById("filterSearch").value.trim();
    if (eventType) params.set("event_type", eventType);
    if (fileId) params.set("file_id", fileId);
    if (search) params.set("search", search);
    return params;
  }

  function td(text) {
    const cell = document.createElement("td");
    cell.textContent = text == null ? "" : text;
    return cell;
  }

  async function load() {
    const params = currentFilters();
    params.set("page", page);
    params.set("page_size", PAGE_SIZE);
    try {
      const data = await window.SDApi.get(`/api/admin/audit?${params.toString()}`);
      tbody.innerHTML = "";
      for (const item of data.items) {
        const row = document.createElement("tr");
        row.appendChild(td(new Date(item.timestamp).toLocaleString()));
        row.appendChild(td(item.event_type));
        row.appendChild(td(item.file_id ? item.file_id.slice(0, 8) + "…" : ""));
        row.appendChild(td(item.user_id ? item.user_id.slice(0, 8) + "…" : (item.actor_token || "")));
        row.appendChild(td(item.ip_address || "—"));
        row.appendChild(td(item.user_agent ? item.user_agent.slice(0, 40) : "—"));
        row.appendChild(td(item.detail || ""));
        tbody.appendChild(row);
      }
      resultCount.textContent = `${data.total} total events`;
      const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
      pageLabel.textContent = `Page ${page} of ${totalPages}`;
    } catch (e) {
      showAlert(e.message);
    }
  }

  document.getElementById("applyFiltersBtn").addEventListener("click", () => { page = 1; load(); });
  document.getElementById("prevPageBtn").addEventListener("click", () => { if (page > 1) { page--; load(); } });
  document.getElementById("nextPageBtn").addEventListener("click", () => { page++; load(); });

  window.SDApi.get("/api/admin/settings").then((cfg) => {
    document.getElementById("auditDisabledNotice").hidden = !cfg.disable_audit_log;
  }).catch(() => {});

  async function exportLogs(format) {
    const params = currentFilters();
    params.set("format", format);
    const res = await fetch(`/api/admin/audit/export?${params.toString()}`, {
      headers: { Authorization: "Bearer " + window.SDApi.getToken() },
    });
    if (!res.ok) { showAlert("Export failed"); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit_log.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
  document.getElementById("exportCsvBtn").addEventListener("click", () => exportLogs("csv"));
  document.getElementById("exportJsonBtn").addEventListener("click", () => exportLogs("json"));

  document.getElementById("pruneBtn").addEventListener("click", async () => {
    const days = document.getElementById("pruneDays").value;
    if (!confirm(`Permanently delete audit entries older than ${days} days?`)) return;
    try {
      const res = await window.SDApi.post(`/api/admin/audit/prune?days=${days}`);
      showAlert(`Pruned ${res.deleted} entries.`, "success");
      load();
    } catch (e) {
      showAlert(e.message);
    }
  });

  load();
})();
