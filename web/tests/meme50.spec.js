import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";
const requestId = "10000000-0000-4000-8000-000000000001";
const jobId = "20000000-0000-4000-8000-000000000001";
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAIAAABvFaqvAAAAKklEQVR4nGPc4W3AQA3ARBVTGEYNIgaMGkQYjBpEGIwaRBiMGkQYDD6DAN66AWOTozgdAAAAAElFTkSuQmCC",
  "base64",
);
const accepted = {
  request_id: requestId,
  job_id: jobId,
  status: "pending",
  search_profile: "meme50-v2",
  contract_version: 2,
  target_count: 50,
};
const candidates = Array.from({ length: 50 }, (_, i) => ({
  candidate_id: `30000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`,
  rank: i + 1,
  score: 0.9 - i / 100,
  media_kind: i % 2 ? "animated" : "static",
  media_format: i % 2 ? "GIF" : "PNG",
  mime_type: i % 2 ? "image/gif" : "image/png",
  frame_count: i % 2 ? 2 : 1,
  media_url: `/candidates/${i + 1}/media`,
  preview_url: `/candidates/${i + 1}/preview`,
  source_url: `https://example.org/${i + 1}`,
}));

// Deliberately controlled responses: contract/UI checks, not live quality evidence.
test("empty text submits v2 once, pages fifty, filters, downloads and restores", async ({
  page,
}) => {
  const uploads = [];
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/health/ready", (r) =>
    r.fulfill({ json: { status: "ok" } }),
  );
  await page.route("**/search-requests", (r) => {
    uploads.push(r.request().postDataBuffer().toString());
    return r.fulfill({ status: 202, json: accepted });
  });
  await page.route(`**/search-jobs/${jobId}`, (r) =>
    r.fulfill({
      json: {
        ...accepted,
        status: "completed",
        stage: "completed",
        result_count: 50,
        result_revision: "frozen",
        partial: false,
        progress: {},
        analysis: { observations: ["controlled visible facts"] },
      },
    }),
  );
  await page.route(`**/search-jobs/${jobId}/results?*`, async (r) => {
    const params = new URL(r.request().url()).searchParams;
    const kind = params.get("media_kind");
    if (kind === "animated")
      await new Promise((resolve) => setTimeout(resolve, 200));
    const items = candidates.filter(
      (c) => kind === "all" || c.media_kind === kind,
    );
    const offset = Number(params.get("cursor") || 0);
    return r.fulfill({
      json: {
        job_id: jobId,
        revision: "frozen",
        items: items.slice(offset, offset + 20),
        total: items.length,
        total_all: 50,
        counts: { static: 25, animated: 25 },
        next_cursor: offset + 20 < items.length ? String(offset + 20) : null,
      },
    });
  });
  await page.route("**/candidates/*/preview", (r) =>
    r.fulfill({ contentType: "image/png", body: png }),
  );
  await page.route("**/candidates/*/media", (r) =>
    r.fulfill({ contentType: "image/png", body: png }),
  );
  await page.goto("/web/");
  await expect(page.locator("#submit")).toBeDisabled();
  await page
    .locator("#file-input")
    .setInputFiles({ name: "random.png", mimeType: "image/png", buffer: png });
  await expect(page.locator("#submit")).toBeEnabled();
  await page.locator("#submit").click();
  await expect(page.locator(".candidate")).toHaveCount(20);
  expect(uploads).toHaveLength(1);
  expect(uploads[0]).toContain("meme50-v2");
  expect(uploads[0]).toMatch(/name="description"\r\n\r\n\r\n/);
  await expect(page.locator("#review-panel")).toBeHidden();
  await page.locator("#next-page").click();
  await expect(page.locator(".candidate").first()).toContainText("#21");
  await page.locator("#next-page").click();
  await expect(page.locator(".candidate")).toHaveCount(10);
  await expect(page.locator("#next-page")).toBeDisabled();
  await page.locator("#media-filter").selectOption("static");
  await expect(page.locator(".candidate")).toHaveCount(20);
  await expect(
    page.getByRole("button", { name: "Play animation", exact: true }),
  ).toHaveCount(0);
  await page.reload();
  await expect(page.locator("#media-filter")).toHaveValue("static");
  await expect(page.locator(".candidate")).toHaveCount(20);
  const downloadPromise = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download image ↓", exact: true })
    .first()
    .click();
  expect((await downloadPromise).suggestedFilename()).toMatch(/\.png$/);
  // A second navigation during an outstanding result fetch must win. This
  // reproduces the real filter/page race rather than only checking fast mocks.
  const animatedRequest = page.waitForRequest((r) =>
    r.url().includes("media_kind=animated"),
  );
  await page.locator("#media-filter").selectOption("animated");
  await animatedRequest;
  const finalStaticResponse = page.waitForResponse((r) =>
    r.url().includes("media_kind=static"),
  );
  await page.locator("#media-filter").selectOption("static");
  await finalStaticResponse;
  await expect(page.locator("#refresh")).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Play animation", exact: true }),
  ).toHaveCount(0);
  await page.locator("#next-page").click();
  await expect(page.locator(".candidate")).toHaveCount(5);
  await expect(page.locator(".candidate").first()).toContainText("#41");
  expect(errors).toEqual([]);
});

test("local human review stays unreviewed and exports bound identities only", async ({
  page,
}) => {
  const binding = {
    case_id: "controlled-case",
    job_id: "controlled-job",
    revision: "rev",
    candidate_id: "candidate",
    rank: "1",
    sha256: "a".repeat(64),
  };
  await page.setContent(
    `<input id="reviewer"><button id="export-labels">Export labels.csv</button><p id="review-message"></p><article data-result="0"></article><script id="bindings" type="application/json">${JSON.stringify([binding])}</script>`,
  );
  await page.addScriptTag({
    content: readFileSync(
      new URL("../../scripts/meme50_review_ui.js", import.meta.url),
      "utf8",
    ),
  });
  for (const name of [
    "relevance",
    "duplicate_status",
    "media_valid",
    "low_quality",
  ])
    await expect(page.locator(`[name="${name}"]`)).toHaveValue("unreviewed");
  await page.locator("#export-labels").click();
  await expect(page.locator("#review-message")).toContainText(
    "actual reviewer identity",
  );
  await page.locator("#reviewer").fill("CONTROLLED TEST REVIEWER");
  const waiting = page.waitForEvent("download");
  await page.locator("#export-labels").click();
  const csv = readFileSync(await (await waiting).path(), "utf8");
  expect(csv).toContain('"controlled-job","rev","candidate","1"');
  expect(csv).toContain('"unreviewed"');
  expect(csv).not.toContain('"clearly_related"');
});

test("favorites replay both keys, recover index status after refresh, and switch to local", async ({
  page,
}) => {
  const candidate = candidates[1];
  const assetId = "40000000-0000-4000-8000-000000000001";
  const uploads = [];
  const reviews = [];
  const saves = [];
  let indexStatus = "pending";
  const asset = () => ({
    asset_id: assetId,
    save_status: "saved",
    media_url: `/saved-assets/${assetId}/media`,
    index_status: indexStatus,
    index_error: indexStatus === "failed" ? "Model unavailable" : null,
  });
  await page.route("**/search-requests", (route) => {
    uploads.push(route.request().postData());
    return route.fulfill({
      status: 202,
      json:
        uploads.length === 1
          ? accepted
          : {
              request_id: requestId,
              job_id: jobId,
              status: "pending",
            },
    });
  });
  await page.route(`**/search-requests/${requestId}`, (route) =>
    route.fulfill({
      json: {
        request_id: requestId,
        job_id: jobId,
        job_kind: "local",
        status: "completed",
        result_kind: "candidates",
        candidates: [{ ...candidate, rank: 1, ...asset() }],
      },
    }),
  );
  await page.route(`**/search-jobs/${jobId}`, (route) =>
    route.fulfill({
      json: { ...accepted, status: "completed", result_revision: "frozen" },
    }),
  );
  await page.route(`**/search-jobs/${jobId}/results?*`, (route) =>
    route.fulfill({
      json: { revision: "frozen", items: [candidate], total: 1, total_all: 1 },
    }),
  );
  await page.route("**/reviews", (route) => {
    reviews.push(route.request().postDataJSON());
    return reviews.length === 1
      ? route.abort()
      : route.fulfill({ json: { review_id: "ack" } });
  });
  await page.route("**/candidates/*/save", (route) => {
    saves.push(route.request().postDataJSON());
    return saves.length === 1
      ? route.abort()
      : route.fulfill({ json: asset() });
  });
  await page.route(`**/saved-assets/${assetId}`, (route) =>
    route.fulfill({ json: asset() }),
  );
  await page.route(`**/saved-assets/${assetId}/index-retry`, (route) => {
    indexStatus = "ready";
    return route.fulfill({ json: asset() });
  });
  await page.goto("/web/");
  await page.locator("#file-input").setInputFiles({
    name: "screenshot.png",
    mimeType: "image/png",
    buffer: png,
  });
  await page.locator("#submit").click();
  await page.getByRole("button", { name: /Confirm and save/ }).click();
  await page.getByText(/Connection interrupted/).waitFor();
  await page.getByRole("button", { name: /Resume saving/ }).click();
  await page.getByText(/Connection interrupted/).waitFor();
  await page.reload();
  await page.getByRole("button", { name: /Resume saving/ }).click();
  await expect(page.getByText(/indexing queued/)).toBeVisible();
  expect(reviews).toHaveLength(2);
  expect(reviews[1]).toEqual(reviews[0]);
  expect(saves).toHaveLength(2);
  expect(saves[1]).toEqual(saves[0]);
  expect(saves[0].client_save_key).not.toBe(reviews[0].client_review_key);
  indexStatus = "failed";
  await expect(page.getByText(/Model unavailable/)).toBeVisible();
  await page.getByRole("button", { name: /Retry indexing/ }).click();
  await expect(page.getByText(/Saved, searchable locally/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/Saved, searchable locally/)).toBeVisible();
  await page.locator("#search-mode").selectOption("legacy");
  await page.locator("#submit").click();
  await expect(
    page.getByRole("button", { name: /Download GIF/ }),
  ).toBeVisible();
  expect(uploads[1]).not.toContain('name="search_profile"');
  expect(uploads[1]).not.toContain('name="target_count"');
  const submissionKey = /name="client_submission_key"\r\n\r\n([^\r]+)/;
  expect(uploads[1].match(submissionKey)[1]).not.toBe(
    uploads[0].match(submissionKey)[1],
  );
});

test("local results survive linked search acknowledgement loss, retry, and refresh", async ({
  page,
}) => {
  const gif = readFileSync(
    new URL("./fixtures/two-frames.gif", import.meta.url),
  );
  await page.addInitScript(() => {
    navigator.canShare = () => true;
    navigator.share = async ({ files }) => {
      window.linkedShare = Array.from(
        new Uint8Array(await files[0].arrayBuffer()),
      );
    };
  });
  await page.route("**/candidates/2/media", (route) =>
    route.fulfill({ contentType: "image/gif", body: gif }),
  );
  const webId = "20000000-0000-4000-8000-000000000002";
  const retryId = "20000000-0000-4000-8000-000000000003";
  const local = {
    request_id: requestId,
    job_id: jobId,
    status: "completed",
    job_kind: "local",
    result_kind: "candidates",
  };
  const candidate = candidates[1];
  const linked = { ...accepted, job_id: webId, job_kind: "web" };
  let latest;
  let uploads = 0;
  const creates = [];
  const reviews = [];
  await page.route("**/search-requests", (route) => {
    uploads++;
    return route.fulfill({ status: 202, json: local });
  });
  await page.route(`**/search-requests/${requestId}`, (route) =>
    route.fulfill({
      json: {
        ...(latest || local),
        local_job_id: jobId,
        web_searches: latest ? [latest] : [],
        candidates: latest ? [] : [candidate],
      },
    }),
  );
  await page.route(`**/search-jobs/${jobId}`, (route) =>
    route.fulfill({ json: local }),
  );
  await page.route(`**/search-jobs/${jobId}/candidates`, (route) =>
    route.fulfill({ json: [candidate] }),
  );
  await page.route(`**/search-jobs/${jobId}/reviews`, (route) => {
    reviews.push(route.request().postDataJSON());
    return route.fulfill({ json: { review_id: "local-review" } });
  });
  await page.route(`**/search-requests/${requestId}/web-search`, (route) => {
    creates.push(route.request().postDataJSON());
    latest = {
      ...linked,
      status: "failed",
      error: { message: "Provider unavailable" },
    };
    return creates.length === 1
      ? route.abort()
      : route.fulfill({ status: 202, json: linked });
  });
  await page.route(`**/search-jobs/${webId}`, (route) =>
    route.fulfill({ json: latest }),
  );
  await page.route(`**/search-jobs/${webId}/retry`, (route) => {
    expect(route.request().postDataJSON().client_retry_key).toBeTruthy();
    latest = {
      ...linked,
      job_id: retryId,
      status: "completed",
      result_revision: "retry",
    };
    return route.fulfill({ status: 202, json: latest });
  });
  await page.route(`**/search-jobs/${retryId}`, (route) =>
    route.fulfill({ json: latest }),
  );
  await page.route(`**/search-jobs/${retryId}/results?*`, (route) =>
    route.fulfill({
      json: { revision: "retry", items: [candidate], total: 1, total_all: 1 },
    }),
  );
  await page.goto("/web/");
  await page.locator("#search-mode").selectOption("legacy");
  await page.locator("#file-input").setInputFiles({
    name: "screenshot.png",
    mimeType: "image/png",
    buffer: png,
  });
  await page.locator("#submit").click();
  await page.getByRole("button", { name: "This is the one" }).click();
  await expect(page.locator("#review-id")).toHaveText("local-review");
  expect(creates).toHaveLength(0);
  await page.locator("#continue-description").fill("  green parrot  ");
  await page.locator("#continue-submit").click();
  await expect(page.locator("#continue-feedback")).toContainText(
    "Connection interrupted",
  );
  await page.reload();
  await expect(page.locator("#continue-description")).toHaveValue(
    "green parrot",
  );
  await page.locator("#continue-submit").click();
  await expect(page.locator("#web-status")).toHaveText("Provider unavailable");
  await expect(page.locator("#candidates .candidate")).toHaveCount(1);
  await page.locator("#meme-retry").click();
  await expect(page.locator("#web-candidates .candidate")).toHaveCount(1);
  await expect(page.locator("#web-candidates")).toContainText(
    "Confirm and save",
  );
  await page.reload();
  await expect(page.locator("#web-candidates .candidate")).toHaveCount(1);
  await expect(page.locator("#candidates .candidate")).toHaveCount(1);
  await expect(page.locator("#review-id")).toHaveText("local-review");
  await page
    .locator("#web-candidates")
    .getByRole("button", { name: /Share GIF/ })
    .click();
  await page.getByRole("button", { name: /Open share menu/ }).click();
  await expect
    .poll(() => page.evaluate(() => window.linkedShare))
    .toEqual([...gif]);
  expect(uploads).toBe(1);
  expect(reviews).toHaveLength(1);
  expect(creates).toHaveLength(2);
  expect(creates[0]).toEqual(creates[1]);
  expect(creates[0]).toMatchObject({
    description: "green parrot",
    search_profile: "meme50-v2",
  });
});

test("online file sharing is lazy, preserves bytes, and invalidates on favorite", async ({
  page,
}) => {
  const gif = readFileSync(
    new URL("./fixtures/two-frames.gif", import.meta.url),
  );
  const item = candidates[1];
  const asset = "50000000-0000-4000-8000-000000000001";
  const saved = {
    asset_id: asset,
    media_url: `/saved-assets/${asset}/media`,
    save_status: "saved",
    index_status: "ready",
  };
  const reads = [];
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  await page.addInitScript(() => {
    window.shareCalls = [];
    window.rejectShare = "AbortError";
    window.shareSupported = false;
    navigator.canShare = () => window.shareSupported;
    navigator.share = async (data) => {
      const [file] = data.files;
      window.shareCalls.push({
        keys: Object.keys(data),
        count: data.files.length,
        name: file.name,
        type: file.type,
        bytes: Array.from(new Uint8Array(await file.arrayBuffer())),
      });
      if (window.rejectShare)
        throw new DOMException("Share rejected", window.rejectShare);
    };
  });
  await page.route("**/search-requests", (r) => r.fulfill({ json: accepted }));
  await page.route(`**/search-jobs/${jobId}`, (r) =>
    r.fulfill({
      json: { ...accepted, status: "completed", result_revision: "share" },
    }),
  );
  await page.route("**/results?*", (r) =>
    r.fulfill({
      json: {
        revision: "share",
        items: [
          candidates[0],
          item,
          { ...candidates[2], media_format: "GIF", mime_type: "image/gif" },
          { ...candidates[3], media_format: "WEBP", mime_type: "image/webp" },
        ],
        total: 4,
        total_all: 4,
      },
    }),
  );
  await page.route("**/preview", (r) =>
    r.fulfill({ contentType: "image/png", body: png }),
  );
  await page.route("**/candidates/2/media", async (r) => {
    reads.push("candidate");
    await gate;
    await r.fulfill({ contentType: "image/gif", body: gif });
  });
  await page.route("**/reviews", (r) =>
    r.fulfill({ json: { review_id: "ok" } }),
  );
  await page.route("**/save", (r) => r.fulfill({ json: saved }));
  await page.route(`**/saved-assets/${asset}`, (r) =>
    r.fulfill({ json: saved }),
  );
  await page.route(`**/saved-assets/${asset}/media`, (r) => {
    reads.push("saved");
    return r.fulfill({ contentType: "image/gif", body: gif });
  });
  await page.goto("/web/");
  await page
    .locator("#file-input")
    .setInputFiles({ name: "test.png", mimeType: "image/png", buffer: png });
  await page.locator("#submit").click();
  const prepare = page.getByRole("button", { name: /Share GIF/ });
  const open = page.getByRole("button", { name: /Open share menu/ });
  await expect(prepare).toHaveCount(1);
  expect(reads).toEqual([]);
  await prepare.click();
  await expect(prepare).toBeDisabled();
  await expect(
    page.getByRole("button", { name: /Download image/ }).nth(1),
  ).toBeEnabled();
  release();
  await expect(page.getByText(/暂不支持分享/)).toBeVisible();
  await page.evaluate(() => {
    window.shareSupported = true;
  });
  await prepare.click();
  await expect(open).toBeEnabled();
  expect(await page.evaluate(() => window.shareCalls)).toEqual([]);
  await open.click();
  await expect(page.getByText(/分享未完成/)).toBeVisible();
  await page.evaluate(() => {
    window.rejectShare = "NotAllowedError";
  });
  await open.click();
  await expect(page.getByText(/分享未完成/)).toBeVisible();
  await page.getByRole("button", { name: /Confirm and save/ }).click();
  await expect(prepare).toBeVisible();
  await expect(open).toHaveCount(0);
  await prepare.click();
  await page.evaluate(() => {
    window.rejectShare = "";
  });
  await open.click();
  await expect(page.getByText(/已交给系统分享/)).toBeVisible();
  expect(reads).toEqual(["candidate", "candidate", "saved"]);
  const calls = await page.evaluate(() => window.shareCalls);
  expect(calls).toHaveLength(3);
  for (const call of calls)
    expect(call).toEqual({
      keys: ["files"],
      count: 1,
      name: `meme-${item.candidate_id}.gif`,
      type: "image/gif",
      bytes: [...gif],
    });
});
