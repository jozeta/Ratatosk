(function () {
  function score(password) {
    if (!password) return 0;
    let s = 0;
    s += Math.min(password.length, 16) * 4;
    if (/[a-z]/.test(password)) s += 5;
    if (/[A-Z]/.test(password)) s += 5;
    if (/[0-9]/.test(password)) s += 5;
    if (/[^A-Za-z0-9]/.test(password)) s += 10;
    if (password.length >= 12) s += 10;
    return Math.min(s, 100);
  }

  function label(pct) {
    if (pct < 30) return { text: "Weak", cls: "weak" };
    if (pct < 60) return { text: "Fair", cls: "fair" };
    if (pct < 85) return { text: "Good", cls: "good" };
    return { text: "Strong", cls: "strong" };
  }

  function checkPolicy(password, cfg) {
    return [
      { text: `At least ${cfg.password_min_length || 8} characters`, met: password.length >= (cfg.password_min_length || 8) },
      { text: "An uppercase letter", met: !cfg.password_require_uppercase || /[A-Z]/.test(password), required: !!cfg.password_require_uppercase },
      { text: "A lowercase letter", met: !cfg.password_require_lowercase || /[a-z]/.test(password), required: !!cfg.password_require_lowercase },
      { text: "A number", met: !cfg.password_require_number || /[0-9]/.test(password), required: !!cfg.password_require_number },
      { text: "A special character", met: !cfg.password_require_special || /[^A-Za-z0-9]/.test(password), required: !!cfg.password_require_special },
    ].filter((r) => r.required || r.text.startsWith("At least"));
  }

  /**
   * Wires a password <input> to a strength bar + policy checklist.
   * @param {HTMLInputElement} input
   * @param {HTMLElement} barFillEl
   * @param {HTMLElement} labelEl
   * @param {HTMLElement} checklistEl
   * @param {object} cfg - from /api/config (password_min_length, password_require_*)
   */
  function attach(input, barFillEl, labelEl, checklistEl, cfg) {
    function render() {
      const pw = input.value;
      const pct = score(pw);
      const { text, cls } = label(pct);
      barFillEl.style.width = pw ? pct + "%" : "0%";
      barFillEl.className = "strength-fill " + (pw ? cls : "");
      labelEl.textContent = pw ? text : "";

      if (checklistEl) {
        const rules = checkPolicy(pw, cfg);
        checklistEl.innerHTML = "";
        for (const rule of rules) {
          const li = document.createElement("li");
          li.textContent = (rule.met ? "✓ " : "○ ") + rule.text;
          li.className = rule.met ? "met" : "unmet";
          checklistEl.appendChild(li);
        }
      }
    }
    input.addEventListener("input", render);
    render();
  }

  window.SDPasswordStrength = { score, label, checkPolicy, attach };
})();
