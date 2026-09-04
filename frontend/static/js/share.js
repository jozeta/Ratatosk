(function () {
  const fileId = location.pathname.split("/").filter(Boolean).pop();
  const urlKey = location.hash ? location.hash.slice(1) : null;

  const metaCard = document.getElementById("metaCard");
  const metaInfo = document.getElementById("metaInfo");
  const passwordGroup = document.getElementById("passwordGroup");
  const passwordInput = document.getElementById("passwordInput");
  const downloadBtn = document.getElementById("downloadBtn");
  const progressWrap = document.getElementById("progressWrap");
  const progressLabel = document.getElementById("progressLabel");

  function showAlert(message, type = "danger") {
    window.SDToast.show(message, type);
  }

  let meta = null;

  async function init() {
    if (await window.SDDownload.guardAnonymousDownload()) return;
    try {
      meta = await window.SDApi.get(`/api/files/${fileId}/meta`);
    } catch (e) {
      metaInfo.textContent = "This file was not found — it may have expired, been deleted, or reached its download limit.";
      downloadBtn.style.display = "none";
      return;
    }

    metaInfo.textContent = `${window.SDDownload.humanSize(meta.size_bytes)} · ${window.SDDownload.timeRemaining(meta.expires_at)}` +
      (meta.max_downloads ? ` · ${meta.download_count}/${meta.max_downloads} downloads used` : "") +
      (meta.burn_after_download ? " · burns after this download" : "");

    if (meta.requires_password) {
      passwordGroup.style.display = "";
    } else if (!urlKey) {
      showAlert("This link is missing its decryption key fragment.");
      downloadBtn.disabled = true;
      return;
    }
    downloadBtn.disabled = false;
  }

  downloadBtn.addEventListener("click", async () => {
    const password = meta.requires_password ? passwordInput.value : null;
    if (meta.requires_password && !password) {
      showAlert("Enter the passphrase for this file.");
      return;
    }
    downloadBtn.disabled = true;
    progressWrap.style.display = "";
    progressLabel.textContent = "Downloading...";
    try {
      const result = await window.SDDownload.fetchAndDecrypt(fileId, password, urlKey);
      progressLabel.textContent = "Decrypted. Saving...";
      window.SDDownload.saveDecrypted(result);
      showAlert(`Decrypted and saved "${result.name}".`, "success");
    } catch (e) {
      showAlert(e.message || "Download failed.");
    } finally {
      downloadBtn.disabled = false;
      progressWrap.style.display = "none";
    }
  });

  init();
})();
