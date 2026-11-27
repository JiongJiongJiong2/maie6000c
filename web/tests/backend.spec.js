import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test.skip(
  !process.env.WEB_BACKEND_TEST,
  "Requires disposable real-backend harness; see web/README.md",
);

async function start(page) {
  await page.goto("/web/");
  await page.getByRole("radio", { name: "Register" }).check();
  await page.getByLabel("Username").fill("tester-" + crypto.randomUUID());
  await page.getByLabel("Password").fill("fixture-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(page.locator("#file-input")).toBeEnabled();
  await page.getByRole("radio", { name: "Local only", exact: true }).check();
  const crop = await page.request.get("/__test__/crop");
  await page.locator("#file-input").setInputFiles({
    name: "fixture.png",
    mimeType: "image/png",
    buffer: await crop.body(),
  });
  await expect(page.locator("#submit")).toBeEnabled();
}

test("real API + database + worker: upload replay, review replay and two-frame GIF download", async ({
  page,
}) => {
  await start(page);
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
  const completed = await page.request.post("/__test__/complete/candidates");
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
    await (await page.request.get(`/__test__/counts/${requestId}`)).json(),
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
  test(`real backend ${mode} is shown correctly`, async ({ page }) => {
    await start(page);
    await page.locator("#submit").click();
    await expect(page.locator("#status-title")).toHaveText(
      "Waiting for processing",
    );
    expect((await page.request.post(`/__test__/complete/${mode}`)).ok()).toBe(
      true,
    );
    await page.locator("#refresh").click();
    await expect(page.locator("#status-title")).toHaveText(title);
    if (mode === "unavailable")
      await expect(page.locator("#status-description")).toContainText(
        "retrieval_unavailable",
      );
  });
}

test("a returning account restores its browser session and a second account starts empty", async ({
  page,
}) => {
  await start(page);
  const user = await page.locator("#account-name").textContent();
  await expect(page.locator("#file-name")).toHaveText("fixture.png");
  await page.reload();
  await expect(page.locator("#account-name")).toHaveText(user);
  const secondTab = await page.context().newPage();
  await secondTab.goto("/web/");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    secondTab.getByRole("heading", { name: "Sign in" }),
  ).toBeVisible();
  await page.getByRole("radio", { name: "Register" }).check();
  await page.getByLabel("Username").fill("second-" + crypto.randomUUID());
  await page.getByLabel("Password").fill("fixture-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(page.locator("#file-name")).toHaveText("No image selected");
  await page.getByRole("button", { name: "Sign out" }).click();
  // The Mac launcher offers both actions even when opened with an owner setup link.
  await page.goto("/web/sign-in#setup=fixture-setup");
  const login = page.getByRole("radio", { name: "Sign in" });
  await expect(page.getByRole("radio", { name: "Register" })).toBeChecked();
  for (const width of [1440, 800, 390, 320]) {
    await page.setViewportSize({ width, height: 800 });
    await expect(login).toBeInViewport();
    await expect(page.locator("#account-title")).toHaveCSS(
      "letter-spacing",
      "normal",
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await login.check();
  await expect(page.getByLabel("Password")).toHaveAttribute(
    "autocomplete",
    "current-password",
  );
  const loginRequest = page.waitForRequest((r) =>
    r.url().endsWith("/auth/login"),
  );
  await page.getByLabel("Username").fill(user);
  await page.getByLabel("Password").fill("fixture-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  expect((await loginRequest).postDataJSON()).not.toHaveProperty("owner_setup");
  await expect(page.locator("#file-name")).toHaveText("fixture.png");
});

test("stickers keep moving inside both account forms with reduced motion enabled", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 760 });
  await page.goto("/web/sign-in");
  for (const mode of ["Sign in", "Register"]) {
    await page.getByRole("radio", { name: mode, exact: true }).check();
    const sticker = page.locator(".account-fields .heading-sticker");
    const transform = () =>
      sticker.evaluate((el) => getComputedStyle(el, "::before").transform);
    const initial = await transform();
    await expect.poll(transform).not.toBe(initial);
    await expect(page.locator(".parade-track")).toHaveCSS(
      "animation-name",
      "marquee",
    );
    await page.getByLabel("Username", { exact: true }).fill("example");
    await page.getByLabel("Password", { exact: true }).fill("test-password");
    await expect(page.locator("#account-submit")).toBeEnabled();
  }
  await expect(page.getByRole("button", { name: /motion|pause/i })).toHaveCount(
    0,
  );
});
