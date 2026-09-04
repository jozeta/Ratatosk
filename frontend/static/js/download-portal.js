(function () {
  window.SDDownload.guardAnonymousDownload();

  const fileIdInput = document.getElementById("fileIdInput");
  const secretInput = document.getElementById("secretInput");
  const metaInfo = document.getElementById("metaInfo");
  const lookupBtn = document.getElementById("lookupBtn");
  const progressWrap = document.getElementById("progressWrap");
  const progressLabel = document.getElementById("progressLabel");

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
      const meta = await window.SDApi.get(`/api/files/${fileId}/meta`);
      metaInfo.textContent = `${window.SDDownload.humanSize(meta.size_bytes)} · ${window.SDDownload.timeRemaining(meta.expires_at)}`;

      const password = meta.requires_password ? secret : null;
      const urlKey = meta.requires_password ? null : secret;

      progressLabel.textContent = "Downloading...";
      const result = await window.SDDownload.fetchAndDecrypt(fileId, password, urlKey);
      progressLabel.textContent = "Decrypted. Saving...";
      window.SDDownload.saveDecrypted(result);
      showAlert(`Decrypted and saved "${result.name}".`, "success");
    } catch (e) {
      showAlert(e.message || "Lookup failed.");
    } finally {
      lookupBtn.disabled = false;
      progressWrap.style.display = "none";
    }
  });
})();
