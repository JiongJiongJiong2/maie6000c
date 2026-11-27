"""Invoke the retrieval owner's saved-asset index adapter in a bounded subprocess."""

from __future__ import annotations

import importlib
import json
import sys


def main() -> int:
    asset_id = sys.argv[1]
    retrieval = importlib.import_module("services.retrieval")
    indexer = getattr(retrieval, "index_saved_asset", None)
    if not callable(indexer):
        print(json.dumps({"error_code": "saved_asset_indexer_unavailable"}))
        return 3
    result = indexer(asset_id)
    if isinstance(result, str):
        index_version = result
    elif isinstance(result, dict):
        index_version = result.get("index_version")
    else:
        index_version = None
    if not isinstance(index_version, str) or not index_version.strip():
        print(json.dumps({"error_code": "invalid_index_result"}))
        return 4
    print(json.dumps({"index_version": index_version}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
