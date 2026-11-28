import { test, expect } from "@playwright/test";

const exampleImage = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAIAAABvFaqvAAAAKklEQVR4nGPc4W3AQA3ARBVTGEYNIgaMGkQYjBpEGIwaRBiMGkQYDD6DAN66AWOTozgdAAAAAElFTkSuQmCC",
  "base64",
);

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(AbortSignal, "any", {
      value: undefined,
      configurable: true,
    });
  });
  await page.route("**/health/ready", (route) =>
    route.fulfill({ json: { status: "ok" } }),
  );
  await page.route("**/demo-library", (route) =>
    route.fulfill({
      json: {
        examples: [
          {
            id: "example",
            title: "Mind blown",
            screenshot_url: "/example.png",
            source_reference: "https://example.org/artist",
            permission_note: "Artist credit <b>as provided</b>.",
          },
        ],
      },
    }),
  );
});

test("example picker initializes without AbortSignal.any", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/web/");
  await expect(page.locator("#demo-library")).toBeVisible();
  await page.route("**/example.png", (route) =>
    route.fulfill({ contentType: "image/png", body: exampleImage }),
  );
  const localOnly = page.getByRole("radio", {
    name: "Local only",
    exact: true,
  });
  const online = page.getByRole("radio", {
    name: "Online search",
    exact: true,
  });
  await expect(online).toBeChecked();
  const requests = [];
  await page.route("**/search-requests", (route) => {
    requests.push(route.request().postDataBuffer());
    return route.fulfill({
      status: 422,
      json: { detail: "Stopped after checking upload" },
    });
  });
  await page.locator("#demo-library summary").click();
  await page.getByRole("button", { name: "Mind blown", exact: true }).click();
  await expect(page.locator("#file-name")).toHaveText("Mind blown.png");
  await expect(localOnly).toBeChecked();
  await expect(page.locator("#demo-credit")).toContainText(
    "Artist credit <b>as provided</b>.",
  );
  await expect(page.locator("#demo-credit b")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "View source" })).toHaveAttribute(
    "href",
    "https://example.org/artist",
  );
  await expect(page.locator("#submit")).toBeEnabled();
  expect(requests).toHaveLength(0);
  await page.locator("#submit").click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].includes(exampleImage)).toBe(true);
  expect(requests[0].includes(Buffer.from('name="search_profile"'))).toBe(
    false,
  );
  await online.check();
  await expect(online).toBeChecked();
  await expect(page.locator("#file-name")).toHaveText("Mind blown.png");
  await expect(page.locator("#demo-credit")).toContainText("Artist credit");
  await page.locator("#submit").click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].includes(exampleImage)).toBe(true);
  expect(requests[1].includes(Buffer.from('name="search_profile"'))).toBe(true);
  expect(requests[1].includes(Buffer.from("meme50-v2"))).toBe(true);
  await expect(page.locator("#file-input")).toBeEnabled();
  await page.locator("#file-input").setInputFiles({
    name: "own.png",
    mimeType: "image/png",
    buffer: exampleImage,
  });
  await expect(page.locator("#file-name")).toHaveText("own.png");
  await expect(online).toBeChecked();
  await expect(page.locator("#demo-credit")).toBeHidden();
  expect(errors).toEqual([]);
});

test("fallback cancels work from either source and handles an already stopped source", async ({
  page,
}) => {
  await page.goto("/web/");
  const results = await page.evaluate(async () => {
    const { combineSignals } = await import("/web/api.js");
    const results = [];
    for (const index of [0, 1]) {
      const sources = [new AbortController(), new AbortController()];
      const combined = combineSignals(sources.map((source) => source.signal));
      let events = 0;
      combined.addEventListener("abort", () => events++);
      sources[index].abort("screenshot changed");
      sources[1 - index].abort("page left");
      results.push([combined.aborted, combined.reason, events]);
    }
    const stopped = new AbortController();
    stopped.abort("already stopped");
    const combined = combineSignals([
      new AbortController().signal,
      stopped.signal,
    ]);
    results.push([combined.aborted, combined.reason]);
    return results;
  });
  expect(results).toEqual([
    [true, "screenshot changed", 1],
    [true, "screenshot changed", 1],
    [true, "already stopped"],
  ]);
});
