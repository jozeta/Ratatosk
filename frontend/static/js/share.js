(function () {
  const fileId = location.pathname.split("/").filter(Boolean).pop();
  const urlKey = location.hash ? location.hash.slice(1) : null;

  const metaInfo = document.getElementById("metaInfo");
  const passwordGroup = document.getElementById("passwordGroup");
  const passwordInput = document.getElementById("passwordInput");
  const downloadBtn = document.getElementById("downloadBtn");
  const progressWrap = document.getElementById("progressWrap");
  const progressBar = document.getElementById("progressBar");
  const progressLabel = document.getElementById("progressLabel");
  const resultView = document.getElementById("resultView");
  const heading = document.querySelector("#metaCard h2");

  function showAlert(message, type = "danger") {
    window.SDToast.show(message, type);
  }

  let meta = null;

  async function init() {
    if (await window.SDDownload.guardAnonymousDownload()) return;
    try {
      meta = await window.SDDownload.fetchMeta(fileId);
    } catch (e) {
      metaInfo.textContent = "This file was not found — it may have expired, been deleted, or reached its download limit.";
      downloadBtn.style.display = "none";
      return;
    }

    const last = meta.burn_after_download || (meta.max_downloads && meta.download_count + 1 >= meta.max_downloads);
    metaInfo.textContent = `${window.SDDownload.humanSize(meta.size_bytes)} · ${window.SDDownload.timeRemaining(meta.expires_at)}` +
      (meta.max_downloads ? ` · ${meta.download_count}/${meta.max_downloads} downloads used` : "") +
      (last ? " · deleted after this download" : "");

    if (meta.requires_password) {
      passwordGroup.style.display = "";
      passwordInput.focus();
    } else if (!urlKey) {
      showAlert("This link is missing its decryption key (the part after #). Ask the sender for the complete link.");
      downloadBtn.disabled = true;
      return;
    }
    downloadBtn.disabled = false;
  }

  function setProgress(fraction, label) {
    progressBar.style.width = `${Math.round(fraction * 100)}%`;
    progressBar.setAttribute("aria-valuenow", String(Math.round(fraction * 100)));
    progressLabel.textContent = label;
  }

  async function run() {
    const password = meta.requires_password ? passwordInput.value : null;
    if (meta.requires_password && !password) {
      showAlert("Enter the passphrase for this file.");
      return;
    }
    if (!window.SDDownload.confirmDestructive(meta)) return;
    downloadBtn.disabled = true;
    progressWrap.style.display = "";
    setProgress(0, meta.requires_password ? "Checking passphrase..." : "Checking key...");
    try {
      const result = await window.SDDownload.fetchAndDecrypt(fileId, password, urlKey, {
        meta,
        onProgress: (f) => setProgress(f, `Downloading and decrypting... ${Math.round(f * 100)}% of ${window.SDDownload.humanSize(meta.size_bytes)}`),
      });
      if (result.kind === "text") {
        await window.SDDownload.renderText(result, resultView);
        heading.textContent = "Message";
        downloadBtn.hidden = true; // nothing to download - the message is shown on the page
        showAlert("Message decrypted.", "success");
      } else if (result.kind === "bundle") {
        await window.SDDownload.renderBundle(result, resultView);
        showAlert("Decrypted the file list - download the files below.", "success");
      } else {
        setProgress(1, result.streamed ? "Saving to disk..." : "Decrypted. Saving...");
        window.SDDownload.saveDecrypted(result);
        showAlert(`Decrypted and saved "${result.name}".`, "success");
      }
      if (result.kind !== "text") downloadBtn.style.display = meta.burn_after_download ? "none" : "";
    } catch (e) {
      showAlert(e.message || "Download failed.");
    } finally {
      downloadBtn.disabled = false;
      progressWrap.style.display = "none";
    }
  }

  downloadBtn.addEventListener("click", run);
  passwordInput.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });

  init();
})();
