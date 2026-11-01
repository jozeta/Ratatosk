// Page script for /register - kept out of the HTML so the
// Content-Security-Policy can forbid inline scripts entirely (SEC-009).
(function () {
  const form = document.getElementById("registerForm");
  const passwordInput = document.getElementById("password");
  let cfg = { password_min_length: 8 };

  window.SDApi.get("/api/config").then((c) => {
    cfg = c;
    if (!cfg.allow_user_registration) {
      document.getElementById("registerFormCard").hidden = true;
      document.getElementById("registerDisabledNotice").hidden = false;
      return;
    }
    window.SDPasswordStrength.attach(
      passwordInput,
      document.getElementById("strengthFill"),
      document.getElementById("strengthLabel"),
      document.getElementById("policyChecklist"),
      cfg
    );
  }).catch(() => {
    window.SDPasswordStrength.attach(passwordInput, document.getElementById("strengthFill"), document.getElementById("strengthLabel"), document.getElementById("policyChecklist"), cfg);
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await window.SDApi.post("/api/auth/register", {
        username: document.getElementById("username").value,
        email: document.getElementById("email").value.trim() || null,
        password: passwordInput.value,
      });
      if (res.access_token) {
        window.SDApi.setSession(res.access_token, { id: res.id, username: res.username, is_admin: res.is_admin });
        window.location.href = "/files";
      } else if (res.mfa_setup_required) {
        // Same policy as login (SEC-007): two-factor must be set up before
        // the first session. The login page walks through it.
        window.location.href = "/login?registered=mfa";
      } else {
        window.location.href = "/login?registered=1";
      }
    } catch (err) {
      window.SDToast.danger(err.message);
    }
  });
})();
