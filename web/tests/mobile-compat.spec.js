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
  await localOnly.check();
  await expect(localOnly).toBeChecked();
  await page.locator("#demo-library summary").click();
  await page.getByRole("button", { name: "Mind blown", exact: true }).click();
  await expect(page.locator("#file-name")).toHaveText("Mind blown.png");
  await expect(page.locator("#submit")).toBeEnabled();
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
