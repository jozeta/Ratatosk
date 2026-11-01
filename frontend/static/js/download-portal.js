(function () {
  window.SDDownload.guardAnonymousDownload();

  const fileIdInput = document.getElementById("fileIdInput");
  const secretInput = document.getElementById("secretInput");
  const metaInfo = document.getElementById("metaInfo");
  const lookupBtn = document.getElementById("lookupBtn");
  const progressWrap = document.getElementById("progressWrap");
  const progressLabel = document.getElementById("progressLabel");
  const progressBar = document.getElementById("progressBar");
  const resultView = document.getElementById("resultView");

  function showAlert(message, type = "danger") {
    window.SDToast.show(message, type);
  }
  function clearAlert() {}

  lookupBtn.addEventListener("click", async () => {
    clearAlert();
    const fileId = fileIdInput.value.trim();
    const secret = secretInput.value.trim();
    if (!fileId || !secret) {
      showAlert("Enter both the File ID and the key/passphrase.");
      return;
    }

    lookupBtn.disabled = true;
    progressWrap.style.display = "";
    progressLabel.textContent = "Looking up file...";

    try {
      const meta = await window.SDDownload.fetchMeta(fileId);
      metaInfo.textContent = `${window.SDDownload.humanSize(meta.size_bytes)} · ${window.SDDownload.timeRemaining(meta.expires_at)}`;

      const password = meta.requires_password ? secret : null;
      const urlKey = meta.requires_password ? null : secret;
      if (!window.SDDownload.confirmDestructive(meta)) return;

      progressBar.style.width = "0%";
      progressLabel.textContent = "Checking key...";
      const result = await window.SDDownload.fetchAndDecrypt(fileId, password, urlKey, {
        meta,
        onProgress: (f) => {
          progressBar.style.width = `${Math.round(f * 100)}%`;
          progressLabel.textContent = `Downloading and decrypting... ${Math.round(f * 100)}%`;
        },
      });
      if (result.kind === "text") {
        await window.SDDownload.renderText(result, resultView);
      } else if (result.kind === "bundle") {
        await window.SDDownload.renderBundle(result, resultView);
      } else {
        progressLabel.textContent = "Decrypted. Saving...";
        window.SDDownload.saveDecrypted(result);
        showAlert(`Decrypted and saved "${result.name}".`, "success");
      }
    } catch (e) {
      showAlert(e.message || "Lookup failed.");
    } finally {
      lookupBtn.disabled = false;
      progressWrap.style.display = "none";
    }
  });
})();
