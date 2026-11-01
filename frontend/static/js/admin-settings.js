(function () {
  const FIELDS = [
    "brand_name", "footer_text",
    "allow_anonymous_upload", "allow_anonymous_download", "allow_user_registration", "allow_user_login",
    "allow_secondary_password", "enforce_secondary_password",
    "enable_mfa", "enforce_mfa_users", "enforce_mfa_admins",
    "enable_login_rate_limit", "login_lockout_minutes",
    "enable_user_management", "enable_file_management", "enable_user_sharing", "enable_api_keys", "enable_multi_file_upload",
    "password_min_length", "password_require_uppercase", "password_require_lowercase", "password_require_number", "password_require_special",
    "max_file_size_mb", "chunk_size_mb", "max_concurrent_uploads", "extension_rule_mode",
    "default_ttl", "allow_custom_ttl", "allow_burn_after_download", "force_burn_after_download",
    "default_max_downloads", "allow_custom_max_downloads",
    "total_storage_cap_gb", "cleanup_interval_minutes", "max_active_upload_sessions",
    "rate_limit_enabled", "rate_limit_per_minute", "onion_address",
    "zero_log_mode", "ip_obfuscation_level", "timestamp_fuzzing",
    "audit_log_retention_days", "disable_audit_log", "max_login_attempts",
    "hide_upload_link", "hide_download_link",
    "custom_theme_enabled", "custom_theme_paper", "custom_theme_surface", "custom_theme_navbar_bg",
    "custom_theme_border", "custom_theme_text", "custom_theme_accent", "custom_theme_danger",
    "custom_theme_heading_color", "custom_theme_heading_scale", "custom_theme_body_scale",
    "smtp_enabled", "smtp_host", "smtp_port", "smtp_username", "smtp_encryption",
    "smtp_from_email", "smtp_from_name", "public_base_url", "password_reset_token_expiry_minutes",
    "enable_download_notifications",
  ];
  // extension_list and allowed_ttl_presets are handled by the tag-list widgets, not this generic list.
  // smtp_password is write-only (never returned by the API) and handled separately.
  const CHECKBOX_FIELDS = new Set([
    "allow_anonymous_upload", "allow_anonymous_download", "allow_user_registration", "allow_user_login",
    "allow_secondary_password", "enforce_secondary_password",
    "enable_mfa", "enforce_mfa_users", "enforce_mfa_admins",
    "enable_login_rate_limit",
    "enable_user_management", "enable_file_management", "enable_user_sharing", "enable_api_keys", "enable_multi_file_upload",
    "password_require_uppercase", "password_require_lowercase", "password_require_number", "password_require_special",
    "allow_custom_ttl", "allow_burn_after_download", "force_burn_after_download", "allow_custom_max_downloads",
    "zero_log_mode", "disable_audit_log",
    "hide_upload_link", "hide_download_link", "custom_theme_enabled",
    "smtp_enabled", "enable_download_notifications", "rate_limit_enabled",
  ]);
  const NUMBER_FIELDS = new Set([
    "password_min_length", "login_lockout_minutes",
    "max_file_size_mb", "chunk_size_mb", "max_concurrent_uploads", "default_max_downloads",
    "total_storage_cap_gb", "cleanup_interval_minutes", "audit_log_retention_days", "max_login_attempts",
    "smtp_port", "password_reset_token_expiry_minutes",
    "custom_theme_heading_scale", "custom_theme_body_scale",
    "max_active_upload_sessions", "rate_limit_per_minute",
  ]);

  function showAlert(message, type) {
    window.SDToast.show(message, type);
  }

  if (!window.SDApi.isAdmin()) {
    window.location.href = "/login";
    return;
  }

  function createTagList(containerEl, inputEl, addBtnEl, initialCSV) {
    let items = (initialCSV || "").split(",").map((s) => s.trim()).filter(Boolean);

    function render() {
      containerEl.innerHTML = "";
      items.forEach((item, idx) => {
        const chip = document.createElement("span");
        chip.className = "tag-chip";
        const text = document.createElement("span");
        text.textContent = item;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "tag-chip-remove";
        remove.textContent = "×";
        remove.title = "Remove";
        remove.addEventListener("click", () => { items.splice(idx, 1); render(); });
        chip.appendChild(text);
        chip.appendChild(remove);
        containerEl.appendChild(chip);
      });
      if (items.length === 0) {
        const empty = document.createElement("span");
        empty.className = "text-muted small";
        empty.textContent = "(none)";
        containerEl.appendChild(empty);
      }
    }

    function addFromInput() {
      const val = inputEl.value.trim().replace(/^\./, "");
      if (val && !items.includes(val)) {
        items.push(val);
        render();
      }
      inputEl.value = "";
    }

    addBtnEl.addEventListener("click", addFromInput);
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addFromInput(); }
    });

    render();
    return {
      getCSV: () => items.join(","),
      setCSV: (csv) => { items = (csv || "").split(",").map((s) => s.trim()).filter(Boolean); render(); },
    };
  }

  let extensionTagList = null;
  let ttlTagList = null;

  function populate(cfg) {
    for (const field of FIELDS) {
      const el = document.getElementById(field);
      if (!el) continue;
      if (CHECKBOX_FIELDS.has(field)) el.checked = !!cfg[field];
      else el.value = cfg[field];
    }
    if (extensionTagList) extensionTagList.setCSV(cfg.extension_list);
    else extensionTagList = createTagList(
      document.getElementById("extension_list_tags"),
      document.getElementById("extension_list_input"),
      document.getElementById("extension_list_add"),
      cfg.extension_list
    );
    if (ttlTagList) ttlTagList.setCSV(cfg.allowed_ttl_presets);
    else ttlTagList = createTagList(
      document.getElementById("allowed_ttl_presets_tags"),
      document.getElementById("allowed_ttl_presets_input"),
      document.getElementById("allowed_ttl_presets_add"),
      cfg.allowed_ttl_presets
    );

    document.getElementById("smtp_password").value = "";
    document.getElementById("smtpPasswordHint").textContent = cfg.smtp_password_set
      ? "A password is currently saved."
      : "No password saved.";

    document.getElementById("brandPreviewName").textContent = cfg.brand_name || "Ratatosk";
    const img = document.getElementById("logoPreviewImg");
    const fallback = document.getElementById("logoPreviewDefault");
    if (cfg.brand_logo_filename) {
      img.src = `/api/branding/logo?v=${encodeURIComponent(cfg.brand_logo_filename)}`;
      img.hidden = false;
      fallback.style.display = "none";
    } else {
      img.hidden = true;
      img.removeAttribute("src");
      fallback.style.display = "";
    }
  }

  function collect() {
    const out = {};
    for (const field of FIELDS) {
      const el = document.getElementById(field);
      if (!el) continue;
      if (CHECKBOX_FIELDS.has(field)) out[field] = el.checked;
      else if (NUMBER_FIELDS.has(field)) out[field] = parseInt(el.value, 10);
      else out[field] = el.value;
    }
    out.extension_list = extensionTagList.getCSV();
    out.allowed_ttl_presets = ttlTagList.getCSV();
    const smtpPassword = document.getElementById("smtp_password").value;
    if (smtpPassword) out.smtp_password = smtpPassword;
    return out;
  }

  async function load() {
    try {
      const cfg = await window.SDApi.get("/api/admin/settings");
      populate(cfg);
      // Read-only: the storage location comes from RATATOSK_STORAGE_ROOT (SEC-010).
      document.getElementById("storage_path").value = cfg.storage_path || "(set by RATATOSK_STORAGE_ROOT)";
    } catch (e) {
      showAlert(e.message, "danger");
    }
  }

  document.getElementById("saveBtn").addEventListener("click", async () => {
    try {
      const cfg = await window.SDApi.patch("/api/admin/settings", collect());
      populate(cfg);
      document.getElementById("storage_path").value = cfg.storage_path || "(set by RATATOSK_STORAGE_ROOT)";
      showAlert("Settings saved and applied immediately.", "success");
    } catch (e) {
      showAlert(e.message, "danger");
    }
  });

  const logoFileInput = document.getElementById("logoFileInput");
  document.getElementById("logoUploadBtn").addEventListener("click", () => logoFileInput.click());
  logoFileInput.addEventListener("change", async () => {
    const file = logoFileInput.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      showAlert("Logo must be under 2MB.", "danger");
      logoFileInput.value = "";
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    try {
      await window.SDApi.postFile("/api/admin/branding/logo", formData);
      showAlert("Logo updated.", "success");
      load();
    } catch (e) {
      showAlert(e.message, "danger");
    } finally {
      logoFileInput.value = "";
    }
  });
  document.getElementById("smtpTestBtn").addEventListener("click", async () => {
    const toEmail = document.getElementById("smtpTestEmail").value.trim();
    if (!toEmail) { showAlert("Enter an address to send the test email to.", "danger"); return; }
    try {
      await window.SDApi.post("/api/admin/settings/smtp-test", { to_email: toEmail });
      showAlert(`Test email sent to ${toEmail}.`, "success");
    } catch (e) {
      showAlert(e.message, "danger");
    }
  });

  document.getElementById("logoRemoveBtn").addEventListener("click", async () => {
    try {
      await window.SDApi.del("/api/admin/branding/logo");
      showAlert("Logo removed.", "success");
      load();
    } catch (e) {
      showAlert(e.message, "danger");
    }
  });

  // ---- Category navigation ----
  const navItems = Array.from(document.querySelectorAll(".settings-nav-item"));
  const panels = Array.from(document.querySelectorAll(".settings-panel"));
  const validTargets = new Set(navItems.map((el) => el.dataset.target));

  function showTab(target, updateHash) {
    if (!validTargets.has(target)) target = navItems[0].dataset.target;
    for (const panel of panels) panel.hidden = panel.dataset.panel !== target;
    for (const item of navItems) item.classList.toggle("active", item.dataset.target === target);
    if (updateHash) history.replaceState(null, "", "#" + target);
  }

  navItems.forEach((item) => {
    item.addEventListener("click", () => showTab(item.dataset.target, true));
  });
  window.addEventListener("hashchange", () => showTab(window.location.hash.slice(1), false));
  showTab(window.location.hash.slice(1), false);

  // ---- Danger zone: full database reset ----
  const resetConfirmModal = document.getElementById("resetConfirmModal");
  const resetResultModal = document.getElementById("resetResultModal");
  const resetConfirmPassword = document.getElementById("resetConfirmPassword");
  const resetConfirmPhrase = document.getElementById("resetConfirmPhrase");

  function openResetConfirmModal() {
    resetConfirmPassword.value = "";
    resetConfirmPhrase.value = "";
    resetConfirmModal.hidden = false;
  }
  function closeResetConfirmModal() {
    resetConfirmModal.hidden = true;
  }

  document.getElementById("openResetModalBtn").addEventListener("click", openResetConfirmModal);
  document.getElementById("resetConfirmCloseBtn").addEventListener("click", closeResetConfirmModal);
  resetConfirmModal.addEventListener("click", (e) => { if (e.target === resetConfirmModal) closeResetConfirmModal(); });

  document.getElementById("resetConfirmBtn").addEventListener("click", async () => {
    if (resetConfirmPhrase.value.trim().toUpperCase() !== "RESET") {
      showAlert('Type RESET (in capitals) to confirm.', "danger");
      return;
    }
    if (!resetConfirmPassword.value) {
      showAlert("Enter your current password.", "danger");
      return;
    }
    try {
      const result = await window.SDApi.post("/api/admin/system/reset", { password: resetConfirmPassword.value });
      closeResetConfirmModal();
      window.SDApi.clearSession();
      document.getElementById("resetResultUsername").value = result.admin_username;
      document.getElementById("resetResultPassword").value = result.admin_password;
      resetResultModal.hidden = false;
    } catch (e) {
      showAlert(e.message, "danger");
    }
  });

  document.getElementById("resetResultCopyBtn").addEventListener("click", (e) => {
    const field = document.getElementById("resetResultPassword");
    window.SDUtil.copyText(field.value, e.currentTarget, field);
  });
  document.getElementById("resetResultGoToLoginBtn").addEventListener("click", () => {
    window.location.href = "/login";
  });

  load();
})();
