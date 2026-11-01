// Page script for /reset-password - kept out of the HTML so the
// Content-Security-Policy can forbid inline scripts entirely (SEC-009).
(function () {
  const token = new URLSearchParams(window.location.search).get("token");
  const form = document.getElementById("resetForm");
  const submitBtn = document.getElementById("submitBtn");
  const doneNotice = document.getElementById("doneNotice");

  if (!token) {
    document.getElementById("noTokenNotice").hidden = false;
    form.hidden = true;
  }

  window.SDApi.get("/api/config").then((cfg) => {
    window.SDPasswordStrength.attach(
      document.getElementById("newPassword"),
      document.getElementById("strengthFill"),
      document.getElementById("strengthLabel"),
      document.getElementById("policyChecklist"),
      cfg
    );
  }).catch(() => {});

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const newPassword = document.getElementById("newPassword").value;
    const confirmPassword = document.getElementById("confirmPassword").value;
    if (newPassword !== confirmPassword) {
      window.SDToast.danger("Passwords don't match.");
      return;
    }
    submitBtn.disabled = true;
    try {
      await window.SDApi.post("/api/auth/reset-password", { token, new_password: newPassword });
      form.hidden = true;
      doneNotice.hidden = false;
    } catch (err) {
      window.SDToast.danger(err.message);
      submitBtn.disabled = false;
    }
  });
})();
