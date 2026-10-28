# Week 7 — Midterm milestone demo

Team: Memeory. Members: Jiongle He, Haoxuan Jiang, YuanJian Li, Zirui Huang. Repository: https://github.com/JiongJiongJiong2/maie6000c. Integration is prepared for dev review; final team acceptance is pending. `w07-midterm` has not been created. Merge to main, checkpoint SHA/tag, and Canvas submission follow acceptance.

## 1. What currently works

The integrated browser slice accepts a cropped screenshot, persists a request/job in PostgreSQL, performs asynchronous local CLIP retrieval through an independent worker, displays up to three animated candidates, stores acceptance or rejection, and downloads original GIF bytes. The searchable collection is 12 attributed Google Noto Animated Emoji GIFs.

## 2. Live demo sequence

Start [the local profile](../../docs/local-demo.md), open `/web/`, upload a crop or choose an extracted example, and show pending/running/completed state plus correlated worker logs. Preview candidates, accept one, download and inspect animation, then refresh to restore state. Demonstrate rejection and an explicit failure/no-candidate case separately. Verify persisted results after an API/worker restart.

## 3. Implementation status

Implemented in the integrated code: web upload/polling/review/download, durable API/database paths, worker retrieval adapter, corpus preparation, pinned model/index, and explicit failure handling. Independent live reproduction and team acceptance remain pending. Native iOS inbox/save, automatic cropping, external search, and WeChat export are not implemented in this W07 slice.

## 4. Architecture status

Compared with W04, W07 uses a browser client and 12-GIF demonstration corpus instead of the planned native client and 50–100-GIF collection. Host Python runs FastAPI and a separate worker; Docker runs PostgreSQL 16. CLIP runs inside the worker retrieval module, not a separate AI HTTP service. See [architecture](../../docs/architecture.md).

## 5. Integration evidence

`POST /search-requests` stores input and commits request/job records; `GET /search-requests/{request_id}` exposes state/results. The worker persists ranked candidates from real local CLIP inference; `POST /search-jobs/{job_id}/reviews` stores decisions and candidate media endpoints return GIFs. API readiness and job-correlated logs provide operational signals. The model revision is `37000f5cdccec47a3f6f83142bff131370757470`; corpus provenance and checksums are in [the catalog](../../docs/demo-corpus.json).

## 6. Testing and verification

Prior PR #3 Actions reported Python 60 passed / 1 skipped and 16 web checks. The [author-reported local evidence](../../docs/local-demo-verification.json), dated 2026-10-28, records real inference, original multi-frame GIF download/hash, idempotent replay, review persistence, restart persistence, and in-corpus examples. Its local counts are separate from Actions and have not yet been independently reproduced during this integration. Fresh integration checks on 2026-10-29: 70 Python tests passed, with 4 PostgreSQL-specific tests skipped locally; all 14 retrieval unit cases executed. Ruff, web formatting, and 16 Chrome browser fixture tests passed. Real CPU CLIP rebuilt the 12-GIF/96-frame index, ranked all 12 extracted queries correctly at Top-1, and returned no candidates for a white image; see [integration evidence](../../docs/w07-integration-verification.json). Local Docker Desktop crashed during startup with a dockerInference socket error, so the complete PostgreSQL/API/worker live flow and restart check still require reproduction on a working Docker host. Example frames come from indexed animations and are a functionality check, not an independent accuracy benchmark.

## 7. Risks and revised scope

The largest risk is reproducibility of weights, corpus preparation, and CPU inference on the demo machine. The deliberate scope cut is browser upload/review/download with a small permitted corpus. Physical iPhone saving and arbitrary internet meme recovery remain unverified. The 0.82 similarity threshold is experimental and does not guarantee rejection of unrelated inputs. Fully containerized inference and production deployment hardening remain separate work.

## 8. Week 7 to Week 13

First reproduce the complete live flow and agree team acceptance. Then expand the permitted corpus and evaluate held-out screenshots and out-of-corpus failures; improve ranking from measured errors. Validate native/device collection and saving feasibility before adding automation or external-source integrations. Preserve persistence, real inference, review, and playable output while controlling scope.

## 9. Artifact index

[Architecture](../../docs/architecture.md), [operations](../../docs/operations.md), [local demo and commands](../../docs/local-demo.md), [verification record](../../docs/local-demo-verification.json), [W07 plan](../../docs/week07-plan.md), and [historical W04 submission](../week04/README.md). Final slides/screenshots and accepted checkpoint SHA are pending team preparation.

## 10. AI Use Statement

Codex assisted with integrating team backend, encoder, and web work; retrieval/index and local preparation code; tests; and documentation. Existing component authorship is retained. Prior author checks are recorded separately from new integration checks. Team members must review generated changes, reproduce the demo, and accept or revise claims before final main/tag/Canvas submission. AI-assisted implementation and an author walkthrough do not replace team acceptance or independent retrieval evaluation.

