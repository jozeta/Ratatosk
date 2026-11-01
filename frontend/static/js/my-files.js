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

  const humanSize = (b) => window.SDUtil.humanSize(b);

  function badge(text, cls) {
    const b = document.createElement("span");
    b.className = `badge ${cls}`;
    b.textContent = text;
    return b;
  }

  function actionButton(label, cls, onClick) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `btn ${cls} btn-sm`;
    btn.textContent = label;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try { await onClick(); } catch (e) { window.SDToast.danger(e.message); } finally { btn.disabled = false; }
    });
    return btn;
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
      if (f.is_bundle) idCell.appendChild(badge(`bundle · ${f.bundle_file_count} files`, "badge-muted"));
      if (f.disabled) idCell.appendChild(badge("link off", "badge-warn"));
      if (f.locked) idCell.appendChild(badge("locked", "badge-danger"));
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

      // Link management (FEAT-007): switch the link off/on, end it now, or
      // lift a wrong-passphrase lockout - limits can only be tightened.
      const actionCell = document.createElement("td");
      actionCell.className = "row-actions";
      if (!f.expired) {
        actionCell.appendChild(actionButton(f.disabled ? "Turn link on" : "Turn link off", "btn-outline", async () => {
          await window.SDApi.patch(`/api/files/${f.file_id}`, { disabled: !f.disabled });
          load();
        }));
        actionCell.appendChild(actionButton("Expire now", "btn-outline", async () => {
          if (!confirm("End this link now? Nobody will be able to download the file afterwards.")) return;
          await window.SDApi.patch(`/api/files/${f.file_id}`, { expires_at: new Date().toISOString() });
          load();
        }));
      }
      if (f.locked) {
        actionCell.appendChild(actionButton("Unlock", "btn-outline", async () => {
          await window.SDApi.post(`/api/files/${f.file_id}/unlock`, {});
          window.SDToast.show("Passphrase lockout lifted.", "success");
          load();
        }));
      }
      actionCell.appendChild(actionButton("Delete", "btn-danger", async () => {
        if (!confirm(f.is_bundle ? "Delete this bundle and all its files permanently?" : "Delete this file permanently?")) return;
        await window.SDApi.del(`/api/files/${f.file_id}`);
        load();
      }));
      row.appendChild(actionCell);

      tbody.appendChild(row);
    }
  }

  load();
})();
