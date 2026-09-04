(function () {
  const TOKEN_KEY = "sd_token";
  const USER_KEY = "sd_user";

  function getToken() {
    try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; }
  }
  function setSession(token, user) {
    try {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    } catch (e) {}
  }
  function clearSession() {
    try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); } catch (e) {}
  }
  function getUser() {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch (e) { return null; }
  }

  async function request(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {});
    const token = getToken();
    if (token) headers["Authorization"] = "Bearer " + token;
    if (opts.json !== undefined) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
    }
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) {
      clearSession();
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

  window.SDApi = {
    get: (path) => request(path, { method: "GET" }),
    post: (path, json) => request(path, { method: "POST", json }),
    patch: (path, json) => request(path, { method: "PATCH", json }),
    del: (path) => request(path, { method: "DELETE" }),
    postFile: (path, formData) => request(path, { method: "POST", body: formData }),
    raw: request,
    getToken, setSession, clearSession, getUser,
    isLoggedIn: () => !!getToken(),
    isAdmin: () => { const u = getUser(); return !!(u && u.is_admin); },
  };
})();
