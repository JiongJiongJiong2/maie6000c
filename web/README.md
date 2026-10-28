# MemeRetrieve W07 web client

Owner: Zirui Huang. Implements the upload, polling, GIF preview, review, download, and integration responsibilities in the [W07 team plan](../docs/week07-plan.md).

## Implementation and current boundary

The client uses native HTML, CSS, and JavaScript. There is no frontend build step, CDN, or runtime npm dependency. FastAPI serves it at **`/web/`** alongside the existing API. The original `/`, `/docs`, health checks, and application routes remain available. The Docker image copies only the five browser assets; all API calls use same-origin paths.

This integration starts from `dev` at `bbd6902` and incorporates `feature/w07-backend` at **`501969f4ee11fb2d03c09c96c8744d3118824a67`**, including that branch's actual routes, persistence models, worker transitions, and GIF validation.

**The local full-stack demo is now available.** It combines the backend with real offline CLIP inference and a 12-GIF Noto reaction collection. Follow [the local demo guide](../docs/local-demo.md), then use the example picker or upload a screenshot. The historical injected-result checks below are retained as isolated backend contract tests; live model and browser evidence is recorded separately in [local-demo-verification.json](../docs/local-demo-verification.json). Final team acceptance and physical iPhone checks remain outstanding.

## Visual direction

The interface uses an original Internet Lost & Found theme: bold lime-and-lilac stickers, a playful SVG mascot, retro window frames, and a candidate lineup. It includes keyboard-accessible mascot interaction and a persistent motion control that respects reduced-motion preferences. Research sources and design choices are documented in [DESIGN.md](DESIGN.md).

## Run

From the repository root, with Python 3.11:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn services.api.app.main:app --host 127.0.0.1 --port 8000
```

For the prepared complete local stack, use `.venv/bin/python scripts/run_local_demo.py` from the repository root instead of launching the API alone. Open `http://127.0.0.1:8000/web/`. A standalone API still requires a configured database, corpus, model/index, and independent worker.

After the backend and retrieval are integrated, configure the database, storage, corpus, and model using the backend's `.env.example`, then use the team's `docker compose up --build` workflow. Visit the same `/web/` URL. Do not open the HTML with `file://` or serve it on another port while expecting relative requests to reach a different API origin.

If the server sets `DEVICE_TOKEN`, open the connection panel at the top right, enter the token, and select **Apply and reconnect**. The token stays in page memory and must be entered again after a reload. Search, review, preview, and download requests all carry `Authorization: Bearer …`. Tokens are not placed in URLs, IndexedDB, source files, or logs.

## Behavior

- Select or drop one cropped PNG, JPEG, or WebP. Before upload, the browser checks decoding, the 10 MiB limit, and the 20-megapixel limit. Server validation remains authoritative.
- Before submission, IndexedDB stores the exact image and a stable `client_submission_key`. **Retry this upload** reuses both after a lost response, including across reloads. Changing the image or starting a new search creates a new key.
- Poll every 1.5 seconds while work is active. Pause further polling when the page is hidden; resume when it becomes visible. Stop automatic polling at completion or failure. Network errors retain the request ID and expose manual refresh; reconnection also triggers a status check.
- Distinguish `pending`, `running`, `completed/candidates`, `completed/no_candidates`, and `failed`. Show up to three animations using the supplied `media_url`, never a server filesystem path. Similarity is not displayed as confidence or probability.
- **This is the one** submits `accept` with the candidate ID. **None of these match** submits `reject_all` with `candidate_id: null`. Persist the review key before sending. An unacknowledged choice must be retried before another choice is made; successful decisions can later be changed through a new review event.
- Enable download for the accepted candidate. Fetch the GIF again, check its signature, and show an actionable error for expired media. Download failure does not erase the review. Starting a browser download does not prove local saving or playback; the user is prompted to open the file and check.
- Restore the current image, request/job IDs, and locally acknowledged review after reload. This is a single current search, not a history library. **Clear local search** removes only browser state, not backend records. Use one active tab at a time.
- Cancel old client requests when changing images so delayed responses cannot overwrite a new search. Closing the page or selecting another image does not cancel backend work.

## API integration

| Endpoint | Client contract |
|---|---|
| `POST /search-requests` | Multipart `image`, `client_submission_key`; accept `202` with request/job UUIDs |
| `GET /search-requests/{request_id}` | Read and validate `status`, `result_kind`, `candidates`, and `error` |
| `GET /candidates/{candidate_id}/media` | Fetch the supplied same-origin `media_url` as a Blob, with the optional token |
| `POST /search-jobs/{job_id}/reviews` | JSON `decision`, `candidate_id`, `client_review_key`; retain `review_id` |
| `GET /health/ready` | API connection indicator; does not establish worker or model readiness |

Handles FastAPI `detail: {code, message}`, string details, validation errors, and non-JSON errors. Error text is rendered with `textContent`. Actual HTTP examples and environment details are recorded in [verification.json](verification.json), using generated test media without user images or credentials.

The client does not call the W04 failed-job retry endpoint. Starting another search creates a new submission key, following the W07 minimum contract. Coordinate endpoint, authentication, and field changes with Haoxuan, updating `api.js`, callers, and tests together.

## Verification

Python regression and static-route checks:

```bash
pytest -q
ruff check .
```

Browser interaction tests require Node.js 20+; npm is only needed for development:

```bash
cd web
npm ci
npx playwright install chromium
npm test -- client.spec.js design.spec.js
npm run format:check
```

With Google Chrome already installed, use `PLAYWRIGHT_CHANNEL=chrome npm test -- client.spec.js design.spec.js`. Tests start a local static server. Network mocks exist only inside tests. Coverage includes multipart fields, polling, authenticated media, lost upload/review responses, reload recovery, no-match versus failure, expired downloads, invalid images, reconnection, stale responses, mobile layout, and safe rendering of error strings.

### Isolated real-backend integration

Prepare a local backend checkout with its own Python environment and dependencies from its `pyproject.toml`. Run the test harness from this web checkout, pointing to that backend:

```bash
# Replace both /path/to/backend paths.
WEB_BACKEND_ROOT=/path/to/backend \
  /path/to/backend/.venv/bin/python web/tests/backend_server.py
```

In another terminal:

```bash
cd web
WEB_BASE_URL=http://127.0.0.1:8766 WEB_BACKEND_TEST=1 \
  PLAYWRIGHT_CHANNEL=chrome npm test -- backend.spec.js
```

The harness binds only to `127.0.0.1:8766`. It creates SQLite, media, and model-cache directories in a disposable system temporary directory and cleans them on exit. It does not use the team's configured database. Its `/__test__/` routes exist only in this test process. **Never use the harness as an application server.** Successful cases replace only retrieval results; uploads, persistence, worker processing, media validation, reviews, and downloads use real backend code. The missing-module case invokes the real worker subprocess and checks `retrieval_unavailable`; adjust this test environment once retrieval is installed.

Verified on 2026-10-28: 11 client browser tests passed; 3 real-backend browser tests passed, including with the backend's pinned FastAPI 0.162.0; 9 Python tests passed and 1 deployed smoke test was skipped because the full stack was not running. Five additional redesign checks passed for keyboard interaction, motion preferences, and three-candidate layouts at 1440, 768, 390, and 320 pixels. All four widths were inspected.

The later local integration verifies PostgreSQL, 12 permitted GIFs, real CLIP inference, independent worker processing, and API/worker restart persistence. Full application-container deployment and physical iPhone playback/saving remain team acceptance work. SQLite and injected-result tests alone do not establish these outcomes.

## Integration handoff

Original web branch: `feature/w07-web`. Local integration branch: `codex/w07-fullstack-demo`. PR target: `dev`. The client lives in `web/`. Supporting changes add `services/api/app/web.py`, register its router in `main.py`, package the browser assets in `Dockerfile`, exclude development artifacts from the build context, and add static-route and browser CI checks. Shared data models, migrations, `compose.yaml`, `.env.example`, and Python dependencies are unchanged.

1. Confirm the contract and token configuration with Haoxuan using the backend SHA above. Keep both search and web routers registered in `main.py`.
2. Integrate YuanJian's real `services.retrieval.search`. Prepare a known match, an out-of-corpus screenshot, and an unavailable-model case.
3. On the latest `dev`, run upload → database → independent worker → real inference → web results → review → download daily. Retain request/job IDs.
4. Verify API/worker restarts, duplicate submissions, invalid input, and multi-frame playback on the actual deployment. Give the observed results and limitations to Jiongle for the W07 submission.

AI use: Codex assisted with implementation, API adaptation, automated tests, and documentation, and ran the checks above. Zirui completed a local browser walkthrough of the integrated application. Final team acceptance remains pending. Generated fixtures and automated checks are not reported as real-model or corpus validation.
