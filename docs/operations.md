# Operations notes

The W07 supported local profile runs host Python API and worker processes with Docker PostgreSQL. Follow [the local demo guide](local-demo.md), including PowerShell commands, preparation, and verification. Python 3.11 and Docker Desktop are required; Node.js is needed for browser tests. Model weights, corpus, and index must be prepared before startup. The base application Docker image lacks the optional retrieval dependencies and is not the verified inference deployment.

The runner applies migrations, imports the corpus, creates an ignored random-password environment file, and starts separate API/worker processes. API: `http://127.0.0.1:8000`; web: `/web/`; database: loopback port 55432 in the `memeretrieve-local` Compose project. Stop the runner with Ctrl+C. Stop PostgreSQL without deleting records using:

```text
docker compose -p memeretrieve-local --env-file .cache/local-demo.env stop db
```

`/health/live` checks API liveness; `/health/ready` checks dependencies. Readiness alone does not prove worker progress or successful inference. Check persisted job transitions and `.cache/local-api.log` / `.cache/local-worker.log`, correlated by request/job IDs. Missing models or stale indexes require preparation/reindexing; execution failures should persist a failed job, not synthetic results.

Database data lives in a persistent Docker volume; GIFs, uploads, model cache, and index live in ignored host paths under `data/`. Keep both for restart checks. Volume deletion is destructive and is not a routine stop command. Never commit local environment files or downloaded weights.

See [the backend guide](backend-guide.md) for migrations, API contracts, retention, and PostgreSQL verification. The [starter guide](starter-guide.md) documents the historical case/triage flow and its separate AI service, enabled with the starter Compose profile. Those AI health/metrics endpoints do not describe the W07 in-worker CLIP module.

The [author verification record](local-demo-verification.json) reports live inference and restart persistence; independent reproduction and final team acceptance remain pending. CI fixture tests do not establish live model behavior.
