(function () {
  function humanSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    const units = ["KB", "MB", "GB"];
    let val = bytes;
    for (const u of units) {
      val /= 1024;
      if (val < 1024) return val.toFixed(1) + " " + u;
    }
    return val.toFixed(1) + " TB";
  }

  function timeRemaining(expiresAtIso) {
    const diffMs = new Date(expiresAtIso).getTime() - Date.now();
    if (diffMs <= 0) return "expired";
    const mins = Math.floor(diffMs / 60000);
    if (mins < 60) return `${mins}m remaining`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h remaining`;
    return `${Math.floor(hrs / 24)}d remaining`;
  }

  async function fetchAndDecrypt(fileId, password, urlKey) {
    const headers = {};
    if (password) headers["X-Secondary-Password"] = password;
    const token = window.SDApi.getToken();
    if (token) headers["Authorization"] = "Bearer " + token;
    const res = await fetch(`/api/files/${fileId}/blob`, { headers });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    const buf = await res.arrayBuffer();
    return window.SDCrypto.decryptDownload(buf, urlKey, password);
  }

  function saveDecrypted(result) {
    const blob = new Blob([result.fileBytes], { type: result.type || "application/octet-stream" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = result.name || "download";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  async function guardAnonymousDownload() {
    if (window.SDApi.isLoggedIn()) return false;
    try {
      const cfg = await window.SDApi.get("/api/config");
      if (!cfg.allow_anonymous_download) {
        window.location.href = "/login";
        return true;
      }
    } catch (e) { /* config fetch failing shouldn't block the page */ }
    return false;
  }

  window.SDDownload = { humanSize, timeRemaining, fetchAndDecrypt, saveDecrypted, guardAnonymousDownload };
})();
