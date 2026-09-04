(function () {
  if (!window.SDApi.isLoggedIn()) {
    window.location.href = "/login";
    return;
  }

  function showAlert(message, type = "danger") {
    window.SDToast.show(message, type);
  }

  const cfgPromise = window.SDApi.get("/api/config").catch(() => ({}));

  const emailInput = document.getElementById("email");
  function refreshMe() {
    return Promise.all([window.SDApi.get("/api/auth/me"), cfgPromise]).then(([me, cfg]) => {
      emailInput.value = me.email || "";
      setMfaView(me.mfa_enabled, !!cfg.enable_mfa);
      return me;
    }).catch(() => {});
  }
  refreshMe();

  document.getElementById("emailForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await window.SDApi.patch("/api/auth/email", { email: emailInput.value.trim() || null });
      showAlert("Email updated.", "success");
    } catch (err) {
      showAlert(err.message);
    }
  });

  // ---- Two-factor authentication ----
  const mfaStatusBadge = document.getElementById("mfaStatusBadge");
  const mfaDisabledView = document.getElementById("mfaDisabledView");
  const mfaEnabledView = document.getElementById("mfaEnabledView");
  const mfaDisableForm = document.getElementById("mfaDisableForm");
  const mfaSetupView = document.getElementById("mfaSetupView");
  const mfaBackupCodesView = document.getElementById("mfaBackupCodesView");

  function setMfaView(enabled, siteFeatureOn) {
    // The card stays visible if the user already has MFA on, even if the
    // site feature gets turned off later - they still need a way to
    // disable their own now-dormant setup. Only a fresh "Enable" entry
    // point requires the site feature to be on.
    document.getElementById("mfaCard").hidden = !siteFeatureOn && !enabled;
    document.getElementById("mfaEnableBtn").disabled = !siteFeatureOn;
    mfaStatusBadge.textContent = enabled ? "Enabled" : "Disabled";
    mfaStatusBadge.className = "badge " + (enabled ? "badge-success" : "");
    mfaDisabledView.style.display = enabled ? "none" : "";
    mfaEnabledView.style.display = enabled ? "" : "none";
    mfaDisableForm.style.display = "none";
    mfaSetupView.style.display = "none";
    mfaBackupCodesView.style.display = "none";
  }

  document.getElementById("mfaEnableBtn").addEventListener("click", async () => {
    try {
      const res = await window.SDApi.post("/api/auth/mfa/setup");
      document.getElementById("mfaManualSecret").value = res.secret;
      mfaDisabledView.style.display = "none";
      mfaSetupView.style.display = "";
      document.getElementById("mfaConfirmCode").value = "";
      if (window.SDQRCode) {
        try { window.SDQRCode.renderToCanvas(document.getElementById("mfaQrCanvas"), res.otpauth_url); }
        catch (e) { /* QR is a convenience, manual code still works */ }
      }
    } catch (err) {
      showAlert(err.message);
    }
  });

  document.getElementById("mfaCopySecretBtn").addEventListener("click", () => {
    navigator.clipboard.writeText(document.getElementById("mfaManualSecret").value);
  });

  document.getElementById("mfaCancelSetupBtn").addEventListener("click", () => setMfaView(false));

  let pendingBackupCodes = [];

  document.getElementById("mfaConfirmForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await window.SDApi.post("/api/auth/mfa/confirm", {
        code: document.getElementById("mfaConfirmCode").value,
      });
      pendingBackupCodes = res.backup_codes;
      mfaSetupView.style.display = "none";
      mfaBackupCodesView.style.display = "";
      const list = document.getElementById("mfaBackupCodesList");
      list.innerHTML = "";
      for (const code of pendingBackupCodes) {
        const chip = document.createElement("span");
        chip.className = "tag-chip";
        chip.textContent = code;
        list.appendChild(chip);
      }
    } catch (err) {
      showAlert(err.message);
    }
  });

  document.getElementById("mfaCopyBackupCodesBtn").addEventListener("click", () => {
    navigator.clipboard.writeText(pendingBackupCodes.join("\n"));
  });

  document.getElementById("mfaBackupCodesDoneBtn").addEventListener("click", () => {
    showAlert("Two-factor authentication enabled.", "success");
    refreshMe();
  });

  document.getElementById("mfaShowDisableBtn").addEventListener("click", () => {
    mfaEnabledView.style.display = "none";
    mfaDisableForm.style.display = "";
    document.getElementById("mfaDisablePassword").value = "";
  });
  document.getElementById("mfaCancelDisableBtn").addEventListener("click", () => setMfaView(true));

  mfaDisableForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await window.SDApi.post("/api/auth/mfa/disable", {
        password: document.getElementById("mfaDisablePassword").value,
      });
      showAlert("Two-factor authentication disabled.", "success");
      refreshMe();
    } catch (err) {
      showAlert(err.message);
    }
  });

  const newPasswordInput = document.getElementById("newPassword");
  cfgPromise.then((cfg) => {
    window.SDPasswordStrength.attach(
      newPasswordInput,
      document.getElementById("strengthFill"),
      document.getElementById("strengthLabel"),
      document.getElementById("policyChecklist"),
      cfg
    );
  });

  document.getElementById("changePasswordForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await window.SDApi.post("/api/auth/change-password", {
        current_password: document.getElementById("currentPassword").value,
        new_password: newPasswordInput.value,
      });
      // Changing the password invalidates every session for this account,
      // including this one - the server issues a fresh token specifically
      // so this device doesn't get logged out too.
      window.SDApi.setSession(res.access_token, window.SDApi.getUser());
      showAlert("Password updated. You've been logged out of all other sessions.", "success");
      e.target.reset();
      newPasswordInput.dispatchEvent(new Event("input"));
    } catch (err) {
      showAlert(err.message);
    }
  });

  const logoutEverywhereBtn = document.getElementById("logoutEverywhereBtn");
  if (logoutEverywhereBtn) {
    logoutEverywhereBtn.addEventListener("click", async () => {
      if (!confirm("Log out every other session for this account? This device will stay logged in.")) return;
      try {
        const res = await window.SDApi.post("/api/auth/logout-everywhere", {});
        window.SDApi.setSession(res.access_token, window.SDApi.getUser());
        showAlert("Logged out everywhere else.", "success");
      } catch (err) {
        showAlert(err.message);
      }
    });
  }

  document.getElementById("deleteAccountBtn").addEventListener("click", async () => {
    if (!confirm("Permanently delete your account? This cannot be undone.")) return;
    try {
      await window.SDApi.del("/api/auth/me");
      window.SDApi.clearSession();
      window.location.href = "/";
    } catch (err) {
      showAlert(err.message);
    }
  });

  // ---- API keys ----
  const apiKeysCard = document.getElementById("apiKeysCard");
  const apiKeysBody = document.getElementById("apiKeysTableBody");
  const apiKeysEmptyState = document.getElementById("apiKeysEmptyState");
  const newKeyForm = document.getElementById("newKeyForm");
  const newKeyResult = document.getElementById("newKeyResult");

  function td(text) {
    const cell = document.createElement("td");
    cell.textContent = text == null ? "—" : text;
    return cell;
  }

  async function loadApiKeys() {
    let keys;
    try {
      keys = await window.SDApi.get("/api/account/api-keys");
    } catch (e) {
      if (e.status === 403) { apiKeysCard.style.display = "none"; return; }
      showAlert(e.message);
      return;
    }
    apiKeysCard.style.display = "";
    apiKeysBody.innerHTML = "";
    apiKeysEmptyState.style.display = keys.length ? "none" : "";

    for (const key of keys) {
      const row = document.createElement("tr");
      row.appendChild(td(key.name));
      row.appendChild(td(key.scope === "upload" ? "Upload only" : "Full access"));
      const prefixCell = document.createElement("td");
      const code = document.createElement("code");
      code.textContent = key.prefix + "…";
      prefixCell.appendChild(code);
      row.appendChild(prefixCell);
      row.appendChild(td(new Date(key.created_at).toLocaleString()));
      row.appendChild(td(key.last_used_at ? new Date(key.last_used_at).toLocaleString() : "never"));

      const actionCell = document.createElement("td");
      const revokeBtn = document.createElement("button");
      revokeBtn.className = "btn btn-danger btn-sm";
      revokeBtn.textContent = "Revoke";
      revokeBtn.addEventListener("click", async () => {
        if (!confirm(`Revoke "${key.name}"? Anything using it will stop working immediately.`)) return;
        try {
          await window.SDApi.del(`/api/account/api-keys/${key.id}`);
          loadApiKeys();
        } catch (e) { showAlert(e.message); }
      });
      actionCell.appendChild(revokeBtn);
      row.appendChild(actionCell);

      apiKeysBody.appendChild(row);
    }
  }

  document.getElementById("newKeyBtn").addEventListener("click", () => {
    newKeyForm.style.display = newKeyForm.style.display === "none" ? "flex" : "none";
    newKeyResult.style.display = "none";
  });
  document.getElementById("cancelNewKeyBtn").addEventListener("click", () => {
    newKeyForm.style.display = "none";
  });
  document.getElementById("createKeyBtn").addEventListener("click", async () => {
    const name = document.getElementById("newKeyName").value.trim();
    const scope = document.getElementById("newKeyScope").value;
    if (!name) { showAlert("Give the key a name."); return; }
    try {
      const res = await window.SDApi.post("/api/account/api-keys", { name, scope });
      document.getElementById("newKeyName").value = "";
      newKeyForm.style.display = "none";
      newKeyResult.style.display = "";
      newKeyResult.innerHTML = "";
      const label = document.createElement("div");
      label.className = "mb-1";
      label.textContent = `Key created. Copy it now - it won't be shown again:`;
      const field = document.createElement("div");
      field.className = "copy-field";
      const input = document.createElement("input");
      input.type = "text";
      input.readOnly = true;
      input.value = res.key;
      const copyBtn = document.createElement("button");
      copyBtn.className = "btn btn-outline btn-sm";
      copyBtn.textContent = "Copy";
      copyBtn.addEventListener("click", () => navigator.clipboard.writeText(input.value));
      field.appendChild(input);
      field.appendChild(copyBtn);
      newKeyResult.appendChild(label);
      newKeyResult.appendChild(field);
      loadApiKeys();
    } catch (e) {
      showAlert(e.message);
    }
  });

  loadApiKeys();
})();
