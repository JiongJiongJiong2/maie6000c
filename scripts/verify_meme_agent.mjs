// Opt-in live browser smoke. Run against a separate --data-root: this saves a test meme.
// Uses real provider calls and the real local CLIP model; no intercepted requests.
import { chromium } from "../web/node_modules/playwright/index.mjs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const base = process.env.MEME_TEST_URL || "http://127.0.0.1:8011";
const target = new URL(base);
if (!["127.0.0.1", "localhost"].includes(target.hostname)) {
  throw new Error("The smoke test must target a local isolated test server.");
}
const out = path.resolve(
  import.meta.dirname,
  "../.cache/meme-agent-verification",
);
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const evidence = { captured_at: new Date().toISOString(), simulated: false };
function check(value, message) {
  if (!value) throw new Error(message);
}
async function responseAfter(pathname, action) {
  const pending = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === pathname && r.request().method() === "POST",
    { timeout: 120000 },
  );
  await action();
  const response = await pending;
  check(response.ok(), `HTTP ${response.status()} at ${pathname}`);
  return response.json();
}
try {
  await page.goto(base + "/studio/", { waitUntil: "networkidle" });
  await page.screenshot({
    path: path.join(out, "01-home.png"),
    fullPage: true,
  });
  await page.locator("#query").fill("上面拒绝下面赞同的 Drake");
  const found = await responseAfter("/api/search", () =>
    page.locator("#search-form button[type=submit]").click(),
  );
  check(
    found.candidates.some((c) => c.title === "Drake Hotline Bling"),
    "Missing live template",
  );
  evidence.trace = found.trace;
  evidence.warnings = found.warnings;
  evidence.candidate_count = found.candidates.length;
  await page
    .locator("#results .card")
    .filter({ hasText: "Drake Hotline Bling" })
    .getByRole("button", { name: "空白模板加字" })
    .click();
  const baseItem = found.candidates.find(
    (c) => c.title === "Drake Hotline Bling",
  );
  await page.locator("#top").fill("周一上班");
  await page.locator("#bottom").fill("周五下班");
  const edited = await responseAfter(
    `/api/candidates/${baseItem.id}/edit`,
    () => page.locator("#edit-form button").click(),
  );
  check(
    edited.format === "PNG" &&
      !edited.saved &&
      edited.parent_id === baseItem.id,
    "Edit provenance failed",
  );
  const saved = await responseAfter(`/api/candidates/${edited.id}/save`, () =>
    page.locator("#edit-preview .actions button").first().click(),
  );
  check(saved.item.saved, "Save did not complete vector indexing");
  evidence.saved_id = saved.item.id;
  evidence.sha256 = saved.item.sha256;
  await page
    .locator("#edit-preview .actions button")
    .first()
    .getByText("已收藏")
    .waitFor();
  const crop = await page.locator("#edit-preview .media img").screenshot();
  await writeFile(path.join(out, "query-resized.png"), crop);
  await page.screenshot({
    path: path.join(out, "02-caption-and-save.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "关闭编辑器" }).click();
  await page.locator("#query").fill("");
  await page.locator("#scope").selectOption("library");
  await page.locator("#reference").setInputFiles({
    name: "resized.png",
    mimeType: "image/png",
    buffer: crop,
  });
  const reused = await responseAfter("/api/search", () =>
    page.locator("#search-form button[type=submit]").click(),
  );
  check(
    reused.candidates[0]?.id === saved.item.id,
    "Resized screenshot did not retrieve the saved item",
  );
  evidence.resized_query_top1 = true;
  evidence.similarity = reused.candidates[0].score;
  await page.reload({ waitUntil: "networkidle" });
  check(
    (await page.locator("#library .card").count()) > 0,
    "Collection did not survive refresh",
  );
  evidence.refresh_persisted = true;
  await page.screenshot({
    path: path.join(out, "03-library.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  check(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    "Mobile horizontal overflow",
  );
  await page.screenshot({
    path: path.join(out, "04-mobile.png"),
    fullPage: true,
  });
  check(errors.length === 0, "Browser JavaScript error");
  evidence.browser_errors = errors;
  evidence.mobile_no_horizontal_overflow = true;
  await writeFile(
    path.join(out, "evidence.json"),
    JSON.stringify(evidence, null, 2),
  );
  console.log(JSON.stringify(evidence, null, 2));
} finally {
  await browser.close();
}
