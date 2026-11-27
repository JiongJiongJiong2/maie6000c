"""Opt-in live verification. Run from the repository root with python -m scripts..."""

import argparse
import json
import os
import subprocess
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from services.common.storage import sha256, validate_image
from services.retrieval import prepare_candidates
from services.search_agent import SearchBudget, search_web
from services.search_agent.models import CandidateBudget, Source
from services.search_agent.resolvers import resolve_sources
from services.search_agent.settings import SearchAgentSettings
from services.worker.app.web_search_runner import to_worker_result


def main():
    parser = argparse.ArgumentParser(description="Explicit live GIF verification; never mocks")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="New attempt directory")
    parser.add_argument("--source", help="Direct source check, separate from provider search")
    parser.add_argument("--description")
    parser.add_argument(
        "--provider", default="ddgs", choices=["deepseek", "ddgs", "brave", "tavily", "searxng"]
    )
    parser.add_argument("--use-model", action="store_true")
    args = parser.parse_args()
    if not args.image.is_file() or bool(args.source) == bool(args.description):
        parser.error("Existing image and exactly one of --source / --description required")
    args.out.mkdir(parents=True, exist_ok=False)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    implementation = sorted(
        [
            *Path("services/search_agent").glob("*.py"),
            *Path("services/retrieval").glob("*.py"),
            Path("services/worker/app/web_search_runner.py"),
        ]
    )
    fingerprint = sha256(b"".join(str(p).encode() + b"\0" + p.read_bytes() for p in implementation))
    common = dict(
        executed_at=datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        implementation_sha256=fingerprint,
        baseline_sha=baseline,
        image_sha256=sha256(args.image.read_bytes()),
        threshold=os.environ.get("RETRIEVAL_MIN_SIMILARITY", "0.82"),
        sample_rule="uniform min(8, frame_count); max normalized dot product",
        target_confirmation="requires independent human review",
    )
    started = time.monotonic()
    if args.source:
        resolved = resolve_sources(
            [Source(source_url=args.source, provider="direct_source_check")],
            deadline=started + 60,
            remaining_pages=6,
            remaining_downloads=6,
        )
        (args.out / "resolution.json").write_text(resolved.model_dump_json(indent=2))
        result = prepare_candidates(
            args.image,
            [s.model_dump() for s in resolved.sources],
            args.out,
            CandidateBudget(remaining_downloads=6, deadline=started + 60),
        )
        passed = bool(result.candidates)
        common.update(check="direct_source_check", provider="manual source")
    else:
        settings = SearchAgentSettings(
            search_agent_provider=args.provider,
            search_agent_mode="web",
            search_agent_use_model=args.use_model,
        )
        agent = search_web(
            args.image,
            args.description,
            args.out,
            SearchBudget(),
            settings=settings,
            prepare_candidates=prepare_candidates,
            resolver=resolve_sources,
        )
        (args.out / "agent.json").write_text(agent.model_dump_json(indent=2))
        result = to_worker_result(agent)
        passed = result.status == "completed" and result.result_kind == "candidates"
        common.update(
            check="live_search_check",
            provider=args.provider,
            mode="web",
            planner=args.use_model,
            backend=settings.search_agent_ddgs_backend,
            source_domains=settings.search_agent_domains,
        )
    (args.out / "result.json").write_text(result.model_dump_json(indent=2))
    evidence = []
    for candidate in result.candidates:
        path = args.out / candidate.relative_path
        data = path.read_bytes()
        count = validate_image(data, animated_gif=True)
        assert sha256(data) == candidate.sha256 and count == candidate.frame_count
        evidence.append(
            dict(
                sha256=candidate.sha256,
                byte_size=len(data),
                frame_count=count,
                score=candidate.score,
                relative_path=candidate.relative_path,
            )
        )
    common.update(passed=passed, elapsed_seconds=time.monotonic() - started, files=evidence)
    (args.out / "verification.json").write_text(json.dumps(common, indent=2))
    print(json.dumps(common, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
