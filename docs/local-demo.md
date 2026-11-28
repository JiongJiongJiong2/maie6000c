# Local end-to-end demo

This local integration connects Zirui's web client, Haoxuan's W07 API and PostgreSQL worker, and a completed CLIP retrieval adapter based on YuanJian's image encoder. It runs real inference over 12 attributed animated reaction GIFs. No mock search responses or test-only routes are used by the application.

## Start

Use Python 3.11, Node.js 20+ for browser tests, and the installed Docker Desktop for PostgreSQL. Start Docker Desktop first. Run these commands from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,retrieval]'
.venv/bin/python scripts/prepare_demo.py
.venv/bin/python scripts/download_model.py
HF_HUB_OFFLINE=1 .venv/bin/python -m services.retrieval.engine index
.venv/bin/python scripts/run_local_demo.py
```

Open **http://127.0.0.1:8000/web/**. The first preparation downloads approximately 600 MB of model weights. Subsequent starts need only the last command. The runner imports the corpus, applies migrations, and starts separate API and worker processes. PostgreSQL runs in the `memeretrieve-local` Compose project on `127.0.0.1:55432`, with its own persistent volume. Existing course starter containers are not reused.

The runner generates an ignored `.cache/local-demo.env` with a random local database password. It configures absolute storage paths and enables the optional example picker. The API binds only to `127.0.0.1:8000`; this local profile does not set a device token. Other deployments retain the backend's optional token authentication. Neither model inference nor upload processing sends screenshots to an external service. Downloads of model weights and public corpus files happen only during preparation.

Stop the API and worker with Ctrl+C in the runner. PostgreSQL and its data remain available. To stop the database without deleting its volume:

```bash
docker compose -p memeretrieve-local --env-file .cache/local-demo.env stop db
```

### Windows PowerShell

Use these equivalents from the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,retrieval]"
.\.venv\Scripts\python.exe scripts/prepare_demo.py
.\.venv\Scripts\python.exe scripts/download_model.py
$env:HF_HUB_OFFLINE = "1"
.\.venv\Scripts\python.exe -m services.retrieval.engine index
.\.venv\Scripts\python.exe scripts/run_local_demo.py
```

For verification, use `.\.venv\Scripts\python.exe -m pytest -q` and `.\.venv\Scripts\python.exe -m ruff check .`. For live browser tests in `web/`, set `$env:WEB_BASE_URL = "http://127.0.0.1:8000"`, `$env:WEB_LIVE_DEMO = "1"`, and `$env:PLAYWRIGHT_CHANNEL = "chrome"` before the same npm command shown below.

## Try the flow

### Windows without Docker

The 2026-10-29 PPT capture used native PostgreSQL 16.15 after Docker Desktop failed to initialize its runtime socket. Download the Windows x64 PostgreSQL 16 binary archive from [EDB](https://www.enterprisedb.com/download-postgresql-binaries) and extract its `pgsql` directory to `.cache/pg16/`. With the same model/corpus preparation above, run:

```powershell
.\.venv\Scripts\python.exe scripts/run_windows_demo.py
```

This starts PostgreSQL on loopback port 55432 with the password in the ignored `.cache/local-demo.env`, applies migrations, imports the corpus, and runs the same API and independent worker. The cluster is stored in `.cache/w07-postgres`; no Windows service is installed. Do not start this profile concurrently with Docker PostgreSQL or another copy of the API/worker. Ctrl+C stops API/worker while retaining the database. Stop the database without deleting records using `python scripts/run_windows_demo.py --stop-database` from the prepared virtual environment. Treat `.cache/w07-postgres` as persistent demo data despite its location in `.cache`; retain it for restart checks. The binary archive is a local dependency and must not be committed.

### Browser walkthrough

1. Scroll to **Okay, show us the evidence.**
2. Upload a PNG/JPEG/WebP crop, or expand **No screenshot? Borrow some evidence.** and choose an example. Choosing a library example selects **Local only** and loads a frame from its original GIF as a regular PNG upload. You can still switch search modes before submitting.
3. Click **Find my GIF**. The API persists the input and a pending job. The independent worker claims it, performs local CLIP inference, and stores the ranked candidates.
4. Click **This is the one** to save your choice, then **Download GIF**. The download contains the original multi-frame animation.
5. Refresh to restore the current browser search. **Start a new search** allows another upload; **None of these match** stores a rejection.

The default reference collection has 12 Noto GIFs. Standalone example frames for those files are in `data/reference/examples/`. A prepared local course benchmark can also supply four Chinese meme examples for this page.

### Use the four examples from the local benchmark

With the [Chinese evaluation corpus](retrieval-benchmark-at-scale.md) already present, run the following from the repository root before starting the demo. The preparation step verifies each selected original against its frozen SHA-256. The normal demo launcher imports the resulting manifest into its database at startup.

```powershell
.\.venv\Scripts\python.exe scripts/prepare_demo.py --evaluation-library .cache/meme-eval-cn
.\.venv\Scripts\python.exe -m services.retrieval.engine index
.\.venv\Scripts\python.exe scripts/run_windows_demo.py
```

The local picker will show 哈吉米接电话、奶龙、肥嘟嘟在雪地摇摆 and 回来把代码写完 ahead of the existing examples. This 16-GIF demo index contains 124 frame vectors. The larger quantitative benchmark uses its own indexes. The example media stay in the local course installation. The checked-in [selection](demo-evaluation-examples.json) identifies the source and use conditions for each asset.

All four example PNGs went through the local API and worker. In each case the first-ranked download matched the benchmark GIF byte for byte. The [acceptance record](evidence/home-example-retrieval-20261128.json) includes the query hash, download hash and decoded frame count.

## Retrieval and provenance

- Model: [CLIP ViT-B/32](https://huggingface.co/openai/clip-vit-base-patch32), pinned to revision `37000f5cdccec47a3f6f83142bff131370757470`, loaded from safetensors. Inference uses CPU and the [Transformers CLIP image-feature API](https://huggingface.co/docs/transformers/model_doc/clip).
- Corpus: [Google Noto Animated Emoji](https://googlefonts.github.io/noto-emoji-animation/), by Google, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Google's [announcement](https://developers.googleblog.com/en/updates-to-emoji-new-characters-new-animation-new-color-customization-and-more/) identifies this license for the animations. Original downloaded GIF bytes are unchanged. The example PNGs are extracted frames composited on white.
- The committed [source catalog](demo-corpus.json) contains titles, source URLs, and SHA-256 checksums. Preparation rejects upstream content changes. UUIDs are derived from source URLs and used consistently by the manifest, index, and database.
- Eight evenly spaced frames per GIF produce 96 normalized CLIP vectors. Each query receives a fresh embedding; the best frame score ranks each distinct GIF. Up to three candidates at or above cosine similarity `0.82` are returned. Set `RETRIEVAL_MIN_SIMILARITY` before starting the runner to change this experimental threshold. It is not a calibrated probability or a guarantee that unrelated images are rejected.
- The index records model and corpus versions plus the manifest checksum. Stale indexes are rejected and must be rebuilt. Runtime inference uses local files only.

The 12 example queries are an in-corpus functionality check, not an independent accuracy benchmark. They are derived from the same animations as the index. General meme retrieval, unseen screenshot robustness, and a larger corpus still need team evaluation.

## Verification and troubleshooting

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/python scripts/verify_local_demo.py
cd web
npm ci
WEB_BASE_URL=http://127.0.0.1:8000 WEB_LIVE_DEMO=1 PLAYWRIGHT_CHANNEL=chrome \
  npm test -- client.spec.js design.spec.js live.spec.js
```

The live browser tests upload a real screenshot, wait for actual inference, save and restore a review, and compare the downloaded file's SHA-256 with the source GIF. They also exercise the example picker and rejection. The normal client tests use isolated network fixtures for error and recovery coverage. See [the author verification record](local-demo-verification.json) for reported results and limitations. This record has not yet been independently reproduced during integration; its counts are distinct from CI. Prior PR #3 Actions reported Python 60 passed / 1 skipped and 16 browser checks. Fresh integration results belong in the W07 submission.

Logs are in `.cache/local-api.log` and `.cache/local-worker.log`. They include request/job IDs. Model weights, reference GIFs, uploads, and the index live under ignored `data/` paths. Database records live in the Docker volume. These survive API/worker restarts. If port 8000 is occupied, stop the earlier preview server before running the complete demo. If an index or model is unavailable, rerun the preparation steps; the worker reports an explicit failed job instead of fabricating candidates.

The author-reported deployment uses host Python processes plus containerized PostgreSQL. Running all services inside application containers, general deployment hardening, physical iPhone saving, and final team acceptance are separate checks. The base Dockerfile does not install the optional retrieval extra; a fully containerized worker requires that extra and the prepared model/index mounts.

## Integration scope

Backend baseline: `origin/feature/w07-backend` at `501969f4ee11fb2d03c09c96c8744d3118824a67`. Encoder baseline: `origin/feature/w07-retrieval` at `37ba4d2`. The full integration is prepared on `codex/w07-fullstack-demo` for review into `dev`. The backend and encoder commits retain their original authorship. This work does not publish a course submission or milestone tag.

AI use: Codex integrated the existing modules, implemented missing local retrieval/index preparation and example controls, and ran the recorded checks. Zirui completed a local browser walkthrough before publication. Final team acceptance and code review remain pending.
`codex/w07-integration` retains the #3 engine/index contract and adapts validation coverage informed by YuanJian's #4 prototype. The separate CSV/index format in #4 is not an active runtime path. Fresh CPU inference evidence is in [the integration record](w07-integration-verification.json); the full live database flow still needs reproduction on a working Docker host.
