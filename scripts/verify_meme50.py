"""Live API evidence, with no injected captions, target URLs or route stubs.

Exit 0 means an immutable final list and every returned media SHA were verified;
quality/40..50 count and independent human acceptance remain separate fields.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx

from services.common.media import inspect_media


def run(args):
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(exist_ok=False)
    data = args.image.read_bytes()
    meta = inspect_media(data)
    evidence = dict(
        input_sha256=meta.sha256,
        input_metadata=meta.model_dump(),
        description=args.description or "",
        target_count=args.target_count,
        states=[],
        results=[],
        human_review="pending",
        independent_reproduction="pending",
    )
    headers = (
        {"Authorization": "Bearer " + os.environ["DEVICE_TOKEN"]}
        if os.environ.get("DEVICE_TOKEN")
        else {}
    )
    started = time.monotonic()

    def save():
        (out / "evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
        )

    try:
        with httpx.Client(
            base_url=args.base_url.rstrip("/"),
            headers=headers,
            timeout=30,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            fields = dict(
                client_submission_key=str(uuid4()),
                search_profile="meme50-v2",
                target_count=str(args.target_count),
            )
            if args.description is not None:
                fields["description"] = args.description
            response = client.post(
                "/search-requests",
                data=fields,
                files={"image": ("random-input." + meta.suffix, data, meta.mime_type)},
            )
            response.raise_for_status()
            accepted = response.json()
            assert accepted["search_profile"] == "meme50-v2" and accepted["contract_version"] == 2
            evidence["accepted"] = accepted
            replay = client.post(
                "/search-requests",
                data=fields,
                files={"image": ("different-name." + meta.suffix, data, meta.mime_type)},
            )
            replay.raise_for_status()
            replayed = replay.json()
            # The worker may advance while a large upload is decoded again.
            # Idempotency preserves identity/content, not a stale status value.
            assert all(
                replayed[k] == accepted[k]
                for k in [
                    "request_id",
                    "job_id",
                    "search_profile",
                    "contract_version",
                    "target_count",
                ]
            )
            assert replayed["status"] in {"pending", "running", "completed", "failed"}
            evidence["replay"] = replayed
            job_path = "/search-jobs/" + accepted["job_id"]
            first_preview = None
            while True:
                response = client.get(job_path)
                response.raise_for_status()
                job = response.json()
                evidence["states"].append(
                    dict(elapsed_seconds=round(time.monotonic() - started, 3), **job)
                )
                evidence["job"] = job
                save()
                if job["status"] in {"completed", "failed"}:
                    break
                previews = client.get(job_path + "/previews")
                previews.raise_for_status()
                if previews.json()["items"] and first_preview is None:
                    first_preview = round(time.monotonic() - started, 3)
                if time.monotonic() - started > args.timeout:
                    raise TimeoutError("job deadline exceeded")
                time.sleep(1)
            evidence["first_preview_seconds"] = first_preview
            if job["status"] != "completed":
                evidence["machine_status"] = "failed"
                return 2
            revision = job["result_revision"]
            cursor = None
            items = []
            pages = []
            cursors = set()
            while True:
                params = dict(limit=20, media_kind="all", revision=revision)
                if cursor:
                    params["cursor"] = cursor
                page = client.get(job_path + "/results", params=params)
                page.raise_for_status()
                value = page.json()
                assert value["revision"] == revision and value["total_all"] <= 50
                assert value["job_id"] == accepted["job_id"]
                assert len(pages) < 3
                pages.append(value)
                items.extend(value["items"])
                cursor = value["next_cursor"]
                if cursor:
                    assert cursor not in cursors
                    cursors.add(cursor)
                if not cursor:
                    break
            evidence["pages"] = pages
            assert len(items) == job["result_count"] <= args.target_count
            assert [i["rank"] for i in items] == list(range(1, len(items) + 1))
            assert len({i["candidate_id"] for i in items}) == len(items)
            assert len({i["content_group_id"] for i in items}) == len(items)
            assert len({i["sha256"] for i in items}) == len(items)
            for item in items:
                for field in ["media_url", "preview_url"]:
                    assert item[field].startswith("/") and not item[field].startswith("//")
                response = client.get(item["media_url"])
                response.raise_for_status()
                actual = inspect_media(response.content)
                assert (
                    response.headers["content-type"].split(";")[0]
                    == actual.mime_type
                    == item["mime_type"]
                )
                assert actual.sha256 == item["sha256"] and actual.frame_count == item["frame_count"]
                assert (
                    actual.format == item["media_format"]
                    and actual.media_kind == item["media_kind"]
                )
                filename = f"{item['rank']:02d}-{item['candidate_id']}.{actual.suffix}"
                (out / filename).write_bytes(response.content)
                poster = client.get(item["preview_url"])
                poster.raise_for_status()
                assert inspect_media(poster.content).format == "PNG"
                evidence["results"].append(
                    dict(
                        **item,
                        downloaded_file=filename,
                        downloaded_sha256=hashlib.sha256(response.content).hexdigest(),
                        human_label=None,
                    )
                )
            for kind in ["static", "animated"]:
                page = client.get(
                    job_path + "/results", params=dict(limit=50, media_kind=kind, revision=revision)
                )
                page.raise_for_status()
                filtered = page.json()
                assert filtered["total"] == sum(i["media_kind"] == kind for i in items)
                assert {i["candidate_id"] for i in filtered["items"]} == {
                    i["candidate_id"] for i in items if i["media_kind"] == kind
                }
            assert (
                client.get(
                    job_path + "/results", params={"revision": "invalid-revision"}
                ).status_code
                == 409
            )
            evidence["database_check"] = "not_requested"
            if getattr(args, "check_db", False):
                from sqlalchemy import create_engine, select
                from sqlalchemy.orm import Session
                from services.common.search_models import Candidate, SearchJob
                from services.common.config import get_settings

                engine = create_engine(get_settings().database_url)
                try:
                    with Session(engine) as db:
                        row = db.get(SearchJob, accepted["job_id"])
                        assert row and row.result_revision == revision
                        records = list(
                            db.scalars(select(Candidate).where(Candidate.job_id == row.id))
                        )
                        assert {r.id for r in records} == {i["candidate_id"] for i in items}
                        by_id = {r.id: r for r in records}
                        for item in items:
                            r = by_id[item["candidate_id"]]
                            assert (
                                r.rank,
                                r.media_sha256,
                                r.media_format,
                                r.mime_type,
                                r.frame_count,
                            ) == (
                                item["rank"],
                                item["sha256"],
                                item["media_format"],
                                item["mime_type"],
                                item["frame_count"],
                            )
                        evidence["database_check"] = "passed"
                finally:
                    engine.dispose()
            evidence["machine_status"] = "passed"
            evidence["quantity_gate_40_to_50"] = 40 <= len(items) <= 50
            evidence["quality_gate"] = "unreviewed"
            return 0
    except Exception as exc:
        evidence["machine_status"] = "error"
        evidence["error_type"] = type(exc).__name__
        return 3
    finally:
        evidence["elapsed_seconds"] = round(time.monotonic() - started, 3)
        save()
        print(
            json.dumps(
                {
                    "machine_status": evidence.get("machine_status"),
                    "result_count": len(evidence["results"]),
                    "evidence": str(out / "evidence.json"),
                },
                ensure_ascii=False,
            )
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--description", default=None)
    parser.add_argument("--target-count", type=int, default=50, choices=range(1, 51))
    parser.add_argument(
        "--check-db",
        action="store_true",
        help="Compare with DATABASE_URL from the current environment",
    )
    parser.add_argument("--timeout", type=float, default=330)
    parser.add_argument("--out", type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
