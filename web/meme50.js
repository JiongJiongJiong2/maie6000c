import { ApiError, sameOriginPath } from "./api.js";
let signature = "";
const urls = new Set();
let observer;
let cardWork;

export function disposeMemeResults() {
  observer?.disconnect();
  cardWork?.abort();
  for (const url of urls) URL.revokeObjectURL(url);
  urls.clear();
  signature = "";
}

export async function memeStatus(api, accepted, state, signal, summary) {
  const job =
    summary ||
    (await api.request(`/search-jobs/${accepted.job_id}`, { signal }));
  if (
    job.job_id !== accepted.job_id ||
    job.request_id !== accepted.request_id ||
    job.search_profile !== "meme50-v2" ||
    job.contract_version !== 2 ||
    (accepted.job_kind === "web"
      ? job.job_kind !== "web"
      : job.job_kind && job.job_kind !== "web") ||
    !["pending", "running", "completed", "failed"].includes(job.status)
  ) {
    throw new ApiError("Invalid image-search response.", 0, "invalid_response");
  }
  if (state.revision && state.revision !== job.result_revision) {
    state.cursor = null;
    state.pageHistory = [];
  }
  if (job.status === "completed") {
    state.revision = job.result_revision;
    const query = new URLSearchParams({
      limit: "20",
      media_kind: state.filter || "all",
      revision: job.result_revision,
    });
    if (state.cursor) query.set("cursor", state.cursor);
    const page = await api.request(
      `/search-jobs/${job.job_id}/results?${query}`,
      { signal },
    );
    if (
      page.revision !== state.revision ||
      page.items.length > 50 ||
      page.total_all > 50 ||
      page.items.some(
        (c) =>
          !Number.isFinite(c.score) ||
          !Number.isInteger(c.frame_count) ||
          c.frame_count < 1 ||
          !["static", "animated"].includes(c.media_kind) ||
          {
            PNG: "image/png",
            JPEG: "image/jpeg",
            WEBP: "image/webp",
            GIF: "image/gif",
          }[c.media_format] !== c.mime_type ||
          (c.media_kind === "static") !== (c.frame_count === 1),
      )
    ) {
      throw new ApiError("Invalid media result page.", 0, "invalid_response");
    }
    for (const c of page.items) {
      sameOriginPath(c.media_url);
      sameOriginPath(c.preview_url);
    }
    return { ...job, candidates: page.items, page };
  }
  const previews = ["pending", "running"].includes(job.status)
    ? await api.request(`/search-jobs/${job.job_id}/previews`, { signal })
    : { items: [] };
  return { ...job, candidates: [], previewItems: previews.items };
}

function button(label, handler, name = "secondary") {
  const node = document.createElement("button");
  node.type = "button";
  node.className = name;
  node.textContent = label;
  node.addEventListener("click", handler);
  return node;
}

export function renderMemeResults(container, result, api, signal, callbacks) {
  const provisional = result.status !== "completed";
  const items = provisional ? result.previewItems || [] : result.candidates;
  const next = JSON.stringify([
    result.job_id,
    result.result_revision,
    provisional,
    items.map((c) => c.candidate_id || c.draft_id),
  ]);
  if (next === signature) return;
  disposeMemeResults();
  signature = next;
  cardWork = new AbortController();
  const cardSignal = AbortSignal.any([signal, cardWork.signal]);
  container.replaceChildren();
  container.classList.add("meme50-grid");
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const card = entry.target;
        if (entry.isIntersecting) card.loadPoster?.();
        else card.pauseAnimation?.();
      }
    },
    { rootMargin: "150px" },
  );
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "candidate";
    if (!provisional) {
      card.dataset.candidateId = item.candidate_id;
      card.dataset.mediaKind = item.media_kind;
      card.dataset.rank = String(item.rank);
      card.dataset.sha256 = item.sha256 || "";
    }
    const media = document.createElement("div");
    media.className = "candidate-media";
    const image = new Image();
    image.alt = provisional
      ? "Verified provisional preview"
      : `Media candidate ${item.rank}`;
    const note = document.createElement("p");
    note.className = "media-note";
    note.textContent = "Preview loads when visible";
    media.append(image, note);
    const body = document.createElement("div");
    body.className = "candidate-body";
    const score = document.createElement("p");
    const meta = item.metadata || item;
    score.textContent = `${provisional ? "Provisional" : `#${item.rank}`} · ${meta.media_kind === "animated" ? "Animated" : "Static"} · relevance ${item.score.toFixed(3)}`;
    let poster;
    let animated;
    let requested = false;
    card.loadPoster = async () => {
      if (requested || cardSignal.aborted) return;
      requested = true;
      try {
        const blob = await api.media(item.preview_url, cardSignal);
        if (cardSignal.aborted || !card.isConnected) return;
        poster = URL.createObjectURL(blob);
        urls.add(poster);
        image.src = poster;
        note.hidden = true;
      } catch (error) {
        note.textContent = error.message;
      }
    };
    const play = button("Play animation", async () => {
      if (animated) {
        card.pauseAnimation();
        return;
      }
      try {
        const blob = await api.media(item.media_url, cardSignal);
        if (cardSignal.aborted || !card.isConnected) return;
        animated = URL.createObjectURL(blob);
        urls.add(animated);
        image.src = animated;
        play.textContent = "Pause animation";
      } catch (error) {
        note.hidden = false;
        note.textContent = error.message;
      }
    });
    card.pauseAnimation = () => {
      if (animated) {
        URL.revokeObjectURL(animated);
        urls.delete(animated);
        animated = null;
        if (poster) image.src = poster;
        play.textContent = "Play animation";
      }
    };
    body.append(score);
    if (!provisional) {
      if (item.media_kind === "animated") body.append(play);
      const mediaUrl = () => download.dataset.mediaUrl || item.media_url;
      const download = button("Download image ↓", () =>
        callbacks.download({
          ...item,
          media_url: mediaUrl(),
        }),
      );
      body.append(download);
      if (item.media_format === "GIF" && item.frame_count > 1) {
        callbacks.share(
          body,
          download,
          item.candidate_id,
          mediaUrl,
          cardSignal,
        );
        callbacks.favorite(result.job_id, item, body, download, cardSignal);
      }
      if (item.source_url) {
        const link = document.createElement("a");
        link.href = item.source_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "Source";
        body.append(link);
      }
    }
    card.append(media, body);
    container.append(card);
    observer.observe(card);
  }
}
