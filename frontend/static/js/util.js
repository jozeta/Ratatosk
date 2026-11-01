/* Small helpers shared by several pages (ARCH-003: these were duplicated). */
(function () {
  function humanSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    const units = ["KB", "MB", "GB", "TB"];
    let val = bytes;
    for (const u of units) {
      val /= 1024;
      if (val < 1024 || u === "TB") return val.toFixed(1) + " " + u;
    }
    return val.toFixed(1) + " TB";
  }

  /**
   * Copy text with visible feedback (UI-006). On success the button briefly
   * reads "Copied ✓"; if the clipboard is unavailable (plain-HTTP
   * deployments, denied permission) the source field is selected and the
   * user is told how to copy by hand - never a silent failure.
   */
  async function copyText(text, button, sourceInput) {
    const original = button ? button.textContent : null;
    try {
      if (!navigator.clipboard || !window.isSecureContext) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(text);
      if (button) {
        button.textContent = "Copied ✓";
        setTimeout(() => { button.textContent = original; }, 1500);
      }
      if (window.SDToast) window.SDToast.show("Copied to clipboard.", "success");
    } catch (e) {
      if (sourceInput && sourceInput.select) { sourceInput.focus(); sourceInput.select(); }
      const mac = /Mac|iPhone|iPad/.test(navigator.platform || "");
      if (window.SDToast) window.SDToast.show(`Couldn't copy automatically - press ${mac ? "⌘" : "Ctrl"}+C to copy.`, "warning");
    }
  }

  window.SDUtil = { humanSize, copyText };
})();
