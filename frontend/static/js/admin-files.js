(function () {
  if (!window.SDApi.isAdmin()) {
    window.location.href = "/login";
    return;
  }

  const disabledNotice = document.getElementById("disabledNotice");
  const content = document.getElementById("content");
  const tbody = document.getElementById("filesTableBody");
  const pageLabel = document.getElementById("pageLabel");
  const selectAllCheckbox = document.getElementById("selectAllCheckbox");
  const batchDeleteBtn = document.getElementById("batchDeleteBtn");
  const PAGE_SIZE = 50;
  let page = 1;
  let selected = new Set();
  let currentItems = [];

  function updateBatchDeleteBtn() {
    batchDeleteBtn.hidden = selected.size === 0;
    batchDeleteBtn.textContent = `Delete selected (${selected.size})`;
  }

  function showAlert(message, type = "danger") {
    window.SDToast.show(message, type);
  }

  function td(text) {
    const cell = document.createElement("td");
    cell.textContent = text == null ? "" : text;
    return cell;
  }

  function humanSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    const units = ["KB", "MB", "GB"];
    let val = bytes;
    for (const u of units) { val /= 1024; if (val < 1024) return val.toFixed(1) + " " + u; }
    return val.toFixed(1) + " TB";
  }

  async function load() {
    let data;
    try {
      data = await window.SDApi.get(`/api/admin/files?page=${page}&page_size=${PAGE_SIZE}`);
    } catch (e) {
      if (e.status === 403) {
        disabledNotice.style.display = "";
        content.style.display = "none";
        return;
      }
      showAlert(e.message);
      return;
    }
    disabledNotice.style.display = "none";
    content.style.display = "";

    selected = new Set();
    currentItems = data.items;
    selectAllCheckbox.checked = false;
    updateBatchDeleteBtn();

    tbody.innerHTML = "";
    for (const f of data.items) {
      const row = document.createElement("tr");

      const selectCell = document.createElement("td");
      selectCell.className = "checkbox-cell";
      const selectBox = document.createElement("input");
      selectBox.type = "checkbox";
      selectBox.addEventListener("change", () => {
        if (selectBox.checked) selected.add(f.file_id);
        else selected.delete(f.file_id);
        selectAllCheckbox.checked = selected.size === data.items.length;
        updateBatchDeleteBtn();
      });
      selectCell.appendChild(selectBox);
      row.appendChild(selectCell);

      const idCell = document.createElement("td");
      const code = document.createElement("code");
      code.textContent = f.file_id.slice(0, 8) + "…";
      code.title = f.file_id;
      idCell.appendChild(code);
      row.appendChild(idCell);

      row.appendChild(td(f.owner));
      row.appendChild(td(humanSize(f.size_bytes)));
      row.appendChild(td(new Date(f.created_at).toLocaleString()));

      const expiresCell = td(f.expired ? "expired" : new Date(f.expires_at).toLocaleString());
      row.appendChild(expiresCell);

      row.appendChild(td(`${f.download_count}${f.max_downloads ? "/" + f.max_downloads : ""}${f.burn_after_download ? " (burn)" : ""}`));
      row.appendChild(td(f.password_protected ? "yes" : "no"));

      const actionCell = document.createElement("td");
      const delBtn = document.createElement("button");
      delBtn.className = "btn btn-danger btn-sm";
      delBtn.textContent = "Delete";
      delBtn.addEventListener("click", async () => {
        if (!confirm("Delete this file permanently?")) return;
        try {
          await window.SDApi.del(`/api/admin/files/${f.file_id}`);
          load();
        } catch (err) { showAlert(err.message); }
      });
      actionCell.appendChild(delBtn);
      row.appendChild(actionCell);

      tbody.appendChild(row);
    }

    const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
    pageLabel.textContent = `Page ${page} of ${totalPages} (${data.total} files)`;
  }

  document.getElementById("prevPageBtn").addEventListener("click", () => { if (page > 1) { page--; load(); } });
  document.getElementById("nextPageBtn").addEventListener("click", () => { page++; load(); });

  selectAllCheckbox.addEventListener("change", () => {
    selected = new Set();
    if (selectAllCheckbox.checked) {
      tbody.querySelectorAll('input[type="checkbox"]').forEach((cb) => { cb.checked = true; });
      for (const f of currentItems) selected.add(f.file_id);
    } else {
      tbody.querySelectorAll('input[type="checkbox"]').forEach((cb) => { cb.checked = false; });
    }
    updateBatchDeleteBtn();
  });

  batchDeleteBtn.addEventListener("click", async () => {
    if (selected.size === 0) return;
    if (!confirm(`Delete ${selected.size} file(s) permanently?`)) return;
    try {
      const result = await window.SDApi.post("/api/admin/files/batch-delete", { ids: Array.from(selected) });
      showAlert(`Deleted ${result.deleted} file(s).`, "success");
      load();
    } catch (err) { showAlert(err.message); }
  });

  load();
})();
