# Week 7 — Midterm milestone demo

Team: Memeory. Members: Jiongle He, Haoxuan Jiang, YuanJian Li, Zirui Huang. Repository: https://github.com/JiongJiongJiong2/maie6000c. The 2026-10-29 evidence was captured from dev baseline `c9f2922c149044efeb8eb0d0afa72539a408a109` plus the worker log timezone correction and native PostgreSQL launcher included in this checkpoint. Resolve the `w07-midterm` tag to identify the submitted commit. Team members should review the final submission.

**PPT materials:** [visual gallery](assets/index.html), [Chinese slide guide with English captions](PPT素材说明.txt), and [run summary](assets/run-summary.json). The PNGs and original animated GIF are under `assets/`.

## 1. What currently works

The integrated browser slice accepts a cropped screenshot, persists a request/job in PostgreSQL, performs asynchronous local CLIP retrieval through an independent worker, displays up to three animated candidates, stores acceptance or rejection, and downloads original GIF bytes. The searchable collection is 12 attributed Google Noto Animated Emoji GIFs.

## 2. Live demo sequence

Start [the local profile](../../docs/local-demo.md), open `/web/`, upload a crop or choose an extracted example, and show pending/running/completed state plus correlated worker logs. Preview candidates, accept one, download and inspect animation, then refresh to restore state. Demonstrate rejection and an explicit failure/no-candidate case separately. Verify persisted results after an API/worker restart.

## 3. Implementation status

Implemented and reproduced locally: web upload/polling/review/download, durable API/database paths, independent worker retrieval, corpus preparation, and pinned model/index. Fresh real-browser evidence shows pending, running and completed states, three persisted candidates, one accepted review, an original 83-frame GIF download with a matching SHA-256, and browser refresh restoration. A separate captured request retained identical results after restarting the API and worker. Team acceptance remains pending. Native iOS inbox/save, automatic cropping, external search, and WeChat export are not implemented in this W07 slice.

## 4. Architecture status

Compared with W04, W07 uses a browser client and 12-GIF demonstration corpus instead of the planned native client and 50–100-GIF collection. Host Python runs FastAPI and a separate worker. The original profile uses Docker PostgreSQL 16; this capture used native PostgreSQL 16.15 because Docker Desktop could not start. CLIP runs through the worker retrieval module, not a separate AI HTTP service. See [architecture](../../docs/architecture.md) and the [current flow diagram](assets/10-w07-system-flow.png).

## 5. Integration evidence

`POST /search-requests` stores input and commits request/job records; `GET /search-requests/{request_id}` exposes state/results. The worker persists ranked candidates from real local CLIP inference; `POST /search-jobs/{job_id}/reviews` stores decisions and candidate media endpoints return GIFs. API readiness and job-correlated logs provide operational signals. The model revision is `37000f5cdccec47a3f6f83142bff131370757470`; corpus provenance and checksums are in [the catalog](../../docs/demo-corpus.json).

## 6. Testing and verification

Prior PR #3 Actions reported Python 60 passed / 1 skipped and 16 web checks. The [author-reported local evidence](../../docs/local-demo-verification.json), dated 2026-10-28, records real inference, original multi-frame GIF download/hash, idempotent replay, review persistence, restart persistence, and in-corpus examples. Its local counts are separate from Actions and have not yet been independently reproduced during this integration. Fresh integration checks on 2026-10-29: 70 Python tests passed, with 4 PostgreSQL-specific tests skipped locally; all 14 retrieval unit cases executed. Ruff, web formatting, and 16 Chrome browser fixture tests passed. Real CPU CLIP rebuilt the 12-GIF/96-frame index, ranked all 12 extracted queries correctly at Top-1, and returned no candidates for a white image; see [integration evidence](../../docs/w07-integration-verification.json). Local Docker Desktop crashed during startup with a dockerInference socket error, so the complete PostgreSQL/API/worker live flow and restart check still require reproduction on a working Docker host. Example frames come from indexed animations and are a functionality check, not an independent accuracy benchmark.

## 7. Risks and revised scope

The later live capture resolves the earlier full-flow reproduction gap described above using native PostgreSQL. [Browser responses](assets/browser-evidence.json), [database rows](assets/database-records.json), [worker logs](assets/worker-log.txt), and [restart evidence for a separate request](assets/earlier-request-restart-check.json) preserve the observations. The main capture request is `dbe3a8aa-b060-4c2c-a57b-b763dc5f68db`; job `852892f8-4f68-4e3b-b4c8-1406457210ea`. Worker execution took 20.497452 seconds in this one run, not a performance benchmark. A non-UTC PostgreSQL session exposed incorrect log-duration timezone handling; the local correction passed four focused regression cases and the recaptured worker log reports a positive duration. Earlier raw verification records remain historical.

The largest risk is reproducibility of weights, corpus preparation, and CPU inference on the demo machine. The deliberate scope cut is browser upload/review/download with a small permitted corpus. Physical iPhone saving and arbitrary internet meme recovery remain unverified. The 0.82 similarity threshold is experimental and does not guarantee rejection of unrelated inputs. Fully containerized inference and production deployment hardening remain separate work.

## 8. Week 7 to Week 13

First review the captured live flow, agree team acceptance, and finalize the PPT and repository checkpoint. Then expand the permitted corpus and evaluate held-out screenshots and out-of-corpus failures; improve ranking from measured errors. Validate native/device collection and saving feasibility before adding automation or external-source integrations. Preserve persistence, real inference, review, and playable output while controlling scope.

## 9. Artifact index

[Architecture](../../docs/architecture.md), [operations](../../docs/operations.md), [local demo and commands](../../docs/local-demo.md), [prior author verification record](../../docs/local-demo-verification.json), [W07 plan](../../docs/week07-plan.md), and [historical W04 submission](../week04/README.md). Current screenshots, raw evidence, attribution and an editable flowchart are in [assets](assets/index.html). The [slide guide](PPT素材说明.txt) maps these assets to the instructor's required evidence. The PowerPoint is submitted separately and identifies the tagged checkpoint.

### Reproduce the captured Windows profile

Prepare the dependencies, corpus and model as described in the local demo guide. Extract the [EDB PostgreSQL 16 Windows binaries](https://www.enterprisedb.com/download-postgresql-binaries) into `.cache/pg16/`, then run `scripts/run_windows_demo.py` using the repository's Python 3.11 virtual environment. Open `http://127.0.0.1:8000/web/` and upload `data/reference/examples/1f92f.png`. The startup script creates a dedicated local PostgreSQL cluster, applies migrations and imports the corpus. With the services running, `node scripts/capture_w07_browser.mjs` regenerates the browser evidence (requires `npm ci` in `web/` and Chrome), and `python scripts/export_w07_evidence.py` exports the matching records and logs. Run from the repository root with the prepared virtual environment. Preserve the original capture before regenerating it. Screenshots and evidence boards are a static record of the stated run.

## 10. AI Use Statement

Codex assisted with integrating team backend, encoder, and web work; retrieval/index and local preparation code; tests; documentation; real-browser evidence capture; the native PostgreSQL launcher; and the worker-duration timezone correction. Existing component authorship is retained. Prior author checks are recorded separately from new integration checks and this live capture. Team members must review generated changes and evidence, reproduce the demo, and accept or revise claims before final main/tag/Canvas submission. AI-assisted verification does not replace team acceptance or independent retrieval evaluation.
