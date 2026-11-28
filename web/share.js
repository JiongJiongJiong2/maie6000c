const imageTypes = {
  GIF: ["image/gif", "gif"],
  JPEG: ["image/jpeg", "jpg"],
  PNG: ["image/png", "png"],
  WEBP: ["image/webp", "webp"],
};
let sharing = false;

export function mountMediaShare({
  api,
  body,
  download,
  id,
  url,
  format,
  signal,
}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary share-media";
  button.textContent = "Share";
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  body.append(button, status);

  let prepared;
  let preparation;
  let fallbackUrl;
  const mediaUrl = () => download.dataset.mediaUrl || url;
  const active = () => !signal.aborted && button.isConnected;
  function invalidate() {
    preparation?.abort();
    preparation = null;
    prepared = null;
    if (fallbackUrl) URL.revokeObjectURL(fallbackUrl);
    fallbackUrl = null;
    button.textContent = "Share";
    button.disabled = false;
    status.textContent = "";
  }
  signal.addEventListener("abort", invalidate, { once: true });
  download.addEventListener("mediachange", invalidate);

  function offerDownload(
    file,
    message = "This browser can’t share this file. Download the original to send it.",
  ) {
    status.textContent = message;
    if (fallbackUrl) URL.revokeObjectURL(fallbackUrl);
    fallbackUrl = null;
    if (download.hidden && file) {
      const link = document.createElement("a");
      fallbackUrl = URL.createObjectURL(file);
      link.href = fallbackUrl;
      link.download = file.name;
      link.textContent = "Download original";
      status.append(" ", link);
    }
  }

  button.addEventListener("click", async () => {
    if (!active() || preparation) return;
    if (prepared?.url === mediaUrl()) {
      if (sharing) {
        status.textContent = "Finish sharing the other image first.";
        return;
      }
      const file = prepared.file;
      sharing = true;
      button.disabled = true;
      try {
        await navigator.share({ files: [file] });
        if (active() && prepared?.file === file)
          status.textContent = "Opened in system sharing.";
      } catch {
        if (active() && prepared?.file === file)
          offerDownload(
            file,
            "Sharing didn’t finish. Try again or download the original.",
          );
      } finally {
        sharing = false;
        if (prepared?.file === file) button.disabled = false;
      }
      return;
    }

    invalidate();
    const supported =
      window.isSecureContext &&
      typeof navigator.share === "function" &&
      typeof navigator.canShare === "function";
    if (!supported && !download.hidden) {
      offerDownload();
      return;
    }
    const source = mediaUrl();
    const controller = new AbortController();
    preparation = controller;
    button.disabled = true;
    status.textContent = "Preparing original…";
    const current = () =>
      preparation === controller && active() && mediaUrl() === source;
    try {
      const blob = await api.media(source, controller.signal);
      if (!current()) return;
      const type = imageTypes[format];
      if (!type || blob.type.split(";")[0] !== type[0]) {
        status.textContent =
          "The original file’s format doesn’t match this result.";
        return;
      }
      const file = new File([blob], `meme-${id}.${type[1]}`, { type: type[0] });
      if (!supported || !navigator.canShare({ files: [file] })) {
        offerDownload(file);
        return;
      }
      // A fresh click preserves the user activation required by native share sheets.
      prepared = { url: source, file };
      button.textContent = "Open share menu";
      status.textContent = "";
    } catch (error) {
      if (current()) status.textContent = error.message;
    } finally {
      if (preparation === controller) {
        preparation = null;
        button.disabled = false;
      }
    }
  });
}
