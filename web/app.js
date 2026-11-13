import { memeStatus, renderMemeResults, disposeMemeResults } from "./meme50.js";
import { Api, validAccepted, validStatus } from "./api.js";
import {
  loadFavorite,
  saveFavorite,
  loadSession,
  saveSession,
} from "./store.js";

const $ = (id) => document.getElementById(id);
const api = new Api();
const states = {
  pending: [
    "Waiting for processing",
    "Your screenshot is queued. The pixel detectives will be with you shortly.",
  ],
  running: [
    "Looking for your GIF",
    "Comparing frames in the GIF collection. No pixel gets to plead the fifth.",
  ],
  completed: [
    "Here are your candidates",
    "The lineup is ready. Play the animations and identify your little troublemaker.",
  ],
  failed: [
    "This search could not finish",
    "Check the error below. Start a new search once the service is available.",
  ],
};
let session = null;
let epoch = 0;
let lifetime = new AbortController();
let pollTimer;
let polling = false;
let pollAgain = false;
let busy = false;
let initialized = false;
let inputURL;
let cardSignature = "";
const mediaURLs = new Map();
const activeFavorites = new Map();

// crypto.randomUUID is unavailable on plain-HTTP LAN origins; getRandomValues
// still supplies cryptographic UUIDs there.
function newKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function notice(message = "") {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}

function feedback(id, message, error = false) {
  $(id).textContent = message;
  $(id).classList.toggle("error", error);
}

function disposeCards() {
  for (const url of mediaURLs.values()) URL.revokeObjectURL(url);
  mediaURLs.clear();
  cardSignature = "";
  $("candidates").replaceChildren();
}

function cancelSessionWork() {
  epoch += 1;
  lifetime.abort();
  lifetime = new AbortController();
  clearTimeout(pollTimer);
  polling = false;
  clearWebCards();
  disposeCards();
}

function renderInput() {
  $("search-mode").value = session?.searchProfile || $("search-mode").value;
  $("description").value = session?.description || "";
  $("continue-description").value =
    session?.online?.creation?.payload.description || "";
  feedback("continue-feedback", "");
  $("media-filter").value = session?.filter || "all";
  if (inputURL) URL.revokeObjectURL(inputURL);
  inputURL = session?.file ? URL.createObjectURL(session.file) : null;
  $("input-preview").hidden = !inputURL;
  if (inputURL) $("input-preview").src = inputURL;
  else $("input-preview").removeAttribute("src");
  $("upload-placeholder").hidden = !!inputURL;
  $("replace-hint").hidden = !inputURL;
  $("file-name").textContent = session?.file?.name || "No image selected";
  $("file-size").textContent = session?.file
    ? `${(session.file.size / 1024).toFixed(0)} KiB`
    : "";
}

function render() {
  const result = session?.result;
  const accepted = session?.accepted;
  const status = result?.status || accepted?.status;
  const active =
    accepted && (!result || ["pending", "running"].includes(status));
  const hasCandidates = result?.result_kind === "candidates";
  const uncertainReview = session?.review && !session.review.review_id;
  $("submit").hidden = !!accepted;
  $("submit").disabled = !initialized || busy || !session?.file;
  const local = $("search-mode").value === "legacy";
  $("file-input").accept = local
    ? "image/png,image/jpeg,image/webp"
    : "image/png,image/jpeg,image/webp,image/gif";
  $("search-mode").disabled = busy || !initialized;
  $("local-hint").hidden = !local;
  document.querySelector(".image-disclosure").hidden = local;
  $("description").hidden = local;
  document.querySelector('label[for="description"]').hidden = local;
  $("description").disabled =
    local || busy || !!session?.submissionStarted || !!accepted;
  $("submit").textContent = busy
    ? "Submitting…"
    : session?.submissionStarted
      ? "Retry this upload ↗"
      : "Find related memes ↗";
  $("file-input").disabled = busy || !initialized;
  $("new-search").hidden = !accepted;
  $("new-search").disabled = busy;
  $("forget").disabled = busy || !initialized || !session;
  document
    .querySelector(".results-panel")
    .setAttribute("aria-busy", String(!!active));
  document
    .querySelector(".results-panel")
    .classList.toggle("error-state", status === "failed");
  document.querySelectorAll(".steps li").forEach((element, index) => {
    element.classList.toggle(
      "active",
      index === (accepted ? (active ? 1 : 2) : 0),
    );
  });
  $("empty-art").hidden = !!accepted;
  $("progress").hidden = !active;
  $("refresh").hidden = !accepted;
  $("refresh").disabled = busy || polling;
  $("refresh").textContent = polling ? "Checking…" : "Refresh status";
  $("result-count").textContent = status
    ? {
        pending: "Queued",
        running: "Searching",
        completed: `${result?.candidates?.length || 0} candidate${result?.candidates?.length === 1 ? "" : "s"}`,
        failed: "Failed",
      }[status]
    : "Awaiting upload";
  let [title, description] = states[status] || [
    "It's quiet. Too quiet.",
    "Drop a screenshot. We'll round up the GIFs for a little identity parade.",
  ];
  if (result?.result_kind === "no_candidates") {
    title = "No matching GIFs this time";
    description =
      "The search finished without a suitable match in this collection. Try a clearer crop or another screenshot.";
  } else if (status === "failed" && result?.error) {
    description = `${result.error.message} (${result.error.code})`;
  }
  $("status-title").textContent = title;
  $("status-description").textContent = description;
  $("trace").hidden = !accepted;
  $("request-id").textContent = accepted?.request_id || "";
  $("job-id").textContent = result?.job_id || accepted?.job_id || "";
  $("review-id").textContent = session?.review?.review_id || "Not reviewed yet";
  const meme50 = result?.search_profile === "meme50-v2";
  $("review-panel").hidden = meme50 || !hasCandidates;
  $("reject").disabled = busy || !!uncertainReview;
  $("review-retry").hidden = !uncertainReview;
  $("review-retry").disabled = busy;
  if (session?.review?.review_id) {
    feedback(
      "review-status",
      session.review.payload.decision === "accept"
        ? "Choice saved. Your selected GIF is ready to download."
        : "Feedback saved: none of these candidates match.",
    );
  } else if (uncertainReview && !busy) {
    feedback(
      "review-status",
      "Your previous choice has not been acknowledged. Retry saving it; this will not create a duplicate.",
      true,
    );
  }
  renderCandidates(!meme50 && hasCandidates ? result.candidates : []);
  renderOnline();
}

function onlineState() {
  return session?.accepted?.search_profile === "meme50-v2"
    ? session
    : session?.online;
}

function clearWebCards() {
  disposeMemeResults();
  $("web-candidates").replaceChildren();
}

function renderOnline() {
  const state = onlineState();
  const result = state?.result;
  const status = result?.status || state?.accepted?.status;
  const direct = !!state && state === session;
  const active =
    state?.accepted && (!result || ["pending", "running"].includes(status));
  const completed = status === "completed";
  const paged = completed && !!result?.page;
  const localReady = session?.result?.status === "completed" && !direct;
  $("continue-panel").hidden = !localReady;
  $("continue-form").hidden = status === "failed" && !state?.creation;
  $("continue-description").disabled = !!(busy || active || state?.creation);
  $("continue-submit").disabled = !!(busy || active);
  $("continue-submit").textContent = state?.creation
    ? "继续提交 · Resume online search"
    : "继续联网搜索 · Continue online";
  $("web-results").hidden = !state?.accepted;
  $("meme-controls").hidden = !paged;
  $("meme-retry").hidden = status !== "failed";
  $("meme-retry").disabled = busy || !!state?.creation;
  $("meme-analysis").hidden = !result?.analysis;
  $("meme-analysis").textContent =
    result?.analysis?.observations?.join(" · ") || "";
  if (!state?.accepted) return;
  const stages = {
    preprocessing: "Preparing image",
    understanding: "Understanding image",
    verifying: "Checking visual clues",
    recalling: "Searching sources",
    fetching: "Downloading and validating",
    reranking: "Ranking and grouping",
    finalizing: "Publishing results",
  };
  let message = active
    ? `${stages[result?.stage] || "Waiting for image search"} · ${result?.verified_count || 0} verified results`
    : status === "failed"
      ? result.error?.message || "Online search failed."
      : "No related images found";
  if (completed && (result?.page?.total_all || result?.candidates?.length))
    message = "Related images are ready";
  $(direct ? "status-title" : "web-status").textContent = message;
  if (direct) {
    $("web-status").textContent = "";
    if (paged) {
      $("result-count").textContent = `${result.page.total_all} images`;
      $("status-description").textContent =
        `${result.page.total_all} verified results`;
    }
  }
  if (paged) {
    $("media-filter").value = state.filter || "all";
    $("page-summary").textContent =
      `${result.page.total} in this filter · ${result.page.total_all} total`;
    $("next-page").disabled = !result.page.next_cursor;
    $("previous-page").disabled = !state.pageHistory?.length;
  }
  if (result)
    renderMemeResults($("web-candidates"), result, api, lifetime.signal, {
      download: downloadMeme,
      favorite: mountFavorite,
    });
}

function makeButton(label, className, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.className = className;
  button.addEventListener("click", handler);
  return button;
}

function renderCandidates(candidates) {
  const signature = JSON.stringify([session?.result?.job_id, candidates]);
  if (signature !== cardSignature) {
    disposeCards();
    cardSignature = signature;
    for (const candidate of [...candidates].sort((a, b) => a.rank - b.rank)) {
      const card = document.createElement("article");
      card.className = "candidate";
      card.dataset.id = candidate.candidate_id;
      const media = document.createElement("div");
      media.className = "candidate-media";
      const note = document.createElement("span");
      note.className = "media-note";
      note.textContent = "Loading animation…";
      const rank = document.createElement("span");
      rank.className = "rank";
      rank.textContent = `#${candidate.rank}`;
      media.append(note, rank);
      const body = document.createElement("div");
      body.className = "candidate-body";
      const score = document.createElement("p");
      score.textContent = `Similarity ${candidate.score.toFixed(3)}`;
      const accept = makeButton("This is the one", "primary accept", () =>
        choose("accept", candidate.candidate_id),
      );
      const download = makeButton("Download GIF ↓", "secondary download", () =>
        downloadCandidate(candidate, download),
      );
      const reload = makeButton("Reload preview", "quiet reload", () =>
        loadMedia(candidate, media, reload),
      );
      reload.hidden = true;
      body.append(score, accept, download, reload);
      if (candidate.asset_id && candidate.save_status === "saved") {
        card.dataset.saved = "true";
        card.dataset.assetId = candidate.asset_id;
        const status = document.createElement("p");
        status.textContent = favoriteLabel(candidate.index_status);
        body.append(status);
      }
      card.append(media, body);
      $("candidates").append(card);
      loadMedia(candidate, media, reload);
    }
  }
  const review = session?.review;
  for (const card of $("candidates").children) {
    const selected =
      review?.review_id &&
      review.payload.decision === "accept" &&
      review.payload.candidate_id === card.dataset.id;
    card.classList.toggle("selected", !!selected);
    card.querySelector(".accept").textContent = selected
      ? "Selected ✓"
      : "This is the one";
    card.querySelector(".accept").disabled =
      busy || !!(review && !review.review_id) || !!selected;
    card.querySelector(".download").hidden = !selected && !card.dataset.saved;
    card.querySelector(".download").disabled = busy;
  }
}

async function loadMedia(candidate, container, retry) {
  const currentEpoch = epoch;
  retry.hidden = true;
  container.querySelector("img")?.remove();
  const note = container.querySelector(".media-note");
  note.hidden = false;
  note.textContent = "Loading animation…";
  try {
    const blob = await api.media(candidate.media_url, lifetime.signal);
    if (currentEpoch !== epoch || !container.isConnected) return;
    const previous = mediaURLs.get(candidate.candidate_id);
    if (previous) URL.revokeObjectURL(previous);
    const url = URL.createObjectURL(blob);
    mediaURLs.set(candidate.candidate_id, url);
    const image = new Image();
    image.alt = `Animated GIF candidate ${candidate.rank}`;
    image.onload = () => {
      note.hidden = true;
    };
    image.onerror = () => {
      note.textContent =
        "Could not decode this animation. Try loading the preview again.";
      retry.hidden = false;
      image.remove();
    };
    image.src = url;
    container.append(image);
  } catch (error) {
    if (currentEpoch !== epoch) return;
    note.textContent = error.message;
    retry.hidden = false;
  }
}

async function selectFile(file) {
  if (!file || busy || !initialized) return;
  busy = true;
  render();
  notice();
  try {
    if (
      !["image/png", "image/jpeg", "image/webp", "image/gif"].includes(
        file.type,
      )
    )
      throw new Error("Choose a PNG, JPG, WebP, or GIF image.");
    if ($("search-mode").value === "legacy" && file.type === "image/gif")
      throw new Error("Use a PNG, JPEG, or WebP screenshot for local search.");
    if (!file.size || file.size > 10 * 1024 * 1024)
      throw new Error(
        "This file is empty or larger than 10 MiB. Choose a smaller image.",
      );
    const bitmap = await createImageBitmap(file).catch(() => {
      throw new Error(
        "This image could not be decoded. Export the screenshot again.",
      );
    });
    const tooLarge = bitmap.width * bitmap.height > 20000000;
    bitmap.close();
    if (tooLarge)
      throw new Error(
        "This image exceeds 20 megapixels. Crop the target area first.",
      );
    const next = {
      file,
      searchProfile: $("search-mode").value,
      description: $("description").value,
      filter: "all",
      pageHistory: [],
      submissionKey: newKey(),
      submissionStarted: false,
      accepted: null,
      result: null,
      review: null,
    };
    await saveSession(next);
    cancelSessionWork();
    session = next;
    renderInput();
    feedback("review-status", "");
    feedback("download-status", "");
  } catch (error) {
    notice(error.message);
  } finally {
    busy = false;
    $("file-input").value = "";
    render();
  }
}

async function submit() {
  if (busy || !session?.file || session.accepted) return;
  if (session.searchProfile === "legacy" && session.file.type === "image/gif") {
    notice("Use a PNG, JPEG, or WebP screenshot for local search.");
    return;
  }
  busy = true;
  notice();
  render();
  const currentEpoch = epoch;
  try {
    session.submissionStarted = true;
    // Persist the exact File and key before sending, including ambiguous timeouts.
    await saveSession(session);
    const accepted = validAccepted(
      await api.submit(
        session.file,
        session.submissionKey,
        lifetime.signal,
        session.searchProfile === "legacy"
          ? {}
          : {
              search_profile: "meme50-v2",
              description: session.description ?? $("description").value,
              target_count: 50,
            },
      ),
    );
    if (currentEpoch !== epoch) return;
    session.accepted = accepted;
    await saveSession(session);
  } catch (error) {
    if (currentEpoch === epoch)
      notice(`${error.message}${error.code ? ` [${error.code}]` : ""}`);
  } finally {
    if (currentEpoch === epoch) {
      busy = false;
      render();
      if (session?.accepted) poll();
    }
  }
}

async function poll() {
  clearTimeout(pollTimer);
  if (!session?.accepted || document.hidden) return;
  if (polling) {
    pollAgain = true;
    return;
  }
  pollAgain = false;
  const currentEpoch = epoch;
  const requestId = session.accepted.request_id;
  const searchSession = session;
  polling = true;
  render();
  let succeeded = false;
  try {
    const direct = searchSession.accepted.search_profile === "meme50-v2";
    if (!direct) {
      const previousOnline = searchSession.online;
      const previousOnlineJob = previousOnline?.accepted?.job_id;
      const relation = validAccepted(
        await api.status(requestId, lifetime.signal),
      );
      if (relation.request_id !== requestId)
        throw new Error("Search request mismatch.");
      if (currentEpoch !== epoch) return;
      const localId = relation.local_job_id || searchSession.accepted.job_id;
      const local =
        relation.job_id === localId && relation.job_kind !== "web"
          ? validStatus(relation)
          : await readJobResult(requestId, localId, "local");
      if (currentEpoch !== epoch) return;
      if (searchSession.review && searchSession.review.jobId !== local.job_id) {
        searchSession.review = null;
        feedback("review-status", "");
        feedback("download-status", "");
      }
      searchSession.result = local;
      const latest = relation.web_searches?.at(-1);
      const online = searchSession.online;
      if (
        latest &&
        latest.job_id !== online?.accepted?.job_id &&
        online === previousOnline &&
        online?.accepted?.job_id === previousOnlineJob &&
        !online?.creation &&
        !online?.retryKey &&
        !busy
      ) {
        searchSession.online = {
          accepted: validAccepted({ ...latest, request_id: requestId }),
        };
        clearWebCards();
      }
    }
    const web = direct ? searchSession : searchSession.online;
    if (web?.accepted) {
      const webId = web.accepted.job_id;
      const navigation = JSON.stringify([web.filter, web.cursor]);
      const view = { ...web };
      const summary = web.accepted.search_profile
        ? null
        : await api.request(`/search-jobs/${encodeURIComponent(webId)}`, {
            signal: lifetime.signal,
          });
      if (currentEpoch !== epoch) return;
      const profile = summary?.search_profile || web.accepted.search_profile;
      const result =
        profile === "meme50-v2"
          ? await memeStatus(
              api,
              {
                ...web.accepted,
                ...(direct ? {} : { job_kind: "web" }),
              },
              view,
              lifetime.signal,
              summary,
            )
          : await readJobResult(requestId, webId, "web", summary);
      if (currentEpoch !== epoch) return;
      if (
        web !== onlineState() ||
        webId !== web.accepted.job_id ||
        navigation !== JSON.stringify([web.filter, web.cursor])
      ) {
        pollAgain = true;
        return;
      }
      web.accepted = { ...web.accepted, search_profile: result.search_profile };
      web.result = result;
      web.revision = view.revision;
      web.cursor = view.cursor;
      web.pageHistory = view.pageHistory;
    }
    await saveSession(session);
    if (currentEpoch !== epoch) return;
    notice();
    succeeded = true;
  } catch (error) {
    if (currentEpoch === epoch)
      notice(
        `${error.message} Status checks are interrupted; your background task continues. Select Refresh status to reconnect.`,
      );
  } finally {
    if (currentEpoch === epoch) {
      polling = false;
      render();
      if (pollAgain && !document.hidden) {
        pollTimer = setTimeout(poll, 0);
      } else if (
        succeeded &&
        [session.result, onlineState()?.result].some((result) =>
          ["pending", "running"].includes(result?.status),
        ) &&
        !document.hidden
      ) {
        pollTimer = setTimeout(poll, 1500);
      }
    }
  }
}

async function choose(decision, candidateId = null) {
  if (
    busy ||
    session?.result?.status !== "completed" ||
    (session.review && !session.review.review_id)
  )
    return;
  session.review = {
    jobId: session.result.job_id,
    payload: {
      decision,
      candidate_id: candidateId,
      client_review_key: newKey(),
    },
    review_id: null,
  };
  await sendReview();
}

async function sendReview() {
  if (busy || !session?.review || session.review.review_id) return;
  busy = true;
  const currentEpoch = epoch;
  notice();
  feedback("review-status", "Saving your choice…");
  feedback("download-status", "");
  render();
  try {
    const review = session.review;
    await saveSession(session);
    const result = await api.review(
      review.jobId,
      review.payload,
      lifetime.signal,
    );
    if (currentEpoch !== epoch) return;
    if (typeof result.review_id !== "string" || !result.review_id)
      throw new Error(
        "The server did not return a review ID. Retry saving your choice.",
      );
    review.review_id = result.review_id;
    await saveSession(session);
    if (review.payload.decision === "accept") celebrate();
  } catch (error) {
    if (currentEpoch === epoch) notice(error.message);
  } finally {
    if (currentEpoch === epoch) {
      busy = false;
      render();
    }
  }
}

async function downloadCandidate(candidate, button) {
  if (
    busy ||
    (!candidate.asset_id &&
      (!session?.review?.review_id ||
        session.review.payload.candidate_id !== candidate.candidate_id))
  )
    return;
  const currentEpoch = epoch;
  busy = true;
  render();
  button.textContent = "Fetching file…";
  feedback("download-status", "Fetching the GIF file…");
  try {
    // Re-fetch so expired or unavailable media is reported instead of silently
    // treating an earlier preview as a successful current download.
    const urlPath = candidate.asset_id
      ? `/saved-assets/${encodeURIComponent(candidate.asset_id)}/media`
      : candidate.media_url;
    const blob = await api.media(urlPath, lifetime.signal);
    if (currentEpoch !== epoch) return;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `meme-${candidate.candidate_id}.gif`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    feedback(
      "download-status",
      "Download started. Open the file from your browser downloads and check that the animation plays.",
    );
  } catch (error) {
    if (currentEpoch === epoch)
      feedback(
        "download-status",
        `Download failed: ${error.message} Your saved choice is unchanged.`,
        true,
      );
  } finally {
    if (currentEpoch === epoch) {
      busy = false;
      button.textContent = "Download GIF ↓";
      render();
    }
  }
}

async function reset(keepFile = false) {
  if (busy || !initialized) return;
  busy = true;
  render();
  try {
    const next =
      keepFile && session?.file
        ? {
            file: session.file,
            searchProfile: $("search-mode").value,
            description: $("description").value,
            submissionKey: newKey(),
            submissionStarted: false,
            accepted: null,
            result: null,
            review: null,
          }
        : null;
    await saveSession(next);
    cancelSessionWork();
    session = next;
    notice();
    feedback("review-status", "");
    feedback("download-status", "");
    renderInput();
  } catch (error) {
    notice(error.message);
  } finally {
    busy = false;
    render();
  }
}

async function checkHealth() {
  try {
    await api.request("/health/ready", { timeout: 5000 });
    $("health-dot").className = "status-dot ok";
    $("health-label").textContent = "API ready";
  } catch {
    $("health-dot").className = "status-dot bad";
    $("health-label").textContent = "Check connection";
  }
}

// Decorative interactions stay independent of the search and persistence flow.
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
let motionPreference = "on";
try {
  motionPreference = localStorage.getItem("memeretrieve-motion") || "on";
} catch {
  // Search still works when optional preference storage is unavailable.
}
let celebrationTimer;

function motionEnabled() {
  return motionPreference !== "off" && !reducedMotion.matches;
}

function updateMotion() {
  const enabled = motionEnabled();
  document.documentElement.dataset.motion = enabled ? "on" : "off";
  $("motion-toggle").setAttribute("aria-pressed", String(enabled));
  $("motion-toggle").textContent = reducedMotion.matches
    ? "Motion: reduced"
    : `Motion: ${enabled ? "on" : "off"}`;
  $("motion-toggle").disabled = reducedMotion.matches;
  if (!enabled) {
    $("celebration").replaceChildren();
    $("hero-art").style.removeProperty("--eye-x");
    $("hero-art").style.removeProperty("--eye-y");
  }
}

function celebrate() {
  if (!motionEnabled()) return;
  clearTimeout(celebrationTimer);
  const pieces = Array.from({ length: 16 }, (_, index) => {
    const piece = document.createElement("span");
    piece.className = "confetti";
    const angle = (index / 16) * Math.PI * 2;
    piece.style.setProperty("--dx", `${Math.cos(angle) * 230}px`);
    piece.style.setProperty("--dy", `${Math.sin(angle) * 190 - 90}px`);
    piece.style.setProperty("--spin", `${index * 73}deg`);
    return piece;
  });
  $("celebration").replaceChildren(...pieces);
  celebrationTimer = setTimeout(() => $("celebration").replaceChildren(), 1300);
}

$("motion-toggle").addEventListener("click", () => {
  motionPreference = motionEnabled() ? "off" : "on";
  try {
    localStorage.setItem("memeretrieve-motion", motionPreference);
  } catch {
    // The control remains usable for the current page.
  }
  updateMotion();
});
reducedMotion.addEventListener("change", updateMotion);
updateMotion();

const mascotLines = [
  "I was framed. Literally.",
  "No thoughts. Just loops.",
  "Please return me to the group chat.",
  "I'm not lost. I'm buffering.",
  "head empty. GIF folder full.",
];
let boops = 0;
$("mascot").addEventListener("click", () => {
  $("mascot-caption").textContent = mascotLines[boops++ % mascotLines.length];
});
$("hero-art").addEventListener("pointermove", (event) => {
  if (!motionEnabled() || event.pointerType !== "mouse") return;
  const bounds = $("hero-art").getBoundingClientRect();
  const x = ((event.clientX - bounds.left) / bounds.width - 0.5) * 12;
  const y = ((event.clientY - bounds.top) / bounds.height - 0.5) * 10;
  $("hero-art").style.setProperty("--eye-x", `${x.toFixed(1)}px`);
  $("hero-art").style.setProperty("--eye-y", `${y.toFixed(1)}px`);
});
$("hero-art").addEventListener("pointerleave", () => {
  $("hero-art").style.removeProperty("--eye-x");
  $("hero-art").style.removeProperty("--eye-y");
});

$("file-input").addEventListener("change", (event) =>
  selectFile(event.target.files[0]),
);
$("dropzone").addEventListener("dragover", (event) => {
  event.preventDefault();
  $("dropzone").classList.add("dragging");
});
$("dropzone").addEventListener("dragleave", () =>
  $("dropzone").classList.remove("dragging"),
);
$("dropzone").addEventListener("drop", (event) => {
  event.preventDefault();
  $("dropzone").classList.remove("dragging");
  if (event.dataTransfer.files.length !== 1) {
    notice("Choose one screenshot at a time.");
    return;
  }
  selectFile(event.dataTransfer.files[0]);
});
$("submit").addEventListener("click", submit);
$("new-search").addEventListener("click", () => reset(true));
$("forget").addEventListener("click", () => reset(false));
$("refresh").addEventListener("click", poll);
$("reject").addEventListener("click", () => choose("reject_all"));
$("review-retry").addEventListener("click", sendReview);
$("connection-toggle").addEventListener("click", () => {
  $("connection-panel").hidden = !$("connection-panel").hidden;
  $("connection-toggle").setAttribute(
    "aria-expanded",
    String(!$("connection-panel").hidden),
  );
});
$("connection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  api.token = $("token").value.trim();
  loadDemoLibrary();
  // Cancel requests using the previous credential and rebuild media with it.
  cancelSessionWork();
  render();
  await checkHealth();
  if (session?.accepted) poll();
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearTimeout(pollTimer);
  else if (
    session?.accepted &&
    (!["completed", "failed"].includes(session.result?.status) ||
      (onlineState()?.accepted &&
        !["completed", "failed"].includes(onlineState()?.result?.status)))
  )
    poll();
});
window.addEventListener("online", () => {
  checkHealth();
  if (session?.accepted) poll();
});
window.addEventListener("pagehide", () => {
  clearTimeout(pollTimer);
  lifetime.abort();
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    cancelSessionWork();
    render();
    if (session?.accepted) poll();
  }
});

try {
  session = (await loadSession()) || null;
  if (session?.accepted) validAccepted(session.accepted);
  if (
    session?.accepted &&
    !session.accepted.search_profile &&
    session.result?.search_profile === "meme50-v2" &&
    session.result.job_id === session.accepted.job_id &&
    session.result.job_kind !== "local"
  ) {
    session.accepted.search_profile = "meme50-v2";
  }
  if (session?.result && session.accepted?.search_profile !== "meme50-v2") {
    if (
      session.result.search_profile === "meme50-v2" ||
      session.result.job_kind === "web"
    )
      session.result = null;
    else validStatus(session.result);
  }
  renderInput();
} catch (error) {
  session = null;
  notice(error.message);
} finally {
  initialized = true;
  render();
  checkHealth();
  if (session?.accepted) poll();
}

async function loadDemoLibrary() {
  try {
    const { examples } = await api.request("/demo-library");
    if (!Array.isArray(examples) || !examples.length) return;
    const container = $("demo-examples");
    container.replaceChildren();
    for (const example of examples.slice(0, 24)) {
      const button = makeButton(example.title, "demo-example", async () => {
        if (busy || !initialized) return;
        button.disabled = true;
        const selectedEpoch = epoch;
        try {
          const blob = await api.request(example.screenshot_url, {
            binary: true,
          });
          if (epoch !== selectedEpoch) return;
          await selectFile(
            new File([blob], `${example.title}.png`, { type: blob.type }),
          );
        } catch (error) {
          notice(error.message);
        } finally {
          button.disabled = false;
        }
      });
      container.append(button);
    }
    $("demo-library").hidden = false;
  } catch {
    // The example library is optional; normal uploads remain available.
  }
}
loadDemoLibrary();

async function downloadMeme(candidate) {
  try {
    const blob = await api.media(candidate.media_url, lifetime.signal);
    const extension = {
      "image/gif": "gif",
      "image/png": "png",
      "image/jpeg": "jpg",
      "image/webp": "webp",
    }[blob.type.split(";")[0]];
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `meme-${candidate.candidate_id}.${extension}`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) {
    notice(error.message);
  }
}
$("search-mode").addEventListener("change", async () => {
  if (session?.file) await reset(true);
  render();
});
$("description").addEventListener("input", async () => {
  if (session && !session.submissionStarted) {
    session.description = $("description").value;
    await saveSession(session);
  }
});
async function readJobResult(requestId, id, kind, summary = null) {
  const signal = lifetime.signal;
  const path = `/search-jobs/${encodeURIComponent(id)}`;
  const job =
    summary?.result_kind !== undefined
      ? summary
      : await api.request(path, { signal });
  if (
    job.job_id !== id ||
    job.request_id !== requestId ||
    job.job_kind !== kind
  )
    throw new Error("Search job does not belong to this request.");
  const candidates =
    job.status === "completed"
      ? await api.request(`${path}/candidates`, { signal })
      : [];
  return validStatus({
    ...job,
    candidates: candidates.map((candidate) => ({
      ...candidate,
      ...(kind === "web"
        ? {
            media_kind: candidate.media_kind || "animated",
            media_format: candidate.media_format || "GIF",
            frame_count: candidate.frame_count || 2,
            preview_url: candidate.preview_url || candidate.media_url,
          }
        : {}),
    })),
  });
}

$("continue-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (
    busy ||
    session?.result?.status !== "completed" ||
    ["pending", "running"].includes(
      session.online?.result?.status || session.online?.accepted?.status,
    )
  )
    return;
  const state = (session.online ||= {});
  busy = true;
  try {
    state.creation ||= {
      requestId: session.accepted.request_id,
      payload: {
        description: $("continue-description").value.trim(),
        client_search_key: newKey(),
        search_profile: "meme50-v2",
      },
    };
    render();
    await saveSession(session);
    const { requestId, payload } = state.creation;
    const accepted = validAccepted(
      await api.continueOnline(requestId, payload, lifetime.signal),
    );
    validateOnlineAccepted(accepted, session.result.job_id);
    session.online = { accepted };
    clearWebCards();
    await saveSession(session);
    $("continue-description").value = "";
    feedback("continue-feedback", "");
  } catch (error) {
    feedback("continue-feedback", error.message, true);
  } finally {
    busy = false;
    render();
    poll();
  }
});

function validateOnlineAccepted(accepted, previousId, profile = "meme50-v2") {
  if (
    accepted.request_id !== session.accepted.request_id ||
    accepted.job_id === previousId ||
    (accepted.search_profile || "legacy") !== profile
  )
    throw new Error("Invalid linked online search response.");
}

$("media-filter").addEventListener("change", async () => {
  const state = onlineState();
  if (!state) return;
  state.filter = $("media-filter").value;
  state.cursor = null;
  state.pageHistory = [];
  await saveSession(session);
  poll();
});
$("next-page").addEventListener("click", async () => {
  const state = onlineState();
  if (!state?.result?.page?.next_cursor) return;
  state.pageHistory = [...(state.pageHistory || []), state.cursor || null];
  state.cursor = state.result.page.next_cursor;
  await saveSession(session);
  poll();
});
$("previous-page").addEventListener("click", async () => {
  const state = onlineState();
  if (!state?.pageHistory?.length) return;
  state.cursor = state.pageHistory.pop();
  await saveSession(session);
  poll();
});
$("meme-retry").addEventListener("click", async () => {
  const state = onlineState();
  if (busy || state?.result?.status !== "failed") return;
  busy = true;
  render();
  try {
    state.retryKey ||= newKey();
    await saveSession(session);
    const accepted = validAccepted(
      await api.request(`/search-jobs/${state.result.job_id}/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_retry_key: state.retryKey }),
        signal: lifetime.signal,
      }),
    );
    validateOnlineAccepted(
      accepted,
      state.result.job_id,
      state.result.search_profile,
    );
    Object.assign(state, {
      accepted,
      result: null,
      revision: null,
      cursor: null,
      pageHistory: [],
      retryKey: null,
    });
    clearWebCards();
    await saveSession(session);
  } catch (error) {
    notice(error.message);
  } finally {
    busy = false;
    render();
    poll();
  }
});

function favoriteLabel(status) {
  return (
    {
      pending: "已收藏，等待建立索引 · Saved, indexing queued",
      running: "已收藏，正在建立索引 · Saved, indexing",
      ready: "已收藏，可在本地搜到 · Saved, searchable locally",
      failed: "已收藏，索引失败 · Saved, indexing failed",
    }[status] || ""
  );
}

function mountFavorite(jobId, candidate, body, download, signal) {
  const key = `favorite/${jobId}/${candidate.candidate_id}`;
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  const action = makeButton("确认并收藏 · Confirm and save", "secondary", act);
  action.disabled = true;
  body.append(status, action);
  let record;
  let timer;
  let error = "";
  let expired = false;
  signal.addEventListener("abort", () => clearTimeout(timer), { once: true });

  function show(working = false) {
    if (signal.aborted) return;
    const asset = record?.asset;
    if (asset) {
      download.dataset.mediaUrl = asset.media_url;
      body.closest(".candidate")?.setAttribute("data-asset-id", asset.asset_id);
    }
    status.textContent = [
      asset
        ? favoriteLabel(asset.index_status)
        : working
          ? "正在收藏 · Saving…"
          : "",
      asset?.index_error,
      error,
    ]
      .filter(Boolean)
      .join(" · ");
    action.textContent = asset
      ? error
        ? "重新读取 · Refresh index status"
        : "重试索引 · Retry indexing"
      : record?.reviewKey
        ? "继续收藏 · Resume saving"
        : "确认并收藏 · Confirm and save";
    action.hidden =
      expired || (!!asset && !error && asset.index_status !== "failed");
    action.disabled = working;
  }

  async function rememberAsset(asset) {
    if (
      asset?.save_status !== "saved" ||
      !asset.asset_id ||
      !asset.media_url ||
      !favoriteLabel(asset.index_status) ||
      (record.asset && asset.asset_id !== record.asset.asset_id)
    ) {
      throw new Error("The server returned invalid saved GIF details.");
    }
    record.asset = asset;
    await saveFavorite(key, record);
  }

  async function check(retry = false) {
    if (signal.aborted) return;
    clearTimeout(timer);
    error = "";
    show(true);
    try {
      await rememberAsset(
        await api.savedAsset(record.asset.asset_id, signal, retry),
      );
      if (
        ["pending", "running"].includes(record.asset.index_status) &&
        !signal.aborted
      )
        timer = setTimeout(check, 1500);
    } catch (failure) {
      error = failure.message;
    }
    show();
  }

  async function act() {
    if (record?.asset) {
      await check(!error && record.asset.index_status === "failed");
      return;
    }
    if (activeFavorites.has(key)) return;
    error = "";
    show(true);
    // Allow an acknowledged save to reach IndexedDB even if the card goes away.
    const operation = (async () => {
      record ||= { reviewKey: newKey(), saveKey: newKey() };
      await saveFavorite(key, record);
      if (!record.reviewId) {
        const review = await api.review(jobId, {
          candidate_id: candidate.candidate_id,
          decision: "accept",
          client_review_key: record.reviewKey,
        });
        if (!review?.review_id)
          throw new Error("The server did not acknowledge the confirmation.");
        record.reviewId = review.review_id;
        await saveFavorite(key, record);
      }
      await rememberAsset(
        await api.saveCandidate(candidate.candidate_id, record.saveKey),
      );
    })();
    activeFavorites.set(key, operation);
    try {
      await operation;
      await check();
    } catch (failure) {
      error = failure.message;
      expired = failure.status === 410;
      show();
    } finally {
      activeFavorites.delete(key);
    }
  }

  async function restore() {
    await activeFavorites.get(key)?.catch(() => {});
    record = await loadFavorite(key);
    if (!record?.asset && candidate.asset_id) {
      record = {
        ...record,
        asset: {
          asset_id: candidate.asset_id,
          media_url: `/saved-assets/${encodeURIComponent(candidate.asset_id)}/media`,
          save_status: "saved",
          index_status: candidate.index_status,
        },
      };
    }
    show();
    if (record?.asset) await check();
  }
  restore().catch((failure) => {
    error = failure.message;
    show();
  });
}
