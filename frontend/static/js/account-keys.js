// Profile page: set up, re-protect or replace end-to-end encryption keys.
(function () {
  const status = document.getElementById("keysStatus");
  const setupBtn = document.getElementById("keysSetupBtn");
  const rewrapBtn = document.getElementById("keysRewrapBtn");
  const replaceBtn = document.getElementById("keysReplaceBtn");
  if (!status) return;

  function show(material) {
    setupBtn.hidden = !!material;
    rewrapBtn.hidden = !material;
    replaceBtn.hidden = !material;
    status.textContent = material
      ? `Set up. Key fingerprint: ${material.fingerprint.slice(0, 16).match(/.{4}/g).join(" ")}…`
      : "Not set up yet. Until you do, people can only share with you if this site allows server-held keys.";
  }

  async function load() {
    try { show(await window.SDKeysUI.myMaterial(true)); } catch (e) { show(null); }
  }

  async function create(replace) {
    const answer = await window.SDKeysUI.askPassphrase({
      title: replace ? "New keys and passphrase" : "Choose an encryption passphrase",
      message: "At least 10 characters, different from your login password. You'll need it to open files sent to you.",
      confirm: true, remember: true, submitLabel: replace ? "Replace keys" : "Create keys",
    });
    if (!answer) return;
    status.textContent = "Generating keys…";
    const keys = await window.SDKeys.generate(answer.passphrase);
    const saved = await window.SDApi.raw("/api/account/keys", { method: "PUT", json: keys.material });
    const user = window.SDApi.getUser();
    if (answer.remember && user) await window.SDKeys.remember(user.id, saved.fingerprint, keys.privateKey);
    window.SDToast.show(replace ? "New keys created. Shares and request links using the old key were removed." : "Encryption keys created.", "success");
    load();
  }

  setupBtn.addEventListener("click", () => create(false).catch((e) => window.SDToast.danger(e.message)));
  replaceBtn.addEventListener("click", () => {
    if (!confirm("Replace your keys? Files already shared with you end-to-end, and open request links, will stop working.")) return;
    create(true).catch((e) => window.SDToast.danger(e.message));
  });
  rewrapBtn.addEventListener("click", async () => {
    try {
      const material = await window.SDKeysUI.myMaterial(true);
      const old = await window.SDKeysUI.askPassphrase({ title: "Current encryption passphrase", submitLabel: "Continue" });
      if (!old) return;
      const next = await window.SDKeysUI.askPassphrase({ title: "New encryption passphrase", confirm: true, submitLabel: "Change passphrase" });
      if (!next) return;
      const rewrapped = await window.SDKeys.rewrap(material, old.passphrase, next.passphrase);
      await window.SDApi.raw("/api/account/keys", { method: "PUT", json: rewrapped });
      window.SDToast.show("Encryption passphrase changed. Your keys and shares are unchanged.", "success");
      load();
    } catch (e) {
      window.SDToast.danger(e.message);
    }
  });

  load();
})();
