"""Isolate model execution so the worker can enforce a wall-clock timeout."""

from __future__ import annotations

import contextlib
import importlib
import logging
import sys
from pathlib import Path

from services.common.search_schemas import RetrievalResult


def main() -> int:
    try:
        with contextlib.redirect_stdout(sys.stderr):
            module = importlib.import_module("services.retrieval")
            result = module.search(Path(sys.argv[1]), top_k=3)
            validated = RetrievalResult.model_validate(result)
    except ModuleNotFoundError as exc:
        if exc.name == "services.retrieval":
            logging.error("retrieval_module_unavailable")
            return 2
        raise
    print(validated.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
