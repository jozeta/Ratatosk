(function () {
  if (!window.SDApi.isLoggedIn()) {
    window.location.href = "/login";
    return;
  }

  const content = document.getElementById("content");
  const tbody = document.getElementById("sharedTableBody");
  const emptyState = document.getElementById("emptyState");

  function showAlert(message, type = "danger") {
    window.SDToast.show(message, type);
  }

  function td(text) {
    const cell = document.createElement("td");
    cell.textContent = text == null ? "" : text;
    return cell;
  }

  async function load() {
    try {
      const cfg = await window.SDApi.get("/api/config");
      if (!cfg.enable_user_sharing) {
        window.location.href = "/";
        return;
      }
    } catch (e) { /* config fetch failing shouldn't block the page */ }

    let items;
    try {
      items = await window.SDApi.get("/api/files/shared-with-me");
    } catch (e) {
      if (e.status === 403) {
        window.location.href = "/";
        return;
      }
      showAlert(e.message);
      return;
    }
    content.style.display = "";

    tbody.innerHTML = "";
    emptyState.style.display = items.length ? "none" : "";

    for (const item of items) {
      const row = document.createElement("tr");
      row.appendChild(td(window.SDDownload.humanSize(item.size_bytes)));
      row.appendChild(td(item.shared_by));
      row.appendChild(td(item.shared_with.join(", ")));
      row.appendChild(td(window.SDDownload.timeRemaining(item.expires_at)));
      row.appendChild(td(`${item.download_count}${item.max_downloads ? "/" + item.max_downloads : ""}${item.burn_after_download ? " (burn)" : ""}`));

      const actionCell = document.createElement("td");
      const btn = document.createElement("button");
      btn.className = "btn btn-primary btn-sm";
      btn.textContent = "Decrypt & Download";
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "Downloading...";
        try {
          const { key } = await window.SDApi.get(`/api/files/${item.file_id}/shared-key`);
          const result = await window.SDDownload.fetchAndDecrypt(item.file_id, null, key);
          window.SDDownload.saveDecrypted(result);
          showAlert(`Decrypted and saved "${result.name}".`, "success");
          load();
        } catch (e) {
          showAlert(e.message || "Download failed.");
        } finally {
          btn.disabled = false;
          btn.textContent = "Decrypt & Download";
        }
      });
      actionCell.appendChild(btn);
      row.appendChild(actionCell);

      tbody.appendChild(row);
    }
  }

  load();
})();
