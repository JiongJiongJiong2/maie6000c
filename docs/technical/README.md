# Technical documentation

[简体中文](README.zh-CN.md) · [Product overview](../product/README.md) · [Usage and deployment](../guides/README.md)

MemeRetrieve accepts a screenshot and returns candidate GIFs that can be reviewed, saved and downloaded. To trace a failing lookup, start with its `request_id`. Each local search, online continuation or retry has a separate `job_id`. A saved original has a durable `asset_id` and its own index status.

## Runtime and ownership

| Component | What it owns | Implementation |
| --- | --- | --- |
| Web client and FastAPI | The API serves the client at `/web/`, validates uploads, commits jobs, handles sessions and serves verified media. The browser polls the API and displays search progress. | [Web client](../../web), [API](../../services/api/app) |
| Search worker | Claims persistent jobs from PostgreSQL. Local jobs run the pinned CLIP encoder and rank frames. Online jobs run the search agent. Imports and saves create separate index work. | [Queue and index lifecycle](../../services/worker/app/search_worker.py), [local retrieval](../../services/retrieval/engine.py) |
| Agent and public media fetcher | The configured HKUST or HKGAI vision service describes the image. DeepSeek plans queries and searches the web. The isolated fetcher retrieves public pages and media. The worker decodes candidates, groups duplicates, ranks and publishes final results. | [Agent pipeline](../../services/search_agent/meme_pipeline.py), [fetch service](../../services/retrieval/public_fetch.py) |
| PostgreSQL, pgvector and volumes | PostgreSQL stores requests, reviews, accounts, asset IDs and index versions. pgvector mirrors image frames for exact search. Media and model volumes retain original files and NPZ indexes. | [Database and vector design](database-and-vector-search.md), [Compose configuration](../../compose.pgvector.yaml) |

When accounts are enabled, a server-side session selects the private workspace. A new account gets its own PostgreSQL schema and media directory. Only the reference files and model weights are shared. `BETA_INVITE_CODE` gates registration when configured. The rehearsal enables accounts and the private library, binds the API to loopback and sets `ONLINE_SEARCH_ENABLED=false` in both the API and worker. This disables external searches and AI annotations while preserving local retrieval. [Account implementation](../../services/api/app/accounts.py) · [Rehearsal configuration](../../compose.public-beta.yaml)

## Follow one request

| Step | HTTP contract |
| --- | --- |
| Submit or continue | `POST /search-requests` accepts the image and client submission key and returns `202` after persistence. The `legacy` profile starts local retrieval. The `meme50-v2` profile starts online retrieval when enabled. From a local result, `POST /search-requests/{request_id}/web-search` creates a linked job. |
| Inspect progress | `GET /search-requests/{request_id}` exposes the request and its jobs. `GET /search-jobs/{job_id}` includes stage, verified count and available execution details. **Search activity** uses recorded search activity and counters. A completed job can legitimately have zero candidates. |
| Page and review | `GET /search-jobs/{job_id}/results` serves published results. Carry the revision, filter and page size when using the next cursor. `POST /search-jobs/{job_id}/reviews` records the user's decision. |
| Persist and download | `POST /candidates/{candidate_id}/save` saves an accepted animated web candidate and schedules indexing. `GET /saved-assets/{asset_id}` exposes index status and `GET /saved-assets/{asset_id}/media` returns the verified GIF bytes. A failed index can be retried using `POST /saved-assets/{asset_id}/index-retry`. |

Retry an interrupted client operation with its original idempotency key and identical payload. An HTTP `409` can indicate a key conflict or an active attempt. Keep the original job ID when diagnosing a failed attempt. The database permits one active attempt per request. [Search and save routes](../../services/api/app/search.py) · [Job and pagination routes](../../services/api/app/meme_search.py) · [Backend development guide](../backend-guide.md)

## Diagnose retrieval

For a missing local result, check the signed-in workspace, the saved asset's `index_status`, the reference manifest and the model revision. The query is compared against up to eight 512-dimensional image frames per GIF. Each item's best frame score determines its rank. Results must pass the configured similarity threshold (default `0.82`) and at most three distinct assets are returned. Inspect `vector_backend` and `reference_vector_backend` in the job's worker log to see whether the private and shared catalogs used PostgreSQL or NPZ. [Frame sampling, fallback and migration](database-and-vector-search.md)

For a slow online search, correlate the job's stage, model and search call counts, media download attempts, duration, warnings and stop reason. The worker bounds external work per job. A failed or partial search can point to an unavailable provider, an unreachable media source, unsuitable candidates or an exhausted budget. The dedicated local rehearsal rejects online requests with `403 online_search_disabled`. [Job summary](../../services/api/app/meme_search.py) · [Provider configuration](../guides/online-search.md) · [Recorded searches and misses](../evidence/gif-acquisition/hkgai-web-offline-20261128.json)

## Develop and verify

Use Python 3.11 from the repository root. The integration suite uses SQLite for fast checks. Set `TEST_POSTGRES_URL` to a dedicated PostgreSQL test/admin connection with database creation privileges for the PostgreSQL tests, which create and remove temporary databases. CI runs the suite against plain PostgreSQL 16 and pgvector-enabled PostgreSQL 16. [Python CI](../../.github/workflows/ci.yml)

```shell
python -m pip install -e ".[dev,search]"
python -m ruff check .
python -m pytest -q -m "not smoke and not live"
```

For the browser suite, use Node.js 20 with Python available on the path. These commands match the web CI cases. For a regression involving a real application server, also run the backend browser tests and their setup described in the web guide. [Web CI](../../.github/workflows/web.yml) · [Browser test setup](../../web/README.md)

```shell
cd web
npm ci
npx playwright install chromium
npm run format:check
npm test -- client.spec.js design.spec.js meme50.spec.js mobile-compat.spec.js
```

Container CI builds and smoke-tests the API, worker and fetch images. On `main`, the release workflow publishes the tested images to GHCR after the required checks for that commit. To diagnose a running installation, check API liveness at `/health/live`, database and storage readiness at `/health/ready`, then follow a job through completion to test the worker and its model. [Release workflow](../../.github/workflows/container-release.yml) · [Deployment guides](../guides/README.md)

## Verification and performance limits

| Evidence | Result and scope |
| --- | --- |
| [Licensed reference catalog](../../submissions/week13/local-corpus-evaluation.json) | Across 12 screenshots derived from the 12 reference GIFs, first-frame retrieval placed 11 targets in the top three and multi-frame retrieval placed 12. Independent user screenshots and larger collections still require evaluation. |
| [Online browser run](../../submissions/week13/browser-release-verification.json) | With a known source clue, the web interface recovered the 44-frame Earth GIF. After a save and offline restart, a different frame retrieved the same original. The downloads matched the independent reference byte for byte. |
| [Database migration](../../submissions/week13/pgvector-verification.json) | The restored old account kept its asset ID and original hash. The saved-frame mirror and an intentionally incomplete mirror both returned the target through their respective pgvector and NPZ paths. The shared reference catalog mirrored 96 frames. |
| [Invite-only rehearsal](../../submissions/week13/public-beta-rehearsal.json) | Chrome retrieved the same saved asset at rank one before and after API/worker recreation, using frames 13 and 29. Each download contained the same 1,001,718 bytes. This run exercised the loopback installation. |

Exact vector ranking grows with the number of eligible frames. Model startup, queue delay and original-file checks can dominate the observed time. Per-account latency targets, public availability and real-user recovery rates need their own measurements. [Capacity benchmark proposal](database-and-vector-search.md#size-and-performance)
