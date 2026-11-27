# Operations notes

For the current web application, open `/web/`. The **Local only** mode uses the reference library and the current account’s ready saved assets. **Continue online** sends the screenshot to the selected vision provider and searches via DeepSeek. The default vision service is HKUST; HKGAI is available through an explicit policy. The public media fetcher processes external sources separately. See [provider configuration](hkust-deepseek-execution.md), [database and storage lifecycle](database-and-vector-search.md), and [the W13 demo](../submissions/week13/README.md).

The Windows native launcher starts PostgreSQL, API, worker, and the media fetcher. The fetcher binds to loopback port 8120 and receives only the host process variables it needs. The Docker-based local launcher also exposes its isolated fetch service on loopback. For an account-based demo, enable both `ACCOUNT_LOGIN_ENABLED` and `PRIVATE_LIBRARY_ENABLED`. For resolver environments that return non-public addresses for public media sites, `MEME50_DNS_MODE=doh` uses the supported public DNS resolution mode with peer and TLS verification. The default system resolver remains available.

The W07 supported local profile runs host Python API and worker processes with Docker PostgreSQL. Follow [the local demo guide](local-demo.md), including PowerShell commands, preparation, and verification. Python 3.11 and Docker Desktop are required; Node.js is needed for browser tests. Model weights, corpus, and index must be prepared before startup. The base application Docker image lacks the optional retrieval dependencies and is not the verified inference deployment.

The runner applies migrations, imports the corpus, creates an ignored random-password environment file, and starts separate API/worker processes. API: `http://127.0.0.1:8000`; web: `/web/`; database: loopback port 55432 in the `memeretrieve-local` Compose project. Stop the runner with Ctrl+C. Stop PostgreSQL without deleting records using:

```text
docker compose -p memeretrieve-local --env-file .cache/local-demo.env stop db
```

`/health/live` checks API liveness; `/health/ready` checks dependencies. Readiness alone does not prove worker progress or successful inference. Check persisted job transitions and `.cache/local-api.log` / `.cache/local-worker.log`, correlated by request/job IDs. Missing models or stale indexes require preparation/reindexing; execution failures should persist a failed job, not synthetic results.

Database data lives in a persistent Docker volume; GIFs, uploads, model cache, and index live in ignored host paths under `data/`. Keep both for restart checks. Volume deletion is destructive and is not a routine stop command. Never commit local environment files or downloaded weights.

See [the backend guide](backend-guide.md) for migrations, API contracts, retention, and PostgreSQL verification. The [starter guide](starter-guide.md) documents the historical case/triage flow and its separate AI service, enabled with the starter Compose profile. Those AI health/metrics endpoints do not describe the W07 in-worker CLIP module.

When Docker Desktop is unavailable on Windows, the [native PostgreSQL profile](local-demo.md#windows-without-docker) runs the same API and worker using `scripts/run_windows_demo.py`. It keeps its cluster at `.cache/w07-postgres`, binds to loopback port 55432, and uses the existing ignored environment file. Retain this directory as persistent data. Use `--stop-database` for a non-destructive database shutdown. Avoid concurrent launchers or another database on the same port.

The [fresh W07 evidence](../submissions/week07/assets/run-summary.json) records real browser upload, persisted candidates/review, original GIF download and health. The separate [restart check](../submissions/week07/assets/earlier-request-restart-check.json) records an unchanged result after API/worker restart. This native PostgreSQL run is distinct from the [prior author verification record](local-demo-verification.json). Final team acceptance remains pending. CI fixture tests do not establish live model behavior.
