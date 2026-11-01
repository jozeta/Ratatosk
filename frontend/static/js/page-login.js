// Page script for /login - kept out of the HTML so the
// Content-Security-Policy can forbid inline scripts entirely (SEC-009).
(function () {
  let cfg = null;
  function applyCfgVisibility() {
    document.getElementById("forgotPasswordRow").hidden = !cfg || !cfg.password_reset_enabled;
    document.getElementById("registerRow").hidden = !cfg || !cfg.allow_user_registration;
  }
  window.SDApi.get("/api/config").then((c) => { cfg = c; applyCfgVisibility(); }).catch(() => {});

  window.SDApi.config().then((c) => {
    if (c.oidc_enabled) {
      const sso = document.getElementById("ssoBtn");
      sso.textContent = c.oidc_button_label || "Sign in with SSO";
      sso.hidden = false;
    }
  }).catch(() => {});

  const params = new URLSearchParams(location.search);
  if (params.get("sso_error")) window.SDToast.danger("Single sign-on was cancelled or failed. Please try again.");
  if (params.get("sso") === "1") {
    // Back from the identity provider: the session cookie is set; fetch who we are.
    window.SDApi.get("/api/auth/me").then((me) => {
      window.SDApi.setSession(null, { id: me.id, username: me.username, is_admin: me.is_admin });
      return redirectAfterLogin(me.is_admin);
    }).catch(() => window.SDToast.danger("Single sign-on didn't complete. Please try again."));
  }

  const registered = params.get("registered");
  if (registered) {
    window.SDToast.show(registered === "mfa"
      ? "Account created. Sign in to finish setting up two-factor authentication."
      : "Account created. You can sign in once sign-in is enabled for your account.", "success", 9000);
  }

  async function redirectAfterLogin(isAdmin) {
    if (isAdmin) {
      // First-run setup wizard runs once, right after an admin's first login.
      try {
        const settings = await window.SDApi.get("/api/admin/settings");
        window.location.href = settings.setup_completed ? "/admin/settings" : "/admin/setup";
      } catch (e) {
        window.location.href = "/admin/settings";
      }
    } else {
      window.location.href = "/files";
    }
  }

  async function completeLogin(res) {
    window.SDApi.setSession(res.access_token, { id: res.id, username: res.username, is_admin: res.is_admin });
    await redirectAfterLogin(res.is_admin);
  }

  const loginForm = document.getElementById("loginForm");
  const mfaForm = document.getElementById("mfaForm");
  const mfaCodeInput = document.getElementById("mfaCode");
  const mfaSetupRequiredView = document.getElementById("mfaSetupRequiredView");
  const mfaSetupBackupCodesView = document.getElementById("mfaSetupBackupCodesView");
  let mfaToken = null;
  let setupToken = null;
  let pendingBackupCodes = [];

  function hideAllRows() {
    loginForm.hidden = true;
    document.getElementById("forgotPasswordRow").hidden = true;
    document.getElementById("registerRow").hidden = true;
    mfaForm.hidden = true;
    mfaSetupRequiredView.hidden = true;
    mfaSetupBackupCodesView.hidden = true;
  }

  function showMfaStep(token) {
    mfaToken = token;
    hideAllRows();
    mfaForm.hidden = false;
    mfaCodeInput.value = "";
    mfaCodeInput.focus();
  }

  function showMfaSetupRequiredStep(token) {
    setupToken = token;
    hideAllRows();
    mfaSetupRequiredView.hidden = false;
    document.getElementById("mfaSetupCode").value = "";
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await window.SDApi.post("/api/auth/login", {
        username: document.getElementById("username").value,
        password: document.getElementById("password").value,
      });
      if (res.mfa_required) {
        showMfaStep(res.mfa_token);
      } else if (res.mfa_setup_required) {
        const setup = await window.SDApi.post("/api/auth/mfa/enforce-setup", { setup_token: res.setup_token });
        showMfaSetupRequiredStep(res.setup_token);
        document.getElementById("mfaSetupManualSecret").value = setup.secret;
        if (window.SDQRCode) {
          try { window.SDQRCode.renderToCanvas(document.getElementById("mfaSetupQrCanvas"), setup.otpauth_url); }
          catch (err) { /* QR is a convenience, manual code still works */ }
        }
      } else {
        await completeLogin(res);
      }
    } catch (err) {
      window.SDToast.danger(err.message);
    }
  });

  mfaForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await window.SDApi.post("/api/auth/mfa/verify", {
        mfa_token: mfaToken,
        code: mfaCodeInput.value,
      });
      await completeLogin(res);
    } catch (err) {
      window.SDToast.danger(err.message);
    }
  });

  document.getElementById("mfaBackBtn").addEventListener("click", () => {
    mfaToken = null;
    hideAllRows();
    loginForm.hidden = false;
    applyCfgVisibility();
  });

  document.getElementById("mfaSetupCopySecretBtn").addEventListener("click", () => {
    navigator.clipboard.writeText(document.getElementById("mfaSetupManualSecret").value);
  });

  document.getElementById("mfaSetupRequiredForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await window.SDApi.post("/api/auth/mfa/enforce-confirm", {
        setup_token: setupToken,
        code: document.getElementById("mfaSetupCode").value,
      });
      pendingBackupCodes = res.backup_codes;
      // Full login has already been granted by this response - stash the
      // session now so a closed tab or interrupted "Continue" click doesn't
      // strand the user back at the login form after they've already set up MFA.
      window.SDApi.setSession(res.access_token, { id: res.id, username: res.username, is_admin: res.is_admin });
      hideAllRows();
      mfaSetupBackupCodesView.hidden = false;
      const list = document.getElementById("mfaSetupBackupCodesList");
      list.innerHTML = "";
      for (const code of pendingBackupCodes) {
        const chip = document.createElement("span");
        chip.className = "tag-chip";
        chip.textContent = code;
        list.appendChild(chip);
      }
    } catch (err) {
      window.SDToast.danger(err.message);
    }
  });

  document.getElementById("mfaSetupCopyBackupCodesBtn").addEventListener("click", () => {
    navigator.clipboard.writeText(pendingBackupCodes.join("\n"));
  });

  document.getElementById("mfaSetupBackupCodesDoneBtn").addEventListener("click", async () => {
    const me = window.SDApi.getUser();
    await redirectAfterLogin(!!(me && me.is_admin));
  });
})();
