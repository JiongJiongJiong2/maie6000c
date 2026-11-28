# Backend guide | 后端开发与验证

## Current status / 当前状态 (2026-11-28)

**中文**

本指南记录当前产品后端，而非 W07 初版。FastAPI 与 PostgreSQL 持久化请求、本地和联网任务、候选、审核、收藏和索引状态；独立 worker 执行 CLIP 本地检索、联网候选处理、媒体校验和收藏索引更新。`services.retrieval` 中的候选处理和索引模块已实现。网页端由独立模块维护，边界见[团队计划](final-project-plan.md)。

完整生命周期集成测试使用确定性替身验证提交、worker、候选、审核、收藏、索引和本地复用；它不证明线上供应商可用性或总体检索准确率。2026 年 11 月 28 日的一次真实网页闭环及尚未完成的评估工作见[W13 交付报告](../submissions/week13/README.md)。

**English**

This guide describes the current product backend, not only the original W07
slice. FastAPI and PostgreSQL persist requests, local and web jobs, candidates,
reviews, saved assets, and index states. A separate worker runs CLIP retrieval,
web-candidate processing, media validation, and saved-asset indexing. The
candidate-processing and saved-index modules are implemented under
`services.retrieval`. The web client is maintained separately; see the
[team plan](final-project-plan.md) for ownership boundaries.

The deterministic lifecycle integration test covers submission, worker
execution, candidate delivery, review, saving, indexing, and local reuse. It
does not prove live-provider availability or overall retrieval accuracy. The
[W13 delivery report](../submissions/week13/README.md) records the real browser
workflow verified on 28 November and the evaluation work that remains open.

## Implementation and integration details

Owner: Haoxuan Jiang. This document covers backend services rather than the
web-client implementation. The W04 architecture and the W07 submission are
historical milestones; the [current architecture](architecture.md) summarizes
the product as of 2026-11-28.

Implemented backend behavior includes multipart submissions, PostgreSQL
migrations, persistent jobs, atomic claims, retry/review idempotency, GIF
catalog import and validation, shared storage, media expiry, and Docker
API/worker separation.

Post-midterm additions include linked web-search jobs, persisted agent
execution traces, provenance-bearing temporary candidates, idempotent
collection into a separate saved-asset table, and a durable saved-index queue.
A saved GIF is not inserted into `reference_assets` merely because it was
collected.

Migration `20261109_0003` alters existing PostgreSQL tables in place to preserve
inbound foreign keys; Alembic uses batch table recreation only where SQLite
requires it. PostgreSQL CI validates migration upgrade, downgrade, and ORM
metadata consistency. Local SQLite tests and generated PostgreSQL SQL alone
do not replace live-database validation.

The worker calls `services.retrieval.search(image_path, top_k=3)` and the
`services.search_agent` runner in bounded subprocesses. Candidate processing
validates downloaded media; saved-index updates validate the original file and
publish a versioned index before reporting it ready. The worker resolves
reference and saved-asset IDs through their separate data models and verifies
media checksums and frame counts.

## Run (PowerShell, from the repository root)

After copying `.env.example`, set `POSTGRES_PASSWORD` in `.env` to a private,
hexadecimal password before starting Compose. Compose refuses to start when the
password is empty.

```powershell
Copy-Item .env.example .env  # only when .env does not already exist
docker compose up --build -d
Invoke-RestMethod http://localhost:8000/health/ready
docker compose logs --tail 30 worker
```

Open `http://localhost:8000/docs` to exercise the API. The default stack is
PostgreSQL, API, and **one** search worker. The old case/AI starter remains
available with `docker compose --profile starter up --build -d`, which also
starts `ai` and `starter-worker`. Both workers use PostgreSQL advisory locks to
reject a second instance before startup recovery. Interrupted starter triage
jobs are returned to `pending` and their cases to `queued`; the bounded AI
request's processing path returns before shutdown after SIGTERM; the AI call
uses the configured `WORKER_REQUEST_TIMEOUT_SECONDS` value. The default
`STARTER_WORKER_STOP_GRACE_PERIOD` is 30 seconds; if increasing the AI request
timeout, also increase the stop grace period to exceed it with enough margin
for database updates.
The search worker also finishes its current bounded retrieval operation after
SIGTERM. Its default `SEARCH_WORKER_STOP_GRACE_PERIOD` is 330 seconds, covering
the 300-second maximum saved-index operation and bounded web/local operations.
Keep this grace period above the largest configured web-search, index, or local
retrieval timeout with enough margin for validation and database writes.
All Compose services use `unless-stopped` restart behavior; a manually stopped
service remains stopped, while a container process failure is restarted.
Docker `json-file` logs rotate at 10 MiB per file and retain at most three
files per service container.
The API, workers, AI service, and Prometheus drop all Linux capabilities and
disallow privilege escalation. The API, AI, and worker image processes use
unprivileged UID 10001, with writable media and model-cache volume directories
prepared at build time; PostgreSQL retains the capabilities needed by its
official entrypoint to initialize and manage the data directory.
Set a private `POSTGRES_PASSWORD` containing only URI-unreserved characters
(letters, digits, `-`, `.`, `_`, or `~`) in `.env`; API and both workers use
that value to build their internal PostgreSQL connection URL. Changing this
variable after PostgreSQL has initialized an existing data volume does not
rotate the stored database password; update the PostgreSQL role password
separately before changing the application configuration.
Compose passes only each service's required settings from `.env`; the database
password is not separately exposed to application containers as a standalone
environment variable.

The API, AI service (started by either the `starter` or `observability`
profile), Prometheus, and PostgreSQL host ports bind to loopback by default.
For LAN integration, first set a private
`DEVICE_TOKEN` in `.env`, then set `API_BIND_HOST=0.0.0.0`; callers must send
`Authorization: Bearer <token>` on search, candidate, review, and retry routes.
Health and the legacy starter routes remain unauthenticated. This is a local
development deployment, **not an internet-facing authenticated service**.
Never publish database credentials. Restrict LAN access with the host firewall.
Keep `AI_BIND_HOST` and `PROMETHEUS_BIND_HOST` on loopback; those
services do not provide authentication. PostgreSQL's published port remains
loopback-only.

## Shared files and persistence

| Class | Compose location | Persistence |
|---|---|---|
| Requests/jobs/results/reviews/catalog | PostgreSQL `postgres_data` volume | Retained across container recreation |
| Crops and GIF transport copies | `task_media` volume, `/data/media` | Seven days after terminal execution |
| Reference GIFs and manifest | Host `data/reference`, read-only at `/data/reference` in API and worker | Persistent, not task cleanup |
| Model cache | `model_cache` volume, `/data/models` | Persistent |
| Prometheus time series | `prometheus_data` volume, `/prometheus` | Retained across container recreation; capped at 15 days or 2 GiB |

`docker compose down` preserves named volumes. **`down -v` deletes database,
task-media, model-cache, and Prometheus volumes.** It does not remove host
reference files.
Configure `REFERENCE_HOST_PATH` before starting if the corpus lives elsewhere.
The API and worker mount the corpus read-only; publish corpus files on the host
before importing their manifest.
Compose explicitly supplies shared container paths for media, reference, and
model-cache storage to API and worker. Retrieval code must use those settings
rather than a personal absolute path. Git and the Docker build context exclude
`data/`; never commit screenshots, bulk GIFs, weights, caches, or `.env`.

The API validates decoded JPEG/PNG/WebP input (10 MiB default, 20 megapixels),
writes the crop atomically, and commits request and job in one transaction
before returning `202`. Database failures remove the uncommitted input.
An interrupted upload can leave an orphan; startup/hourly cleanup removes
unreferenced files older than one day. Cleanup errors are logged without
replacing the original database or storage error; the orphan remains eligible
for a later cleanup. Enforce an ingress request-size limit
at a reverse proxy before any non-local deployment; multipart parsing can spool
a file before route-level byte validation.

The worker claims with `FOR UPDATE SKIP LOCKED`, commits `running`, and performs
inference/file operations outside the claim transaction. Candidates and final
state commit together. Retrieval has a 120-second default subprocess timeout.
Each candidate must match its catalog checksum, be a fully decoded multi-frame
GIF, and fit 25 MiB, 20 megapixels per frame, 1000 frames, and 100 megapixels
total decoding work. The worker enforces the byte limit during the read for
both web candidates and saved GIFs used in local retrieval, even if a file
grows after it is created. At most three are stored.
Scores are finite ranking signals, not probabilities.
PostgreSQL also rejects non-finite similarity scores, invalid job state/timestamp
combinations, and terminal times earlier than their start times. The request /
attempt and job / rank unique indexes also cover the matching lookup prefixes,
so no redundant single-column indexes are created.

Startup recovery changes abandoned `running` jobs to `failed` /
`worker_interrupted`; it never silently reruns them. A user retry creates a new
attempt and retains the old failure. Cleanup preserves active inputs and
metadata, removes expired transport files and candidate previews, and returns `410 media_expired` for
expired candidates. Re-submit with a **new submission key** after media expiry.

## Corpus import

Place permitted files under `data/reference` and provide `manifest.json`:

```json
{
  "corpus_version": "team-corpus-v1",
  "assets": [{
    "reference_asset_id": "08b72e37-f396-49ae-8204-a9d791393af0",
    "title": "Replace with a permitted animation",
    "source_reference": "Replace with the actual source",
    "permission_note": "Replace with documented permission",
    "gif_path": "example.gif",
    "sha256": "<actual lowercase 64-character SHA-256>"
  }]
}
```

This is a format example, not a distributed corpus. Import only verified content:

```powershell
docker compose exec api python -m services.common.reference_assets /data/reference/manifest.json
```

The importer validates every referenced GIF and checksum before opening a
database session, then loads and checks catalog rows in batches of 400 before
committing the catalog changes together. It checks required provenance and
stable UUIDs, and rejects duplicate GIF checksums both within a manifest and
against a different catalog ID. Repeating an unchanged import is safe.
An existing asset's content/provenance may not change under the same ID.
A new corpus manifest can update that asset's active `corpus_version`; old jobs
retain their recorded version. Stop the worker while publishing a new corpus,
then restart it after files, features, manifest, and catalog agree.

`search` must return this JSON-compatible shape (no local paths):

```json
{
  "matches": [{
    "reference_asset_id": "08b72e37-f396-49ae-8204-a9d791393af0",
    "score": 0.87
  }],
  "model_version": "encoder-version",
  "corpus_version": "team-corpus-v1"
}
```

Matches must be distinct, descending by score, and reference imported assets in
the declared corpus. An empty list means a completed `no_candidates` result,
not a technical failure. Raise on unavailable models/corpus or decoding errors.

## Client contracts

All IDs below are UUID strings; JSON field names are snake_case.

| Endpoint | Contract |
|---|---|
| `POST /search-requests` | Multipart `image`, `client_submission_key`; optional `user_keywords`, `client_item_id`; `202` with `request_id`, `job_id`, `status` |
| `GET /search-requests/{request_id}` | Latest attempt with `request_id`, `job_id`, `status`, `result_kind`, `candidates`, `error` |
| `GET /search-jobs/{job_id}/candidates` | Candidates from that particular attempt |
| `GET /candidates/{candidate_id}/media` | Validated `image/gif` for preview or download; after save, serves durable asset media beyond temporary expiry |
| `POST /search-jobs/{job_id}/reviews` | JSON `decision`, `candidate_id`, `client_review_key`; `201` with `review_id` |
| `POST /search-requests/{request_id}/retry` | JSON `client_retry_key`; only after failure; `202` with accepted attempt |
| `POST /search-requests/{request_id}/web-search` | JSON `description`, `client_search_key`; creates a distinct linked web job; `202` |
| `POST /search-jobs/{job_id}/retry` | JSON `client_retry_key`; retries the specified failed local or web job; `202` |
| `POST /candidates/{candidate_id}/save` | JSON `client_save_key`; requires an accepted web candidate; `202` with asset/save/index status |
| `GET /saved-assets/{asset_id}` | Durable saved-file and indexing status |
| `GET /saved-assets/{asset_id}/media` | Validated `image/gif` from persistent storage, independent of temporary candidate expiry |
| `POST /saved-assets/{asset_id}/index-retry` | Re-queues a failed saved-asset index update |

Initial response:

```json
{"request_id":"<uuid>","job_id":"<uuid>","status":"pending"}
```

Polling response:

```json
{
  "request_id": "<uuid>",
  "job_id": "<uuid>",
  "status": "completed",
  "result_kind": "candidates",
  "candidates": [{
    "candidate_id": "<uuid>",
    "rank": 1,
    "score": 0.87,
    "media_url": "/candidates/<uuid>/media"
  }],
  "error": null
}
```

The polling response also includes `job_kind`, `stage`, `local_job_id`, and
`web_searches` so a client can restore each linked task after refresh. Each
candidate includes `source_url`, `image_url`, `provider`, `save_status`,
`asset_id`, and `index_status` where applicable. Temporary web candidates and
saved files are distinct: a review records acceptance, the save endpoint
persists the file and returns its durable `media_url`, and the worker later
updates its index status. The saved-media endpoint checks the stored checksum
and animation frame count before serving the file. A saved candidate's existing
candidate media URL also serves that durable asset after temporary cleanup;
unsaved candidate media still expires normally.

Submission and web-search keys replay only identical input/description; using
the same key with changed content returns `409`. A request may have only one
active local-or-web task. Web retries target a specific failed job so original
results and execution traces remain available. A save key replays the same
candidate/asset mapping; content SHA-256 deduplicates saved assets. Search
execution records retain bounded calls, downloads, stage trace, warnings,
duration, stop reason, agent version, and model version, never provider
credentials.

States are `pending -> running -> completed / failed`. `result_kind` is null
until completed; failed jobs expose `error: {"code": "...", "message": "..."}`.
HTTP domain errors use FastAPI's `detail: {"code": "...", "message": "..."}`;
request-schema validation uses standard FastAPI `422` details.

Keys are non-whitespace strings of at most 128 characters. Reusing an upload
key requires exactly the same bytes, keywords, and local item ID; otherwise
`409`. Replay returns the original job, while GET returns the latest attempt.
Reviews are append-only: `accept` requires a candidate belonging to the
completed job; `reject_all` requires a null candidate. Replay of a review/retry
key returns the original record; changed content or request/job means `409`.
A review is **not** evidence that the client saved or played a GIF.

The worker reads `WEB_SEARCH_TIMEOUT_SECONDS` (default 60, maximum 300),
`WEB_SEARCH_CALL_TIMEOUT_SECONDS` (default 12, maximum 60),
`WEB_SEARCH_MAX_DOWNLOADS` (default/maximum 6), and
`SAVED_INDEX_TIMEOUT_SECONDS` (default 300, maximum 600). The first two web
limits are also passed to the agent's shared `SearchBudget`; the agent itself
caps rounds at two and results at three. Search-provider credentials and
selection (`SEARCH_AGENT_PROVIDER`, `SEARCH_AGENT_MODE`, and provider-specific
keys) are passed only to the worker in Compose. Avoid logging or returning those
values.

## Verification

Use Python 3.11 and the existing development dependencies:

```powershell
python -m pip install -e ".[dev]"
ruff check .
pytest tests\unit tests\integration -q
```

The development extra installs `httpx2`, used by the Starlette test client.

SQLite tests cover HTTP contracts and worker/media behavior. PostgreSQL tests
require an explicitly supplied local test/admin connection; they create and
drop only randomly named test databases, never the supplied database:

```powershell
$env:TEST_POSTGRES_URL="postgresql+psycopg://postgres:postgres@localhost:5432/maie6000c"
pytest tests\integration\test_search_postgres.py -q
```

CI supplies that connection and verifies migration upgrade/downgrade,
metadata agreement, eight concurrent duplicate submissions, retries, and
reviews, row-lock claims, active-job uniqueness, and cross-job review constraints.

Run the deterministic full search lifecycle integration test with:

```powershell
.venv\Scripts\python.exe -m pytest tests\integration\test_web_search_backend.py::test_web_search_lifecycle_save_index_and_local_reuse -q -W error
```

This test exercises submission, worker processing, candidate delivery,
acceptance, saving, indexing and local reuse with deterministic test doubles.
It validates application and persistence contracts, not live provider
availability or retrieval quality.

For a deployed-stack smoke test, point the test at a running product API:

```powershell
$env:SMOKE_BASE_URL="http://localhost:8000"
.venv\Scripts\python.exe -m pytest tests\smoke\test_smoke_search.py -q
```

The smoke test must reach a successful terminal state; a failed search is a
test failure, not an expected result. The synthetic crop and a single request
do not establish retrieval accuracy or large-scale performance. Evaluate
permitted positive and no-match examples separately. Starter smoke tests
require the `starter` profile.

### Earlier deployed verification

The deployed-stack verification below was completed on 2026-10-27 before the
FastAPI and test-client dependency refresh. It used Python 3.11.9, PostgreSQL
16, and Docker Compose:

- `ruff check .` passed; editor diagnostics reported no errors in the new modules.
- All 46 tests passed: 44 unit/integration tests and two deployed smoke tests.
- Clean container builds and automatic migrations produced a ready API and a
  running search worker; the optional starter case/AI flow also passed.
- Recreating the database/API containers without deleting volumes preserved
  request/job state, a generated two-frame candidate GIF, an acceptance review,
  and submission/review replay behavior.
- Restarting the worker recorded `worker_interrupted` for an abandoned running
  job. Starting a second search worker was rejected by the advisory lock.

The durability exercise injected a ranking result and generated its own GIF;
it verified backend persistence, **not pretrained inference**. The search smoke
test explicitly expected `retrieval_unavailable`. Real corpus retrieval, web
integration, and device saving/playback remain unverified. Dependency
deprecation warnings were present during this historical run. The isolated
verification stack and its test volumes were removed afterward.

### Latest dependency and deployment verification

The following is a historical deployment snapshot and predates the current
successful-search smoke-test requirement:

After the FastAPI/test-client dependency refresh, storage-cleanup regression
tests, and corpus import improvements, `pytest -q -W error` reported **45 passed,
6 skipped**, with no warnings.
Four PostgreSQL tests were skipped when `TEST_POSTGRES_URL` was not set, and
two deployed smoke tests were skipped when `SMOKE_BASE_URL` was not set in the
code-level run. `ruff check .`, `uv pip check`, and `git diff --check` also
passed.

A fresh Docker build was then started with PostgreSQL 16, the API, and the
search worker. The API became ready, the worker started, and the search
deployment smoke test passed with the expected `retrieval_unavailable` result.
With the optional `starter` profile enabled, the AI and starter-worker services
also became healthy/started and both deployment smoke tests passed. All four
PostgreSQL integration tests passed against this disposable stack under
`-W error`, including migration round trips, concurrent idempotency, row-lock
claims, and schema constraints. The disposable Compose stack and its volumes
were removed after verification; the host reference-corpus directory was not
removed.

The PostgreSQL suite also verifies that eight concurrent duplicate reviews
produce one immutable decision.

Search API metrics use FastAPI route templates rather than literal UUID-bearing
URLs; distinct users' job/request IDs therefore do not create unbounded
Prometheus label cardinality.
