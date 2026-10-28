import { test, expect } from "@playwright/test";

const requestId = "10000000-0000-4000-8000-000000000001";
const jobId = "20000000-0000-4000-8000-000000000001";
const candidateId = "30000000-0000-4000-8000-000000000001";
const reviewId = "40000000-0000-4000-8000-000000000001";
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAIAAABvFaqvAAAAKklEQVR4nGPc4W3AQA3ARBVTGEYNIgaMGkQYjBpEGIwaRBiMGkQYDD6DAN66AWOTozgdAAAAAElFTkSuQmCC",
  "base64",
);
const gif = Buffer.from(
  "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
  "base64",
);
const candidate = {
  candidate_id: candidateId,
  rank: 1,
  score: 0.87,
  media_url: `/candidates/${candidateId}/media`,
};
const accepted = { request_id: requestId, job_id: jobId, status: "pending" };
const complete = {
  ...accepted,
  status: "completed",
  result_kind: "candidates",
  candidates: [candidate],
  error: null,
};

async function fixtures(page, state = complete) {
  const uploads = [];
  const reviews = [];
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/health/ready", (route) =>
    route.fulfill({ json: { status: "ok" } }),
  );
  await page.route("**/search-requests", (route) => {
    uploads.push(route.request().postDataBuffer().toString());
    return route.fulfill({ status: 202, json: accepted });
  });
  await page.route(`**/search-requests/${requestId}`, (route) =>
    route.fulfill({ json: typeof state === "function" ? state() : state }),
  );
  await page.route("**/candidates/*/media", (route) =>
    route.fulfill({ contentType: "image/gif", body: gif }),
  );
  await page.route("**/search-jobs/*/reviews", (route) => {
    reviews.push(route.request().postDataJSON());
    return route.fulfill({ status: 201, json: { review_id: reviewId } });
  });
  await page.goto("/web/");
  await expect(page.locator("#file-input")).toBeEnabled();
  return { uploads, reviews, errors };
}

async function upload(page) {
  await page
    .locator("#file-input")
    .setInputFiles({ name: "crop.png", mimeType: "image/png", buffer: png });
  await expect(page.locator("#submit")).toBeEnabled();
  await page.locator("#submit").click();
}

function key(body) {
  return body.match(/name="client_submission_key"\r\n\r\n([^\r]+)/)?.[1];
}

test("upload, state progression, authenticated animation, review and download are separate", async ({
  page,
}) => {
  let polls = 0;
  const captured = await fixtures(page, () =>
    ++polls === 1
      ? {
          ...accepted,
          status: "running",
          result_kind: null,
          candidates: [],
          error: null,
        }
      : complete,
  );
  await page.locator("#connection-toggle").click();
  await page.locator("#token").fill("private-test-token");
  await page.getByRole("button", { name: "Apply and reconnect" }).click();
  const mediaRequest = page.waitForRequest((request) =>
    request.url().endsWith("/media"),
  );
  await upload(page);
  await expect(page.locator("#status-title")).toHaveText(
    "Looking for your GIF",
  );
  await expect(page.locator(".candidate img")).toBeVisible();
  expect((await mediaRequest).headers().authorization).toBe(
    "Bearer private-test-token",
  );
  expect(captured.uploads[0]).toContain('name="image"; filename="crop.png"');
  await expect(page.locator(".download")).toBeHidden();
  await page.getByRole("button", { name: "This is the one" }).click();
  await expect(page.locator("#review-status")).toContainText("Choice saved");
  expect(captured.reviews[0]).toMatchObject({
    decision: "accept",
    candidate_id: candidateId,
  });
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download GIF" }).click();
  expect((await download).suggestedFilename()).toBe(`meme-${candidateId}.gif`);
  await expect(page.locator("#download-status")).toContainText(
    "Download started",
  );
  await expect(page.locator("#review-status")).toContainText("Choice saved");
  expect(captured.errors).toEqual([]);
});

test("lost upload response survives reload and reuses exact submission key and file", async ({
  page,
}) => {
  await fixtures(page);
  const bodies = [];
  await page.route("**/search-requests", async (route) => {
    bodies.push(route.request().postDataBuffer().toString());
    if (bodies.length === 1) await route.abort();
    else await route.fulfill({ status: 202, json: accepted });
  });
  await upload(page);
  await expect(page.locator("#notice")).toContainText("Connection interrupted");
  await page.reload();
  await expect(page.locator("#file-name")).toHaveText("crop.png");
  await page.getByRole("button", { name: "Retry this upload" }).click();
  await expect(page.locator(".candidate")).toHaveCount(1);
  expect(key(bodies[0])).toBeTruthy();
  expect(key(bodies[1])).toBe(key(bodies[0]));
  await page.locator("#new-search").click();
  await page.locator("#submit").click();
  await expect.poll(() => bodies.length).toBe(3);
  expect(key(bodies[2])).not.toBe(key(bodies[0]));
});

test("lost review acknowledgement survives reload; reject-all uses null candidate", async ({
  page,
}) => {
  await fixtures(page);
  const payloads = [];
  await page.route("**/search-jobs/*/reviews", async (route) => {
    payloads.push(route.request().postDataJSON());
    if (payloads.length === 1) await route.abort();
    else await route.fulfill({ status: 201, json: { review_id: reviewId } });
  });
  await upload(page);
  await page.locator("#reject").click();
  await expect(page.locator("#review-retry")).toBeVisible();
  await expect(page.locator("#notice")).toContainText("Connection interrupted");
  await page.reload();
  await page.locator("#review-retry").click();
  await expect(page.locator("#review-status")).toContainText(
    "none of these candidates match",
  );
  expect(payloads[0]).toEqual(payloads[1]);
  expect(payloads[0]).toMatchObject({
    decision: "reject_all",
    candidate_id: null,
  });
});

test("no candidates and failed execution have distinct outcomes", async ({
  page,
}) => {
  let state = { ...complete, result_kind: "no_candidates", candidates: [] };
  await fixtures(page, () => state);
  await upload(page);
  await expect(page.locator("#status-title")).toHaveText(
    "No matching GIFs this time",
  );
  await expect(page.locator("#review-panel")).toBeHidden();
  state = {
    ...accepted,
    status: "failed",
    result_kind: null,
    candidates: [],
    error: { code: "retrieval_unavailable", message: "Model unavailable" },
  };
  await page.locator("#refresh").click();
  await expect(page.locator("#status-title")).toHaveText(
    "This search could not finish",
  );
  await expect(page.locator("#status-description")).toContainText(
    "retrieval_unavailable",
  );
});

test("expired GIF download preserves the accepted review", async ({ page }) => {
  await fixtures(page);
  await upload(page);
  await page.getByRole("button", { name: "This is the one" }).click();
  await expect(page.locator("#review-status")).toContainText("Choice saved");
  await page.route("**/candidates/*/media", (route) =>
    route.fulfill({
      status: 410,
      json: { detail: { code: "media_expired", message: "Expired" } },
    }),
  );
  await page.locator(".download").click();
  await expect(page.locator("#download-status")).toContainText(
    "GIF has expired",
  );
  await expect(page.locator("#review-status")).toContainText("Choice saved");
});

test("bad images, oversized input, and non-images are rejected before upload", async ({
  page,
}) => {
  const captured = await fixtures(page);
  for (const file of [
    { name: "bad.png", mimeType: "image/png", buffer: Buffer.from("broken") },
    {
      name: "large.png",
      mimeType: "image/png",
      buffer: Buffer.alloc(10 * 1024 * 1024 + 1),
    },
    {
      name: "script.svg",
      mimeType: "image/svg+xml",
      buffer: Buffer.from("<svg/>"),
    },
  ]) {
    await page.locator("#file-input").setInputFiles(file);
    await expect(page.locator("#notice")).toBeVisible();
    await expect(page.locator("#submit")).toBeDisabled();
  }
  expect(captured.uploads).toEqual([]);
});

test("status network failure can resume without another upload", async ({
  page,
}) => {
  const captured = await fixtures(page);
  let fail = true;
  await page.route(`**/search-requests/${requestId}`, (route) =>
    fail ? route.abort() : route.fulfill({ json: complete }),
  );
  await upload(page);
  await expect(page.locator("#notice")).toContainText(
    "Status checks are interrupted",
  );
  fail = false;
  await page.locator("#refresh").click();
  await expect(page.locator(".candidate")).toHaveCount(1);
  expect(captured.uploads).toHaveLength(1);
});

test("reload restores completed search and review without re-submitting", async ({
  page,
}) => {
  const captured = await fixtures(page);
  await upload(page);
  await page.getByRole("button", { name: "This is the one" }).click();
  await expect(page.locator("#review-status")).toContainText("Choice saved");
  await page.reload();
  await expect(page.locator(".download")).toBeVisible();
  expect(captured.uploads).toHaveLength(1);
  expect(captured.reviews).toHaveLength(1);
  await page.locator("#forget").click();
  await expect(page.locator("#file-name")).toHaveText("No image selected");
  await page.reload();
  await expect(page.locator("#trace")).toBeHidden();
});

test("401 is actionable, token is not persisted, and cross-origin media is rejected", async ({
  page,
}) => {
  let remote = false;
  await fixtures(page, () =>
    remote
      ? {
          ...complete,
          candidates: [
            { ...candidate, media_url: "https://example.com/secret.gif" },
          ],
        }
      : complete,
  );
  await page.route("**/search-requests", (route) =>
    route.request().headers().authorization === "Bearer valid-token"
      ? route.fulfill({ status: 202, json: accepted })
      : route.fulfill({
          status: 401,
          json: { detail: { code: "unauthorized", message: "Token required" } },
        }),
  );
  await upload(page);
  await expect(page.locator("#notice")).toContainText("access token");
  await page.locator("#connection-toggle").click();
  await page.locator("#token").fill("valid-token");
  await page.getByRole("button", { name: "Apply and reconnect" }).click();
  await page.locator("#submit").click();
  await expect(page.locator(".candidate")).toHaveCount(1);
  await page.reload();
  await expect(page.locator("#token")).toHaveValue("");
  remote = true;
  await page.locator("#refresh").click();
  await expect(page.locator("#notice")).toContainText("unsupported media URL");
});

test("late status response cannot replace a newly selected screenshot", async ({
  page,
}) => {
  await fixtures(page);
  let finish;
  const pending = new Promise((resolve) => {
    finish = resolve;
  });
  await page.route(`**/search-requests/${requestId}`, async (route) => {
    await pending;
    await route.fulfill({ json: complete }).catch(() => {});
  });
  await upload(page);
  await expect(page.locator("#new-search")).toBeVisible();
  await page
    .locator("#file-input")
    .setInputFiles({ name: "new.png", mimeType: "image/png", buffer: png });
  await expect(page.locator("#file-name")).toHaveText("new.png");
  finish();
  await expect(page.locator("#trace")).toBeHidden();
  await expect(page.locator("#candidates")).toBeEmpty();
  await expect(page.locator("#submit")).toBeEnabled();
});

test("mobile layout fits, controls are labeled, and errors are not HTML", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixtures(page, {
    ...accepted,
    status: "failed",
    result_kind: null,
    candidates: [],
    error: { code: "test", message: '<img src=x onerror="alert(1)">' },
  });
  await upload(page);
  await expect(page.locator("#status-description")).toContainText("<img");
  expect(await page.locator("#status-description img").count()).toBe(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await expect(page.getByLabel("Choose screenshot")).toBeVisible();
});
