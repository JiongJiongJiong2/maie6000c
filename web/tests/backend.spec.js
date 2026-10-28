import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test.skip(
  !process.env.WEB_BACKEND_TEST,
  "Requires disposable real-backend harness; see web/README.md",
);

async function start(page, request) {
  await page.goto("/web/");
  await expect(page.locator("#file-input")).toBeEnabled();
  await page.locator("#connection-toggle").click();
  await page.locator("#token").fill("web-test-token");
  await page.getByRole("button", { name: "Apply and reconnect" }).click();
  const crop = await request.get("/__test__/crop");
  await page.locator("#file-input").setInputFiles({
    name: "fixture.png",
    mimeType: "image/png",
    buffer: await crop.body(),
  });
  await expect(page.locator("#submit")).toBeEnabled();
}

test("real API + database + worker: upload replay, review replay and two-frame GIF download", async ({
  page,
  request,
}) => {
  await start(page, request);
  let firstUpload = true;
  await page.route("**/search-requests", async (route) => {
    const response = await route.fetch(); // Actually commit to backend before dropping response.
    if (firstUpload) {
      firstUpload = false;
      await route.abort();
    } else await route.fulfill({ response });
  });
  await page.locator("#submit").click();
  await expect(page.locator("#notice")).toContainText("Connection interrupted");
  await page.locator("#submit").click();
  await expect(page.locator("#status-title")).toHaveText(
    "Waiting for processing",
  );
  const requestId = await page.locator("#request-id").textContent();
  const completed = await request.post("/__test__/complete/candidates");
  expect(completed.ok()).toBe(true);
  await page.locator("#refresh").click();
  await expect(page.locator(".candidate img")).toBeVisible();
  let firstReview = true;
  await page.route("**/search-jobs/*/reviews", async (route) => {
    const response = await route.fetch();
    if (firstReview) {
      firstReview = false;
      await route.abort();
    } else await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "This is the one" }).click();
  await page.locator("#review-retry").click();
  await expect(page.locator("#review-status")).toContainText("Choice saved");
  expect(
    await (await request.get(`/__test__/counts/${requestId}`)).json(),
  ).toEqual({ requests: 1, jobs: 1, reviews: 1 });
  const downloadEvent = page.waitForEvent("download");
  await page.locator(".download").click();
  const download = await downloadEvent;
  const bytes = await readFile(await download.path());
  expect(bytes.subarray(0, 6).toString()).toBe("GIF89a");
  // Each fixture frame has a Graphic Control Extension; the backend also fully
  // decodes and validates the multi-frame file before publishing it.
  expect([...bytes.toString("hex").matchAll(/21f904/g)]).toHaveLength(2);
  await page.reload();
  await expect(page.locator("#review-status")).toContainText("Choice saved");
  await expect(page.locator("#request-id")).toHaveText(requestId);
});

for (const [mode, title] of [
  ["no_candidates", "No matching GIFs this time"],
  ["unavailable", "This search could not finish"],
]) {
  test(`real backend ${mode} is shown correctly`, async ({ page, request }) => {
    await start(page, request);
    await page.locator("#submit").click();
    await expect(page.locator("#status-title")).toHaveText(
      "Waiting for processing",
    );
    expect((await request.post(`/__test__/complete/${mode}`)).ok()).toBe(true);
    await page.locator("#refresh").click();
    await expect(page.locator("#status-title")).toHaveText(title);
    if (mode === "unavailable")
      await expect(page.locator("#status-description")).toContainText(
        "retrieval_unavailable",
      );
  });
}
