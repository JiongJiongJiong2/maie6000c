# Real GIF acquisition verification and handoff

Date: 2026-11-11, Asia/Hong_Kong. Execution used one agent and no subagents.

**Latest update:** G1, engineering G2, real-stack G3, playback, failure/retry,
interrupted-job recovery, and PostgreSQL regression have now passed. G4 real-user
inputs/human target decisions and G5 another member's reproduction remain open.
See "Post-repair acceptance" below. The original sections are retained as the
historical first-pass report, including their failures.
**The main task is not accepted as complete.** Implementation and offline contracts
are delivered; production network acquisition, deployed API verification, and a
confirmed original-meme match remain open.

## Baseline and changes

- Clean original checkout: `codex/w07-fullstack-demo` at `6dd60a1`.
- Fetched origin; PR [#8](https://github.com/JiongJiongJiong2/maie6000c/pull/8)
  was open, not draft, not merged, targeting `dev`.
- Working branch: `codex/real-gif-acquisition`, based on
  `c34d9f6c55a1febbe78fcbf275baab70536424d7`
  (`feature/backend-final-integration`). Changes remain local and uncommitted;
  nothing was pushed or merged. PR #8's existing backend work is a dependency,
  not a contribution of this iteration. No local AGENTS.md was present.
- The final production implementation fingerprint, calculated over all Python
  modules in `services/search_agent`, `services/retrieval`, and the formal runner,
  is `e36b08188b270d73f77c0465b913ab5132c6fbe5dce1e7ab6d013e163f5f3316`.
  The verification script records the fingerprint and baseline independently of
  any later documentation commit.

Implemented source resolution before filtering (including images mode), separate
job-wide page and media ledgers, safe normalization and URL/SHA deduplication,
controlled operational failures and trace, bounded registered-host download,
original-byte full GIF validation, local CLIP sampling/ranking, lazy processor
export, CLI recovery, explicit runner conversion, worker-only retrieval Docker
target, deployment settings, and root-level CI coverage. The existing worker,
API, database schema, UI, provider adapters, and saved-index adapter were retained.

## Stage results

| Gate | Result | Evidence and precise scope |
| --- | --- | --- |
| G0 baseline | Complete | PR checked through GitHub connector; Python 3.11, torch/transformers and local CLIP weights present; DDGS installed from declared dependency; DeepSeek/Brave/Tavily keys absent |
| G1 production download + decode + rank | **Blocked** | `direct-source-resolution.json` rejects `dns_non_public` before GET; `direct-source-verification.json` has `passed=false` and no candidates |
| G1 independent reference check | Partial component evidence | Public sample retrieved separately with curl; 1,001,718 bytes, 400×400, 44 decoded frames; real local CLIP inference succeeded; does not prove application downloader works live |
| G2 real provider recovery | **Not passed** | Natural-description DDGS discovery returned six sources in one call. Earlier filename-assisted recovery made two real searches, reached supported Commons results, and failed safely on reserved DNS. Final repeat had two `provider_unavailable` errors. No GIF candidates, zero media attempts |
| G3 production worker + DB + API | **Blocked** | Docker daemon unavailable; no disposable PostgreSQL URL supplied. No production request/job/candidate IDs or API SHA match exist |
| G3 offline integration | Passed | Real processor → actual agent → strict runner serialization → existing worker → API media endpoint; bytes and decoded frames verified; network and embeddings are controlled test inputs |
| G4 real meme targets | **0/3 planned, none acceptance-ready** | Three legacy screening cases below lack the required input/target/permission bundle; no original-GIF hit or human confirmation is claimed |
| G5 handoff | Written, not independently reproduced | Commands, limits, source support, regression evidence and owner notes supplied; another member's reproduction has not occurred |

Evidence files are in [evidence/gif-acquisition](evidence/gif-acquisition/).
They are copied from actual runtime artifacts, not manually fabricated success
records. Larger raw outputs, original GIF, screenshot and source HTML remain in
ignored `.cache/gif-acquisition/`. The historical direct subprocess runner record
predates final diagnostic refinements; `live-search-result.json` and verification
fingerprint identify the final production code. `live-search-attempt02-result.json`
preserves the earlier successful-discovery/blocked-resolution run; the final
fingerprinted repeat instead failed at the intermittently available provider.
Neither failure is discarded or classified as a recovered GIF.

## Actual public sample and independent CLIP check

Sample: [Rotating earth (large)](https://commons.wikimedia.org/wiki/File:Rotating_earth_(large).gif),
author Marvel, [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/)
license option. Retain attribution when redistributing it.

Original bytes SHA-256:
`b0acdc9a01f91f6123dbff38d4bee59d0d6e4b26071b5c83937b242b6b202378`.
The screenshot is frame 12 extracted for engineering verification, SHA-256
`fb69020693a4a54cda6d987a8611158e036c713d0f300c898d7474947219434c`.
It is neither an independently supplied target nor a real-meme acceptance case.

Fixed model: `clip-vit-base-patch32@37000f5cdccec47a3f6f83142bff131370757470`.
Eight uniform frames, maximum frame cosine, real score `0.9999995827674866`;
encoding including model load took about 3.87 seconds. This near-identical-frame
check establishes runtime availability, not retrieval accuracy or threshold
calibration. The development threshold remains explicitly 0.82, unchanged per case.

The application downloader rejected Commons DNS `198.18.0.9` and media DNS
`198.18.0.10`. These are reserved addresses. Curl could obtain reference bytes
through the machine's network setup, but its route is **not** substituted for the
production downloader or presented as a passed G1. No private-address whitelist,
DNS patch, or mock result was used in live acceptance.

## Three existing cases screened for G4

These are pre-existing case IDs from `experiments/meme_search/queries.json`,
not newly invented user targets. Their earlier AI source annotations are not
human target confirmation. Keep all three in the planned work list; none counts
as a completed screenshot-based recovery experiment or a valid effectiveness-rate
observation. They were screened before further target-media acquisition and were
not downloaded as new authorized target GIFs.

| Case | Existing description / target family | Current missing evidence / failure |
| --- | --- | --- |
| c05 | Black-and-white panda body with human face, textless base | Existing judgment explicitly says no unique target; no authorized screenshot/target-animation pair; historical proxy image failed and another candidate was JPEG |
| c06 | Jacky Cheung “吃屎啦你”, textless version | No independently saved target GIF or supplied screenshot; previous 24-frame file is explicitly a blurred preview; permission to save the original is not established; site adapter unsupported |
| c07 | Wang Jingze “真香” | No independently saved original target/screenshot pair; historical `.gif` preview decoded to one frame; original-download permission not established; site adapter unsupported |

Historical facts come from `media_probe.json`, `media_sources.json`, and
`independent_judgments.json` in that directory and are **not** new live results.
The current repository's twelve example GIFs are not substituted for outside-library
targets. G4 requires three screenshot/description/independent-target/permission
bundles and a real licensed meme-source adapter; one confirmed original must then
succeed through G3. No additional key, paid provider, or human match is invented.

## Regression and live checks

Final ordinary suite: **218 passed, 4 skipped, 2 deselected**. The four skips are
PostgreSQL-specific integration tests requiring `TEST_POSTGRES_URL`; the two
excluded tests are deployment smoke tests. One pre-existing Starlette/AnyIO
deprecation warning remains. `ruff check .` and `git diff --check` pass.

```bash
MEME_FONT_PATH='/System/Library/Fonts/Supplemental/Arial.ttf' \
  .venv/bin/python -m pytest -q -m 'not smoke' -rs
.venv/bin/python -m ruff check .
git diff --check
```

Without the font setting, the pre-existing macOS caption-rendering test fails
because its default Linux font paths do not exist. Its English test fixture was
rerun against an installed Arial font; production Chinese rendering still needs a
Chinese-capable font. No application font behavior was changed.

New coverage includes download policy/DNS/redirects/stream byte caps/deadlines,
actual animated versus static/invalid/non-GIF decoding, same-URL budget consumption,
content deduplication, finite max-frame ranking/Top 3/low scores/model failures,
write failures and symlink containment, resolver-before-filter, cross-round page
and media budgets, operational failures without processor calls, strict actual
SearchResult conversion, lazy import, safe missing-export failure, single JSON
stdout in runner main, and real-processor worker/API integration. The existing
parent-process timeout test remains in the suite (it simulates TimeoutExpired;
it is not a live deployment hard-kill test).

Live checks performed separately:

1. Actual Commons HTML fetch and original-link fixture extraction.
2. Actual public GIF reference download, complete decoding, hash, real local CLIP.
3. Actual DDGS natural-description discovery, no candidate success asserted.
4. Actual formal runner subprocess, two DDGS calls, strict stdout validated by
   `WebSearchResult.model_validate_json`.
5. Final fingerprinted direct-source and recovery runs, both correctly failed
   without candidates. Filename-assisted search is explicitly a debug record,
   not natural-description target recovery.

Model-enabled planning, deployed container build, worker model-volume readability,
production PostgreSQL, API media download, browser animation playback, and human
original-version confirmation were not passed. No saved-asset index readiness or
successful local reuse is claimed.

## Reproduction and remaining work

Run commands from the repository root with Python 3.11. Installation and discovery/
recovery commands are in [web-search-agent.md](web-search-agent.md). Start with a
worker environment whose public DNS and actual egress satisfy the network policy.
Configure an existing provider explicitly; DDGS needs no paid key. DeepSeek requires
the existing authorized key. No environment file or credentials were overwritten.

The final direct and recovery commands used the ignored engineering screenshot:

```bash
.venv/bin/python -m scripts.verify_gif_acquisition \
  --source 'https://commons.wikimedia.org/wiki/File:Rotating_earth_(large).gif' \
  --image .cache/gif-acquisition/reference-screenshot.png \
  --out .cache/gif-acquisition/new-direct-attempt

.venv/bin/python -m scripts.verify_gif_acquisition \
  --description 'Rotating earth large Wikimedia Commons GIF' --provider ddgs \
  --image .cache/gif-acquisition/reference-screenshot.png \
  --out .cache/gif-acquisition/new-live-attempt
```

Both return nonzero in this environment, as documented. Fresh output directories
are mandatory. Replace the screenshot and description with authorized independent
inputs for real acceptance. Screenshots are never sent to the provider/planner.

After network G1/G2 pass, use the existing deployed stack (avoid duplicate workers):
upload screenshot via `POST /search-requests`, wait for local job, create web job
via `POST /search-requests/{request_id}/web-search`, poll request and job candidates,
then download `GET /candidates/{candidate_id}/media`. Record request/job/candidate
IDs, MIME, all decoded frames, SHA, and `SearchExecution`; compare to the pipeline's
candidate SHA before the worker deletes its temporary job directory. Device auth
is required if configured; never store its token in evidence. Perform original
version/action/subtitle/crop confirmation separately from animation validation.

## Owner handoff

- **Jiongle:** review `resolvers.py`, the resolver-before-filter boundary, page/media
  ledgers, CLI, trace diagnostics, and Commons registry. Add a permission-reviewed
  real-meme source; unknown hosts currently yield coverage misses.
- **YuanJian:** review `download.py`, `candidates.py`, shared decoder/atomic writer
  reuse, local CLIP sampling, the lazy export, and controlled failure taxonomy.
  Use the reference GIF only for engineering checks. Target threshold calibration
  and original-version matching remain unvalidated.
- **Haoxuan:** minimal compatible changes are explicit runner conversion/resolver
  injection, Compose web-mode/settings parity, worker-only retrieval build target,
  and CI coverage. Existing worker revalidation/persistence/API contracts are
  preserved. Verify real model-cache volume and deployed PostgreSQL/API flow.
- **Zirui:** the offline integration verifies existing candidate media routes and
  provenance fields; no UI rewrite is needed. There are currently no accepted
  live candidate IDs to plug into the page. Do not display discovery pages or
  operational failures as recovered GIFs.

`index_saved_asset` and collection-to-local-retrieval integration remain a separate
follow-up; no placeholder adapter was added. No messages or review requests were
sent to team members automatically.


## Post-repair acceptance — 2026-11-11 Hong Kong

The implementation remains on `codex/real-gif-acquisition`, based on `c34d9f6`.
Final production-module fingerprint:
`42f7036d8c1848a7d40abf1af8049306d3923f0bd6227150ceca4957b427acc3`.
A complete code/test/configuration snapshot and its SHA manifest are supplied
separately from runtime evidence; nothing was merged or pushed. Earlier fingerprints
remain attached to their own attempts rather than being rewritten.

### Current gates

| Gate | Current result | Actual evidence |
| --- | --- | --- |
| G1 | **Passed**, engineering | Host production resolver + fetch + preparation: Earth, 1,001,718 bytes, 44 frames, original SHA, real CLIP ~0.99999994. Nonroot Docker production check also passed with real public DNS and locally mounted weights |
| G2 | **Passed for engineering natural-description input** | Actual DDGS search, fixed disclosed partyparrot domain scope, actual page/bytes/local CLIP, original-green 10-frame GIF; screenshot is engineering frame, therefore no real-user success claimed |
| G3 | **Passed for engineering input** | Actual PostgreSQL 16 Docker database; separate host API/worker and formal runner; actual HTTP upload/web job/media; read-only ORM SHA/provenance/score/frame reconciliation |
| Browser | **Passed** | Actual installed Chrome; candidate animation renders different frames; browser download SHA equals API and DB |
| Failure/recovery | **Passed at tested boundaries** | Real provider failure then retry with new linked job; same-key replay and changed-description conflict; real low-score API no_candidates; controlled process killed by parent timeout; task-owned worker interrupted/restarted, old candidate preserved |
| Regression | **236 passed, 0 skipped**, 2 smoke deselected | Full non-smoke suite on the project's actual PostgreSQL, including the four previously skipped tests and real sleep-process termination; Ruff and diff checks pass |
| G4 | **Pending: 0 eligible real-user cases** | Three sourced animation proposals ready for review, but not three qualified real screenshot/description/target bundles. No human original-target confirmation exists |
| G5 | **Ready for handoff, not independently reproduced** | Reproducible commands, snapshot, evidence and blank human decision fields supplied; no other member was impersonated or automatically messaged |

The project-wide main task is still **not fully accepted** until G4/G5 are actually
performed. The two deployment smoke tests remain separately excluded; real HTTP,
PostgreSQL, browser and Docker checks above are explicit acceptance runs, not a
claim that those old W07 smoke tests ran. Model planning was explicitly disabled;
paid-provider credentials remain absent, and no actual planner-call acceptance is
claimed. No UI integration or saved-index implementation was added.

### Real jobs and exact byte reconciliation

First transfer sequence:

- Request `eb43024a-61ee-459f-8e83-57b9009cbc7e`;
  local job `529ca97d-0628-4006-a505-e0a7e888e30d`.
- Original web job `51ca6226-d2a9-42fb-922d-ad226a8c18f4` failed with
  `web_provider_unavailable`; its trace is preserved.
- Explicit retry job `b70cc3f8-dc82-48a4-be89-df68d3a3396c` succeeded;
  actual DB `retry_of_job_id` and same-key retry replay were checked.
- Candidate `dea6fad2-f325-483a-8ec2-0fad16397e0b`: actual API/DB/browser SHA
  `ecfacdf40753e363e4022f79ee48ddf55d6b3d537b6a6fa80929718b653b7022`.
  A read-only historical audit confirmed zero exact target entries in the reference
  library, saved library, or prior candidate jobs before that request, and zero
  exact local target hits. Local retrieval did return three **wrong alternatives**;
  this is not a correct original-target hit or a reason to lower the threshold.

Final production-fingerprint sequence, explicit Yahoo backend:

- Request `9e49dd06-f059-42a2-af32-352397aae722`.
- Local job `129dcdc5-caa9-4353-a946-fd4e44ab03e3`.
- Web job `b67f942c-c0dd-4ee5-b4ef-9b888c9a2884`.
- Candidate `40953a1a-5b48-47ed-91f0-454a592a0a06`: 13,485 bytes, 128×128,
  10 frames, score `0.9509462118148804`, same SHA as above.
- Source `https://cultofthepartyparrot.com/`; actual selected media
  `https://cultofthepartyparrot.com/parrots/hd/originalparrot.gif`.

The final repeated requests correctly observe earlier copies in historical
candidate storage; they are not falsely labeled fresh outside-library tests.
The known independent reference was kept in an ignored review folder, never
passed to search, used as a fallback candidate, or inserted into the reference
library. The screenshot used for these runs was extracted from that reference,
so all these successful transfers remain **engineering cases**.

### Real failures and environment repairs

The persistent Clash Merge file was backed up and only four host exclusions were
added. Docker was launched, its daemon became usable, and the existing
`memeretrieve-local` database/credentials/volume were reused without resetting data.
The existing launcher ran migrations and validated twelve reference assets.

The host initially resolved real public DNS, then Commons returned a stale fake-IP
answer despite the correct persistent/generated filters. Both documented cache
endpoints on the actual service-mode socket returned 204; loading the current
persistent-generated configuration also returned 204. A system mDNSResponder
refresh could not proceed without a sudo password. No password was obtained and
no address check was weakened. The verified task-owned Docker alternative uses
`--dns 1.1.1.1` and ordinary production code. Partyparrot host acquisition works
on the host stack. These distinct environment outcomes are retained.

The first Commons production GET returned HTTP 403. A public-project identifying
User-Agent succeeded; no login, CAPTCHA, certificate-validation bypass or guessed
original media URL was used. DDGS Bing has actual intermittent failures; Yahoo was
selected explicitly after separate diagnostics and passed positive and negative
runs. The final runtime settings must be supplied explicitly when reproducing.

The full regression initially inherited `ENABLE_DEMO_LIBRARY=true` from the demo
launcher and failed a test that expects its default opt-out. The final regression
kept the dedicated DB connection but set that unrelated feature flag false;
236 tests passed. This was test-environment isolation, not an application behavior
change or a hidden skipped test.

### Failure and replay evidence

- Actual low-score web job `06c4e477-9146-4c19-aaab-bae9b7626fd8`, request
  `fa4df033-d80f-4303-af1b-314d914b71ec`: real media download, one low-score reject,
  two searches, completed/no_candidates, no technical error concealed. The deliberately
  inconsistent Earth screenshot/parrot description is a negative engineering check.
- Actual interrupted job `d49c770e-d6ea-4cf7-9374-5a4097b37b80`: only this task's
  verified worker and child runner were killed. After restarting the same stack,
  API reports `worker_interrupted` and the earlier successful GIF is byte-identical.
- `test_web_search_actual_timeout.py` runs a real controlled 30-second process
  through the parent boundary, times out after about 5.1 seconds, and verifies
  the child PID is gone. It does not mock `subprocess.run` or `TimeoutExpired`.
- The ordinary regression verifies two-round/six-media shared budgets and DNS,
  encoded namespace, relative-link, HTTP status, and file-level permission scopes.
  Live traffic was not intentionally exhausted to test limits.

### Sources and human review material

[gif-acceptance-cases.json](gif-acceptance-cases.json) records three source proposals:
original green parrot (Geiger Powell's recorded permission), ASCII dance (קקון,
public-domain dedication), walking cat (Sheilagraber, CC BY-SA 3.0). Actual original
bytes were acquired and decoded as 10, 7, and 5 frames respectively in the public-DNS
container. Their review page and GIFs are in ignored
`.cache/gif-acceptance/container-review/review-samples/`.

All three still have `eligible_g4=false`, missing real screenshot/input SHA and
missing human target confirmation. The suggested descriptions are clearly
agent-authored source proposals, **not user demands**. c05/c06/c07 remain retired
screening items with their original deficiencies recorded; their failures were
not erased or replaced with a misleading 3/3 claim. Three proposals are not three
qualified development cases. A real user's screenshot and independent target
judgment cannot be supplied by this agent.

### Reproduction

Keep the existing `.cache/local-demo.env` protected; never print or overwrite its
password. Run from the repository root, after starting Docker and preparing the
existing reference library and fixed local model weights:

```bash
SEARCH_AGENT_PROVIDER=ddgs SEARCH_AGENT_MODE=web SEARCH_AGENT_USE_MODEL=false SEARCH_AGENT_DDGS_BACKEND=yahoo SEARCH_AGENT_DOMAINS='["cultofthepartyparrot.com"]'   .venv/bin/python scripts/run_local_demo.py
```

That command stays running with separate API and worker. Do not launch duplicate
workers. The currently running final stack uses those settings. For a new attempt:

```bash
SEARCH_AGENT_PROVIDER=ddgs SEARCH_AGENT_MODE=web SEARCH_AGENT_DDGS_BACKEND=yahoo SEARCH_AGENT_DOMAINS='["cultofthepartyparrot.com"]' .venv/bin/python -m scripts.verify_gif_acquisition_e2e   --local-demo --image /absolute/path/to/real-screenshot.png   --description 'actual user natural description'   --out .cache/gif-acceptance/new-case-attempt
```

`--target /absolute/path/to/independent-target.gif` performs post-hoc SHA comparison
only. `--retry-from previous-attempt/result.json` uses the actual retry API.
`--expect-no-candidates` accepts only the explicit completed/no_candidates negative
outcome. Each output directory must be new. The helper records configured execution
context; actual worker queries/backend are authoritative in DB trace. It uses real
HTTP and a read-only PostgreSQL transaction, never TestClient or injected searchers.

```bash
node scripts/verify_gif_acquisition_browser.mjs   .cache/gif-acceptance/new-case-attempt/result.json   .cache/gif-acceptance/new-browser-attempt
```

This uses the installed Chrome by default and existing web Playwright dependency.
It captures different rendered frames and downloads actual candidate bytes; it
never intercepts API responses. Browser traces/auth headers are not collected.

The final worker image is built with `docker build --target worker`; installation
runs as root inside the build and runtime returns to UID 10001. Actual image build,
local model readability and real encoding were verified. The local stack's API/
worker run as host processes with Docker PostgreSQL; this is not a claim that the
entire Compose stack or formal UI was deployed. The standalone container G1 mount/
DNS command and final image identity are in the handoff manifest.

### Only remaining non-substitutable acceptance inputs

1. Three genuine screenshot + user-description + independent-target/permission
   bundles, with initial-state proof, frozen before their final searches.
2. A real person must review at least one recovered original version (action,
   subtitles, crop) through G3 and enter name/date/verdict; byte match alone does
   not invent that judgment. The existing engineering candidate is ready to view.
3. Another actual team member must reproduce a real case and record their own
   result. No subagent or self-authored document is counted as that member.

Use the blank reviewer fields and command sheet; no ordinary implementation
approval is needed. `index_saved_asset`, full formal webpage integration and
model-enabled planning remain outside the accepted machine results.


### Final artifact integrity

The code-only snapshot contains 128 code/test/configuration files, SHA-256
`7f06bdd74fad2b18aca94c50601abe014aa0584e547c698e7c82791b0921ca4e`.
Every archived file was compared against the current workspace and manifest.
Documentation/evidence are delivered separately to avoid a self-referential archive
hash. The final container's production-module fingerprint exactly equals the
final API job's fingerprint. See
[evidence/gif-acceptance/handoff-manifest.json](evidence/gif-acceptance/handoff-manifest.json)
for actual image identity, request/job/candidate IDs, checks and artifact paths.
The code snapshot, raw GIFs and review page remain in ignored `.cache/gif-acceptance/`;
credentials, network subscriptions, user screenshots and weights are not archived.

Current local stack is left running for review on `http://127.0.0.1:8000`.
Only task-owned processes were interrupted; the project database, prior results,
user network rules and model files were retained. No changes were pushed or merged.
