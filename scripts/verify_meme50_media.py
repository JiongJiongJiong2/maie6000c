"""Decode a browser download and optionally reconcile the actual PostgreSQL row."""

import argparse
import json
from pathlib import Path

from services.common.media import inspect_media


def check(path, expected, job_id, revision, candidate_id, *, check_db=False, local_stack=False):
    metadata = inspect_media(path.read_bytes())
    if (metadata.sha256, metadata.mime_type, metadata.format, metadata.frame_count) != (
        expected["sha256"],
        expected["mime_type"],
        expected["media_format"],
        expected["frame_count"],
    ):
        raise ValueError("download metadata mismatch")
    if path.suffix.lower() != "." + metadata.suffix:
        raise ValueError("download extension mismatch")
    result = dict(verified=True, metadata=metadata.model_dump(), database_check="not_requested")
    if check_db:
        if local_stack:
            import os
            from scripts.run_local_demo import local_environment

            os.environ.update(local_environment())
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from services.common.config import get_settings
        from services.common.search_models import Candidate, SearchJob

        get_settings.cache_clear()
        engine = create_engine(get_settings().database_url)
        try:
            with Session(engine) as db:
                job = db.get(SearchJob, job_id)
                candidate = db.get(Candidate, candidate_id)
                if (
                    not job
                    or not candidate
                    or job.result_revision != revision
                    or candidate.job_id != job_id
                    or (
                        candidate.media_sha256,
                        candidate.mime_type,
                        candidate.media_format,
                        candidate.frame_count,
                    )
                    != (metadata.sha256, metadata.mime_type, metadata.format, metadata.frame_count)
                ):
                    raise ValueError("download/database membership mismatch")
            result["database_check"] = "passed"
        finally:
            engine.dispose()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--check-db", action="store_true")
    parser.add_argument("--local-stack", action="store_true")
    args = parser.parse_args()
    try:
        result = check(
            args.file,
            json.loads(args.expected.read_text()),
            args.job_id,
            args.revision,
            args.candidate_id,
            check_db=args.check_db,
            local_stack=args.local_stack,
        )
    except Exception as exc:
        print(json.dumps(dict(verified=False, error_type=type(exc).__name__)))
        raise SystemExit(3) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
