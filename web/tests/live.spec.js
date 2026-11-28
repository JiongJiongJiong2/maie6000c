import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../..");
test.skip(
  process.env.WEB_LIVE_DEMO !== "1",
  "Requires the real local CLIP demo stack",
);
test.use({ launchOptions: { args: ["--disable-gpu"] } });
test.setTimeout(120000);

test("real screenshot upload, live inference, saved review, refresh, and original GIF download", async ({
  page,
}) => {
  await page.goto("/web/#workspace");
  await expect(page.locator("#file-input")).toBeEnabled();
  await page.getByRole("radio", { name: "Local only", exact: true }).check();
  await page
    .locator("#file-input")
    .setInputFiles(path.join(root, "data/reference/examples/1f47b.png"));
  await page.locator("#submit").click();
  await expect(
    page.getByRole("heading", { name: "Here are your candidates" }),
  ).toBeVisible({ timeout: 90000 });
  await page.getByRole("button", { name: "This is the one" }).first().click();
  await expect(page.locator("#review-status")).toContainText("Choice saved");
  await page.reload();
  const downloadButton = page.getByRole("button", { name: "Download GIF" });
  await expect(downloadButton).toBeVisible();
  const pendingDownload = page.waitForEvent("download");
  await downloadButton.click();
  const download = await pendingDownload;
  const saved = path.join(root, ".cache/browser-downloaded.gif");
  await download.saveAs(saved);
  const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");
  expect(digest(await readFile(saved))).toBe(
    digest(await readFile(path.join(root, "data/reference/1f47b.gif"))),
  );
  await page.locator("#workspace").scrollIntoViewIfNeeded();
  await page.screenshot({
    path: path.join(root, ".cache/web-preview/live-flow-desktop.png"),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#results-title").scrollIntoViewIfNeeded();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(root, ".cache/web-preview/live-flow-mobile.png"),
  });
});

test("the example picker submits a real screenshot through the same search API", async ({
  page,
}) => {
  await page.goto("/web/#workspace");
  await expect(page.locator("#demo-library")).toBeVisible();
  await page.locator("#demo-library summary").click();
  await expect(
    page.getByRole("button", { name: "Robot friend", exact: true }),
  ).toBeVisible();
  const { examples } = await (await page.request.get("/demo-library")).json();
  const example = examples[0];
  await page.locator(".demo-example").first().click();
  await expect(page.locator("#file-name")).toHaveText(`${example.title}.png`);
  await expect(
    page.getByRole("radio", { name: "Local only", exact: true }),
  ).toBeChecked();
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/search-requests") &&
      response.request().method() === "POST",
  );
  await page.locator("#submit").click();
  expect((await responsePromise).status()).toBe(202);
  await expect(
    page.getByRole("heading", { name: "Here are your candidates" }),
  ).toBeVisible({ timeout: 90000 });
  const manifest = JSON.parse(
    await readFile(path.join(root, "data/reference/manifest.json"), "utf8"),
  );
  const expected = manifest.assets.find(
    (item) => item.reference_asset_id === example.id,
  ).sha256;
  const cards = page.locator("#candidates .candidate");
  const ids = await cards.evaluateAll((rows) =>
    rows.slice(0, 3).map((row) => row.dataset.id),
  );
  const digests = await Promise.all(
    ids.map(async (id) => {
      const response = await page.request.get(`/candidates/${id}/media`);
      expect(response.ok()).toBe(true);
      return createHash("sha256")
        .update(await response.body())
        .digest("hex");
    }),
  );
  expect(digests).toContain(expected);
});
