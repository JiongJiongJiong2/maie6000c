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
  const picker = panel.querySelector("#library-files");
  const backupPicker = panel.querySelector("#library-backup-manifest");
  const backupFeedback = panel.querySelector("[data-restore-results]");
  const filterForm = panel.querySelector("[data-filters]");
  let filters = new URLSearchParams();
  const selection = new Set();
  const submit = panel.querySelector("[data-import]");
  const resume = panel.querySelector("[data-resume]");
  const refresh = panel.querySelector("[data-refresh]");
  const more = panel.querySelector("[data-more]");
  const feedback = panel.querySelector("[role=status]");
  const receipts = panel.querySelector("[data-receipts]");
  const assets = panel.querySelector("[data-assets]");
  const query = panel.querySelector("input[type=search]");
  const annotate = panel.querySelector("[data-annotate]");
  const errors = new Map();
  const scanLabels = ["角色", "动作", "情绪", "语气"];
  let submittedQuery = "";
  let active = false;
  let batches = [];
  let states = [];
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

  function saveState() {
    localStorage.setItem(storageKey, JSON.stringify(states));
  }

  function renderReceipts() {
    const groups = batches.map((batch, index) => {
      const counts = batch.counts;
      const group = element(
        "li",
        `批次 ${index + 1}：成功 ${counts.imported}、重复 ${counts.duplicate}、拒绝 ${counts.rejected}、待续传 ${counts.waiting}`,
      );
      const items = element("ul");
      for (const item of batch.items) {
        const label =
          errors.get(item.client_item_id) ||
          (item.error_code === "file_too_large"
            ? "文件超过大小限制"
            : statusLabels[item.status]);
        items.append(element("li", `${item.filename} — ${label}`));
      }
      group.append(items);
      return group;
    });
    receipts.replaceChildren(...groups);
    resume.hidden = !batches.some((batch) => batch.counts.waiting);
  }

  async function resolveBatch(state) {
    const receipt = state.batch_id
      ? await api.request(`/library/imports/${state.batch_id}`)
      : await json("/library/imports", "POST", state.manifest);
    state.batch_id = receipt.batch_id;
    delete state.manifest;
    saveState();
    return receipt;
  }

  async function restore() {
    const stored = JSON.parse(localStorage.getItem(storageKey) || "null");
    states = Array.isArray(stored) ? stored : stored ? [stored] : [];
    batches = [];
    for (const state of [...states]) {
      try {
        batches.push(await resolveBatch(state));
      } catch (error) {
        if (error.code !== "import_not_found") throw error;
        states = states.filter((entry) => entry !== state);
        saveState();
      }
      renderReceipts();
    }
    if (batches.some((batch) => batch.counts.waiting))
      report("请重新选择尚未上传的 GIF，再点继续上传。");
  }

  async function beginImport(selected, purpose = "upload") {
    const pending = [];
    for (let offset = 0; offset < selected.length; offset += 20) {
      pending.push({
        manifest: {
          client_batch_key: newKey(),
          purpose,
          items: selected.slice(offset, offset + 20).map(({ item }) => item),
        },
      });
    }
    states.push(...pending);
    saveState();
    for (const state of pending) {
      batches.push(await resolveBatch(state));
      renderReceipts();
    }
  }

  function updateSelection() {
    panel.querySelector("[data-selection]").textContent = selection.size
      ? `已选 ${selection.size} 张`
      : "";
  }

  function previewMatches(parent, asset) {
    const button = element(
      "button",
      `查看可能重复的 ${asset.possible_duplicates.length} 张 GIF`,
    );
    button.type = "button";
    button.addEventListener("click", async () => {
      button.disabled = true;
      const { signal } = media;
      try {
        for (const id of asset.possible_duplicates) {
          const match = await api.request(
            `/library/assets/${encodeURIComponent(id)}`,
            { signal },
          );
          const blob = await api.request(match.media_url, {
            media: true,
            signal,
          });
          if (signal.aborted) return;
          const url = URL.createObjectURL(blob);
          urls.add(url);
          const photo = element("img");
          photo.src = url;
          photo.alt = match.title;
          const figure = element("figure");
          figure.append(photo, element("figcaption", match.title));
          parent.append(figure);
        }
        button.hidden = true;
      } catch (error) {
        if (!signal.aborted) report(errorMessage(error));
      } finally {
        button.disabled = false;
      }
    });
    parent.append(button);
  }

  function card(asset) {
    const li = element("li");
    const title = element("strong", asset.title);
    const state = element(
      "p",
      `${asset.frame_count} 帧 · 图片索引 ${asset.index_status} · AI ${asset.annotation_status}`,
    );
    const show = element("button", "预览与下载");
    show.type = "button";
    show.addEventListener("click", async () => {
      show.disabled = true;
      const { signal } = media;
      try {
        const blob = await api.request(asset.media_url, {
          media: true,
          signal,
        });
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
    const select = element("input");
    select.type = "checkbox";
    select.value = asset.asset_id;
    select.checked = selection.has(asset.asset_id);
    select.addEventListener("change", () => {
      if (select.checked) selection.add(asset.asset_id);
      else selection.delete(asset.asset_id);
      updateSelection();
    });
    const selectLabel = element("label");
    selectLabel.append(select, document.createTextNode(` 选择 ${asset.title}`));
    li.append(title, state, selectLabel, show);
    if (asset.index_status === "failed") {
      const retry = element("button", "重试图片索引");
      retry.type = "button";
      retry.addEventListener("click", () =>
        run(async () => {
          await api.request(`/saved-assets/${asset.asset_id}/index-retry`, {
            method: "POST",
          });
          await loadAssets();
        }),
      );
      li.append(retry);
    }
    if (asset.annotation_error)
      li.append(
        element("p", `识别失败 · ${asset.annotation_error}。可选中后重试。`),
      );
    if (asset.possible_duplicates?.length) previewMatches(li, asset);
    if (asset.ocr_text || asset.ocr_uncertain) {
      li.append(
        element(
          "p",
          `图片文字：${asset.ocr_text}${asset.ocr_uncertain ? "（有不确定文字）" : ""}`,
        ),
      );
    }
    if (asset.caption_zh) li.append(element("p", asset.caption_zh));
    if (asset.tags?.length) li.append(element("p", asset.tags.join("、")));
    if (asset.match_reasons?.length)
      li.append(element("p", `命中：${asset.match_reasons.join("、")}`));
    li.append(editor(asset));
    return li;
  }

  function editor(asset) {
    const details = element("details");
    details.append(element("summary", "编辑标题与标签"));
    const form = element("form");
    const manual = asset.manual || {};
    const fields = [
      ["title", "标题", asset.title],
      ["tags", "手动标签", (manual.tags || []).join("、")],
      ...["subject_tags", "action_tags", "emotion_tags", "tone_tags"].map(
        (key, index) => [
          key,
          scanLabels[index],
          (manual[key] || []).join("、"),
        ],
      ),
      ["ocr_text", "修正图中文字", manual.ocr_text || ""],
    ];
    const inputs = new Map();
    for (const [key, label, value] of fields) {
      const input = element("input");
      input.value = value;
      input.maxLength = key === "ocr_text" ? 2000 : key === "title" ? 200 : 327;
      input.placeholder =
        key === "title"
          ? ""
          : key === "ocr_text"
            ? "留空使用 AI 结果"
            : "用顿号分隔，留空使用默认值";
      const row = element("label", label);
      row.append(input);
      form.append(row);
      inputs.set(key, input);
    }
    const save = element("button", "保存编辑");
    save.type = "submit";
    form.append(save);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void run(async () => {
        const body = {};
        for (const [key, input] of inputs) {
          const value = input.value.trim();
          body[key] = !value
            ? null
            : key.endsWith("tags")
              ? value
                  .split(/[、,，]/)
                  .map((tag) => tag.trim())
                  .filter(Boolean)
              : value;
        }
        await json(`/library/assets/${asset.asset_id}`, "PATCH", body);
        await loadAssets();
        report("已保存编辑。");
      });
    });
    details.append(form);
    return details;
  }

  async function loadAssets(append = false) {
    if (!panel.open) return;
    if (!append) dispose();
    const { signal } = media;
    const params = new URLSearchParams(filters);
    if (append && cursor) params.set("cursor", cursor);
    const path = params.size ? `?${params}` : "";
    const result = submittedQuery
      ? await api.request("/library/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: submittedQuery }),
          signal,
        })
      : await api.request(`/library/assets${path}`, { signal });
    if (signal.aborted) return;
    assets.append(...result.assets.map(card));
    if (!append && !result.assets.length) {
      assets.append(
        element(
          "li",
          submittedQuery
            ? "未找到匹配项。试试图中文字、角色、动作或标签。"
            : "尚无收藏或导入的 GIF。",
        ),
      );
    }
    cursor = result.next_cursor;
    more.hidden = !cursor || !!submittedQuery;
  }

  function errorMessage(error) {
    return (
      {
        library_disabled: "此部署未启用私人表情库。",
        annotation_unconfigured:
          "此部署尚未配置视觉模型网关。仍可手动标注和搜索。",
      }[error.code] || error.message
    );
  }

  async function run(task) {
    if (active) return;
    active = true;
    for (const button of [submit, resume, refresh, more])
      button.disabled = true;
    report("");
    try {
      await task();
    } catch (error) {
      if (error.name !== "AbortError") {
        report(errorMessage(error));
      }
    } finally {
      active = false;
      for (const button of [submit, resume, refresh, more])
        button.disabled = false;
    }
  }

  async function selectedFiles() {
    if (!crypto.subtle) throw new Error("导入需要 HTTPS 或 localhost。");
    const files = Array.from(picker.files);
    if (!files.length || files.length > 60) {
      throw new Error("请选择 1–60 个 GIF。");
    }
    const selected = [];
    for (const file of files) {
      const digest = await crypto.subtle.digest(
        "SHA-256",
        await file.arrayBuffer(),
      );
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
    const available = new Map(
      selected.map(({ item, file }) => [
        `${item.sha256}:${item.byte_size}`,
        file,
      ]),
    );
    const pending = [];
    for (const batch of batches) {
      for (const item of batch.items) {
        const file = available.get(`${item.sha256}:${item.byte_size}`);
        if (item.status === "waiting" && file)
          pending.push({ batch, item, file });
      }
    }
    async function worker() {
      while (pending.length) {
        const { batch, item, file } = pending.shift();
        const form = new FormData();
        form.append("file", file);
        try {
          const receipt = await api.request(
            `/library/imports/${batch.batch_id}/items/${item.client_item_id}`,
            { method: "PUT", body: form },
          );
          batch.counts[item.status]--;
          Object.assign(item, receipt);
          batch.counts[item.status]++;
          errors.delete(item.client_item_id);
        } catch (error) {
          errors.set(item.client_item_id, `暂时失败，可重试（${error.code}）`);
        }
        renderReceipts();
      }
    }
    await Promise.all([worker(), worker()]);
    await restore();
    await loadAssets();
  }

  submit.addEventListener("click", () =>
    run(async () => {
      const selected = await selectedFiles();
      await restore();
      await beginImport(selected);
      await transfer(selected);
    }),
  );
  resume.addEventListener("click", () =>
    run(async () => {
      await restore();
      await transfer(await selectedFiles());
    }),
  );

  panel.querySelector("[data-restore-backup]").addEventListener("click", () =>
    run(async () => {
      const manifestFile = backupPicker.files[0];
      if (!manifestFile || manifestFile.size > 1024 * 1024)
        throw new Error("请选择大小不超过 1 MiB 的 manifest.json。");
      const manifest = JSON.parse(await manifestFile.text());
      if (
        manifest.version !== 1 ||
        manifest.profile !== "original_zip" ||
        !Array.isArray(manifest.assets) ||
        !manifest.assets.length ||
        manifest.assets.length > 60 ||
        new Set(manifest.assets.map((asset) => asset.sha256)).size !==
          manifest.assets.length ||
        !manifest.assets.every(
          (asset) =>
            /^[0-9a-f]{64}$/.test(asset.sha256) &&
            asset.path === `assets/${asset.sha256}.gif`,
        )
      )
        throw new Error("不支持此备份清单。");
      const selected = await selectedFiles();
      const byName = new Map(selected.map((entry) => [entry.file.name, entry]));
      const valid = [];
      const rows = new Map();
      for (const entry of manifest.assets) {
        const picked = byName.get(`${entry.sha256}.gif`);
        let status = "缺少原 GIF";
        if (picked) {
          status = "文件字节或 SHA 不一致";
          if (
            picked.item.sha256 === entry.sha256 &&
            picked.item.byte_size === entry.byte_size
          ) {
            status = "待还原";
            valid.push(picked);
          }
        }
        rows.set(entry.sha256, { title: entry.title, status });
      }
      function showResults() {
        backupFeedback.replaceChildren(
          ...[...rows.values()].map(({ title, status }) =>
            element("li", `${title} — ${status}`),
          ),
        );
      }
      showResults();
      if (!valid.length) return;
      await restore();
      await beginImport(valid, "backup_restore");
      await transfer(valid);
      const completed = new Set(
        batches.flatMap((batch) =>
          batch.items
            .filter(
              (item) =>
                item.asset_id &&
                ["imported", "duplicate"].includes(item.status),
            )
            .map((item) => item.sha256),
        ),
      );
      const uploaded_sha256 = valid
        .map(({ item }) => item.sha256)
        .filter((sha) => completed.has(sha));
      if (!uploaded_sha256.length) return;
      const result = await json("/library/restores/metadata", "POST", {
        manifest,
        uploaded_sha256,
      });
      for (const item of result.items)
        rows.get(item.sha256).status =
          item.status === "restored"
            ? "已还原"
            : `还原失败（${item.error_code}）`;
      showResults();
      await loadAssets();
    }),
  );

  panel.querySelector("[data-export]").addEventListener("click", () =>
    run(async () => {
      if (!selection.size || selection.size > 60)
        throw new Error("请选择 1–60 张 GIF。");
      const blob = await api.request("/library/exports", {
        method: "POST",
        binary: true,
        timeout: 120000,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asset_ids: [...selection],
          profile: "original_zip",
          include_manual: panel.querySelector("[data-export-manual]").checked,
          include_annotations: panel.querySelector("[data-export-annotations]")
            .checked,
        }),
      });
      const url = URL.createObjectURL(blob);
      const link = element("a");
      link.href = url;
      link.download = "private-gifs.zip";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }),
  );

  panel
    .querySelector("[data-bulk-tags]")
    .addEventListener("submit", (event) => {
      event.preventDefault();
      const tags = event.currentTarget.elements.tags.value
        .split(/[、,，]/)
        .map((tag) => tag.trim())
        .filter(Boolean);
      run(async () => {
        if (!selection.size || selection.size > 60)
          throw new Error("请选择 1–60 张 GIF。");
        if (!tags.length || tags.length > 8)
          throw new Error("请输入 1–8 个标签。");
        const result = await json("/library/assets/bulk-tags", "POST", {
          asset_ids: [...selection],
          tags,
        });
        await loadAssets();
        report(`已为 ${result.updated} 张 GIF 更新标签。`);
      });
    });

  filterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    filters = new URLSearchParams(
      [...new FormData(filterForm)].filter(([, value]) => value.trim()),
    );
    submittedQuery = "";
    query.value = "";
    run(() => loadAssets());
  });
  const reload = () =>
    run(async () => {
      await loadAssets();
      await restore();
    });
  function search() {
    submittedQuery = query.value.trim();
    loadAssets().catch((error) => {
      if (error.name !== "AbortError") report(error.message);
    });
  }
  panel.querySelector("[data-search]").addEventListener("submit", (event) => {
    event.preventDefault();
    search();
  });
  panel.querySelector("[data-clear]").addEventListener("click", () => {
    query.value = "";
    search();
  });
  annotate.addEventListener("click", () =>
    run(async () => {
      const asset_ids = [...selection];
      if (!asset_ids.length || asset_ids.length > 20) {
        report("请选择 1–20 张 GIF。");
        return;
      }
      if (
        !window.confirm(
          "会把所选 GIF 最多 4 张抽样帧发送给配置的视觉模型网关。这些帧包含画面中可见的信息。确认发送并识别？",
        )
      )
        return;
      const result = await json("/library/annotations", "POST", {
        asset_ids,
        consent: true,
      });
      await loadAssets();
      if (result.assets.some((asset) => asset.annotation_status !== "ready")) {
        report("已提交识别。用刷新查看状态。");
      }
    }),
  );
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
    batches = [];
    states = [];
    selection.clear();
    updateSelection();
    if (panel.open) reload();
  };
}
