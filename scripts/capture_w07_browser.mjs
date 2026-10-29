// Capture the real browser/API/worker flow. No request interception or fixtures.
import { chromium } from "../web/node_modules/playwright/index.mjs";
import { mkdir, writeFile, readFile, copyFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
const root = path.resolve(import.meta.dirname, "..");
const out = path.join(root, "submissions/week07/assets");
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 1 });
const evidence = { captured_at: new Date().toISOString(), base_url: "http://127.0.0.1:8000", responses: [] };
const jobs = [];
page.on("response", response => {
  if (/\/search-requests|\/search-jobs.*reviews|\/health\/ready/.test(response.url())) {
    jobs.push((async () => {
      try { evidence.responses.push({ at: new Date().toISOString(), method: response.request().method(),
        path: new URL(response.url()).pathname, http_status: response.status(), body: await response.json() }); }
      catch { /* Only JSON API responses are recorded. */ }
    })());
  }
});
try {
  await page.goto("http://127.0.0.1:8000/web/", { waitUntil: "networkidle" });
  await page.locator("#file-input").waitFor({ state: "attached" });
  await page.screenshot({ path: path.join(out, "00-product-home.png") });
  await page.locator("#file-input").setInputFiles(path.join(root, "data/reference/examples/1f92f.png"));
  await page.locator("#submit").waitFor({ state: "visible" });
  await page.locator("#workspace").screenshot({ path: path.join(out, "01-input.png") });
  const acceptedPromise = page.waitForResponse(r => r.url().endsWith("/search-requests") && r.request().method() === "POST");
  await page.locator("#submit").click();
  const accepted = await acceptedPromise;
  if (accepted.status() !== 202) throw new Error(await accepted.text());
  evidence.accepted = await accepted.json();
  await writeFile(path.join(out, "browser-evidence.json"), JSON.stringify(evidence, null, 2));
  await page.locator("#trace summary").click();
  await page.locator("#workspace").screenshot({ path: path.join(out, "02-async-processing.png") });
  await page.getByRole("heading", { name: "Here are your candidates", exact: true }).waitFor({ timeout: 120000 });
  await page.locator("#workspace").screenshot({ path: path.join(out, "03-candidates.png") });
  const reviewPromise = page.waitForResponse(r => r.url().includes("/reviews") && r.request().method() === "POST");
  await page.getByRole("button", { name: "This is the one", exact: true }).first().click();
  const review = await reviewPromise;
  if (!review.ok()) throw new Error(await review.text());
  evidence.review = await review.json();
  await writeFile(path.join(out, "browser-evidence.json"), JSON.stringify(evidence, null, 2));
  await page.getByText("Choice saved. Your selected GIF is ready to download.", { exact: true }).waitFor();
  const downloadPromise = page.waitForEvent("download");
  await page.locator(".download:visible").first().click();
  const download = await downloadPromise;
  await download.saveAs(path.join(out, "05-downloaded-original.gif"));
  await page.locator("#workspace").screenshot({ path: path.join(out, "04-review-and-download.png") });
  await page.reload({ waitUntil: "networkidle" });
  await page.getByText("Choice saved. Your selected GIF is ready to download.", { exact: true }).waitFor();
  await page.locator("#trace summary").click();
  await page.locator("#workspace").screenshot({ path: path.join(out, "06-restored-after-refresh.png") });
  evidence.browser_refresh = "persisted search and accepted review restored";
  const bytes = await readFile(path.join(out, "05-downloaded-original.gif"));
  const original = await readFile(path.join(root, "data/reference/1f92f.gif"));
  evidence.download_sha256 = createHash("sha256").update(bytes).digest("hex");
  evidence.original_sha256 = createHash("sha256").update(original).digest("hex");
  if (evidence.download_sha256 !== evidence.original_sha256) throw new Error("Downloaded GIF differs from original");
  await copyFile(path.join(root, "data/reference/examples/1f92f.png"), path.join(out, "input-crop.png"));
  await Promise.all(jobs);
  await writeFile(path.join(out, "browser-evidence.json"), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify({ request_id: evidence.accepted.request_id, job_id: evidence.accepted.job_id,
    review_id: evidence.review.review_id, original_gif_sha256_match: true, screenshots: 7 }, null, 2));
} finally { await browser.close(); }
