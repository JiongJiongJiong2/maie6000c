const statusLabels = {
  waiting: "Waiting",
  imported: "Imported",
  duplicate: "Already in library",
  rejected: "Rejected",
};
const analysisInProgress = (status) =>
  status === "pending" || status === "running";
const element = (tag, text = "") => {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
};

export function mountLibrary(api, newKey, onlineEnabled) {
  const storageKey = api.account
    ? "private-library-import:" + api.account
    : "private-library-import";
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
  const less = panel.querySelector("[data-less]");
  const visibleCount = panel.querySelector("[data-visible-count]");
  const feedback = panel.querySelector("[role=status]");
  const receipts = panel.querySelector("[data-receipts]");
  const assets = panel.querySelector("[data-assets]");
  const query = panel.querySelector("input[type=search]");
  const annotate = panel.querySelector("[data-annotate]");
  annotate.parentElement.hidden = !onlineEnabled;
  const confirmation = panel.querySelector("#library-analysis-confirm");
  for (const input of [picker, backupPicker]) {
    const description = document.getElementById(
      input.getAttribute("aria-describedby"),
    );
    input.addEventListener("change", () => {
      const files = input.files;
      description.textContent =
        files.length > 1
          ? `${files.length} files chosen`
          : files[0]?.name || "No file chosen";
    });
  }
  const errors = new Map();
  const scanLabels = ["Subjects", "Actions", "Emotions", "Tone"];
  let submittedQuery = "";
  let active = false;
  let batches = [];
  let states = [];
  let cursor = null;
  let media = new AbortController();
  const pages = [];
  const analysisProgress = panel.querySelector("[data-analysis-progress]");
  const pendingAnalysis = new Set();
  const analysisBatch = new Map();
  let analysisTimer;
  let analysisRequest;
  let connectionVersion = 0;
  const tools = [...panel.querySelectorAll("[data-tool]")];
  function openTool(current) {
    for (const button of tools) {
      const opened = button === current;
      button.setAttribute("aria-expanded", String(opened));
      document.getElementById(button.getAttribute("aria-controls")).hidden =
        !opened;
    }
  }
  for (const button of tools) {
    button.addEventListener("click", () =>
      openTool(button.getAttribute("aria-expanded") === "true" ? null : button),
    );
  }

  function showAnalysisProgress(note = "") {
    const counts = new Map();
    for (const status of analysisBatch.values())
      counts.set(status, (counts.get(status) || 0) + 1);
    const labels = {
      pending: "queued",
      running: "analyzing",
      ready: "ready",
      failed: "failed",
      unavailable: "unavailable",
    };
    const parts = Object.entries(labels)
      .filter(([status]) => counts.has(status))
      .map(([status, label]) => `${counts.get(status)} ${label}`);
    const message = [
      parts.length ? `AI analysis: ${parts.join(" · ")}.` : "",
      note,
    ]
      .filter(Boolean)
      .join(" ");
    if (analysisProgress.textContent !== message)
      analysisProgress.textContent = message;
  }

  function pauseAnalysis() {
    clearTimeout(analysisTimer);
    analysisTimer = undefined;
    analysisRequest?.abort();
    analysisRequest = null;
  }

  function scheduleAnalysis(delay = 2000) {
    if (
      !panel.open ||
      document.hidden ||
      !pendingAnalysis.size ||
      analysisTimer !== undefined ||
      analysisRequest
    )
      return;
    analysisTimer = setTimeout(checkAnalysis, delay);
  }

  async function checkAnalysis() {
    analysisTimer = undefined;
    const request = new AbortController();
    analysisRequest = request;
    let retry = false;
    // Rotate through large selections without fetching the GIFs or rebuilding the gallery.
    await Promise.all(
      [...pendingAnalysis].slice(0, 6).map(async (id) => {
        try {
          const asset = await api.request(
            `/library/assets/${encodeURIComponent(id)}`,
            { signal: request.signal },
          );
          if (request.signal.aborted) return;
          pendingAnalysis.delete(id);
          if (analysisInProgress(asset.annotation_status))
            pendingAnalysis.add(id);
          if (analysisBatch.has(id))
            analysisBatch.set(id, asset.annotation_status);
          for (const page of pages) page.annotations.get(id)?.(asset);
        } catch (error) {
          if (request.signal.aborted) return;
          pendingAnalysis.delete(id);
          if ([401, 403, 404].includes(error.status)) {
            if (analysisBatch.has(id)) analysisBatch.set(id, "unavailable");
          } else {
            pendingAnalysis.add(id);
            retry = true;
          }
        }
      }),
    );
    if (request.signal.aborted) return;
    analysisRequest = null;
    showAnalysisProgress(
      retry ? "Connection interrupted. Checking again shortly." : "",
    );
    scheduleAnalysis(retry ? 5000 : 2000);
  }

  function releasePages(start) {
    for (const page of pages.splice(start)) {
      page.controller.abort();
      page.observer?.disconnect();
      for (const url of page.urls) URL.revokeObjectURL(url);
      for (const node of page.nodes) node.remove();
    }
  }

  function updatePaging() {
    cursor = pages.at(-1)?.cursor || null;
    more.hidden = !cursor || !!submittedQuery;
    less.hidden = pages.length < 2;
    const count = pages.reduce((total, page) => total + page.nodes.length, 0);
    visibleCount.textContent = count
      ? `${count} ${count === 1 ? "GIF" : "GIFs"} shown`
      : "";
  }

  function dispose() {
    media.abort();
    media = new AbortController();
    releasePages(0);
    assets.replaceChildren();
    updatePaging();
  }

  async function mediaUrl(path, page) {
    const blob = await api.media(path, page.controller.signal);
    if (page.controller.signal.aborted)
      throw new DOMException("Aborted", "AbortError");
    const url = URL.createObjectURL(blob);
    page.urls.add(url);
    return url;
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
        `Batch ${index + 1} · ${counts.imported ?? 0} imported, ${counts.duplicate ?? 0} duplicates, ${counts.rejected ?? 0} rejected, ${counts.waiting} waiting`,
      );
      const items = element("ul");
      for (const item of batch.items) {
        const label =
          errors.get(item.client_item_id)?.label ||
          (item.error_code === "file_too_large"
            ? "File exceeds size limit"
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
    let needsManifest = false;
    const stored = JSON.parse(localStorage.getItem(storageKey) || "null");
    states = Array.isArray(stored) ? stored : stored ? [stored] : [];
    batches = [];
    for (const state of [...states]) {
      try {
        batches.push(await resolveBatch(state));
      } catch (error) {
        if (error.code === "backup_manifest_required") needsManifest = true;
        else if (error.code !== "import_not_found") throw error;
        states = states.filter((entry) => entry !== state);
        saveState();
      }
      renderReceipts();
    }
    if (needsManifest)
      report(
        "Previous restore was not started. Select the backup manifest again.",
      );
    else if (batches.some((batch) => batch.counts.waiting))
      report(
        "Open Import GIFs, select the remaining files and choose Resume upload.",
      );
  }

  async function beginImport(selected, backup = null) {
    const pending = [];
    for (let offset = 0; offset < selected.length; offset += 20) {
      const items = selected.slice(offset, offset + 20).map(({ item }) => item);
      pending.push({
        manifest: {
          client_batch_key: newKey(),
          purpose: backup ? "backup_restore" : "upload",
          items,
          ...(backup && {
            backup: {
              version: backup.version,
              profile: backup.profile,
              assets: items.map(({ sha256, byte_size }) => ({
                sha256,
                byte_size,
                path: `assets/${sha256}.gif`,
              })),
            },
          }),
        },
      });
    }
    states.push(...pending);
    saveState();
    for (const state of pending) {
      batches.push(await resolveBatch(state));
      renderReceipts();
    }
    return new Set(pending.map(({ batch_id }) => batch_id));
  }

  function updateSelection() {
    panel.querySelector("[data-selection]").textContent = selection.size
      ? ` (${selection.size})`
      : "";
  }

  function previewMatches(parent, asset, page) {
    const button = element(
      "button",
      `Review similar GIFs (${asset.possible_duplicates.length})`,
    );
    button.type = "button";
    button.addEventListener("click", async () => {
      button.disabled = true;
      const { signal } = page.controller;
      try {
        const matches = document.createDocumentFragment();
        for (const id of asset.possible_duplicates) {
          const match = await api.request(
            `/library/assets/${encodeURIComponent(id)}`,
            { signal },
          );
          const photo = element("img");
          photo.src = await mediaUrl(match.media_url, page);
          photo.alt = match.title;
          const figure = element("figure");
          figure.append(photo, element("figcaption", match.title));
          matches.append(figure);
        }
        parent.append(matches);
        button.hidden = true;
      } catch (error) {
        if (!signal.aborted) report(errorMessage(error));
      } finally {
        button.disabled = false;
      }
    });
    parent.append(button);
  }

  function card(asset, page) {
    const li = element("li");
    li.className = "library-card";
    const preview = element("div");
    preview.className = "library-thumb";
    const select = element("input");
    select.type = "checkbox";
    select.value = asset.asset_id;
    select.checked = selection.has(asset.asset_id);
    select.setAttribute("aria-label", `Select ${asset.title}`);
    select.addEventListener("change", () => {
      if (select.checked) selection.add(asset.asset_id);
      else selection.delete(asset.asset_id);
      updateSelection();
    });
    const pick = element("label");
    pick.className = "library-pick";
    pick.append(select);
    const progress = element("span", "Loading GIF…");
    const download = element("a", "Download GIF");
    download.hidden = true;
    download.download = `${asset.asset_id}.gif`;
    async function loadPreview() {
      progress.textContent = "Loading GIF…";
      try {
        const url = await mediaUrl(asset.media_url, page);
        if (page.controller.signal.aborted) return;
        const image = element("img");
        image.alt = asset.title;
        image.src = url;
        progress.replaceWith(image);
        download.href = url;
        download.hidden = false;
      } catch (error) {
        if (page.controller.signal.aborted) return;
        const retry = element("button", "Retry preview");
        retry.type = "button";
        retry.title = errorMessage(error);
        retry.addEventListener("click", loadPreview, { once: true });
        progress.replaceChildren(retry);
      }
    }
    preview.append(progress, pick);
    if (page.observer) {
      preview.addEventListener("loadpreview", loadPreview, { once: true });
      page.observer.observe(preview);
    } else {
      void loadPreview();
    }
    const body = element("div");
    body.className = "library-card-body";
    const title = element("h3", asset.title);
    const state = element("p");
    state.className = "library-meta";
    const caption = element("p");
    const tags = element("ul");
    tags.className = "library-tags";
    tags.setAttribute("aria-label", "Tags");
    body.append(title, state, caption, tags);
    if (asset.match_reasons?.length)
      body.append(
        element(
          "p",
          `Matched: ${(asset.match_reasons_en || asset.match_reasons).join(", ")}`,
        ),
      );
    const details = editor(asset);
    const notes = element("div");
    const ocr = element("p");
    const originalCaption = element("p");
    notes.append(ocr, originalCaption);
    if (asset.possible_duplicates?.length) previewMatches(notes, asset, page);
    details.querySelector("summary").after(notes);
    const retry = element("button", "Retry image indexing");
    retry.type = "button";
    retry.addEventListener("click", () =>
      run(async () => {
        await api.request(`/saved-assets/${asset.asset_id}/index-retry`, {
          method: "POST",
        });
        await loadAssets();
      }),
    );
    const failure = element("p");
    body.append(retry, failure);

    function paintAnalysis(update) {
      Object.assign(asset, update);
      state.textContent = `${asset.frame_count} frames · Index ${asset.index_status.replaceAll("_", " ")} · AI ${asset.annotation_status.replaceAll("_", " ")}`;
      caption.textContent = asset.caption_en || "";
      caption.hidden = !caption.textContent;
      tags.replaceChildren(
        ...(asset.tags || []).map((tag) => element("li", tag)),
      );
      tags.hidden = !tags.childElementCount;
      ocr.textContent = `Image text: ${asset.ocr_text || ""}${asset.ocr_uncertain ? " (uncertain)" : ""}`;
      ocr.hidden = !asset.ocr_text && !asset.ocr_uncertain;
      originalCaption.textContent = asset.caption_zh || "";
      originalCaption.hidden = !!asset.caption_en || !asset.caption_zh;
      retry.hidden = asset.index_status !== "failed";
      failure.textContent = asset.annotation_error
        ? `Analysis failed (${asset.annotation_error}).`
        : "";
      if (failure.textContent && onlineEnabled)
        failure.textContent +=
          " Select this GIF and choose Analyze selected GIFs to retry.";
      failure.hidden = !failure.textContent;
    }
    paintAnalysis({});
    page.annotations.set(asset.asset_id, paintAnalysis);
    if (analysisInProgress(asset.annotation_status)) {
      pendingAnalysis.add(asset.asset_id);
      scheduleAnalysis();
    }
    const actions = element("div");
    actions.className = "library-card-actions";
    actions.append(download, details);
    body.append(actions);
    li.append(preview, body);
    return li;
  }

  function editor(asset) {
    const details = element("details");
    details.append(element("summary", "Edit details"));
    const form = element("form");
    const manual = asset.manual || {};
    const fields = [
      ["title", "Title", asset.title],
      ["tags", "Manual tags", (manual.tags || []).join(", ")],
      ...["subject_tags", "action_tags", "emotion_tags", "tone_tags"].map(
        (key, index) => [
          key,
          scanLabels[index],
          (manual[key] || []).join(", "),
        ],
      ),
      ["ocr_text", "Correct image text", manual.ocr_text || ""],
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
            ? "Leave blank to use AI text"
            : "Separate tags with commas";
      const row = element("label", label);
      row.append(input);
      form.append(row);
      inputs.set(key, input);
    }
    const save = element("button", "Save changes");
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
        report("Changes saved.");
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
    params.set("limit", "8");
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
    const page = {
      controller: new AbortController(),
      urls: new Set(),
      cursor: result.next_cursor,
      nodes: [],
      observer: null,
      annotations: new Map(),
    };
    if ("IntersectionObserver" in window) {
      page.observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting || page.controller.signal.aborted)
              continue;
            page.observer.unobserve(entry.target);
            entry.target.dispatchEvent(new Event("loadpreview"));
          }
        },
        { rootMargin: "160px" },
      );
    }
    pages.push(page);
    page.nodes = result.assets.map((asset) => card(asset, page));
    assets.append(...page.nodes);
    if (!append && !result.assets.length) {
      assets.append(
        element(
          "li",
          submittedQuery
            ? "No matches. Try an action, character, tag or words from the GIF."
            : filters.size
              ? "No GIFs match these filters."
              : "Your library is empty. Use Import GIFs to add your first GIF.",
        ),
      );
    }
    updatePaging();
  }

  function errorMessage(error) {
    return (
      {
        library_disabled: "The private library is disabled on this server.",
        annotation_unconfigured:
          "AI analysis is unavailable. You can still add tags and search.",
      }[error.code] || error.message
    );
  }

  async function run(task) {
    if (active) return;
    active = true;
    for (const button of [submit, resume, refresh, more, less, annotate])
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
      for (const button of [submit, resume, refresh, more, less, annotate])
        button.disabled = false;
    }
  }

  async function selectedFiles() {
    if (!crypto.subtle) throw new Error("Import requires HTTPS or localhost.");
    const files = Array.from(picker.files);
    if (!files.length || files.length > 60) {
      throw new Error("Choose 1–60 GIF files.");
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
          const tooLarge =
            error.status === 413 || error.code === "file_too_large";
          errors.set(item.client_item_id, {
            tooLarge,
            label: tooLarge
              ? "Exceeds the destination file limit"
              : `Upload interrupted. Try again (${error.code}).`,
          });
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
        throw new Error("Choose a manifest.json file up to 1 MiB.");
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
        throw new Error("Unsupported backup manifest.");
      const selected = await selectedFiles();
      const byName = new Map(selected.map((entry) => [entry.file.name, entry]));
      const valid = [];
      const rows = new Map();
      for (const entry of manifest.assets) {
        const picked = byName.get(`${entry.sha256}.gif`);
        let status = "Original GIF missing";
        if (picked) {
          status = "Size or checksum mismatch";
          if (
            picked.item.sha256 === entry.sha256 &&
            picked.item.byte_size === entry.byte_size
          ) {
            status = "Waiting to restore";
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
      const currentBatches = await beginImport(valid, manifest);
      await transfer(valid);
      const uploaded_sha256 = [];
      for (const batch of batches) {
        if (!currentBatches.has(batch.batch_id)) continue;
        for (const item of batch.items) {
          const row = rows.get(item.sha256);
          const error = errors.get(item.client_item_id);
          if (
            item.asset_id &&
            ["imported", "duplicate"].includes(item.status)
          ) {
            uploaded_sha256.push(item.sha256);
            row.status = "GIF saved. Restoring metadata…";
          } else if (item.error_code === "file_too_large" || error?.tooLarge) {
            row.status = "Exceeds the destination file limit";
          } else if (item.status === "rejected") {
            row.status = `Restore failed (${item.error_code})`;
          } else if (error) {
            row.status = "Upload interrupted. Resume to retry.";
          }
        }
      }
      showResults();
      if (!uploaded_sha256.length) return;
      const result = await json("/library/restores/metadata", "POST", {
        manifest,
        uploaded_sha256,
      });
      for (const item of result.items)
        rows.get(item.sha256).status =
          item.status === "restored"
            ? "Restored"
            : `Restore failed (${item.error_code})`;
      showResults();
      await loadAssets();
    }),
  );

  panel.querySelector("[data-export]").addEventListener("click", () =>
    run(async () => {
      if (!selection.size || selection.size > 60)
        throw new Error("Select 1–60 GIFs.");
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
          throw new Error("Select 1–60 GIFs.");
        if (!tags.length || tags.length > 8) throw new Error("Enter 1–8 tags.");
        const result = await json("/library/assets/bulk-tags", "POST", {
          asset_ids: [...selection],
          tags,
        });
        await loadAssets();
        report(`Tags updated for ${result.updated} GIFs.`);
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
  annotate.addEventListener("click", () => {
    if (!onlineEnabled || active || confirmation.open) return;
    const asset_ids = [...selection];
    if (!asset_ids.length || asset_ids.length > 20) {
      report("Select 1–20 GIFs.");
      return;
    }
    const version = connectionVersion;
    confirmation.querySelector("h2").textContent =
      `Analyze ${asset_ids.length} selected ${asset_ids.length === 1 ? "GIF" : "GIFs"}?`;
    confirmation.returnValue = "cancel";
    confirmation.addEventListener(
      "close",
      () => {
        if (
          confirmation.returnValue === "analyze" &&
          version === connectionVersion &&
          panel.open
        ) {
          void run(() => submitAnalysis(asset_ids, version));
        }
      },
      { once: true },
    );
    confirmation.showModal();
  });

  async function submitAnalysis(asset_ids, version) {
    report("Submitting GIFs for analysis…");
    const result = await json("/library/annotations", "POST", {
      asset_ids,
      consent: true,
    });
    if (version !== connectionVersion) return;
    report("");
    pauseAnalysis();
    analysisBatch.clear();
    for (const receipt of result.assets) {
      const id = receipt.asset_id;
      analysisBatch.set(id, receipt.annotation_status);
      pendingAnalysis.add(id);
      for (const page of pages)
        page.annotations.get(id)?.({
          annotation_status: receipt.annotation_status,
          annotation_error: null,
        });
    }
    showAnalysisProgress();
    scheduleAnalysis(0);
  }

  refresh.addEventListener("click", reload);
  more.addEventListener("click", () => run(() => loadAssets(true)));
  less.addEventListener("click", () => {
    releasePages(1);
    updatePaging();
    more.focus();
    assets.scrollIntoView({ block: "start", behavior: "instant" });
  });
  panel.addEventListener("toggle", () => {
    if (panel.open) {
      reload();
      scheduleAnalysis(0);
    } else {
      if (confirmation.open) confirmation.close("cancel");
      pauseAnalysis();
      dispose();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) pauseAnalysis();
    else scheduleAnalysis(0);
  });
  window.addEventListener("pagehide", () => {
    if (confirmation.open) confirmation.close("cancel");
    pauseAnalysis();
    dispose();
  });
  return () => {
    connectionVersion++;
    if (confirmation.open) confirmation.close("cancel");
    pauseAnalysis();
    pendingAnalysis.clear();
    analysisBatch.clear();
    showAnalysisProgress();
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
