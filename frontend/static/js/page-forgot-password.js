// Page script for /forgot-password - kept out of the HTML so the
// Content-Security-Policy can forbid inline scripts entirely (SEC-009).
(function () {
  const form = document.getElementById("forgotForm");
  const submitBtn = document.getElementById("submitBtn");
  const sentNotice = document.getElementById("sentNotice");

  window.SDApi.get("/api/config").then((cfg) => {
    if (!cfg.password_reset_enabled) {
      document.getElementById("forgotFormCard").hidden = true;
      document.getElementById("resetDisabledNotice").hidden = false;
    }
  }).catch(() => {});

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    try {
      await window.SDApi.post("/api/auth/forgot-password", {
        identifier: document.getElementById("identifier").value.trim(),
      });
      form.hidden = true;
      sentNotice.hidden = false;
    } catch (err) {
      window.SDToast.danger(err.message);
      submitBtn.disabled = false;
    }
  });
})();
