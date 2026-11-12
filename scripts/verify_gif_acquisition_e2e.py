"""Explicit real HTTP + read-only PostgreSQL acceptance; no injected searchers."""

import argparse
import json
import os
import time
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select, func

from services.common.db import make_engine, make_session_factory
from services.common.search_models import (
    Candidate,
    SearchExecution,
    SearchJob,
    ReferenceAsset,
    SavedAsset,
)
from services.common.storage import sha256, validate_image


def wait_job(client, request_id, job_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/search-requests/{request_id}")
        response.raise_for_status()
        state = response.json()
        jobs = state["web_searches"]
        job = next((j for j in jobs if j["job_id"] == job_id), None)
        if job is None and state["local_job_id"] == job_id:
            job = state
        if job and job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.5)
    raise TimeoutError("API job did not reach a terminal state")


def run(args):
    if not args.image.is_file():
        raise ValueError("Input screenshot must exist")
    args.out.mkdir(parents=True, exist_ok=False)
    token = os.environ.get("DEVICE_TOKEN", "")
    headers = {"Authorization": "Bearer " + token} if token else {}
    record = dict(
        executed_at=datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        code_baseline=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        implementation_sha256=sha256(
            b"".join(
                str(p).encode() + b"\0" + p.read_bytes()
                for p in sorted(
                    [
                        *Path("services/search_agent").glob("*.py"),
                        *Path("services/retrieval").glob("*.py"),
                        Path("services/worker/app/web_search_runner.py"),
                    ]
                )
            )
        ),
        configuration={
            k: os.environ.get(k)
            for k in [
                "SEARCH_AGENT_PROVIDER",
                "SEARCH_AGENT_MODE",
                "SEARCH_AGENT_DDGS_BACKEND",
                "SEARCH_AGENT_DOMAINS",
                "RETRIEVAL_MIN_SIMILARITY",
            ]
        },
        input_sha256=sha256(args.image.read_bytes()),
        description=args.description,
        expected="no_candidates" if args.expect_no_candidates else "candidates",
        transport="actual HTTP; independent worker; no injected search/embedding",
        files=[],
        passed=False,
    )
    # Only this explicit option reads the existing protected project DB configuration.
    database_url = os.environ.get("DATABASE_URL")
    if args.local_demo:
        from scripts.run_local_demo import local_environment

        database_url = local_environment()["DATABASE_URL"]
    if not database_url or not database_url.startswith("postgresql"):
        raise ValueError("A real PostgreSQL DATABASE_URL is required")
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    try:
        with httpx.Client(
            base_url=args.api, headers=headers, timeout=20, trust_env=False
        ) as client:
            health = client.get("/health/ready")
            health.raise_for_status()
            if args.retry_from:
                previous = json.loads(args.retry_from.read_text())
                record.update(
                    request_id=previous["request_id"],
                    local_job_id=previous["local_job_id"],
                    local_result=previous["local_result"],
                    local_candidates=previous["local_candidates"],
                    retry_of_job_id=previous["web_job_id"],
                )
                payload = {"client_retry_key": uuid4().hex}
                route = f"/search-jobs/{previous['web_job_id']}/retry"
                response = client.post(route, json=payload)
                response.raise_for_status()
                web = response.json()
                record["web_job_id"] = web["job_id"]
                replay = client.post(route, json=payload)
                record["same_key_replay"] = replay.status_code == 202 and replay.json() == web
                record["changed_description_conflict"] = previous["changed_description_conflict"]
            else:
                submission = uuid4().hex
                response = client.post(
                    "/search-requests",
                    data={"client_submission_key": submission},
                    files={"image": (args.image.name, args.image.read_bytes(), "image/png")},
                )
                response.raise_for_status()
                accepted = response.json()
                record.update(request_id=accepted["request_id"], local_job_id=accepted["job_id"])
                (args.out / "progress.json").write_text(json.dumps(record, indent=2))
                local = wait_job(client, record["request_id"], record["local_job_id"], args.timeout)
                record["local_result"] = local
                if local["status"] != "completed":
                    raise ValueError(
                        "Local search failed; not evidence of an outside-library target"
                    )
                local_candidates = client.get(f"/search-jobs/{record['local_job_id']}/candidates")
                local_candidates.raise_for_status()
                record["local_candidates"] = local_candidates.json()
                payload = dict(description=args.description, client_search_key=uuid4().hex)
                route = f"/search-requests/{record['request_id']}/web-search"
                response = client.post(route, json=payload)
                response.raise_for_status()
                web = response.json()
                record["web_job_id"] = web["job_id"]
                replay = client.post(route, json=payload)
                record["same_key_replay"] = replay.status_code == 202 and replay.json() == web
                conflict = client.post(
                    route, json={**payload, "description": args.description + " different"}
                )
                record["changed_description_conflict"] = conflict.status_code == 409
            final = wait_job(client, record["request_id"], web["job_id"], args.timeout)
            record["web_result"] = final
            response = client.get(f"/search-jobs/{web['job_id']}/candidates")
            response.raise_for_status()
            candidates = response.json()
            with factory() as db:
                # Read-only transaction; never write success or target state into business tables.
                db.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
                job = db.get(SearchJob, web["job_id"])
                execution = db.get(SearchExecution, web["job_id"])
                record["job_kind"] = job.job_kind
                record["retry_link_matches"] = (
                    not args.retry_from or job.retry_of_job_id == record["retry_of_job_id"]
                )
                record["execution"] = (
                    {
                        k: getattr(execution, k)
                        for k in [
                            "model_version",
                            "agent_version",
                            "stop_reason",
                            "search_calls",
                            "planner_calls",
                            "downloads_used",
                            "duration_ms",
                            "trace",
                            "warnings",
                        ]
                    }
                    if execution
                    else None
                )
                for item in candidates:
                    row = db.get(Candidate, item["candidate_id"])
                    media = client.get(item["media_url"])
                    media.raise_for_status()
                    if media.headers.get("content-type", "").split(";")[0] != "image/gif":
                        raise ValueError("Candidate MIME is not GIF")
                    frames = validate_image(media.content, animated_gif=True)
                    digest = sha256(media.content)
                    if row.job_id != web["job_id"] or row.media_sha256 != digest:
                        raise ValueError("API media and this web-job database SHA do not match")
                    if (
                        row.frame_count != frames
                        or row.source_url != item["source_url"]
                        or row.image_url != item["image_url"]
                        or row.provider != item["provider"]
                        or row.similarity_score != item["score"]
                    ):
                        raise ValueError("Database and API provenance/frame metadata disagree")
                    name = item["candidate_id"] + ".gif"
                    (args.out / name).write_bytes(media.content)
                    from PIL import Image

                    with Image.open(args.out / name) as gif:
                        size = list(gif.size)
                    record["files"].append(
                        dict(
                            candidate_id=row.id,
                            sha256=digest,
                            byte_size=len(media.content),
                            frame_count=frames,
                            size=size,
                            score=row.similarity_score,
                            source_url=row.source_url,
                            image_url=row.image_url,
                            provider=row.provider,
                            relative_path=name,
                            media_url=item["media_url"],
                            db_sha_matches=True,
                        )
                    )
            record["passed"] = (
                final["status"] == "completed"
                and bool(record["files"])
                and record["job_kind"] == "web"
                and record["execution"] is not None
                and record["same_key_replay"]
                and record["changed_description_conflict"]
                and record["retry_link_matches"]
            )
            if args.expect_no_candidates:
                record["passed"] = (
                    final["status"] == "completed"
                    and final["result_kind"] == "no_candidates"
                    and not record["files"]
                    and record["job_kind"] == "web"
                    and record["execution"] is not None
                    and record["same_key_replay"]
                    and record["changed_description_conflict"]
                )
            if args.target:
                target_sha = sha256(args.target.read_bytes())
                record["independent_target_sha256"] = target_sha
                record["target_byte_match"] = any(
                    f["sha256"] == target_sha for f in record["files"]
                )
                with factory() as db:
                    db.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
                    local_row = db.get(SearchJob, record["local_job_id"])
                    counts = dict(
                        reference=db.scalar(
                            select(func.count())
                            .select_from(ReferenceAsset)
                            .where(ReferenceAsset.sha256 == target_sha)
                        ),
                        saved=db.scalar(
                            select(func.count())
                            .select_from(SavedAsset)
                            .where(SavedAsset.sha256 == target_sha)
                        ),
                        candidates_before_request=db.scalar(
                            select(func.count())
                            .select_from(Candidate)
                            .join(SearchJob, Candidate.job_id == SearchJob.id)
                            .where(
                                Candidate.media_sha256 == target_sha,
                                SearchJob.created_at < local_row.created_at,
                            )
                        ),
                        exact_local_target=db.scalar(
                            select(func.count())
                            .select_from(Candidate)
                            .join(ReferenceAsset, Candidate.reference_asset_id == ReferenceAsset.id)
                            .where(
                                Candidate.job_id == local_row.id,
                                ReferenceAsset.sha256 == target_sha,
                            )
                        ),
                    )
                    record["initial_target_lookup_counts"] = counts
                    record["outside_retrieval_library"] = not any(counts.values())
                record["target_note"] = "Post-hoc byte comparison only; human confirmation pending"
    except Exception as exc:
        # Omit connection strings, auth headers and response bodies from evidence.
        record["error_type"] = type(exc).__name__
    finally:
        engine.dispose()
        (args.out / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                k: record.get(k)
                for k in [
                    "passed",
                    "request_id",
                    "local_job_id",
                    "web_job_id",
                    "same_key_replay",
                    "changed_description_conflict",
                    "error_type",
                ]
            },
            indent=2,
        )
    )
    return 0 if record["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--local-demo", action="store_true")
    parser.add_argument("--expect-no-candidates", action="store_true")
    parser.add_argument(
        "--retry-from", type=Path, help="Existing failed e2e result; explicit new retry"
    )
    parser.add_argument("--target", type=Path, help="Post-hoc comparison only, never sent to agent")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
