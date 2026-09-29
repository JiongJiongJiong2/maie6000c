# W03 Individual Readiness Lab

## What I changed

- Added `GET /cases/{case_id}/jobs` in `services/api/app/main.py`:
  - helper `list_jobs_for_case()` queries `jobs` by `case_id`, ordered by `created_at ASC`;
  - endpoint returns `list[JobRead]`, `404` when the case does not exist.
- Added `test_read_jobs_for_case` in `tests/integration/test_api_case_flow.py`:
  - creates a case, asserts `GET /cases/{id}/jobs` returns the 1 linked job;
  - asserts `GET /cases/does-not-exist/jobs` returns `404`.
- No DB migration needed (read-only query on existing `jobs` table).

## How to run

```bash
cp .env.example .env
docker compose up --build -d
curl http://localhost:8000/health/ready
```

Local tests (conda env `maie6000c-w03`, Python 3.11):

```bash
conda run -n maie6000c-w03 ruff check .
conda run -n maie6000c-w03 pytest -q tests/unit tests/integration
$env:SMOKE_BASE_URL="http://localhost:8000"
conda run -n maie6000c-w03 pytest tests/smoke -q
```

## How I verified it

- `ruff check .` → All checks passed.
- `pytest -q tests/unit tests/integration` → 5 passed (baseline was 4, +1 new test).
- `pytest tests/smoke -q` against running stack → 1 passed (end-to-end `triaged` flow still works).
- Manual Docker check:
  - `POST /cases` → 201, got `case_id`;
  - `GET /cases/{id}/jobs` → 200, 1 job with matching `case_id`;
  - `GET /cases/does-not-exist/jobs` → 404;
  - `GET /health/ready` → `{"service":"api","status":"ok"}`.

## AI Use Statement

- Tool: Muse Spark (via OpenCode).
- Used for: scaffolding the new endpoint/helper, drafting the integration test, and drafting this README.
- What I verified/changed/rejected: I kept the change minimal (no schema change), ran ruff + unit/integration + smoke + manual curl myself, and rejected a schema-field alternative to avoid migration risk for W03.
