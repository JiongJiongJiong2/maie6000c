import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test.skip(
  !process.env.WEB_BACKEND_TEST,
  "Requires disposable real-backend harness; see web/README.md",
);

async function start(page) {
  await page.goto("/web/search");
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
  await secondTab.goto("/web/search");
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

test("a search result shares the same original before and after saving to My Library", async ({
  page,
}) => {
  await page.addInitScript(() => {
    navigator.canShare = () => true;
    navigator.share = async ({ files: [file] }) => {
      window.sharedOriginal = {
        name: file.name,
        type: file.type,
        bytes: [...new Uint8Array(await file.arrayBuffer())],
      };
    };
  });
  await start(page);
  await page.locator("#submit").click();
  await expect(page.locator("#status-title")).toHaveText(
    "Waiting for processing",
  );
  expect((await page.request.post("/__test__/complete/candidates")).ok()).toBe(
    true,
  );
  await page.locator("#refresh").click();
  const card = page.locator("#candidates .candidate");
  await expect(card).toBeVisible();
  const id = await card.getAttribute("data-id");
  const response = await page.request.get(`/candidates/${id}/media`);
  expect(response.ok()).toBe(true);
  const bytes = [...(await response.body())];
  async function checkShare(container, fileId) {
    await container.getByRole("button", { name: "Share", exact: true }).click();
    await container.getByRole("button", { name: "Open share menu" }).click();
    await expect
      .poll(() => page.evaluate(() => window.sharedOriginal))
      .toEqual({
        name: `meme-${fileId}.gif`,
        type: "image/gif",
        bytes,
      });
  }
  await checkShare(card, id);
  await card.getByRole("button", { name: "Add to My Library" }).click();
  await card.getByRole("button", { name: "View in My Library" }).click();
  const saved = page.locator("#library-gallery .library-card");
  await expect(saved).toBeVisible();
  const assetId = await saved.getAttribute("data-asset-id");
  await expect(page).toHaveURL(new RegExp(`/web/library\\?asset=${assetId}$`));
  await checkShare(saved, assetId);
  await page.reload();
  await expect(saved).toBeFocused();
});

test("the signed-in workspace separates search, library and official stickers", async ({
  page,
}) => {
  await page.goto("/web/library");
  await page.getByRole("radio", { name: "Register" }).check();
  await page.getByLabel("Username").fill("navigation-" + crypto.randomUUID());
  await page.getByLabel("Password").fill("fixture-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();

  const navigation = page.getByRole("navigation", { name: "Workspace" });
  const searchLink = navigation.getByRole("link", {
    name: "Search",
    exact: true,
  });
  const libraryLink = navigation.getByRole("link", { name: "My Library" });
  const stickerLink = navigation.getByRole("link", {
    name: "Official Stickers",
  });
  await expect(page).toHaveURL(/\/web\/library$/);
  await expect(libraryLink).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { name: "My Library" })).toBeVisible();
  await expect(page.locator("#file-input")).toBeHidden();

  await searchLink.click();
  await expect(searchLink).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("heading", { name: "Search GIFs" }),
  ).toBeVisible();
  await expect(page.locator("#private-library")).toBeHidden();
  await expect(page.locator("#file-input")).toBeEnabled();
  const crop = await page.request.get("/__test__/crop");
  await page.locator("#file-input").setInputFiles({
    name: "sidebar-test.png",
    mimeType: "image/png",
    buffer: await crop.body(),
  });
  await expect(page.locator("#file-name")).toHaveText("sidebar-test.png");

  await libraryLink.click();
  await expect(page.locator("#private-library")).toBeVisible();
  await expect(page.locator("#search-view")).toBeHidden();
  await page.goBack();
  await expect(page.locator("#file-name")).toHaveText("sidebar-test.png");

  await stickerLink.click();
  await expect(page).toHaveURL(/\/web\/stickers$/);
  await expect(stickerLink).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("heading", { name: "Sticker pack directory" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Try a sample" }).click();
  await expect(
    page.getByRole("heading", { name: "Sticker pack found" }),
  ).toBeVisible();

  await page.setViewportSize({ width: 320, height: 760 });
  await expect(navigation).toBeInViewport();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await searchLink.click();
  await expect(page.locator("#file-name")).toHaveText("sidebar-test.png");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);

  await libraryLink.click();
  await page.reload();
  await expect(libraryLink).toHaveAttribute("aria-current", "page");
  await expect(page.locator("#private-library")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("the full-screen theme opens the workbench and is reachable from its logo", async ({
  page,
}) => {
  await page.goto("/web/");
  const home = page.getByRole("heading", { name: /LOST YOUR MEME\s*\?/ });
  const enter = page.getByRole("link", { name: "Enter workspace" });
  await expect(home).toBeVisible();
  await enter.click();
  await expect(page).toHaveURL(/\/web\/search$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  await page.getByRole("radio", { name: "Register" }).check();
  await page.getByLabel("Username").fill("home-" + crypto.randomUUID());
  await page.getByLabel("Password").fill("fixture-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Search GIFs" }),
  ).toBeVisible();

  const crop = await page.request.get("/__test__/crop");
  await page.locator("#file-input").setInputFiles({
    name: "kept-after-home.png",
    mimeType: "image/png",
    buffer: await crop.body(),
  });
  await expect(page.locator("#file-name")).toHaveText("kept-after-home.png");

  const sidebar = page.getByRole("navigation", { name: "Workspace" });
  const homeLogo = page
    .locator(".workspace-sidebar")
    .getByRole("link", { name: "MemeRetrieve home" });
  await sidebar.getByRole("link", { name: "My Library" }).click();
  await homeLogo.click();
  await expect(page).toHaveURL(/\/web\/$/);
  await expect(home).toBeVisible();
  await enter.click();
  await expect(page.locator("#file-name")).toHaveText("kept-after-home.png");

  await sidebar.getByRole("link", { name: "Official Stickers" }).click();
  await expect(page).toHaveURL(/\/web\/stickers$/);
  await homeLogo.click();
  await expect(home).toBeVisible();
  await page.goto("/web/#workspace");
  await expect(page).toHaveURL(/\/web\/search#workspace$/);
  await expect(page.locator("#file-name")).toHaveText("kept-after-home.png");
});
