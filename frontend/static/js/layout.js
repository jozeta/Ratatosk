(function () {
  const DEFAULT_BRAND_NAME = "Ratatosk";
  const DEFAULT_FOOTER_TEXT = "Zero-knowledge encryption happens entirely in your browser. The server never sees your files, filenames, or decryption keys.";

  function setOpen(dropdown, open) {
    dropdown.classList.toggle("open", open);
    const toggle = dropdown.querySelector(".dropdown-toggle");
    if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function closeAllDropdowns(except) {
    document.querySelectorAll(".dropdown.open").forEach((d) => {
      if (d !== except) setOpen(d, false);
    });
  }

  function menuItems(dropdown) {
    return Array.from(dropdown.querySelectorAll(".dropdown-menu a"));
  }

  // Menu-button keyboard pattern (UI-005): Enter/Space/ArrowDown open and
  // focus the first item, arrows move, Home/End jump, Escape closes and
  // returns focus to the toggle, Tab leaves the menu.
  function wireDropdowns(root) {
    root.querySelectorAll(".dropdown").forEach((dropdown) => {
      const toggle = dropdown.querySelector(".dropdown-toggle");
      const menu = dropdown.querySelector(".dropdown-menu");
      if (!toggle || !menu) return;
      const menuId = "sd-menu-" + Math.random().toString(36).slice(2, 8);
      menu.id = menuId;
      menu.setAttribute("role", "menu");
      menuItems(dropdown).forEach((a) => { a.setAttribute("role", "menuitem"); a.tabIndex = -1; });
      toggle.setAttribute("aria-haspopup", "menu");
      toggle.setAttribute("aria-controls", menuId);
      toggle.setAttribute("aria-expanded", "false");

      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        const wasOpen = dropdown.classList.contains("open");
        closeAllDropdowns();
        setOpen(dropdown, !wasOpen);
      });
      toggle.addEventListener("keydown", (e) => {
        if (["ArrowDown", "Enter", " "].includes(e.key)) {
          e.preventDefault();
          closeAllDropdowns();
          setOpen(dropdown, true);
          const items = menuItems(dropdown);
          if (items.length) items[0].focus();
        }
      });
      menu.addEventListener("keydown", (e) => {
        const items = menuItems(dropdown);
        const idx = items.indexOf(document.activeElement);
        if (e.key === "ArrowDown") { e.preventDefault(); items[(idx + 1) % items.length].focus(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); items[(idx - 1 + items.length) % items.length].focus(); }
        else if (e.key === "Home") { e.preventDefault(); items[0].focus(); }
        else if (e.key === "End") { e.preventDefault(); items[items.length - 1].focus(); }
        else if (e.key === "Escape") { e.preventDefault(); setOpen(dropdown, false); toggle.focus(); }
        else if (e.key === "Tab") { setOpen(dropdown, false); }
      });
    });
    document.addEventListener("click", () => closeAllDropdowns());
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeAllDropdowns();
    });
  }

  // Small DOM builder: the nav bar is assembled with DOM APIs rather than an
  // HTML string, so no user-controlled value (brand name, username) can ever
  // be parsed as markup.
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "className") el.className = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return el;
  }

  function lockMark() {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    for (const [k, v] of Object.entries({ class: "brand-mark", width: "20", height: "20", viewBox: "0 0 24 24", fill: "none", "aria-hidden": "true" })) svg.setAttribute(k, v);
    const parts = [
      ["rect", { x: "5", y: "11", width: "14", height: "10", rx: "2", stroke: "currentColor", "stroke-width": "1.6" }],
      ["path", { d: "M8 11V7.5a4 4 0 0 1 8 0V11", stroke: "currentColor", "stroke-width": "1.6", "stroke-linecap": "round" }],
      ["circle", { cx: "12", cy: "15.5", r: "1.4", fill: "currentColor" }],
    ];
    for (const [tag, attrs] of parts) {
      const el = document.createElementNS(NS, tag);
      for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
      svg.appendChild(el);
    }
    return svg;
  }

  function brandLink(cfg) {
    const mark = cfg && cfg.brand_logo_filename
      ? h("img", { className: "brand-mark", src: `/api/branding/logo?v=${encodeURIComponent(cfg.brand_logo_filename)}`, alt: "" })
      : lockMark();
    return h("a", { href: "/", className: "brand" }, mark, h("span", { className: "brand-name" }, (cfg && cfg.brand_name) || DEFAULT_BRAND_NAME));
  }

  function renderNavbar(cfg) {
    const el = document.getElementById("sd-navbar");
    if (!el) return;
    const user = window.SDApi.getUser();
    const loggedIn = window.SDApi.isLoggedIn();
    const isAdmin = window.SDApi.isAdmin();

    // An anonymous visitor would just be bounced to /login if the matching
    // anonymous_* setting is off, so hide those links outright.
    const nav = h("nav", { "aria-label": "Main" });
    if (!cfg.hide_upload_link && (loggedIn || cfg.allow_anonymous_upload)) nav.appendChild(h("a", { href: "/" }, "Upload"));
    if (!cfg.hide_download_link && (loggedIn || cfg.allow_anonymous_download)) nav.appendChild(h("a", { href: "/download" }, "Download"));

    if (loggedIn) {
      const menu = h("div", { className: "dropdown-menu" },
        h("a", { href: "/files" }, "My Files"),
        cfg.enable_user_sharing ? h("a", { href: "/shared" }, "Shared With Me") : null,
        cfg.enable_upload_requests ? h("a", { href: "/requests" }, "Request Links") : null,
        h("a", { href: "/account" }, "Profile"));
      if (isAdmin) {
        menu.append(
          h("div", { className: "dropdown-divider", role: "separator" }),
          h("div", { className: "dropdown-label" }, "Configuration"),
          h("a", { href: "/admin/settings" }, "Settings"),
          h("div", { className: "dropdown-label" }, "People & Content"),
          cfg.enable_user_management ? h("a", { href: "/admin/users" }, "User Management") : "",
          cfg.enable_file_management ? h("a", { href: "/admin/files" }, "File Management") : "",
          h("div", { className: "dropdown-label" }, "Monitoring"),
          h("a", { href: "/admin/stats" }, "Statistics"),
          h("a", { href: "/admin/audit" }, "Audit Log"),
        );
      }
      const logout = h("a", { href: "#", id: "sd-logout" }, "Logout");
      logout.addEventListener("click", async (e) => {
        e.preventDefault();
        await window.SDApi.logout();
        window.location.href = "/";
      });
      menu.append(h("div", { className: "dropdown-divider", role: "separator" }), logout);
      nav.appendChild(h("div", { className: "dropdown", id: "accountDropdown" },
        h("button", { className: "dropdown-toggle", type: "button" }, (user ? user.username : "Account") + " ",
          h("span", { className: "caret", "aria-hidden": "true" }, "▾")),
        menu));
    } else if (cfg.allow_user_login) {
      nav.appendChild(h("a", { href: "/login" }, "Login"));
    }

    if (!cfg.custom_theme_enabled) {
      const toggle = h("button", { className: "theme-toggle", id: "sd-theme-toggle", type: "button",
        title: "Toggle dark/light theme", "aria-label": "Toggle dark or light theme" }, h("span", { "aria-hidden": "true" }, "🌓"));
      toggle.addEventListener("click", () => window.SDTheme.toggle());
      nav.appendChild(toggle);
    }
    el.replaceChildren(brandLink(cfg), nav);
    wireDropdowns(el);
  }

  function renderFooter(cfg) {
    const el = document.getElementById("sd-footer");
    if (!el) return;
    el.textContent = "";
    const text = document.createElement("div");
    text.textContent = (cfg && cfg.footer_text) || DEFAULT_FOOTER_TEXT;
    const meta = document.createElement("div");
    meta.className = "footer-meta";
    const about = document.createElement("a");
    about.href = "/about";
    about.textContent = "About";
    meta.appendChild(about);
    if (cfg && cfg.version) {
      const v = document.createElement("span");
      v.className = "footer-version";
      v.textContent = ` · Ratatosk v${cfg.version}`;
      meta.appendChild(v);
    }
    el.appendChild(text);
    el.appendChild(meta);
  }

  document.addEventListener("DOMContentLoaded", async () => {
    let cfg = { allow_user_login: true, allow_user_registration: true };
    try {
      cfg = await window.SDApi.config();
    } catch (e) { /* fall back to defaults */ }
    renderNavbar(cfg);
    renderFooter(cfg);
    window.SDTheme.applyCustom(cfg);
  });
})();
