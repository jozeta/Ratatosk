(function () {
  // The session token lives in an HttpOnly cookie the server sets (SEC-017):
  // page scripts - including any injected one - can't read it. Only the
  // non-secret user summary (id, name, admin flag) is kept here, for the UI.
  const LEGACY_TOKEN_KEY = "sd_token";
  const USER_KEY = "sd_user";
  // Required by the server for cookie-authenticated requests that change
  // state; a cross-site page can't send custom headers.
  const CSRF_HEADER = "X-Ratatosk-CSRF";

  try { localStorage.removeItem(LEGACY_TOKEN_KEY); } catch (e) { /* pre-2.1 token: never kept again */ }

  function getToken() { return null; } // kept for older callers; the token is no longer script-readable
  function setSession(token, user) {
    try { localStorage.setItem(USER_KEY, JSON.stringify(user)); } catch (e) {}
  }
  function clearSession() {
    try { localStorage.removeItem(USER_KEY); localStorage.removeItem(LEGACY_TOKEN_KEY); } catch (e) {}
  }
  function getUser() {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch (e) { return null; }
  }

  async function request(path, opts = {}) {
    const headers = Object.assign({ [CSRF_HEADER]: "1" }, opts.headers || {});
    if (opts.json !== undefined) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
    }
    const res = await fetch(path, { ...opts, headers, credentials: "same-origin" });
    if (res.status === 401 && getUser() && !opts.keepSessionOn401) {
      clearSession(); // the cookie expired or was revoked
    }
    const contentType = res.headers.get("content-type") || "";
    let data = null;
    if (contentType.includes("application/json")) {
      data = await res.json().catch(() => null);
    }
    if (!res.ok) {
      const detail = (data && data.detail) || res.statusText || "Request failed";
      const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data !== null ? data : res;
  }

  // One shared /api/config request per page load, however many scripts ask
  // for it (PERF-007).
  let configPromise = null;
  function config() {
    if (!configPromise) {
      configPromise = request("/api/config", { method: "GET" }).catch((e) => { configPromise = null; throw e; });
    }
    return configPromise;
  }

  // Revoke the session server-side, then forget it here (SEC-017).
  async function logout() {
    try { await request("/api/auth/logout", { method: "POST", json: {} }); } catch (e) { /* already invalid */ }
    clearSession();
    // Forget any encryption keys remembered on this device (FEAT-002).
    try { indexedDB.deleteDatabase("ratatosk-keys"); } catch (e) { /* not available */ }
  }

  window.SDApi = {
    get: (path) => (path === "/api/config" ? config() : request(path, { method: "GET" })),
    post: (path, json) => request(path, { method: "POST", json }),
    patch: (path, json) => request(path, { method: "PATCH", json }),
    del: (path, json) => request(path, json === undefined ? { method: "DELETE" } : { method: "DELETE", json }),
    postFile: (path, formData) => request(path, { method: "POST", body: formData }),
    raw: request,
    config,
    logout,
    getToken, setSession, clearSession, getUser,
    CSRF_HEADER,
    isLoggedIn: () => !!getUser(),
    isAdmin: () => { const u = getUser(); return !!(u && u.is_admin); },
  };
})();
