const storageKey = "private-library-import";
const statusLabels = {
  waiting: "等待上传",
  imported: "已导入",
  duplicate: "已存在",
  rejected: "格式不支持",
};
const element = (tag, text = "") => {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
};

export function mountLibrary(api, newKey) {
  const panel = document.querySelector("#private-library");
  const picker = panel.querySelector("input[type=file]");
  const submit = panel.querySelector("[data-import]");
  const resume = panel.querySelector("[data-resume]");
  const refresh = panel.querySelector("[data-refresh]");
  const more = panel.querySelector("[data-more]");
  const feedback = panel.querySelector("[role=status]");
  const receipts = panel.querySelector("[data-receipts]");
  const assets = panel.querySelector("[data-assets]");
  const errors = new Map();
  let active = false;
  let batch = null;
  let cursor = null;
  let media = new AbortController();
  const urls = new Set();

  function dispose() {
    media.abort();
    media = new AbortController();
    for (const url of urls) URL.revokeObjectURL(url);
    urls.clear();
    assets.replaceChildren();
  }

  function json(path, method, body) {
    return api.request(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function report(message) {
    feedback.textContent = message;
  }

  function saveState(state) {
    localStorage.setItem(storageKey, JSON.stringify(state));
  }

  function renderReceipts() {
    const rows = (batch?.items || []).map((item) => {
      const label =
        errors.get(item.client_item_id) ||
        (item.error_code === "file_too_large"
          ? "文件超过大小限制"
          : statusLabels[item.status]);
      return element("li", `${item.filename} — ${label}`);
    });
    receipts.replaceChildren(...rows);
    resume.hidden = !batch?.counts.waiting;
  }

  async function restore() {
    const stored = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (!stored) return;
    batch = stored.batch_id
      ? await api.request(`/library/imports/${stored.batch_id}`)
      : await json("/library/imports", "POST", stored.manifest);
    saveState({ batch_id: batch.batch_id });
    renderReceipts();
    if (batch.counts.waiting) report("请重新选择尚未上传的 GIF，再点继续上传。");
  }

  function card(asset) {
    const li = element("li");
    const title = element("strong", asset.title);
    const state = element(
      "p",
      `${asset.frame_count} 帧 · 图片索引 ${asset.index_status}`,
    );
    const show = element("button", "预览与下载");
    show.type = "button";
    show.addEventListener("click", async () => {
      show.disabled = true;
      const { signal } = media;
      try {
        const blob = await api.request(asset.media_url, { media: true, signal });
        if (signal.aborted) return;
        const url = URL.createObjectURL(blob);
        urls.add(url);
        const image = element("img");
        image.src = url;
        image.alt = asset.title;
        const download = element("a", "下载原 GIF");
        download.download = `${asset.asset_id}.gif`;
        download.href = url;
        li.append(image, download);
        show.hidden = true;
      } catch (error) {
        if (!signal.aborted) report(error.message);
      } finally {
        show.disabled = false;
      }
    });
    li.append(title, state, show);
    return li;
  }

  async function loadAssets(append = false) {
    if (!append) dispose();
    const { signal } = media;
    const path = append ? `?cursor=${encodeURIComponent(cursor)}` : "";
    const result = await api.request(`/library/assets${path}`, { signal });
    if (signal.aborted) return;
    assets.append(...result.assets.map(card));
    if (!append && !result.assets.length) {
      assets.append(element("li", "尚无收藏或导入的 GIF。"));
    }
    cursor = result.next_cursor;
    more.hidden = !cursor;
  }

  async function run(task) {
    if (active) return;
    active = true;
    for (const button of [submit, resume, refresh, more]) button.disabled = true;
    report("");
    try {
      await task();
    } catch (error) {
      if (error.name !== "AbortError") {
        report(
          error.code === "library_disabled"
            ? "此部署未启用私人表情库。"
            : error.message,
        );
      }
    } finally {
      active = false;
      for (const button of [submit, resume, refresh, more]) button.disabled = false;
    }
  }

  async function selectedFiles() {
    if (!crypto.subtle) throw new Error("导入需要 HTTPS 或 localhost。");
    const files = Array.from(picker.files);
    if (!files.length || files.length > 20) {
      throw new Error("请选择 1–20 个 GIF。");
    }
    const selected = [];
    for (const file of files) {
      const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
      const sha256 = [...new Uint8Array(digest)]
        .map((byte) => byte.toString(16).padStart(2, "0"))
        .join("");
      selected.push({
        file,
        item: {
          client_item_id: newKey(),
          filename: file.name,
          byte_size: file.size,
          sha256,
        },
      });
    }
    return selected;
  }

  async function transfer(selected) {
    const waiting = batch.items.filter((item) => item.status === "waiting");
    const pending = waiting.flatMap((item) => {
      const found = selected.find(
        (entry) =>
          entry.item.sha256 === item.sha256 &&
          entry.item.byte_size === item.byte_size,
      );
      return found ? [{ item, file: found.file }] : [];
    });
    async function worker() {
      while (pending.length) {
        const { item, file } = pending.shift();
        const form = new FormData();
        form.append("file", file);
        try {
          const receipt = await api.request(
            `/library/imports/${batch.batch_id}/items/${item.client_item_id}`,
            { method: "PUT", body: form },
          );
          Object.assign(item, receipt);
          errors.delete(item.client_item_id);
        } catch (error) {
          errors.set(item.client_item_id, `暂时失败，可重试（${error.code}）`);
        }
        renderReceipts();
      }
    }
    await Promise.all([worker(), worker()]);
    batch = await api.request(`/library/imports/${batch.batch_id}`);
    renderReceipts();
    if (batch.counts.waiting) report("仍有等待项。请选择与原文件 SHA 一致的 GIF，再继续上传。");
    await loadAssets();
  }

  submit.addEventListener("click", () =>
    run(async () => {
      const selected = await selectedFiles();
      if (batch?.counts.waiting && !window.confirm("改为显示新批次的回执？")) return;
      errors.clear();
      const manifest = {
        client_batch_key: newKey(),
        items: selected.map(({ item }) => item),
      };
      saveState({ manifest });
      batch = await json("/library/imports", "POST", manifest);
      saveState({ batch_id: batch.batch_id });
      renderReceipts();
      await transfer(selected);
    }),
  );
  resume.addEventListener("click", () =>
    run(async () => {
      await restore();
      await transfer(await selectedFiles());
    }),
  );
  const reload = () =>
    run(async () => {
      await loadAssets();
      await restore();
    });
  refresh.addEventListener("click", reload);
  more.addEventListener("click", () => run(() => loadAssets(true)));
  panel.addEventListener("toggle", () => {
    if (panel.open) reload();
    else dispose();
  });
  window.addEventListener("pagehide", dispose);
  return () => {
    dispose();
    receipts.replaceChildren();
    errors.clear();
    batch = null;
    if (panel.open) reload();
  };
}
