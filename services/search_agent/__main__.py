"""Run real web discovery: python -m services.search_agent DESCRIPTION."""

import argparse
from pathlib import Path

from .core import search_web
from .models import SearchBudget
from .settings import SearchAgentSettings


def main():
    parser = argparse.ArgumentParser(description="Bounded web/image source discovery")
    parser.add_argument("description")
    parser.add_argument(
        "--provider", choices=["auto", "deepseek", "ddgs", "brave", "tavily", "searxng"]
    )
    parser.add_argument("--mode", choices=["web", "images"])
    parser.add_argument("--no-model", action="store_true")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    recovery = {}
    if args.recover:
        if not args.image or not args.image.is_file() or not args.work_dir:
            parser.error("--recover requires an existing --image and --work-dir")
        from services.retrieval import prepare_candidates
        from .resolvers import resolve_sources
        recovery = dict(image_path=args.image, work_dir=args.work_dir,
                        prepare_candidates=prepare_candidates, resolver=resolve_sources)
    settings = SearchAgentSettings()
    if args.provider:
        settings.search_agent_provider = args.provider
    if args.mode:
        settings.search_agent_mode = args.mode
    if args.no_model:
        settings.search_agent_use_model = False
    result = search_web(
        description=args.description,
        **recovery,
        settings=settings,
        budget=SearchBudget(timeout_seconds=args.timeout),
    )
    output = result.model_dump_json(indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
