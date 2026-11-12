// Real formal UI. No route interception, injected caption, or fixture results.
import { chromium } from "../web/node_modules/playwright-core/index.mjs";
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";
const exec = promisify(execFile);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const options = {};
for (let i = 2; i < process.argv.length; i++) {
  const name = process.argv[i];
  if (["--check-db", "--local-stack"].includes(name)) options[name] = true;
  else options[name] = process.argv[++i];
}
assert(
  options["--image"] && options["--out"],
  "Required: --image FILE --out NEW-DIR",
);
const out = path.resolve(options["--out"]);
await fs.mkdir(path.dirname(out), { recursive: true });
await fs.mkdir(out); // An existing attempt is never overwritten.
const python = process.env.PYTHON || path.join(root, ".venv", "bin", "python");
const browser = await chromium.launch({
  channel: process.env.PLAYWRIGHT_CHANNEL || "chrome",
  headless: true,
});
const context = await browser.newContext({
  baseURL: options["--base-url"] || "http://127.0.0.1:8000",
  viewport: { width: 1440, height: 1040 },
});
const page = await context.newPage();
const headers = process.env.DEVICE_TOKEN
  ? { Authorization: "Bearer " + process.env.DEVICE_TOKEN }
  : {};
const evidence = {
  kind: "browser_acceptance",
  route_interception: false,
  errors: [],
  downloads: [],
  assertions: {},
  human_review: "pending",
  status: "pending",
};
page.on("pageerror", (e) => evidence.errors.push(e.message));
const originalRequests = [];
page.on("request", (r) => {
  if (/\/candidates\/[^/]+\/media$/.test(new URL(r.url()).pathname))
    originalRequests.push(new URL(r.url()).pathname);
});
const sha = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");
async function api(url) {
  const response = await page.request.get(url, { headers });
  assert.equal(response.status(), 200);
  return response.json();
}
async function applyToken() {
  if (process.env.DEVICE_TOKEN) {
    await page.locator("#connection-toggle").click();
    await page.locator("#token").fill(process.env.DEVICE_TOKEN);
    await page.getByRole("button", { name: "Apply and reconnect" }).click();
  }
}
async function ids() {
  return page
    .locator(".candidate")
    .evaluateAll((nodes) => nodes.map((n) => n.dataset.candidateId));
}
async function waitIds(expected) {
  await page.waitForFunction(
    (expected) =>
      JSON.stringify(
        [...document.querySelectorAll(".candidate")].map(
          (n) => n.dataset.candidateId,
        ),
      ) === JSON.stringify(expected),
    expected,
    { timeout: 15000 },
  );
}
async function waitPoster(card) {
  await card.scrollIntoViewIfNeeded();
  const id = await card.getAttribute("data-candidate-id");
  await page.waitForFunction(
    (id) => {
      const img = document.querySelector(`[data-candidate-id="${id}"] img`);
      return img && img.complete && img.naturalWidth > 0;
    },
    id,
    { timeout: 15000 },
  );
}

try {
  evidence.stage = "upload";
  const input = await fs.readFile(path.resolve(options["--image"]));
  evidence.input_sha256 = sha(input);
  evidence.description = options["--description"] || "";
  await page.goto((options["--base-url"] || "http://127.0.0.1:8000") + "/web/");
  await applyToken();
  await page
    .locator("#file-input")
    .setInputFiles(path.resolve(options["--image"]));
  await page.locator("#description").fill(evidence.description);
  const submission = page.waitForResponse(
    (r) =>
      r.url().endsWith("/search-requests") && r.request().method() === "POST",
  );
  await page.locator("#submit").click();
  const acceptedResponse = await submission;
  assert.equal(acceptedResponse.status(), 202);
  evidence.accepted = await acceptedResponse.json();
  assert.equal(evidence.accepted.search_profile, "meme50-v2");
  await page.screenshot({
    path: path.join(out, "submitted.png"),
    fullPage: true,
  });
  const jobPath = "/search-jobs/" + evidence.accepted.job_id;
  evidence.stage = "job_poll";
  const deadline = Date.now() + 330000;
  let job;
  do {
    job = await api(jobPath);
    if (["completed", "failed"].includes(job.status)) break;
    assert(Date.now() < deadline, "job timeout");
    await page.waitForTimeout(500);
  } while (true);
  evidence.job = job;
  evidence.job_id = job.job_id;
  evidence.revision = job.result_revision;
  evidence.result_count = job.result_count;
  // Fingerprints are derived from current code, never supplied as a passing claim.
  evidence.stage = "fingerprint";
  const code =
    "import tempfile,json; from pathlib import Path; from scripts.meme50_acceptance import snapshot; t=tempfile.TemporaryDirectory(); s=snapshot(Path(t.name)); print(json.dumps({k:s[k] for k in ['code_fingerprint','configuration_fingerprint']}))";
  const fingerprint = await exec(python, ["-c", code], { cwd: root });
  Object.assign(evidence, JSON.parse(fingerprint.stdout));
  await page.waitForFunction(
    () =>
      !document.querySelector("#meme-controls").hidden ||
      !document.querySelector("#meme-retry").hidden,
    null,
    { timeout: 15000 },
  );
  await page.screenshot({
    path: path.join(out, "terminal.png"),
    fullPage: true,
  });
  evidence.stage = "terminal";
  if (job.status === "failed") {
    evidence.status = /unconfigured/.test(
      job.stop_reason || job.error?.code || "",
    )
      ? "pending"
      : "failed";
    await page.reload();
    await applyToken();
    await page.locator("#meme-retry").waitFor({ state: "visible" });
    const restored = await api(jobPath);
    assert.equal(restored.job_id, job.job_id);
    assert.equal(restored.status, "failed");
    evidence.assertions.failed_job_restored = true;
    const waiting = page.waitForResponse(
      (r) => r.url().endsWith("/retry") && r.request().method() === "POST",
    );
    await page.locator("#meme-retry").click();
    evidence.retry = await (await waiting).json();
    assert.notEqual(evidence.retry.job_id, job.job_id);
    assert.equal((await api(jobPath)).status, "failed");
    evidence.assertions.retry_new_attempt_old_failure_retained = true;
  } else {
    evidence.stage = "pagination";
    const revision = job.result_revision;
    assert(
      revision && job.result_count > 0 && job.result_count <= 50,
      "no actual result list",
    );
    let cursor = null;
    const all = [],
      apiPages = [];
    do {
      const params = new URLSearchParams({
        limit: "20",
        media_kind: "all",
        revision,
      });
      if (cursor) params.set("cursor", cursor);
      const result = await api(jobPath + "/results?" + params);
      assert.equal(result.revision, revision);
      assert.equal(result.total_all, job.result_count);
      apiPages.push(result.items);
      all.push(...result.items);
      cursor = result.next_cursor;
      assert(apiPages.length <= 3);
    } while (cursor);
    assert.equal(all.length, job.result_count);
    assert.equal(new Set(all.map((x) => x.candidate_id)).size, all.length);
    assert.equal(new Set(all.map((x) => x.content_group_id)).size, all.length);
    evidence.api_candidate_ids = all.map((x) => x.candidate_id);
    evidence.pages = [];
    for (let index = 0; index < apiPages.length; index++) {
      if (index) await page.locator("#next-page").click();
      const expected = apiPages[index].map((x) => x.candidate_id);
      await waitIds(expected);
      evidence.pages.push(await ids());
    }
    assert.deepEqual(evidence.pages.flat(), evidence.api_candidate_ids);
    assert(await page.locator("#next-page").isDisabled());
    evidence.assertions.pagination_ids = true;
    assert.equal(
      originalRequests.length,
      0,
      "original animations loaded before an explicit action",
    );
    evidence.assertions.no_unconditional_original_loading = true;
    evidence.stage = "filters_downloads_animation";
    evidence.coverage = {};
    for (const kind of ["static", "animated"]) {
      const filtered = await api(
        jobPath +
          "/results?" +
          new URLSearchParams({ limit: "50", media_kind: kind, revision }),
      );
      const items = all.filter((x) => x.media_kind === kind);
      assert.deepEqual(
        filtered.items.map((x) => x.candidate_id),
        items.map((x) => x.candidate_id),
      );
      assert.equal(filtered.total, items.length);
      await page.locator("#media-filter").selectOption(kind);
      await waitIds(items.slice(0, 20).map((x) => x.candidate_id));
      evidence.coverage[kind] = {
        api_count: items.length,
        filter_checked: true,
        downloaded: false,
      };
      if (!items.length) continue; // Missing coverage remains explicit for final aggregate gate.
      const item = items[0];
      const card = page.locator(`[data-candidate-id="${item.candidate_id}"]`);
      await waitPoster(card);
      const waiting = page.waitForEvent("download");
      await card
        .getByRole("button", { name: "Download image ↓", exact: true })
        .click();
      const download = await waiting;
      const filename = download.suggestedFilename();
      assert.equal(filename, path.basename(filename));
      const target = path.join(out, filename);
      await download.saveAs(target);
      assert.equal(sha(await fs.readFile(target)), item.sha256);
      const expected = path.join(out, `expected-${item.candidate_id}.json`);
      await fs.writeFile(expected, JSON.stringify(item));
      const command = [
        "-m",
        "scripts.verify_meme50_media",
        "--file",
        target,
        "--expected",
        expected,
        "--job-id",
        job.job_id,
        "--revision",
        revision,
        "--candidate-id",
        item.candidate_id,
      ];
      if (options["--check-db"]) command.push("--check-db");
      if (options["--local-stack"]) command.push("--local-stack");
      const checked = JSON.parse(
        (await exec(python, command, { cwd: root })).stdout,
      );
      assert(checked.verified);
      evidence.downloads.push({
        kind,
        file: filename,
        candidate_id: item.candidate_id,
        sha256: item.sha256,
        ...checked,
      });
      evidence.coverage[kind].downloaded = true;
      if (kind === "animated") {
        await card
          .getByRole("button", { name: "Play animation", exact: true })
          .click();
        await card
          .getByRole("button", { name: "Pause animation", exact: true })
          .waitFor();
        await waitPoster(card);
        const captures = [];
        for (let frame = 0; frame < 10; frame++) {
          await page.waitForTimeout(
            Math.max(100, Math.min((item.duration_ms || 1200) / 8, 700)),
          );
          const pixels = await card
            .locator("img")
            .screenshot({ animations: "allow" });
          const name = `animation-${frame}.png`;
          await fs.writeFile(path.join(out, name), pixels);
          captures.push({ file: name, sha256: sha(pixels) });
        }
        evidence.animation_frames = captures;
        evidence.assertions.animation_pixels_changed =
          new Set(captures.map((x) => x.sha256)).size > 1;
        assert(
          evidence.assertions.animation_pixels_changed,
          "rendered animation never changed pixels",
        );
        await card
          .getByRole("button", { name: "Pause animation", exact: true })
          .click();
        const paused = sha(await card.locator("img").screenshot());
        await page.waitForTimeout(350);
        assert.equal(sha(await card.locator("img").screenshot()), paused);
        evidence.assertions.animation_paused = true;
        if ((await page.locator(".candidate").count()) > 1) {
          await card
            .getByRole("button", { name: "Play animation", exact: true })
            .click();
          await card
            .getByRole("button", { name: "Pause animation", exact: true })
            .waitFor();
          await page.locator(".candidate").last().scrollIntoViewIfNeeded();
          await card
            .getByRole("button", { name: "Play animation", exact: true })
            .waitFor({ state: "attached" });
          evidence.assertions.offscreen_animation_paused = true;
        }
      }
    }
    evidence.assertions.filter_counts = true;
    const kind = "animated";
    const filtered = all.filter((x) => x.media_kind === kind);
    await page.locator("#media-filter").selectOption(kind);
    await waitIds(filtered.slice(0, 20).map((x) => x.candidate_id));
    if (filtered.length > 20) {
      await page.locator("#next-page").click();
      await waitIds(filtered.slice(20).map((x) => x.candidate_id));
    }
    evidence.stage = "refresh_and_mobile";
    const before = await ids();
    await page.reload();
    await applyToken();
    await page.locator("#meme-controls").waitFor({ state: "visible" });
    await waitIds(before);
    assert.equal(await page.locator("#media-filter").inputValue(), kind);
    const restored = await api(jobPath);
    assert.equal(restored.result_revision, revision);
    evidence.assertions.refresh_position = true;
    await page.setViewportSize({ width: 375, height: 812 });
    await page.waitForTimeout(300);
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    if (await page.locator(".candidate").count())
      await page.locator(".candidate").last().scrollIntoViewIfNeeded();
    await page.screenshot({
      path: path.join(out, "mobile.png"),
      fullPage: true,
    });
    evidence.assertions.mobile_scroll = true;
    assert.deepEqual(evidence.errors, []);
    evidence.status = "passed";
  }
} catch (error) {
  evidence.status = "error";
  // Do not serialize request headers, browser context or supplier messages.
  evidence.error_type = error.name;
  evidence.error_code = error.code || "browser_assertion_or_runtime_error";
} finally {
  await fs.writeFile(
    path.join(out, "browser-evidence.json"),
    JSON.stringify(evidence, null, 2) + "\n",
  );
  await browser.close();
}
process.exitCode = { passed: 0, failed: 1, pending: 2, error: 3 }[
  evidence.status
];
