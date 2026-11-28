import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";

const animatedGif = readFileSync(
  new URL("./fixtures/two-frames.gif", import.meta.url),
);
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

async function serveStickerTestPage(page, attributes) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/web/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/web/") {
      const body = readFileSync(
        new URL("../index.html", import.meta.url),
        "utf8",
      ).replace('<html lang="en">', `<html lang="en" ${attributes}>`);
      return route.fulfill({ contentType: "text/html", body });
    }
    const asset = /^\/web\/([a-z0-9-]+\.(js|css))$/.exec(path);
    if (!asset) return route.abort();
    return route.fulfill({
      contentType: asset[2] === "js" ? "text/javascript" : "text/css",
      body: readFileSync(new URL(`../${asset[1]}`, import.meta.url)),
    });
  });
}

test("mobile Discord sticker action shows its destination and supports a retry", async ({
  page,
}) => {
  await serveStickerTestPage(
    page,
    'data-discord-stickers="true" data-discord-guild-name="Test Server"',
  );
  let requests = 0;
  await page.route(
    `**/sticker-integrations/candidates/${candidateId}/discord`,
    (route) => {
      expect(route.request().method()).toBe("POST");
      requests++;
      if (requests === 1) {
        return route.fulfill({
          status: 409,
          json: {
            detail: { message: "The Discord server's sticker slots are full." },
          },
        });
      }
      return route.fulfill({
        json: {
          id: "1234",
          name: "MemeRetrieve 42",
          guild_id: "123456789012345678",
          already_added: requests > 2,
        },
      });
    },
  );
  await fixtures(page);
  await upload(page);
  const add = page.getByRole("button", { name: "Add to Discord Stickers" });
  await expect(add).toBeHidden();
  await page.getByRole("button", { name: "This is the one" }).click();
  await expect(
    page.getByText(
      "Shares this GIF with members of Test Server as a server sticker.",
    ),
  ).toBeVisible();
  await add.click();
  await expect(
    page.getByText("The Discord server's sticker slots are full."),
  ).toBeVisible();
  const link = page.getByRole("link", { name: "Open Discord server" });
  await expect(link).toBeHidden();
  await page.getByRole("button", { name: "Retry adding to Discord" }).click();
  await expect(
    page.getByRole("button", { name: "Added to Discord", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText(
      "Find “MemeRetrieve 42” in the Stickers tab of a channel in Test Server.",
    ),
  ).toBeVisible();
  await expect(link).toHaveAttribute(
    "href",
    "https://discord.com/channels/123456789012345678",
  );
  await page.reload();
  await add.click();
  await expect(
    page.getByRole("button", { name: "Already in Discord" }),
  ).toBeDisabled();
  expect(requests).toBe(3);
});

test("mobile Signal sticker action creates a pack only after the user taps", async ({
  page,
}) => {
  await serveStickerTestPage(page, 'data-signal-stickers="true"');
  const pack = `https://signal.art/addstickers/#pack_id=${"a".repeat(32)}&pack_key=${"b".repeat(64)}`;
  let requests = 0;
  await page.route(
    `**/sticker-integrations/candidates/${candidateId}/signal`,
    (route) => {
      expect(route.request().method()).toBe("POST");
      requests++;
      return route.fulfill({
        json: { url: requests === 1 ? "https://example.com" : pack },
      });
    },
  );
  await fixtures(page);
  await upload(page);
  const add = page.getByRole("button", { name: "Add Sticker to Signal" });
  await expect(add).toBeHidden();
  await page.getByRole("button", { name: "This is the one" }).click();
  await expect(add).toBeVisible();
  expect(requests).toBe(0);

  await add.click();
  const link = page.getByRole("link", { name: "Open Signal to install" });
  await expect(link).toBeHidden();
  await page
    .getByRole("button", { name: "Retry creating Signal sticker" })
    .click();
  await expect(link).toHaveAttribute("href", pack);
  await expect(
    page.getByRole("button", { name: "Signal sticker ready" }),
  ).toBeDisabled();
  expect(requests).toBe(2);
});

test("the desktop Telegram QR flow offers phone sign-in when two-step verification is required", async ({
  page,
}) => {
  await page.route("**/telegram/**", (route) => {
    const request = route.request();
    if (request.url().endsWith("/regions"))
      return route.fulfill({ json: { GB: 44 } });
    expect(request.url()).toMatch(/\/session$/);
    if (request.method() === "POST")
      return route.fulfill({ status: 201, json: { session: "qr-session" } });
    if (request.method() === "DELETE")
      return route.fulfill({ json: { state: "closed" } });
    return route.fulfill({
      json: {
        state: "failed",
        code: "telegram_qr_password_required",
        message: "This account has two-step verification.",
      },
    });
  });

  await fixtures(page);
  await upload(page);
  await page.getByRole("button", { name: "This is the one" }).click();
  await page
    .getByRole("button", { name: "Add to Telegram GIFs", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Add to Telegram GIFs" });
  await expect(dialog.getByLabel("Telegram phone number")).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Get verification code" }),
  ).toBeVisible();
});

test.describe("Telegram on a phone", () => {
  test.use({
    hasTouch: true,
    isMobile: true,
    viewport: { width: 390, height: 844 },
  });

  test("chooses a region and keeps the selected GIF through login and save retries", async ({
    page,
  }) => {
    let sends = 0;
    let codes = 0;
    let saves = 0;
    await page.route("**/telegram/**", (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path.endsWith("/regions"))
        return route.fulfill({ json: { HK: 852, GB: 44 } });
      if (request.method() === "DELETE")
        return route.fulfill({ json: { state: "closed" } });
      if (path.endsWith("/phone")) {
        expect(request.postDataJSON()).toEqual({
          phone: "5555 0123",
          region: "HK",
        });
        if (++sends === 1)
          return route.fulfill({
            status: 429,
            headers: { "Retry-After": "1" },
            json: {
              detail: {
                code: "telegram_code_rate_limited",
                message: "Wait before trying again.",
              },
            },
          });
        return route.fulfill({
          status: 201,
          json: { session: `session-${sends}`, state: "code", retry_after: 1 },
        });
      }
      expect(request.headers()["x-telegram-session"]).toBe(`session-${sends}`);
      if (path.endsWith("/code")) {
        codes++;
        if (codes === 1)
          return route.fulfill({
            status: 400,
            json: {
              detail: {
                code: "telegram_invalid_login_value",
                message: "That code is incorrect.",
              },
            },
          });
        if (codes === 2)
          return route.fulfill({
            status: 404,
            json: {
              detail: {
                code: "telegram_code_expired",
                message: "That code has expired. Request a new one.",
              },
            },
          });
        return route.fulfill({ json: { state: "password" } });
      }
      if (path.endsWith("/password"))
        return route.fulfill({ json: { state: "authorized" } });
      expect(path).toBe(`/telegram/gifs/${candidateId}`);
      if (++saves === 1)
        return route.fulfill({
          status: 409,
          json: {
            detail: {
              code: "telegram_collection_full",
              message: "Your Telegram GIF collection is full.",
            },
          },
        });
      return route.fulfill({ json: { saved: true } });
    });

    await fixtures(page);
    await upload(page);
    await page.getByRole("button", { name: "This is the one" }).click();
    await page
      .getByRole("button", { name: "Add to Telegram GIFs", exact: true })
      .click();
    const dialog = page.getByRole("dialog", { name: "Add to Telegram GIFs" });
    await expect(dialog.getByRole("img")).toBeHidden();
    await dialog.getByLabel("Country or region code").selectOption("HK");
    const phone = dialog.getByLabel("Telegram phone number", { exact: true });
    const send = dialog.getByRole("button", {
      name: "Get verification code",
      exact: true,
    });
    const confirm = dialog.getByRole("button", { name: "Confirm and save" });
    await phone.fill("not-a-phone");
    await send.click();
    await expect(
      dialog.getByText(/Choose a country code and enter a phone number/),
    ).toBeVisible();
    expect(sends).toBe(0);
    await phone.fill("5555 0123");
    await send.click();
    await expect(dialog.getByText("Wait before trying again.")).toBeVisible();
    await send.click();
    const code = dialog.getByLabel("Telegram verification code", {
      exact: true,
    });
    await expect(dialog.getByText(/Didn't get a code/)).toBeVisible();
    await code.fill("11111");
    await confirm.click();
    await expect(dialog.getByText("That code is incorrect.")).toBeVisible();
    await code.fill("22222");
    await confirm.click();
    await expect(
      dialog.getByText("That code has expired. Request a new one."),
    ).toBeVisible();
    await expect(phone).toHaveValue("5555 0123");
    await send.click();
    await code.fill("12345");
    await confirm.click();
    await dialog
      .getByLabel("Telegram two-step verification password")
      .fill("test-password");
    await confirm.click();
    await expect(dialog.getByText(/Remove a saved GIF/)).toBeVisible();
    await dialog.getByRole("button", { name: "Retry save" }).click();
    await expect(
      dialog.getByText(/Added to your saved GIFs in Telegram/),
    ).toBeVisible();
    expect(saves).toBe(2);
    await expect(dialog.locator("#telegram-login-value")).toHaveValue("");
  });
});

for (const mode of ["Online search", "Local only"]) {
  test(`a pasted screenshot sends only the applied crop in ${mode}`, async ({
    page,
  }) => {
    const captured = await fixtures(page);
    await page.evaluate(async () => {
      const canvas = document.createElement("canvas");
      canvas.width = 100;
      canvas.height = 80;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "red";
      ctx.fillRect(0, 0, 100, 80);
      ctx.fillStyle = "blue";
      ctx.fillRect(25, 20, 50, 40);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve));
      const transfer = new DataTransfer();
      transfer.items.add(new File([blob], "chat.png", { type: blob.type }));
      document.body.dispatchEvent(
        new ClipboardEvent("paste", { bubbles: true, clipboardData: transfer }),
      );
    });
    await page.locator("#crop-open").click();
    const stage = page.locator("#crop-stage");
    await stage.scrollIntoViewIfNeeded();
    const bounds = await stage.boundingBox();
    await page.mouse.move(
      bounds.x + bounds.width * 0.75,
      bounds.y + bounds.height * 0.75,
    );
    await page.mouse.down();
    await page.mouse.move(
      bounds.x + bounds.width * 0.25,
      bounds.y + bounds.height * 0.25,
    );
    await page.mouse.up();
    await expect(page.locator("#crop-size")).toContainText("50 × 40 px");
    await page.locator("#crop-apply").click();
    await expect(page.locator("#file-name")).toHaveText("screenshot-crop.png");
    await page.getByRole("radio", { name: mode, exact: true }).check();
    await expect(page.locator("#crop-restore")).toBeVisible();
    expect(captured.uploads).toHaveLength(0);

    const sending = page.waitForRequest("**/search-requests");
    await page.locator("#submit").click();
    const sent = await sending;
    const form = await new Response(sent.postDataBuffer(), {
      headers: { "Content-Type": sent.headers()["content-type"] },
    }).formData();
    expect(form.get("search_profile")).toBe(
      mode === "Online search" ? "meme50-v2" : null,
    );
    const sentFile = form.get("image");
    expect(sentFile.name).toBe("screenshot-crop.png");
    expect(sent.postDataBuffer().includes(Buffer.from("chat.png"))).toBe(false);
    const pixels = await page.evaluate(
      async (bytes) => {
        const image = await createImageBitmap(
          new Blob([Uint8Array.from(bytes)], { type: "image/png" }),
        );
        const canvas = document.createElement("canvas");
        canvas.width = image.width;
        canvas.height = image.height;
        const context = canvas.getContext("2d");
        context.drawImage(image, 0, 0);
        const rgba = context.getImageData(0, 0, image.width, image.height).data;
        const blueOnly = rgba.every(
          (value, index) => value === (index % 4 < 2 ? 0 : 255),
        );
        return [image.width, image.height, blueOnly];
      },
      [...new Uint8Array(await sentFile.arrayBuffer())],
    );
    expect(pixels).toEqual([50, 40, true]);
    expect(captured.errors).toEqual([]);
  });
}

test.describe("mobile touchscreen", () => {
  test.use({ hasTouch: true, viewport: { width: 360, height: 740 } });
  test("touch drag selects the visible part of the screenshot", async ({
    page,
    browserName,
  }) => {
    test.skip(
      browserName !== "chromium",
      "Touch gestures use Chromium's input API.",
    );
    const captured = await fixtures(page);
    await page
      .locator("#file-input")
      .setInputFiles({ name: "chat.png", mimeType: "image/png", buffer: png });
    await page.locator("#crop-open").tap();
    await expect(page.locator("#crop-title")).toBeFocused();
    const stage = page.locator("#crop-stage");
    await stage.scrollIntoViewIfNeeded();
    const bounds = await stage.boundingBox();
    const touch = await page.context().newCDPSession(page);
    for (const [type, position] of [
      ["touchStart", 0.25],
      ["touchMove", 0.75],
    ]) {
      await touch.send("Input.dispatchTouchEvent", {
        type,
        touchPoints: [
          {
            x: bounds.x + bounds.width * position,
            y: bounds.y + bounds.height * position,
          },
        ],
      });
    }
    await touch.send("Input.dispatchTouchEvent", {
      type: "touchEnd",
      touchPoints: [],
    });
    await expect(page.locator("#crop-size")).toContainText("12 × 12 px");
    await page.locator("#crop-apply").tap();
    await expect(page.locator("#file-name")).toHaveText("screenshot-crop.png");
    expect(captured.uploads).toHaveLength(0);
  });
});

test("keyboard crop can be cancelled or restored byte-for-byte on a narrow screen", async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 740 });
  const captured = await fixtures(page);
  await page
    .locator("#file-input")
    .setInputFiles({ name: "old.png", mimeType: "image/png", buffer: png });
  await page.locator("#crop-open").click();
  const right = page.getByRole("spinbutton", { name: "Right", exact: true });
  await right.fill("0");
  await expect(page.locator("#crop-apply")).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(page.locator("#file-name")).toHaveText("old.png");
  await page.locator("#crop-open").press("Enter");
  await expect(right).toHaveValue("24");
  await right.fill("12");
  await page.locator("#crop-apply").press("Enter");
  await expect(page.locator("#file-name")).toHaveText("screenshot-crop.png");
  await page.reload();
  await page.locator("#crop-open").click();
  await expect(right).toHaveValue("12");
  await right.fill("6");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.locator("#file-name")).toHaveText("screenshot-crop.png");
  await page.locator("#crop-restore").click();
  await expect(page.locator("#file-name")).toHaveText("old.png");
  await expect(page.locator("#crop-restore")).toBeHidden();
  expect(captured.uploads).toHaveLength(0);
  const sending = page.waitForRequest("**/search-requests");
  await page.locator("#submit").click();
  const sent = await sending;
  expect(sent.postDataBuffer().includes(png)).toBe(true);
  expect(captured.errors).toEqual([]);
});

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
  const mediaRequest = page.waitForRequest((request) =>
    request.url().endsWith("/media"),
  );
  await upload(page);
  await expect(page.locator("#status-title")).toHaveText(
    "Looking for your GIF",
  );
  await expect(page.locator(".candidate img")).toBeVisible();
  expect((await mediaRequest).headers().authorization).toBeUndefined();
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
  await page.route(
    "**/search-requests",
    (route) => route.fulfill({ status: 401, json: { detail: "Sign in" } }),
    { times: 1 },
  );
  await upload(page);
  await expect(page.locator("#notice")).toContainText("Sign in");
  await page.locator("#submit").click();
  await expect(page.locator(".candidate")).toHaveCount(1);
  await page.reload();
  await expect(page.locator("#token")).toHaveCount(0);
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

test("private library resumes waiting GIFs and requires consent for vision", async ({
  page,
}) => {
  const asset = {
    asset_id: candidateId,
    title: "旧收藏",
    frame_count: 2,
    media_url: `/saved-assets/${candidateId}/media`,
    index_status: "ready",
    annotation_status: "not_requested",
    tags: [],
  };
  const batchId = "40000000-0000-4000-8000-000000000003";
  const uploads = [];
  const requests = [];
  let items = [];
  let interrupt = true;
  const receipt = () => ({
    batch_id: batchId,
    items,
    counts: {
      waiting: items.filter((item) => item.status === "waiting").length,
    },
  });
  await page.route("**/library/assets?limit=8", (route) =>
    route.fulfill({ json: { assets: [asset], next_cursor: null } }),
  );
  await page.route("**/library/imports", (route) => {
    items = route
      .request()
      .postDataJSON()
      .items.map((item) => ({ ...item, status: "waiting" }));
    return route.fulfill({ json: receipt() });
  });
  await page.route(`**/library/imports/${batchId}`, (route) =>
    route.fulfill({ json: receipt() }),
  );
  await page.route("**/library/imports/*/items/*", (route) => {
    const item = items.find((item) =>
      route.request().url().endsWith(item.client_item_id),
    );
    uploads.push(item.filename);
    if (item.filename === "resume.gif" && interrupt) return route.abort();
    item.status = "imported";
    return route.fulfill({ json: item });
  });
  await page.route("**/library/annotations", (route) => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({
      json: { assets: [{ ...asset, annotation_status: "pending" }] },
    });
  });
  await page.route(`**/library/assets/${candidateId}`, (route) =>
    route.fulfill({
      json: { ...asset, annotation_status: "ready", tags: ["cat"] },
    }),
  );
  await page.route("**/library/search", (route) =>
    route.fulfill({
      json: {
        assets:
          route.request().postDataJSON().query === "猫"
            ? [{ ...asset, match_reasons: ["猫"], match_reasons_en: ["cat"] }]
            : [],
      },
    }),
  );
  await fixtures(page);
  const openLibrary = async () => {
    await page.getByText("My GIF Library", { exact: true }).click();
    await page
      .getByRole("button", { name: "Import GIFs", exact: true })
      .click();
    await expect(page.getByText("旧收藏", { exact: true })).toBeVisible();
  };
  const files = [
    { name: "saved.gif", mimeType: "image/gif", buffer: gif },
    {
      name: "resume.gif",
      mimeType: "image/gif",
      buffer: Buffer.concat([gif, gif]),
    },
  ];
  await openLibrary();
  await page.locator("#library-files").setInputFiles(files);
  await page.getByRole("button", { name: "Import files" }).click();
  await expect(page.getByText(/resume.gif — Upload interrupted/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Resume upload" }),
  ).toBeEnabled();

  await page.reload();
  await openLibrary();
  await expect(
    page.getByRole("button", { name: "Resume upload" }),
  ).toBeVisible();
  interrupt = false;
  await page.locator("#library-files").setInputFiles(files);
  await page.getByRole("button", { name: "Resume upload" }).click();
  await expect(page.getByText("resume.gif — Imported")).toBeVisible();
  expect(uploads.filter((name) => name === "saved.gif")).toHaveLength(1);

  await page.getByRole("checkbox", { name: "Select 旧收藏" }).check();
  await page.getByRole("button", { name: /Selection tools/ }).click();
  const vision = page.getByRole("button", {
    name: "Analyze selected GIFs",
  });
  const confirmation = page.getByRole("dialog", {
    name: "Analyze 1 selected GIF?",
  });
  await vision.click();
  await expect(confirmation).toBeVisible();
  await expect(confirmation).not.toContainText(/localhost|18101/);
  await expect(
    confirmation.getByRole("button", { name: "Cancel" }),
  ).toBeFocused();
  await confirmation.getByRole("button", { name: "Cancel" }).click();
  await expect(vision).toBeFocused();
  await vision.click();
  await page.keyboard.press("Escape");
  await expect(confirmation).toBeHidden();
  expect(requests).toEqual([]);
  await vision.click();
  await confirmation
    .getByRole("button", { name: "Analyze", exact: true })
    .click();
  await expect(page.getByText("AI analysis: 1 ready.")).toBeVisible();
  expect(requests).toEqual([{ asset_ids: [candidateId], consent: true }]);

  await page.locator("#library-query").fill("猫");
  await page.locator("#library-query").press("Enter");
  await expect(page.getByText("Matched: cat")).toBeVisible();
  await page.locator("#library-query").fill("飞机");
  await page.locator("#library-query").press("Enter");
  await expect(page.getByText(/No matches/)).toBeVisible();
});

test("private library splits imports, keeps selection, and downloads a backup", async ({
  page,
}) => {
  const manifests = [];
  const batches = new Map();
  let exported;
  let added;
  const names = ["Sample one", "Sample two"];
  const ids = [candidateId, requestId];
  const cards = ids.map((asset_id, index) => ({
    asset_id,
    title: names[index],
    frame_count: 2,
    index_status: "pending",
    annotation_status: "not_requested",
    media_url: `/saved-assets/${asset_id}/media`,
  }));
  await page.route(/\/library\/assets(?:\?|$)/, (route) => {
    const filtered = new URL(route.request().url()).searchParams.get("tag");
    return route.fulfill({
      json: { assets: filtered ? cards.slice(1) : cards },
    });
  });
  await page.route("**/library/imports", (route) => {
    const manifest = route.request().postDataJSON();
    manifests.push(manifest.items.length);
    const batch_id = `batch-${manifests.length}`;
    const items = manifest.items.map((item) => ({
      ...item,
      status: "waiting",
    }));
    const counts = {
      waiting: items.length,
      imported: 0,
      duplicate: 0,
      rejected: 0,
    };
    const batch = { items, batch_id, counts };
    batches.set(batch_id, batch);
    return route.fulfill({ json: batch });
  });
  await page.route(/\/library\/imports\/batch-[0-9]+$/, (route) =>
    route.fulfill({
      json: batches.get(route.request().url().split("/").at(-1)),
    }),
  );
  await page.route("**/library/imports/*/items/*", (route) => {
    const parts = route.request().url().split("/");
    const batch = batches.get(parts.at(-3));
    const item = batch.items.find(
      (item) => item.client_item_id === parts.at(-1),
    );
    item.status = "imported";
    batch.counts.imported++;
    batch.counts.waiting--;
    return route.fulfill({ json: item });
  });
  await page.route("**/library/assets/bulk-tags", (route) => {
    added = route.request().postDataJSON();
    return route.fulfill({ json: { updated: 2 } });
  });
  await page.route("**/library/exports", (route) => {
    exported = route.request().postDataJSON();
    return route.fulfill({
      contentType: "application/zip",
      body: "mock archive",
    });
  });

  await fixtures(page);
  await page.getByText("My GIF Library", { exact: true }).click();
  await page.getByRole("button", { name: "Import GIFs", exact: true }).click();
  await page.getByText("Sample one", { exact: true }).waitFor();
  await page.locator("#library-files").setInputFiles(
    Array.from({ length: 21 }, (_, index) => ({
      name: `batch-file-${index}.gif`,
      mimeType: "image/gif",
      buffer: Buffer.concat([gif, Buffer.from([index])]),
    })),
  );
  await page.getByRole("button", { name: "Import files" }).click();
  await expect(page.getByText("batch-file-20.gif — Imported")).toBeVisible();
  expect(manifests).toEqual([20, 1]);

  for (const name of names)
    await page.getByRole("checkbox", { name: `Select ${name}` }).check();
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await page.locator("[data-filters] input[name=tag]").fill("归档");
  await page
    .getByRole("button", { name: "Apply filters", exact: true })
    .click();
  await expect(page.getByText("Sample one", { exact: true })).toBeHidden();
  await expect(page.getByText("(2)")).toBeVisible();
  await page.getByRole("button", { name: /Selection tools/ }).click();
  await page.locator("[data-bulk-tags] input").fill("归档、保留");
  await page.getByRole("button", { name: "Apply tags" }).click();
  await expect(page.getByText("Tags updated for 2 GIFs.")).toBeVisible();
  expect(added).toEqual({ asset_ids: ids, tags: ["归档", "保留"] });

  await page.locator("[data-export-manual]").check();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Back up selected GIFs" }).click();
  expect((await download).suggestedFilename()).toBe("private-gifs.zip");
  expect(exported).toEqual({
    asset_ids: ids,
    profile: "original_zip",
    include_manual: true,
    include_annotations: false,
  });
});

test("backup restore reports each current receipt and only restores successful metadata", async ({
  page,
}) => {
  const { createHash } = await import("node:crypto");
  const files = ["Large", "Small", "HTTP limit"].map((title, i) => {
    const bytes = Buffer.concat([gif, Buffer.from([i])]);
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    return {
      entry: {
        title,
        sha256,
        path: `assets/${sha256}.gif`,
        byte_size: bytes.length,
      },
      upload: { name: `${sha256}.gif`, mimeType: "image/gif", buffer: bytes },
    };
  });
  const manifests = [];
  const receipts = new Map();
  const metadata = [];
  const uploads = [];
  const historical = {
    batch_id: "history",
    items: [
      {
        ...files[0].entry,
        client_item_id: "old",
        filename: files[0].upload.name,
        status: "imported",
        asset_id: "old-asset",
      },
    ],
    counts: { waiting: 0, imported: 1, duplicate: 0, rejected: 0 },
  };
  receipts.set("history", historical);
  await page.addInitScript(() => {
    localStorage.setItem(
      "private-library-import",
      JSON.stringify([
        {
          manifest: {
            client_batch_key: "unsubmitted",
            purpose: "backup_restore",
            items: [],
          },
        },
        { batch_id: "history" },
      ]),
    );
  });
  await page.route("**/library/assets?limit=8", (route) =>
    route.fulfill({ json: { assets: [] } }),
  );
  await page.route("**/library/imports", (route) => {
    const request = route.request().postDataJSON();
    if (request.client_batch_key === "unsubmitted")
      return route.fulfill({
        status: 422,
        json: { detail: { code: "backup_manifest_required" } },
      });
    manifests.push(request);
    const batch_id = `current-${manifests.length}`;
    const items = request.items.map((item) =>
      item.sha256 === files[0].entry.sha256
        ? { ...item, status: "rejected", error_code: "file_too_large" }
        : { ...item, status: "waiting" },
    );
    const batch = {
      batch_id,
      items,
      counts: {
        waiting: items.length - 1,
        imported: 0,
        duplicate: 0,
        rejected: 1,
      },
    };
    receipts.set(batch_id, batch);
    return route.fulfill({ json: batch });
  });
  await page.route(/\/library\/imports\/(?:history|current-\d+)$/, (route) =>
    route.fulfill({
      json: receipts.get(route.request().url().split("/").at(-1)),
    }),
  );
  await page.route("**/library/imports/*/items/*", (route) => {
    const parts = route.request().url().split("/");
    const batch = receipts.get(parts.at(-3));
    const item = batch.items.find(
      (item) => item.client_item_id === parts.at(-1),
    );
    uploads.push(item.sha256);
    if (item.sha256 === files[2].entry.sha256)
      return route.fulfill({
        status: 413,
        json: { detail: { code: "file_too_large" } },
      });
    Object.assign(item, { status: "imported", asset_id: "small" });
    batch.counts.waiting--;
    batch.counts.imported++;
    return route.fulfill({ json: item });
  });
  await page.route("**/library/restores/metadata", (route) => {
    const request = route.request().postDataJSON();
    metadata.push(request.uploaded_sha256);
    return route.fulfill({
      json: {
        items: request.uploaded_sha256.map((sha256) => ({
          sha256,
          status: "restored",
        })),
      },
    });
  });
  await fixtures(page);
  await page.getByText("My GIF Library", { exact: true }).click();
  await page.getByRole("button", { name: "Import GIFs", exact: true }).click();
  await expect(
    page.getByText(/Previous restore was not started/),
  ).toBeVisible();
  await expect(page.getByText(/\.gif — Imported/)).toBeVisible();
  await page.getByText("Restore a backup", { exact: true }).click();
  await page.locator("#library-backup-manifest").setInputFiles({
    name: "manifest.json",
    mimeType: "application/json",
    buffer: Buffer.from(
      JSON.stringify({
        version: 1,
        profile: "original_zip",
        assets: files.map(({ entry }) => entry),
      }),
    ),
  });
  const restore = page.getByRole("button", { name: "Verify and restore" });
  await page
    .locator("#library-files")
    .setInputFiles(files.map(({ upload }) => upload));
  await restore.click();
  const results = page.locator("[data-restore-results]");
  await expect(results.getByText("Small — Restored")).toBeVisible();
  await expect(
    results.getByText("Large — Exceeds the destination file limit"),
  ).toBeVisible();
  await expect(
    results.getByText("HTTP limit — Exceeds the destination file limit"),
  ).toBeVisible();
  expect(manifests[0].backup.assets).toHaveLength(3);
  expect(metadata).toEqual([[files[1].entry.sha256]]);
  expect(uploads).not.toContain(files[0].entry.sha256);

  await page.locator("#library-files").setInputFiles(files[0].upload);
  await restore.click();
  await expect(results.getByText("Small — Original GIF missing")).toBeVisible();
  await expect(
    results.getByText("Large — Exceeds the destination file limit"),
  ).toBeVisible();
  expect(metadata).toHaveLength(1);
});

test("library previews private GIFs automatically and collapses extra pages", async ({
  page,
}) => {
  const requests = [];
  const tokens = [];
  const first = {
    asset_id: candidateId,
    title: "Laugh",
    frame_count: 6,
    index_status: "ready",
    annotation_status: "ready",
    media_url: "/saved-assets/first/media",
    caption_en: "Laughing until it hurts.",
  };
  const second = {
    ...first,
    asset_id: requestId,
    title: "Wave",
    media_url: "/saved-assets/extra/media",
  };
  await page.route(/\/library\/assets\?/, (route) => {
    const cursor = new URL(route.request().url()).searchParams.get("cursor");
    requests.push(cursor);
    return route.fulfill({
      json: cursor
        ? { assets: [second], next_cursor: null }
        : { assets: [first], next_cursor: "page-two" },
    });
  });
  let failOnce = true;
  await page.route("**/saved-assets/*/media", async (route) => {
    tokens.push(route.request().headers().authorization);
    if (route.request().url().includes("/extra/") && failOnce) {
      failOnce = false;
      return route.fulfill({ status: 503, json: {} });
    }
    return route.fulfill({ body: gif, contentType: "image/gif" });
  });
  await fixtures(page);
  await page.getByText("My GIF Library", { exact: true }).click();
  const gallery = page.locator("#library-gallery");
  const preview = gallery.getByRole("img", { name: "Laugh" });
  await expect(preview).toBeVisible();
  expect(
    await preview.evaluate((img) => img.complete && img.naturalWidth > 0),
  ).toBeTruthy();
  await expect(
    gallery.getByRole("link", { name: "Download GIF" }),
  ).toHaveAttribute("href", /^blob:/);
  const firstUrl = await preview.getAttribute("src");
  await page.getByRole("button", { name: "Load more" }).click();
  await gallery.getByRole("button", { name: "Retry preview" }).click();
  const extra = gallery.getByRole("img", { name: "Wave" });
  await expect(extra).toBeVisible();
  const extraUrl = await extra.getAttribute("src");
  await gallery.getByRole("checkbox", { name: "Select Wave" }).check();
  await page.getByRole("button", { name: "Show fewer" }).click();
  await expect(extra).toHaveCount(0);
  await expect(preview).toHaveAttribute("src", firstUrl);
  expect(
    await page.evaluate(
      (url) =>
        fetch(url).then(
          () => false,
          () => true,
        ),
      extraUrl,
    ),
  ).toBe(true);
  await expect(page.locator("[data-selection]")).toContainText("(1)");
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(
    gallery.getByRole("checkbox", { name: "Select Wave" }),
  ).toBeChecked();
  expect(requests).toEqual([null, "page-two", "page-two"]);
  expect(tokens.every((token) => token === undefined)).toBe(true);
  await page.setViewportSize({ width: 320, height: 720 });
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Apply filters" }),
  ).toBeVisible();
  const library = page.locator("#private-library");
  expect(await library.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(
    true,
  );
  expect(
    await library.evaluate(async (el) => {
      await document.fonts.ready;
      return (
        getComputedStyle(el.querySelector("input")).fontFamily.includes(
          "Computer Modern",
        ) &&
        [...document.fonts].some(
          (font) =>
            font.family.includes("Computer Modern") && font.status === "loaded",
        )
      );
    }),
  ).toBe(true);
});

test("selected GIFs show completed AI tags without a refresh or an index retry", async ({
  page,
}) => {
  const batch = [
    { asset_id: candidateId, title: "Wave" },
    { asset_id: requestId, title: "Applause" },
  ].map((asset) => ({
    ...asset,
    frame_count: 2,
    index_status: "failed",
    annotation_status: "not_requested",
    media_url: `/saved-assets/${asset.asset_id}/media`,
    tags: [],
  }));
  const actions = [];
  let mediaReads = 0;
  const statusReads = new Map();
  await page.route(/\/library\/assets\?/, (route) => {
    const next = new URL(route.request().url()).searchParams.has("cursor");
    return route.fulfill({
      json: {
        assets: [batch[next ? 1 : 0]],
        next_cursor: next ? null : "next",
      },
    });
  });
  await page.route("**/saved-assets/*/media", (route) => {
    mediaReads++;
    return route.fulfill({ contentType: "image/gif", body: gif });
  });
  await page.route("**/saved-assets/*/index-retry", (route) => {
    actions.push("index retry");
    return route.fulfill({ json: {} });
  });
  await page.route("**/library/annotations", (route) => {
    const body = route.request().postDataJSON();
    actions.push(body);
    return route.fulfill({
      json: {
        assets: body.asset_ids.map((asset_id) => ({
          asset_id,
          annotation_status: "pending",
        })),
      },
    });
  });
  await page.route(/\/library\/assets\/[\w-]+$/, (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-1);
    const asset = batch.find((a) => a.asset_id === id);
    const n = (statusReads.get(id) || 0) + 1;
    statusReads.set(id, n);
    if (n === 1)
      return route.fulfill({
        json: { ...asset, annotation_status: "running" },
      });
    return route.fulfill({
      json:
        id === requestId
          ? {
              ...asset,
              annotation_status: "ready",
              tags: ["celebration"],
              ocr_text: "Bravo!",
            }
          : {
              ...asset,
              annotation_status: "failed",
              annotation_error: "provider_timeout",
            },
    });
  });
  await fixtures(page);
  await page.getByText("My GIF Library", { exact: true }).click();
  await page.getByRole("button", { name: "Load more" }).click();
  for (const asset of batch)
    await page.getByRole("checkbox", { name: `Select ${asset.title}` }).check();
  const card = page
    .locator(".library-card")
    .filter({ has: page.getByRole("heading", { name: "Applause" }) });
  await expect(card.getByRole("link", { name: "Download GIF" })).toBeVisible();
  const preview = await card.getByRole("img").getAttribute("src");
  const reads = mediaReads;
  await card.getByText("Edit details", { exact: true }).click();
  await card.getByLabel("Title", { exact: true }).fill("Unsaved title");
  await page.getByRole("button", { name: /Selection tools/ }).click();
  await page.getByRole("button", { name: "Analyze selected GIFs" }).click();
  await page
    .getByRole("dialog", { name: "Analyze 2 selected GIFs?" })
    .getByRole("button", { name: "Analyze", exact: true })
    .click();
  await expect(card.getByText("celebration", { exact: true })).toBeVisible({
    timeout: 10000,
  });
  await expect(card.getByText("Image text: Bravo!")).toBeVisible();
  await expect(
    page.getByText(/Analysis failed \(provider_timeout\)/),
  ).toBeVisible();
  await expect(card.getByLabel("Title", { exact: true })).toHaveValue(
    "Unsaved title",
  );
  await expect(card.getByRole("checkbox")).toBeChecked();
  await expect(card.getByRole("img")).toHaveAttribute("src", preview);
  expect(mediaReads).toBe(reads);
  expect(actions).toEqual([
    { asset_ids: [candidateId, requestId], consent: true },
  ]);
  await expect(page.getByRole("button", { name: "Show fewer" })).toBeVisible();
});

test("legacy share waits for confirmation and falls back to original download", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "share", {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(navigator, "canShare", {
      configurable: true,
      value: undefined,
    });
  });
  const { reviews } = await fixtures(page);
  await page.route("**/candidates/*/media", (route) =>
    route.fulfill({ contentType: "image/gif", body: animatedGif }),
  );
  await upload(page);
  const share = page.locator(".share-gif");
  await expect(share).toBeHidden();
  await page.getByRole("button", { name: "This is the one" }).click();
  await share.click();
  await expect(page.getByText(/暂不支持分享/)).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /Download GIF/ }).click();
  expect(readFileSync(await (await download).path())).toEqual(animatedGif);
  expect(reviews).toHaveLength(1);
});

test("saved local GIF shares its permanent file even with failed indexing", async ({
  page,
}) => {
  const asset = "50000000-0000-4000-8000-000000000001";
  await page.addInitScript(() => {
    navigator.canShare = () => true;
    navigator.share = async ({ files }) => {
      window.shared = Array.from(new Uint8Array(await files[0].arrayBuffer()));
    };
  });
  const { reviews } = await fixtures(page, {
    ...complete,
    candidates: [
      {
        ...candidate,
        asset_id: asset,
        save_status: "saved",
        index_status: "failed",
      },
    ],
  });
  await page.route(`**/saved-assets/${asset}/media`, (route) =>
    route.fulfill({ contentType: "image/gif", body: animatedGif }),
  );
  await upload(page);
  await page.getByRole("button", { name: /Share GIF/ }).click();
  await page.getByRole("button", { name: /Open share menu/ }).click();
  await expect
    .poll(() => page.evaluate(() => window.shared))
    .toEqual([...animatedGif]);
  expect(reviews).toHaveLength(0);
});

test("share media errors stay on the card and never invoke the share menu", async ({
  page,
}) => {
  const asset = "50000000-0000-4000-8000-000000000001";
  await page.addInitScript(() => {
    window.shareCalls = 0;
    navigator.canShare = () => true;
    navigator.share = async () => {
      window.shareCalls++;
    };
  });
  await fixtures(page, {
    ...complete,
    candidates: [{ ...candidate, asset_id: asset, save_status: "saved" }],
  });
  let failure = 401;
  await page.route(`**/saved-assets/${asset}/media`, (route) =>
    failure
      ? route.fulfill({ status: failure })
      : route.fulfill({ contentType: "image/png", body: png }),
  );
  await upload(page);
  const share = page.getByRole("button", { name: /Share GIF/ });
  const card = page.locator(".candidate").filter({ has: share });
  await share.click();
  await expect(card.getByText("Sign in to open your library.")).toBeVisible();
  failure = 410;
  await share.click();
  await expect(card.getByText(/GIF has expired/)).toBeVisible();
  failure = 0;
  await share.click();
  await expect(card.getByText(/原文件不是 GIF/)).toBeVisible();
  await expect(share).toBeEnabled();
  expect(await page.evaluate(() => window.shareCalls)).toBe(0);
});

test("changing the screenshot discards an in-flight GIF preparation", async ({
  page,
}) => {
  const asset = "50000000-0000-4000-8000-000000000001";
  await page.addInitScript(() => {
    window.shareCalls = 0;
    navigator.canShare = () => true;
    navigator.share = async () => {
      window.shareCalls++;
    };
  });
  await fixtures(page, {
    ...complete,
    candidates: [{ ...candidate, asset_id: asset, save_status: "saved" }],
  });
  let respond;
  const held = new Promise((resolve) => {
    respond = resolve;
  });
  await page.route(`**/saved-assets/${asset}/media`, async (route) => {
    await held;
    await route.fulfill({ contentType: "image/gif", body: animatedGif });
  });
  await upload(page);
  const pending = page.waitForRequest(`**/saved-assets/${asset}/media`);
  await page.getByRole("button", { name: /Share GIF/ }).click();
  await pending;
  await page.locator("#file-input").setInputFiles({
    name: "replacement.png",
    mimeType: "image/png",
    buffer: png,
  });
  await expect(page.locator("#file-name")).toHaveText("replacement.png");
  respond();
  await expect(page.locator(".share-gif")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Open share menu/ }),
  ).toHaveCount(0);
  expect(await page.evaluate(() => window.shareCalls)).toBe(0);
});
