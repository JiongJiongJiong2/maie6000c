import { Api } from "./api.js";
import { mountWorkspace } from "./workspace.js";

const byId = (id) => document.getElementById(id);
const variant = document.body.dataset.variant;
const inWorkspace = document.body.dataset.workspacePage === "stickers";
const trafficSource = inWorkspace ? "workspace" : variant;
if (inWorkspace) mountWorkspace(new Api(), "stickers");
const directory = byId("directory");
const directoryStatus = byId("directory-status");
const finder = byId("finder");
const fileInput = byId("screenshot");
const dropZone = byId("drop-zone");
const preview = byId("screenshot-preview");
const fileLabel = byId("file-label");
const submit = byId("submit");
const sample = byId("sample");
const searchStatus = byId("search-status");
const matchPanel = byId("match-panel");
const matchTitle = byId("match-title");
const matchDescription = byId("match-description");
const matchList = byId("match-list");
const dialog = byId("pack-dialog");
const packs = new Map();
const maximumBytes = 5 * 1024 * 1024;
let screenshot;
let previewUrl;
let pending;
let example;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function packMetadata(pack) {
  const metadata = node("div", "pack-copy");
  metadata.append(
    node(
      "p",
      "pack-credit",
      `By ${pack.creator} · Published by ${pack.publisher}`,
    ),
    node("p", "pack-description", pack.description),
  );
  return metadata;
}

function stickerGallery(pack, stickers, full, matched) {
  const gallery = node("ul", `sticker-gallery theme-${pack.color}`);
  for (const sticker of stickers) {
    const item = node("li", "sticker");
    const image = node("img");
    image.alt = full ? "" : sticker.name;
    image.src = sticker.poster;
    image.width = 256;
    image.height = 256;
    image.loading = "lazy";
    item.append(image);
    if (full) {
      const caption = node("div", "sticker-caption", sticker.name);
      if (sticker.id === matched)
        caption.append(node("small", "", "Closest to your screenshot"));
      item.append(caption);
      if (sticker.animation) {
        const play = node("button", "text-button", "Play animation");
        play.type = "button";
        play.setAttribute("aria-label", `Play animation for ${sticker.name}`);
        play.addEventListener("click", () => {
          const playing = image.getAttribute("src") === sticker.animation;
          image.src = playing ? sticker.poster : sticker.animation;
          play.textContent = playing ? "Play animation" : "Stop animation";
          play.setAttribute(
            "aria-label",
            `${play.textContent} for ${sticker.name}`,
          );
        });
        item.append(play);
      }
    }
    gallery.append(item);
  }
  return gallery;
}

function claimActions(pack) {
  const actions = node("div", "claim-actions");
  for (const channel of pack.channels) {
    const form = node("form");
    form.method = "post";
    form.action = `/stickers/packs/${pack.id}/claim/${channel.id}?view=${trafficSource}`;
    const claim = node("button", "button primary", channel.label);
    claim.append(
      node("span", "claim-arrow", channel.id === "archive" ? "↓" : "↗"),
    );
    claim.lastElementChild.setAttribute("aria-hidden", "true");
    form.append(claim);
    actions.append(form);
  }
  return actions;
}

function showPack(pack) {
  byId("pack-dialog-title").textContent = pack.name;
  byId("dialog-content").replaceChildren(
    packMetadata(pack),
    stickerGallery(pack, pack.stickers, true),
    claimActions(pack),
  );
  dialog.showModal();
}

function renderCard(pack, matched, expanded = false) {
  const card = node("article", "pack-card");
  const header = node("div", "card-top");
  header.append(
    node("h3", "", pack.name),
    node(
      "p",
      "pack-count",
      `${pack.stickers.length} ${pack.stickers.length === 1 ? "sticker" : "stickers"}`,
    ),
  );
  const stickers = expanded ? pack.stickers : pack.stickers.slice(0, 3);
  const gallery = stickerGallery(pack, stickers, expanded, matched);
  const details = packMetadata(pack);
  if (expanded) {
    details.append(claimActions(pack));
  } else {
    const open = node("button", "button secondary", "View pack");
    open.type = "button";
    open.setAttribute("aria-label", `View pack: ${pack.name}`);
    open.addEventListener("click", () => showPack(pack));
    details.append(open);
  }
  card.append(header, gallery, details);
  return card;
}

function renderSource(source, verified) {
  const card = node("article", "pack-card web-source");
  const url = new URL(source.url);
  const link = node(
    "a",
    verified ? "button primary source-link" : "button secondary source-link",
    verified ? "Open pickup link ↗" : "Open candidate page ↗",
  );
  link.href = url.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  const detail = [source.channel, source.publisher, url.hostname]
    .filter(Boolean)
    .join(" · ");
  card.append(node("p", "pack-credit", detail), node("h4", "", source.title));
  if (!verified) {
    card.append(
      node(
        "p",
        "source-evidence",
        {
          text: "Name or text match · artwork unverified",
          series: "Related pack or collection · exact sticker unverified",
          artwork: "Artwork match · pickup unverified",
        }[source.match_basis || "artwork"],
      ),
    );
  }
  card.append(link);
  if (source.evidence_url) {
    const evidence = node("a", "text-button", "Publisher source ↗");
    evidence.href = source.evidence_url;
    evidence.target = "_blank";
    evidence.rel = "noopener noreferrer";
    card.append(evidence);
  }
  return card;
}

function showWebSources(result) {
  const verified = result.links.length > 0;
  const candidates = result.leads.length > 0;
  matchTitle.textContent =
    {
      unavailable: "Public search temporarily unavailable",
      busy: "Public search is busy",
      matched: "Verified pickup link found",
      candidates: "Possible pickup sources found",
    }[result.state] || "No pickup source found";
  matchDescription.textContent =
    result.state === "unavailable" || result.state === "busy"
      ? "Try again in a moment."
      : verified
        ? "The published sticker artwork matches your screenshot."
        : candidates
          ? "Compare these sticker packs, collections, and release pages with your screenshot."
          : "Try a tighter crop that includes the sticker and any text printed on it.";
  for (const [title, sources, confirmed] of [
    ["Verified links", result.links, true],
    ["Candidate pages", result.leads, false],
  ]) {
    if (!sources.length) continue;
    matchList.append(
      node("h3", "source-group-title", title),
      ...sources.map((source) => renderSource(source, confirmed)),
    );
  }
}

function status(message = "") {
  searchStatus.textContent = message;
  searchStatus.hidden = !message;
}

function clearMatches() {
  matchPanel.hidden = true;
  matchList.replaceChildren();
}

function selectScreenshot(file, label = file?.name) {
  pending?.abort();
  pending = null;
  clearMatches();
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  preview.removeAttribute("src");
  preview.hidden = true;
  dropZone.classList.remove("has-preview");
  fileLabel.textContent = "Choose or drop a screenshot";
  screenshot = null;
  submit.disabled = true;
  status();
  if (!file) return false;
  if (!file.size || file.size > maximumBytes) {
    status("Choose a screenshot that is between 1 byte and 5 MB.");
    return false;
  }
  if (
    file.type &&
    !["image/jpeg", "image/png", "image/webp"].includes(file.type)
  ) {
    status("Choose a PNG, JPG, or WebP screenshot.");
    return false;
  }
  screenshot = file;
  previewUrl = URL.createObjectURL(file);
  preview.src = previewUrl;
  preview.hidden = false;
  dropZone.classList.add("has-preview");
  fileLabel.textContent = label;
  submit.disabled = false;
  return true;
}

async function search() {
  if (!screenshot || pending) return;
  const attempt = new AbortController();
  pending = attempt;
  submit.disabled = true;
  clearMatches();
  status("Finding the sticker source and checking pickup links…");
  try {
    const response = await fetch(`/stickers/search?view=${trafficSource}`, {
      method: "POST",
      body: screenshot,
      signal: attempt.signal,
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.detail || "Search is temporarily unavailable.");
    if (result.web) {
      showWebSources(result.web);
    } else {
      await directoryReady;
      if (attempt.signal.aborted) return;
      const matches = result.matches.filter((item) => packs.has(item.packId));
      matchTitle.textContent =
        matches.length === 1
          ? "Sticker pack found"
          : matches.length
            ? "Possible sticker packs"
            : "No clear match";
      matchDescription.textContent =
        matches.length > 1
          ? "Compare the closest stickers to find the right pack."
          : "";
      for (const item of matches) {
        matchList.append(
          renderCard(packs.get(item.packId), item.stickerId, true),
        );
      }
    }
    matchDescription.hidden = !matchDescription.textContent;
    matchPanel.hidden = false;
    status();
    matchTitle.focus();
  } catch (error) {
    if (!attempt.signal.aborted) {
      status(
        error instanceof TypeError
          ? "Connection interrupted. Try again."
          : error.message,
      );
    }
  } finally {
    if (pending === attempt) {
      pending = null;
      submit.disabled = false;
    }
  }
}

async function loadDirectory() {
  try {
    const response = await fetch("/stickers/catalog");
    if (!response.ok)
      throw new Error("The sticker catalog is temporarily unavailable.");
    const catalog = await response.json();
    for (const pack of catalog.packs) {
      packs.set(pack.id, pack);
      directory.append(renderCard(pack));
    }
    directoryStatus.hidden = true;
    byId("demo-note").hidden = !catalog.demo;
    example = catalog.example;
    sample.hidden = !example;
  } catch {
    directoryStatus.textContent =
      "The sticker catalog is temporarily unavailable. Please reload to try again.";
  }
}

if (variant === "directory") {
  finder.hidden = true;
  document.querySelector(".hero-lead").hidden = true;
  document.querySelector(".directory-lead").hidden = false;
  byId("hero-title").textContent = "Browse sticker packs.";
}

fileInput.addEventListener("change", () => {
  selectScreenshot(fileInput.files[0]);
  fileInput.value = "";
});
for (const eventName of ["dragenter", "dragover"]) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
}
dropZone.addEventListener("dragleave", (event) => {
  if (!dropZone.contains(event.relatedTarget))
    dropZone.classList.remove("dragging");
});
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
  selectScreenshot(event.dataTransfer.files[0]);
});
finder.addEventListener("submit", (event) => {
  event.preventDefault();
  search();
});
sample.addEventListener("click", async () => {
  sample.disabled = true;
  const previousScreenshot = screenshot;
  try {
    const response = await fetch(example);
    if (!response.ok) throw new Error();
    const image = await response.blob();
    if (
      screenshot === previousScreenshot &&
      selectScreenshot(image, "Sample screenshot")
    )
      await search();
  } catch {
    status("Could not load the sample screenshot. Try again.");
  } finally {
    sample.disabled = false;
  }
});
dialog.addEventListener("close", () =>
  byId("dialog-content").replaceChildren(),
);
const directoryReady = loadDirectory();
