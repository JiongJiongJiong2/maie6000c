const prepareLabel = "分享动图 · Share GIF";
const openLabel = "打开分享面板 · Open share menu";
const fallback = "此浏览器暂不支持分享此文件，请下载 GIF 后手动发送。";
let sharing = false;

export function mountGifShare(
  api,
  body,
  download,
  candidateId,
  mediaUrl,
  signal,
) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary share-gif";
  button.textContent = prepareLabel;
  button.hidden = download.hidden;
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  body.append(button, status);

  let prepared;
  let preparation;
  const eligible = () =>
    !signal.aborted && button.isConnected && !download.hidden;
  function invalidate() {
    preparation?.abort();
    preparation = null;
    prepared = null;
    button.textContent = prepareLabel;
    button.disabled = false;
    status.textContent = "";
  }
  signal.addEventListener("abort", invalidate, { once: true });
  download.addEventListener("mediachange", invalidate);
  download.addEventListener("eligibilitychange", () => {
    button.hidden = download.hidden;
    if (button.hidden) invalidate();
  });

  button.addEventListener("click", async () => {
    if (!eligible() || preparation) return;
    if (
      !window.isSecureContext ||
      typeof navigator.share !== "function" ||
      typeof navigator.canShare !== "function"
    ) {
      status.textContent = fallback;
      return;
    }
    const url = mediaUrl();
    if (prepared?.url === url) {
      if (sharing) {
        status.textContent = "已有分享面板打开，请先完成该操作。";
        return;
      }
      const file = prepared.file;
      sharing = true;
      button.disabled = true;
      try {
        await navigator.share({ files: [file] });
        if (eligible() && prepared?.file === file)
          status.textContent = "已交给系统分享，请在目标应用中确认发送。";
      } catch {
        if (eligible() && prepared?.file === file)
          status.textContent = "分享未完成，可重试或下载 GIF。";
      } finally {
        sharing = false;
        if (prepared?.file === file) button.disabled = false;
      }
      return;
    }

    const controller = new AbortController();
    preparation = controller;
    button.disabled = true;
    status.textContent = "正在准备 GIF…";
    const current = () =>
      preparation === controller && eligible() && mediaUrl() === url;
    try {
      const blob = await api.media(url, controller.signal);
      if (!current()) return;
      if (blob.type !== "image/gif") {
        status.textContent = "原文件不是 GIF，无法分享动图。";
        return;
      }
      const file = new File([blob], `meme-${candidateId}.gif`, {
        type: "image/gif",
      });
      if (!navigator.canShare({ files: [file] })) {
        status.textContent = fallback;
        return;
      }
      prepared = { url, file };
      button.textContent = openLabel;
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
