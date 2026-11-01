// About page: fills in the running version and the instance's own name.
(function () {
  window.SDApi.config().then((cfg) => {
    document.getElementById("aboutVersion").textContent = cfg.version || "unknown";
    if (cfg.brand_name && cfg.brand_name !== "Ratatosk") {
      document.getElementById("aboutInstance").textContent = ` · this instance is called "${cfg.brand_name}"`;
    }
  }).catch(() => {
    document.getElementById("aboutVersion").textContent = "unknown";
  });
  document.getElementById("verifyOrigin").textContent = location.origin;
  fetch("/api/integrity").then((r) => r.json()).then((m) => {
    document.getElementById("verifyVersion").textContent = m.version;
    document.getElementById("verifyDigest").textContent = m.release_digest;
  }).catch(() => { document.getElementById("verifyDigest").textContent = "unavailable"; });
})();
