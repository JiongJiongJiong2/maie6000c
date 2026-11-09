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
    args = parser.parse_args()
    settings = SearchAgentSettings()
    if args.provider:
        settings.search_agent_provider = args.provider
    if args.mode:
        settings.search_agent_mode = args.mode
    if args.no_model:
        settings.search_agent_use_model = False
    result = search_web(
        description=args.description,
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
