(function () {
  if (!window.SDApi.isAdmin()) {
    window.location.href = "/login";
    return;
  }

  const TOTAL_STEPS = 3;
  let step = 1;
  let cfg = null;

  const FIELDS = [
    "brand_name", "footer_text",
    "allow_anonymous_upload", "allow_anonymous_download", "allow_user_registration",
    "enable_login_rate_limit",
  ];
  const CHECKBOX_FIELDS = new Set([
    "allow_anonymous_upload", "allow_anonymous_download", "allow_user_registration",
    "enable_login_rate_limit",
  ]);

  function showAlert(message, type) {
    window.SDToast.show(message, type);
  }

  function populate() {
    for (const field of FIELDS) {
      const el = document.getElementById(field);
      if (!el) continue;
      if (CHECKBOX_FIELDS.has(field)) el.checked = !!cfg[field];
      else el.value = cfg[field] || "";
    }
    document.getElementById("brandPreviewName").textContent = cfg.brand_name || "SecureDrop";
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
      out[field] = CHECKBOX_FIELDS.has(field) ? el.checked : el.value;
    }
    return out;
  }

  const REVIEW_LABELS = {
    brand_name: "Brand name",
    footer_text: "Footer text",
    allow_anonymous_upload: "Anonymous uploading",
    allow_anonymous_download: "Anonymous downloading",
    allow_user_registration: "Public user registration",
    enable_login_rate_limit: "Account login rate limiting",
  };

  function renderReview() {
    const body = document.getElementById("reviewBody");
    body.innerHTML = "";
    const collected = collect();
    for (const field of FIELDS) {
      const row = document.createElement("tr");
      const label = document.createElement("td");
      label.textContent = REVIEW_LABELS[field];
      const value = document.createElement("td");
      const val = collected[field];
      value.textContent = CHECKBOX_FIELDS.has(field) ? (val ? "On" : "Off") : (val || "—");
      row.appendChild(label);
      row.appendChild(value);
      body.appendChild(row);
    }
  }

  function renderStep() {
    for (let i = 1; i <= TOTAL_STEPS; i++) {
      const panel = document.querySelector(`[data-panel="${i}"]`);
      if (panel) panel.hidden = i !== step;
      const nav = document.querySelector(`.setup-step[data-step="${i}"]`);
      if (nav) {
        nav.classList.toggle("active", i === step);
        nav.classList.toggle("done", i < step);
      }
    }
    document.getElementById("backBtn").hidden = step === 1;
    document.getElementById("nextBtn").hidden = step === TOTAL_STEPS;
    document.getElementById("finishBtn").hidden = step !== TOTAL_STEPS;
    if (step === TOTAL_STEPS) renderReview();
  }

  document.getElementById("nextBtn").addEventListener("click", () => {
    if (step < TOTAL_STEPS) { step += 1; renderStep(); }
  });
  document.getElementById("backBtn").addEventListener("click", () => {
    if (step > 1) { step -= 1; renderStep(); }
  });

  document.getElementById("finishBtn").addEventListener("click", async () => {
    try {
      const payload = collect();
      payload.setup_completed = true;
      await window.SDApi.patch("/api/admin/settings", payload);
      showAlert("Setup complete.", "success");
      window.location.href = "/admin/settings";
    } catch (e) {
      showAlert(e.message, "danger");
    }
  });

  document.getElementById("skipLink").addEventListener("click", async (e) => {
    e.preventDefault();
    try {
      await window.SDApi.patch("/api/admin/settings", { setup_completed: true });
      window.location.href = "/admin/settings";
    } catch (err) {
      showAlert(err.message, "danger");
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
      cfg = await window.SDApi.get("/api/admin/settings");
      populate();
    } catch (err) {
      showAlert(err.message, "danger");
    } finally {
      logoFileInput.value = "";
    }
  });
  document.getElementById("logoRemoveBtn").addEventListener("click", async () => {
    try {
      await window.SDApi.del("/api/admin/branding/logo");
      showAlert("Logo removed.", "success");
      cfg = await window.SDApi.get("/api/admin/settings");
      populate();
    } catch (err) {
      showAlert(err.message, "danger");
    }
  });

  async function load() {
    try {
      cfg = await window.SDApi.get("/api/admin/settings");
      populate();
      renderStep();
    } catch (e) {
      showAlert(e.message, "danger");
    }
  }

  load();
})();
