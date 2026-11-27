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
        analysis: {
          observations: ["controlled visible facts"],
          entity_hypotheses: [
            { name: "Paper astronaut", status: "supported" },
            { name: "Unverified character", status: "uncertain" },
          ],
          evidence: [
            { title: "Unconfirmed caption", relation: "unresolved" },
            {
              title: "Paper astronaut in a landscape",
              relation: "supports",
              matching_media_url: "https://example.org/collage.png",
            },
          ],
        },
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
  const previews = await page.evaluate(() =>
    [
      [160, 640],
      [800, 200],
    ].map(([width, height]) => {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      return canvas.toDataURL("image/png").split(",")[1];
    }),
  );
  await page.route("**/candidates/*/preview", (route) => {
    const rank = Number(new URL(route.request().url()).pathname.split("/")[2]);
    return route.fulfill({
      contentType: "image/png",
      body: Buffer.from(previews[(rank - 1) % previews.length], "base64"),
    });
  });
  await page.route("**/candidates/*/media", (r) =>
    r.fulfill({ contentType: "image/png", body: png }),
  );
  await page.goto("/web/");
  await expect(page.locator("#search-mode label span")).toHaveText([
    "Online search",
    "Local only",
  ]);
  await expect(page.locator("#submit")).toBeDisabled();
  await page
    .locator("#file-input")
    .setInputFiles({ name: "random.png", mimeType: "image/png", buffer: png });
  const online = page.getByRole("radio", {
    name: "Online search",
    exact: true,
  });
  const local = page.getByRole("radio", { name: "Local only", exact: true });
  await expect(online).toBeChecked();
  await online.press("ArrowRight");
  await expect(local).toBeChecked();
  await expect(local).toBeFocused();
  await expect(page.locator("#description")).toBeHidden();
  await local.press("ArrowLeft");
  await expect(online).toBeChecked();
  await expect(page.locator("#description")).toBeVisible();
  await expect(page.locator("#submit")).toBeEnabled();
  await page.locator("#submit").click();
  await expect(page.locator(".candidate")).toHaveCount(20);
  await page.evaluate(() => document.fonts.ready);
  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    for (const card of (
      await page.locator("#web-candidates article").all()
    ).slice(0, 2)) {
      await card.scrollIntoViewIfNeeded();
      await expect
        .poll(() => card.locator("img").evaluate((img) => img.naturalWidth))
        .toBeGreaterThan(0);
      const contained = await card.evaluate((node) => {
        const frame = node
          .querySelector(".candidate-media")
          .getBoundingClientRect();
        const image = node.querySelector("img");
        const box = image.getBoundingClientRect();
        const body = node
          .querySelector(".candidate-body")
          .getBoundingClientRect();
        return (
          getComputedStyle(image).objectFit === "contain" &&
          box.top >= frame.top - 1 &&
          box.bottom <= frame.bottom + 1 &&
          box.left >= frame.left - 1 &&
          box.right <= frame.right + 1 &&
          frame.bottom <= body.top + 1
        );
      });
      expect(contained, `preview inside its frame at ${width}px`).toBe(true);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 1040 });
  expect(uploads).toHaveLength(1);
  expect(uploads[0]).toContain("meme50-v2");
  await expect(page.locator("#meme-analysis")).toContainText(
    "Recognized: Paper astronaut",
  );
  await expect(page.locator("#meme-analysis")).not.toContainText(
    "Unverified character",
  );
  await expect(page.locator("#meme-analysis")).toContainText(
    "Paper astronaut in a landscape",
  );
  await expect(page.locator("#meme-analysis")).not.toContainText(
    "Unconfirmed caption",
  );
  expect(uploads[0]).toMatch(/name="description"\r\n\r\n\r\n/);
  await expect(page.locator("#review-panel")).toBeHidden();
  await page.locator("#next-page").click();
  await expect(page.locator(".candidate").first()).toContainText("#21");
  await page.locator("#next-page").click();
  await expect(page.locator(".candidate")).toHaveCount(10);
  await expect(page.locator("#next-page")).toBeDisabled();
  await page
    .getByRole("radio", { name: "All images", exact: true })
    .press("ArrowRight");
  await expect(
    page.getByRole("radio", { name: "Static", exact: true }),
  ).toBeChecked();
  await expect(page.locator(".candidate")).toHaveCount(20);
  await expect(
    page.getByRole("button", { name: "Play animation", exact: true }),
  ).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByRole("radio", { name: "Static", exact: true }),
  ).toBeChecked();
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
  await page.getByRole("radio", { name: "Animated", exact: true }).check();
  await animatedRequest;
  const finalStaticResponse = page.waitForResponse((r) =>
    r.url().includes("media_kind=static"),
  );
  await page.getByRole("radio", { name: "Static", exact: true }).check();
  await finalStaticResponse;
  await expect(page.locator("#refresh")).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Play animation", exact: true }),
  ).toHaveCount(0);
  await page.locator("#next-page").click();
  await expect(page.locator(".candidate")).toHaveCount(5);
  await expect(page.locator(".candidate").first()).toContainText("#41");
  await page.getByRole("button", { name: "Start a new search" }).click();
  await expect(page.locator("#submit")).toBeEnabled();
  await expect(page.locator("#web-results")).toBeHidden();
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
  await page.getByRole("radio", { name: "Local only", exact: true }).check();
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
      error: { message: "图片检索服务暂不可用，请稍后重试。" },
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
  await page.getByRole("radio", { name: "Local only", exact: true }).check();
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
  await expect(page.locator("#web-status")).toHaveText(
    "Image search is temporarily unavailable. Please try again later.",
  );
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
  expect(uploads).toBe(1);
  expect(reviews).toHaveLength(1);
  expect(creates).toHaveLength(2);
  expect(creates[0]).toEqual(creates[1]);
  expect(creates[0]).toMatchObject({
    description: "green parrot",
    search_profile: "meme50-v2",
  });
});
