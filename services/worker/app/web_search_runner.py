"""Run bounded web discovery and candidate preparation outside the worker process."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from services.search_agent import SearchBudget, search_web


def main() -> int:
    payload = json.load(sys.stdin)
    retrieval = importlib.import_module("services.retrieval")
    processor = getattr(retrieval, "prepare_candidates", None)
    if not callable(processor):
        print(json.dumps({"error_code": "candidate_processor_unavailable"}))
        return 3
    result = search_web(
        image_path=Path(payload["image_path"]),
        description=payload["description"],
        work_dir=Path(payload["work_dir"]),
        budget=SearchBudget(
            max_rounds=2,
            max_downloads=payload["max_downloads"],
            max_results=3,
            desired_candidates=1,
            timeout_seconds=payload["timeout_seconds"],
            call_timeout_seconds=payload["call_timeout_seconds"],
        ),
        prepare_candidates=processor,
    )
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
