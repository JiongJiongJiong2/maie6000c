import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

test.use({ launchOptions: { args: ["--disable-gpu"] } });

const requestId = "10000000-0000-4000-8000-000000000001";
const jobId = "20000000-0000-4000-8000-000000000001";
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAIAAABvFaqvAAAAKklEQVR4nGPc4W3AQA3ARBVTGEYNIgaMGkQYjBpEGIwaRBiMGkQYDD6DAN66AWOTozgdAAAAAElFTkSuQmCC",
  "base64",
);

async function ready(page) {
  await page.route("**/health/ready", (route) =>
    route.fulfill({ json: { status: "ok" } }),
  );
  await page.goto("/web/");
  await expect(page.locator("#file-input")).toBeEnabled();
}

test("mascot is keyboard-operable and motion can be disabled across reloads", async ({
  page,
}) => {
  await ready(page);
  await page.getByRole("button", { name: "Poke the mascot" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#mascot-caption")).toHaveText(
    "I was framed. Literally.",
  );
  await page.locator("#motion-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("data-motion", "off");
  expect(
    await page
      .locator(".ticker-track")
      .evaluate((node) => getComputedStyle(node).animationName),
  ).toBe("none");
  await page.reload();
  await expect(page.locator("#motion-toggle")).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await page.locator("#motion-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("data-motion", "on");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator("#motion-toggle")).toBeDisabled();
  await expect(page.locator("#motion-toggle")).toHaveText("Motion: reduced");
  expect(
    await page
      .locator(".star-one")
      .evaluate((node) => getComputedStyle(node).animationName),
  ).toBe("none");
});

for (const width of [1440, 768, 390, 320]) {
  test(`three-candidate layout and review controls work at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width > 800 ? 1040 : 844 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const candidates = [1, 2, 3].map((rank) => ({
      candidate_id: `30000000-0000-4000-8000-00000000000${rank}`,
      rank,
      score: 0.92 - rank / 10,
      media_url: `/candidates/${rank}/media`,
    }));
    const accepted = {
      request_id: requestId,
      job_id: jobId,
      status: "pending",
    };
    await page.route("**/search-requests", (route) =>
      route.fulfill({ status: 202, json: accepted }),
    );
    await page.route(`**/search-requests/${requestId}`, (route) =>
      route.fulfill({
        json: {
          ...accepted,
          status: "completed",
          result_kind: "candidates",
          candidates,
          error: null,
        },
      }),
    );
    await page.route("**/candidates/*/media", (route) =>
      route.fulfill({
        contentType: "image/gif",
        body: Buffer.from(
          "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
          "base64",
        ),
      }),
    );
    const reviews = [];
    await page.route("**/search-jobs/*/reviews", (route) => {
      reviews.push(route.request().postDataJSON());
      return route.fulfill({
        status: 201,
        json: { review_id: "40000000-0000-4000-8000-000000000001" },
      });
    });
    await ready(page);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    if (process.env.WEB_VISUAL_DIR) {
      await mkdir(process.env.WEB_VISUAL_DIR, { recursive: true });
      await page.screenshot({
        path: path.join(process.env.WEB_VISUAL_DIR, `redesign-${width}.png`),
        fullPage: true,
      });
    }
    await page
      .getByRole("link", { name: "Let's find that little guy" })
      .click();
    await page.locator("#file-input").setInputFiles({
      name: "fixture.png",
      mimeType: "image/png",
      buffer: png,
    });
    await page.locator("#submit").click();
    await expect(page.locator(".candidate")).toHaveCount(3);
    await page
      .locator(".candidate")
      .nth(1)
      .getByRole("button", { name: "This is the one" })
      .click();
    await expect(page.locator("#review-status")).toContainText("Choice saved");
    expect(reviews[0].candidate_id).toBe(candidates[1].candidate_id);
    await expect(page.locator(".candidate.selected")).toHaveCount(1);
    await expect(page.locator(".candidate.selected .download")).toBeVisible();
    await expect(page.locator("#celebration")).toBeEmpty();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    if (process.env.WEB_VISUAL_DIR) {
      await page.locator(".workspace").screenshot({
        path: path.join(
          process.env.WEB_VISUAL_DIR,
          `redesign-results-${width}.png`,
        ),
      });
    }
  });
}
