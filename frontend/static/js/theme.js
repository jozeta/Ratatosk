(function () {
  const KEY = "sd_theme";
  function apply(theme) {
    if (theme === "light" || theme === "dark") {
      document.documentElement.setAttribute("data-theme", theme);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }
  function current() {
    try { return localStorage.getItem(KEY) || "auto"; } catch (e) { return "auto"; }
  }
  function set(theme) {
    try { localStorage.setItem(KEY, theme); } catch (e) {}
    apply(theme);
  }
  apply(current());

  // Inline styles win over both the [data-theme] and @media rules, so setting
  // these custom properties on the root element overrides light/dark alike -
  // that's what lets a custom theme replace the toggle instead of fighting it.
  function applyCustom(cfg) {
    const root = document.documentElement;
    if (!cfg || !cfg.custom_theme_enabled) {
      root.removeAttribute("data-custom-theme");
      return;
    }
    root.style.setProperty("--paper", cfg.custom_theme_paper);
    root.style.setProperty("--surface", cfg.custom_theme_surface);
    root.style.setProperty("--navbar-bg", cfg.custom_theme_navbar_bg);
    root.style.setProperty("--border", cfg.custom_theme_border);
    root.style.setProperty("--text", cfg.custom_theme_text);
    root.style.setProperty("--accent", cfg.custom_theme_accent);
    root.style.setProperty("--surface-2", `color-mix(in srgb, ${cfg.custom_theme_surface} 92%, ${cfg.custom_theme_text} 8%)`);
    root.style.setProperty("--text-muted", `color-mix(in srgb, ${cfg.custom_theme_text} 65%, transparent)`);
    root.style.setProperty("--accent-hover", `color-mix(in srgb, ${cfg.custom_theme_accent} 85%, black)`);
    root.style.setProperty("--accent-soft", `color-mix(in srgb, ${cfg.custom_theme_accent} 15%, ${cfg.custom_theme_surface})`);
    root.style.setProperty("--danger", cfg.custom_theme_danger);
    root.style.setProperty("--heading-color", cfg.custom_theme_heading_color);
    root.style.setProperty("--heading-scale", (cfg.custom_theme_heading_scale || 100) / 100);
    root.style.setProperty("--body-scale", (cfg.custom_theme_body_scale || 100) / 100);
    root.setAttribute("data-custom-theme", "true");
  }

  window.SDTheme = {
    toggle() {
      const now = current();
      const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      const effectiveDark = now === "dark" || (now === "auto" && prefersDark);
      set(effectiveDark ? "light" : "dark");
    },
    current,
    applyCustom,
  };
})();
