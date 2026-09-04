(function () {
  const DEFAULT_BRAND_NAME = "SecureDrop";
  const DEFAULT_FOOTER_TEXT = "Zero-knowledge encryption happens entirely in your browser. The server never sees your files, filenames, or decryption keys.";

  // Default mark: a simple padlock, used whenever no custom logo is uploaded.
  const LOCK_MARK_SVG = `<svg class="brand-mark" width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <rect x="5" y="11" width="14" height="10" rx="2" stroke="currentColor" stroke-width="1.6"/>
    <path d="M8 11V7.5a4 4 0 0 1 8 0V11" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
    <circle cx="12" cy="15.5" r="1.4" fill="currentColor"/>
  </svg>`;

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  function closeAllDropdowns(except) {
    document.querySelectorAll(".dropdown.open").forEach((d) => {
      if (d !== except) d.classList.remove("open");
    });
  }

  function wireDropdowns(root) {
    root.querySelectorAll(".dropdown").forEach((dropdown) => {
      const toggle = dropdown.querySelector(".dropdown-toggle");
      if (!toggle) return;
      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        const wasOpen = dropdown.classList.contains("open");
        closeAllDropdowns();
        dropdown.classList.toggle("open", !wasOpen);
      });
    });
    document.addEventListener("click", () => closeAllDropdowns());
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeAllDropdowns();
    });
  }

  function brandMarkup(cfg) {
    const name = escapeHtml((cfg && cfg.brand_name) || DEFAULT_BRAND_NAME);
    const mark = cfg && cfg.brand_logo_filename
      ? `<img class="brand-mark" src="/api/branding/logo?v=${encodeURIComponent(cfg.brand_logo_filename)}" alt="">`
      : LOCK_MARK_SVG;
    return `${mark}<span class="brand-name">${name}</span>`;
  }

  function renderNavbar(cfg) {
    const el = document.getElementById("sd-navbar");
    if (!el) return;
    const user = window.SDApi.getUser();
    const loggedIn = window.SDApi.isLoggedIn();
    const isAdmin = window.SDApi.isAdmin();

    // Primary actions stay flat and visible; personal/admin pages group into dropdowns
    // so the bar doesn't grow a new top-level link every time a feature is added.
    // An anonymous visitor would just get bounced to /login on click if the
    // matching anonymous_* setting is off, so hide the link outright instead
    // of showing a dead end - logged-in users can always see both, since the
    // setting only gates anonymous access.
    let links = "";
    if (!cfg.hide_upload_link && (loggedIn || cfg.allow_anonymous_upload)) links += `<a href="/">Upload</a>`;
    if (!cfg.hide_download_link && (loggedIn || cfg.allow_anonymous_download)) links += `<a href="/download">Download</a>`;

    if (loggedIn) {
      let accountMenu = `<a href="/files">My Files</a>${cfg.enable_user_sharing ? `<a href="/shared">Shared With Me</a>` : ""}<a href="/account">Profile</a>`;

      if (isAdmin) {
        accountMenu += `
          <div class="dropdown-divider"></div>
          <div class="dropdown-label">Configuration</div>
          <a href="/admin/settings">Settings</a>
          <div class="dropdown-label">People &amp; Content</div>
          ${cfg.enable_user_management ? `<a href="/admin/users">User Management</a>` : ""}
          ${cfg.enable_file_management ? `<a href="/admin/files">File Management</a>` : ""}
          <div class="dropdown-label">Monitoring</div>
          <a href="/admin/stats">Statistics</a>
          <a href="/admin/audit">Audit Log</a>`;
      }

      accountMenu += `<div class="dropdown-divider"></div><a href="#" id="sd-logout">Logout</a>`;

      links += `
        <div class="dropdown" id="accountDropdown">
          <button class="dropdown-toggle" type="button">${escapeHtml(user ? user.username : "Account")} <span class="caret">▾</span></button>
          <div class="dropdown-menu">${accountMenu}</div>
        </div>`;
    } else {
      if (cfg.allow_user_login) links += `<a href="/login">Login</a>`;
    }

    const themeToggle = cfg.custom_theme_enabled
      ? ""
      : `<button class="theme-toggle" id="sd-theme-toggle" title="Toggle dark/light">🌓</button>`;
    el.innerHTML = `
      <a href="/" class="brand">${brandMarkup(cfg)}</a>
      <nav>${links}${themeToggle}</nav>
    `;

    const logout = document.getElementById("sd-logout");
    if (logout) {
      logout.addEventListener("click", (e) => {
        e.preventDefault();
        window.SDApi.clearSession();
        window.location.href = "/";
      });
    }
    const toggleBtn = document.getElementById("sd-theme-toggle");
    if (toggleBtn) toggleBtn.addEventListener("click", () => window.SDTheme.toggle());
    wireDropdowns(el);
  }

  function renderFooter(cfg) {
    const el = document.getElementById("sd-footer");
    if (!el) return;
    el.textContent = (cfg && cfg.footer_text) || DEFAULT_FOOTER_TEXT;
  }

  document.addEventListener("DOMContentLoaded", async () => {
    let cfg = { allow_user_login: true, allow_user_registration: true };
    try {
      cfg = await window.SDApi.get("/api/config");
    } catch (e) { /* fall back to defaults */ }
    renderNavbar(cfg);
    renderFooter(cfg);
    window.SDTheme.applyCustom(cfg);
  });
})();
