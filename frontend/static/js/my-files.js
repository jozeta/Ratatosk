(function () {
  const tbody = document.getElementById("filesTableBody");
  const emptyState = document.getElementById("emptyState");

  if (!window.SDApi.isLoggedIn()) {
    window.location.href = "/login";
    return;
  }

  function td(text) {
    const cell = document.createElement("td");
    cell.textContent = text;
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
    let files;
    try {
      files = await window.SDApi.get("/api/files/mine");
    } catch (e) {
      window.SDToast.danger(e.message);
      return;
    }

    tbody.innerHTML = "";
    if (!files.length) {
      emptyState.style.display = "";
      return;
    }
    emptyState.style.display = "none";

    for (const f of files) {
      const row = document.createElement("tr");
      const idCell = document.createElement("td");
      const idCode = document.createElement("code");
      idCode.textContent = f.file_id.slice(0, 8) + "…";
      idCode.title = f.file_id;
      idCell.appendChild(idCode);
      row.appendChild(idCell);

      row.appendChild(td(humanSize(f.size_bytes)));
      row.appendChild(td(new Date(f.created_at).toLocaleString()));

      const expiresCell = td(f.expired ? "expired" : new Date(f.expires_at).toLocaleString());
      if (f.expired) {
        const badge = document.createElement("span");
        badge.className = "badge badge-danger";
        badge.textContent = "expired";
        expiresCell.textContent = "";
        expiresCell.appendChild(badge);
      }
      row.appendChild(expiresCell);

      row.appendChild(td(`${f.download_count}${f.max_downloads ? "/" + f.max_downloads : ""}`));
      row.appendChild(td(f.burn_after_download ? "yes" : "no"));

      const sharedCell = document.createElement("td");
      if (f.password_protected) {
        sharedCell.className = "text-muted small";
        sharedCell.textContent = "not shareable (passphrase file)";
      } else if (!f.shared_with.length) {
        sharedCell.className = "text-muted small";
        sharedCell.textContent = "—";
      } else {
        const chipList = document.createElement("div");
        chipList.className = "share-chip-list";
        for (const recipient of f.shared_with) {
          const chip = document.createElement("span");
          chip.className = "tag-chip";
          const text = document.createElement("span");
          text.textContent = recipient.username;
          const remove = document.createElement("button");
          remove.type = "button";
          remove.className = "tag-chip-remove";
          remove.textContent = "×";
          remove.title = `Unshare from ${recipient.username}`;
          remove.addEventListener("click", async () => {
            try {
              await window.SDApi.del(`/api/files/${f.file_id}/share/${recipient.id}`);
              load();
            } catch (e) { window.SDToast.danger(e.message); }
          });
          chip.appendChild(text);
          chip.appendChild(remove);
          chipList.appendChild(chip);
        }
        sharedCell.appendChild(chipList);
      }
      row.appendChild(sharedCell);

      const actionCell = document.createElement("td");
      const delBtn = document.createElement("button");
      delBtn.className = "btn btn-danger btn-sm";
      delBtn.textContent = "Delete";
      delBtn.addEventListener("click", async () => {
        if (!confirm("Delete this file permanently?")) return;
        try {
          await window.SDApi.del(`/api/files/${f.file_id}`);
          load();
        } catch (e) {
          window.SDToast.danger(e.message);
        }
      });
      actionCell.appendChild(delBtn);
      row.appendChild(actionCell);

      tbody.appendChild(row);
    }
  }

  load();
})();
