(function () {
  if (!window.SDApi.isAdmin()) {
    window.location.href = "/login";
    return;
  }

  const disabledNotice = document.getElementById("disabledNotice");
  const content = document.getElementById("content");
  const tbody = document.getElementById("usersTableBody");
  const selectAllCheckbox = document.getElementById("selectAllCheckbox");
  const batchDeleteBtn = document.getElementById("batchDeleteBtn");
  const me = window.SDApi.getUser();

  let selected = new Set();
  let currentUsers = [];
  let pwCfg = { password_min_length: 8 };
  window.SDApi.get("/api/config").then((cfg) => { pwCfg = cfg; }).catch(() => {});

  function showAlert(message, type = "danger") {
    window.SDToast.show(message, type);
  }

  function updateBatchDeleteBtn() {
    batchDeleteBtn.hidden = selected.size === 0;
    batchDeleteBtn.textContent = `Delete selected (${selected.size})`;
  }

  function td(text) {
    const cell = document.createElement("td");
    cell.textContent = text == null ? "" : text;
    return cell;
  }

  function badge(text, cls) {
    const span = document.createElement("span");
    span.className = "badge " + cls;
    span.textContent = text;
    const cell = document.createElement("td");
    cell.appendChild(span);
    return cell;
  }

  // ---- Modal ----
  const modal = document.getElementById("userModal");
  const modalTitle = document.getElementById("userModalTitle");
  const modalUsername = document.getElementById("modalUsername");
  const modalEmail = document.getElementById("modalEmail");
  const modalPassword = document.getElementById("modalPassword");
  const modalPasswordLabel = document.getElementById("modalPasswordLabel");
  const modalPasswordHint = document.getElementById("modalPasswordHint");
  const modalIsAdmin = document.getElementById("modalIsAdmin");
  const modalIsActiveRow = document.getElementById("modalIsActive").closest(".switch-row");
  const modalIsActive = document.getElementById("modalIsActive");
  const modalCreatedRow = document.getElementById("modalCreatedRow");
  const modalSelfNotice = document.getElementById("modalSelfNotice");
  const modalDeleteBtn = document.getElementById("modalDeleteBtn");
  const modalSaveBtn = document.getElementById("modalSaveBtn");
  const modalMfaRow = document.getElementById("modalMfaRow");
  const modalMfaStatus = document.getElementById("modalMfaStatus");
  const modalMfaResetBtn = document.getElementById("modalMfaResetBtn");
  const modalUnlockBtn = document.getElementById("modalUnlockBtn");

  let modalMode = "create"; // "create" | "edit"
  let modalTarget = null;
  let strengthAttached = false;

  function attachStrength() {
    if (strengthAttached) return;
    strengthAttached = true;
    window.SDPasswordStrength.attach(
      modalPassword,
      document.getElementById("modalStrengthFill"),
      document.getElementById("modalStrengthLabel"),
      document.getElementById("modalPolicyChecklist"),
      pwCfg
    );
  }

  function openCreateModal() {
    modalMode = "create";
    modalTarget = null;
    modalTitle.textContent = "Add user";
    modalUsername.value = "";
    modalEmail.value = "";
    modalPassword.value = "";
    modalPasswordLabel.textContent = "Password";
    modalPasswordHint.textContent = "";
    modalIsAdmin.checked = false;
    modalIsAdmin.disabled = false;
    modalIsActiveRow.hidden = true;
    modalIsActive.checked = true;
    modalCreatedRow.hidden = true;
    modalSelfNotice.hidden = true;
    modalDeleteBtn.hidden = true;
    modalMfaRow.hidden = true;
    modalSaveBtn.textContent = "Create user";
    attachStrength();
    modalPassword.dispatchEvent(new Event("input"));
    modal.hidden = false;
    modalUsername.focus();
  }

  function openEditModal(user) {
    modalMode = "edit";
    modalTarget = user;
    const isSelf = !!me && user.id === me.id;
    modalTitle.textContent = "Edit user";
    modalUsername.value = user.username;
    modalEmail.value = user.email || "";
    modalPassword.value = "";
    modalPasswordLabel.textContent = "New password";
    modalPasswordHint.textContent = "Leave blank to keep their current password.";
    modalIsAdmin.checked = user.is_admin;
    modalIsAdmin.disabled = isSelf;
    modalIsActiveRow.hidden = false;
    modalIsActive.checked = user.is_active;
    modalIsActive.disabled = isSelf;
    modalCreatedRow.hidden = false;
    modalCreatedRow.textContent = `Created ${new Date(user.created_at).toLocaleString()}`;
    modalSelfNotice.hidden = !isSelf;
    modalDeleteBtn.hidden = isSelf;
    modalMfaRow.hidden = false;
    modalMfaStatus.textContent = user.mfa_enabled ? "Enabled" : "Not set up";
    modalMfaResetBtn.hidden = !user.mfa_enabled;
    modalSaveBtn.textContent = "Save changes";
    attachStrength();
    modalPassword.dispatchEvent(new Event("input"));
    modal.hidden = false;
  }

  function closeModal() {
    modal.hidden = true;
  }

  document.getElementById("userModalCloseBtn").addEventListener("click", closeModal);
  document.getElementById("modalCancelBtn").addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeModal(); });

  modalSaveBtn.addEventListener("click", async () => {
    const username = modalUsername.value.trim();
    const email = modalEmail.value.trim();
    const password = modalPassword.value;
    if (!username || username.length < 3) { showAlert("Username must be at least 3 characters."); return; }

    if (modalMode === "create") {
      if (!password) { showAlert("A password is required."); return; }
      try {
        await window.SDApi.post("/api/admin/users", {
          username,
          email: email || null,
          password,
          is_admin: modalIsAdmin.checked,
        });
        showAlert(`User "${username}" created.`, "success");
        closeModal();
        load();
      } catch (err) {
        showAlert(err.message);
      }
      return;
    }

    try {
      await window.SDApi.patch(`/api/admin/users/${modalTarget.id}`, {
        username,
        email: email || null,
        is_admin: modalIsAdmin.checked,
        is_active: modalIsActive.checked,
      });
      if (password) {
        await window.SDApi.post(`/api/admin/users/${modalTarget.id}/reset-password`, { new_password: password });
      }
      showAlert(`Saved changes to "${username}".`, "success");
      closeModal();
      load();
    } catch (err) {
      showAlert(err.message);
    }
  });

  modalDeleteBtn.addEventListener("click", async () => {
    if (!modalTarget) return;
    if (!confirm(`Delete user "${modalTarget.username}"? Their uploaded files are kept but become unowned.`)) return;
    try {
      await window.SDApi.del(`/api/admin/users/${modalTarget.id}`);
      showAlert(`Deleted "${modalTarget.username}".`, "success");
      closeModal();
      load();
    } catch (err) {
      showAlert(err.message);
    }
  });

  modalMfaResetBtn.addEventListener("click", async () => {
    if (!modalTarget) return;
    if (!confirm(`Reset two-factor authentication for "${modalTarget.username}"? They'll be able to log in with just their password and can set it up again.`)) return;
    try {
      await window.SDApi.post(`/api/admin/users/${modalTarget.id}/mfa-reset`);
      showAlert(`Two-factor authentication reset for "${modalTarget.username}".`, "success");
      modalMfaStatus.textContent = "Not set up";
      modalMfaResetBtn.hidden = true;
    } catch (err) {
      showAlert(err.message);
    }
  });

  modalUnlockBtn.addEventListener("click", async () => {
    if (!modalTarget) return;
    try {
      await window.SDApi.post(`/api/admin/users/${modalTarget.id}/unlock`, {});
      showAlert(`Login lockouts cleared for "${modalTarget.username}".`, "success");
    } catch (err) {
      showAlert(err.message);
    }
  });

  document.getElementById("newUserBtn").addEventListener("click", openCreateModal);

  // ---- List ----
  async function load() {
    let users;
    try {
      users = await window.SDApi.get("/api/admin/users");
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
    currentUsers = users;
    selectAllCheckbox.checked = false;
    updateBatchDeleteBtn();

    tbody.innerHTML = "";
    for (const u of users) {
      const row = document.createElement("tr");
      row.className = "clickable-row";
      row.addEventListener("click", () => openEditModal(u));

      const selectCell = document.createElement("td");
      selectCell.className = "checkbox-cell";
      const selectBox = document.createElement("input");
      selectBox.type = "checkbox";
      selectBox.addEventListener("click", (e) => e.stopPropagation());
      if (me && u.id === me.id) {
        selectBox.disabled = true;
        selectBox.title = "You cannot select your own account";
      } else {
        selectBox.addEventListener("change", () => {
          if (selectBox.checked) selected.add(u.id);
          else selected.delete(u.id);
          const selectable = currentUsers.filter((x) => !me || x.id !== me.id);
          selectAllCheckbox.checked = selectable.length > 0 && selected.size === selectable.length;
          updateBatchDeleteBtn();
        });
      }
      selectCell.appendChild(selectBox);
      row.appendChild(selectCell);

      const usernameCell = td(u.username);
      if (me && u.id === me.id) usernameCell.append(" ", (() => { const s = document.createElement("span"); s.className = "text-muted small"; s.textContent = "(you)"; return s; })());
      row.appendChild(usernameCell);

      row.appendChild(td(u.email || "—"));
      row.appendChild(badge(u.is_admin ? "Admin" : "User", u.is_admin ? "badge-success" : ""));
      row.appendChild(badge(u.is_active ? "Active" : "Inactive", u.is_active ? "badge-success" : "badge-danger"));
      row.appendChild(badge(u.mfa_enabled ? "On" : "Off", u.mfa_enabled ? "badge-success" : ""));
      row.appendChild(td(new Date(u.created_at).toLocaleString()));

      tbody.appendChild(row);
    }
  }

  selectAllCheckbox.addEventListener("change", () => {
    selected = new Set();
    const rows = tbody.querySelectorAll('input[type="checkbox"]:not(:disabled)');
    if (selectAllCheckbox.checked) {
      rows.forEach((cb) => { cb.checked = true; });
      for (const u of currentUsers) { if (!me || u.id !== me.id) selected.add(u.id); }
    } else {
      rows.forEach((cb) => { cb.checked = false; });
    }
    updateBatchDeleteBtn();
  });

  batchDeleteBtn.addEventListener("click", async () => {
    if (selected.size === 0) return;
    if (!confirm(`Delete ${selected.size} user(s) permanently? Their uploaded files are kept but become unowned.`)) return;
    try {
      const result = await window.SDApi.post("/api/admin/users/batch-delete", { ids: Array.from(selected) });
      showAlert(`Deleted ${result.deleted} user(s).`, "success");
      load();
    } catch (err) { showAlert(err.message); }
  });

  // ---- CSV import / export / template ----
  const csvFileInput = document.getElementById("csvFileInput");
  document.getElementById("importCsvBtn").addEventListener("click", () => csvFileInput.click());
  csvFileInput.addEventListener("change", async () => {
    const file = csvFileInput.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const result = await window.SDApi.postFile("/api/admin/users/import", formData);
      const errCount = result.errors.length;
      showAlert(
        `Imported ${result.created.length} user(s)${errCount ? `, ${errCount} row(s) failed` : ""}.`,
        errCount && !result.created.length ? "danger" : "success"
      );
      for (const e of result.errors.slice(0, 5)) {
        showAlert(`Row ${e.row} (${e.username || "?"}): ${e.error}`, "danger");
      }
      load();
    } catch (err) {
      showAlert(err.message);
    } finally {
      csvFileInput.value = "";
    }
  });

  document.getElementById("downloadTemplateBtn").addEventListener("click", () => {
    const csv = "username,password,is_admin\nalice,Str0ngPass!23,false\nbob,Str0ngPass!45,true\n";
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "user_import_template.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  });

  document.getElementById("exportUsersBtn").addEventListener("click", async () => {
    try {
      const res = await fetch("/api/admin/users/export", {
        headers: { "X-Ratatosk-CSRF": "1" },
      });
      if (!res.ok) { showAlert("Export failed"); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "users.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (err) {
      showAlert(err.message);
    }
  });

  load();
})();
