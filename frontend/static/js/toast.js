(function () {
  let stack = null;

  function ensureStack() {
    if (stack) return stack;
    stack = document.createElement("div");
    stack.className = "toast-stack";
    stack.setAttribute("role", "status");
    stack.setAttribute("aria-live", "polite");
    document.body.appendChild(stack);
    return stack;
  }

  function show(message, type = "info", duration = 5000) {
    const container = ensureStack();
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;

    const text = document.createElement("span");
    text.className = "toast-text";
    text.textContent = message;

    const closeBtn = document.createElement("button");
    closeBtn.className = "toast-close";
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "Dismiss");
    closeBtn.textContent = "×";

    toast.appendChild(text);
    toast.appendChild(closeBtn);
    container.appendChild(toast);

    let dismissed = false;
    function dismiss() {
      if (dismissed) return;
      dismissed = true;
      toast.classList.add("toast-leaving");
      setTimeout(() => toast.remove(), 180);
    }
    closeBtn.addEventListener("click", dismiss);
    if (duration > 0) setTimeout(dismiss, duration);

    // Force layout then add the "entered" class so the CSS transition runs.
    requestAnimationFrame(() => requestAnimationFrame(() => toast.classList.add("toast-in")));

    return { dismiss };
  }

  window.SDToast = {
    show,
    info: (msg, duration) => show(msg, "info", duration),
    success: (msg, duration) => show(msg, "success", duration),
    danger: (msg, duration) => show(msg, "danger", duration),
  };
})();
