"""Export database rows, runtime signals and original GIF verification for W07."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess

import httpx
from PIL import Image
from sqlalchemy import create_engine, text

from run_local_demo import ROOT, local_environment

OUT = ROOT / "submissions/week07/assets"


def main():
    os.environ.update(local_environment())
    browser = json.loads((OUT / "browser-evidence.json").read_text())
    ids = browser["accepted"]
    engine = create_engine(os.environ["DATABASE_URL"])
    queries = {
        "request": "SELECT * FROM search_requests WHERE id = :request_id",
        "job": "SELECT * FROM search_jobs WHERE id = :job_id",
        "candidates": "SELECT * FROM candidates WHERE job_id = :job_id ORDER BY rank",
        "reviews": "SELECT * FROM review_decisions WHERE job_id = :job_id ORDER BY created_at",
    }
    with engine.connect() as connection:
        database = {name: [dict(row) for row in connection.execute(text(sql), ids).mappings()]
                    for name, sql in queries.items()}
        version = connection.scalar(text("SELECT version()"))
    assert database["job"][0]["status"] == "completed"
    assert database["reviews"][0]["decision"] == "accept"
    (OUT / "database-records.json").write_text(
        json.dumps(database, default=str, indent=2) + "\n", encoding="utf-8")
    (OUT / "database-queries.sql").write_text(
        "-- Named parameters identify the captured browser request and job.\n" +
        "\n\n".join(f"-- {name}\n{sql};" for name, sql in queries.items()) + "\n")
    worker_lines = [line for line in (ROOT / ".cache/local-worker.log").read_text().splitlines()
                    if ids["job_id"] in line or "search_worker_started" in line]
    (OUT / "worker-log.txt").write_text("\n".join(worker_lines) + "\n", encoding="utf-8")
    api_lines = [line for line in (ROOT / ".cache/local-api.log").read_text().splitlines()
                 if ids["request_id"] in line or ids["job_id"] in line]
    (OUT / "api-log.txt").write_text("\n".join(api_lines) + "\n", encoding="utf-8")
    with httpx.Client(base_url="http://127.0.0.1:8000", trust_env=False) as client:
        health = client.get("/health/ready")
        health.raise_for_status()
        result = client.get(f"/search-requests/{ids['request_id']}")
        result.raise_for_status()
        (OUT / "persisted-result.json").write_text(json.dumps(result.json(), indent=2) + "\n")
        metrics = client.get("/metrics")
        metrics.raise_for_status()
        (OUT / "api-metrics.txt").write_text(metrics.text)
    with Image.open(OUT / "05-downloaded-original.gif") as gif:
        frames, dimensions = gif.n_frames, gif.size
    job = database["job"][0]
    request = database["request"][0]
    stored_input = ROOT / "data/media" / request["input_path"]
    assert hashlib.sha256(stored_input.read_bytes()).hexdigest() == request["input_sha256"]
    for candidate in database["candidates"]:
        assert (ROOT / "data/media" / candidate["local_cache_path"]).is_file()
    summary = {
        "captured_at_utc": browser["captured_at"],
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                 cwd=ROOT, text=True).strip(),
        "branch": "dev", "checkpoint_tag": "not created", "database_version": version,
        "working_tree_note": (
            "Includes local native PostgreSQL launcher and worker log timezone fix."
        ),
        "worker_source_sha256": hashlib.sha256(
            (ROOT / "services/worker/app/search_worker.py").read_bytes()).hexdigest(),
        "runtime": "Windows host Python API + independent worker + native PostgreSQL",
        "request_id": ids["request_id"], "job_id": ids["job_id"],
        "review_id": browser["review"]["review_id"],
        "observed_states": list(dict.fromkeys(
            r["body"]["status"] for r in browser["responses"]
            if isinstance(r["body"], dict) and "request_id" in r["body"])),
        "input_sha256_verified": True, "persisted_candidates": len(database["candidates"]),
        "persisted_reviews": len(database["reviews"]),
        "worker_seconds": (job["finished_at"] - job["started_at"]).total_seconds(),
        "model_version": job["model_version"], "corpus_version": job["corpus_version"],
        "gif_frames": frames, "gif_dimensions": dimensions,
        "download_sha256": browser["download_sha256"],
        "download_matches_original": browser["download_sha256"] == browser["original_sha256"],
        "health": {"http_status": health.status_code, "body": health.json()},
        "browser_refresh": browser["browser_refresh"],
        "limitations": "One in-corpus example, not an independent accuracy benchmark. "
                       "Docker startup remains unavailable; native PostgreSQL was used. "
                       "Main/tag/Canvas and team acceptance are pending.",
    }
    (OUT / "run-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
