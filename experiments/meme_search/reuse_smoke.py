"""Offline persistent-vector smoke; controlled resized near-duplicates, not unseen accuracy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
from services.retrieval.encoder import MODEL_VERSION, encode_image  # noqa: E402

DIMENSION = 512
ROOT = Path(".cache/meme-search-pilot").resolve()
SCOPE = (
    "Controlled near-duplicate persistent storage smoke only. Queries resize each corpus "
    "asset to 75% in memory. First frame only; no temporal GIF model, unseen accuracy, "
    "cross-user isolation, or production retrieval claim. No external network or app DB."
)


class CorpusMismatch(ValueError):
    """Query fixtures must contain exactly the stored content hashes."""


def validate_query_corpus(stored_shas, items):
    if set(stored_shas) != {item["sha256"] for item in items}:
        raise CorpusMismatch("stored SHA set differs from current verified probe set")


def local_path(path):
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT) or resolved == ROOT:
        raise ValueError("database/cache path must be inside .cache/meme-search-pilot")
    return resolved


def vector(values):
    values = np.asarray(values, dtype="<f4")
    if values.shape != (DIMENSION,) or not np.isfinite(values).all():
        raise ValueError("embedding dimension or finite-value mismatch")
    norm = np.linalg.norm(values)
    if not np.isclose(norm, 1, atol=0.001):
        raise ValueError("embedding is not normalized")
    return values


def assets(probe, cache):
    items = json.loads(probe.read_text(encoding="utf-8"))["items"]
    verified = [item for item in items if item.get("status") == "verified_image"]
    for item in verified:
        digest = item["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid asset SHA")
        path = cache / digest
        if not path.resolve().is_relative_to(cache):
            raise ValueError("asset path escapes cache")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("asset SHA checksum mismatch")
    return verified, len(items) - len(verified)


def first_frame(cache, item, resize=False):
    with Image.open(cache / item["sha256"]) as source:
        source.seek(0)
        image = source.copy()
    if resize:
        image = image.resize(
            tuple(max(1, int(side * 0.75)) for side in image.size), Image.Resampling.LANCZOS
        )
    return image


def stored_assets(db):
    stored = []
    for sha, source_id, model, dimension, data in db.execute(
        "SELECT sha256,source_id,model_version,dimension,embedding FROM asset ORDER BY sha256"
    ):
        if model != MODEL_VERSION or dimension != DIMENSION:
            raise ValueError("stored model version or dimension mismatch")
        values = vector(np.frombuffer(data, dtype="<f4"))
        stored.append((sha, source_id, values, hashlib.sha256(data).hexdigest()))
    return stored


def execute(args):
    cache, path = local_path(args.cache_dir), local_path(args.db)
    items, excluded = assets(args.probe, cache)
    if args.command == "ingest":
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
    else:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        if args.command == "ingest":
            db.execute("""CREATE TABLE IF NOT EXISTS asset (
                sha256 TEXT PRIMARY KEY, source_id TEXT NOT NULL, model_version TEXT NOT NULL,
                dimension INTEGER NOT NULL, embedding BLOB NOT NULL, source_metadata TEXT NOT NULL
            )""")
        stored = stored_assets(db)
        before, known = len(stored), {row[0] for row in stored}
        if args.command == "ingest":
            for item in items:
                if item["sha256"] in known:
                    continue
                embedding = vector(encode_image(first_frame(cache, item)))
                db.execute(
                    "INSERT INTO asset VALUES (?,?,?,?,?,?)",
                    (
                        item["sha256"],
                        item["id"],
                        MODEL_VERSION,
                        DIMENSION,
                        embedding.tobytes(),
                        json.dumps(item, ensure_ascii=False, sort_keys=True),
                    ),
                )
                known.add(item["sha256"])
            db.commit()
            output = {
                "before_count": before,
                "after_count": len(known),
                "inserted_count": len(known) - before,
                "excluded_failed_probes": excluded,
            }
        else:
            validate_query_corpus(known, items)
            if not stored:
                raise ValueError("no stored assets to query")
            queries = []
            for item in items:
                fresh = vector(encode_image(first_frame(cache, item, resize=True)))
                # Rank exclusively by cosine score; SHA only breaks exact score ties.
                ranked = sorted(
                    [(float(np.clip(fresh @ row[2], -1, 1)), row) for row in stored],
                    key=lambda hit: (-hit[0], hit[1][0]),
                )
                expected = next(
                    (i for i, (_, row) in enumerate(ranked, 1) if row[0] == item["sha256"]), None
                )
                queries.append(
                    {
                        "query_id": item["id"],
                        "query_source_sha256": item["sha256"],
                        "expected_rank": expected,
                        "top3": [
                            {
                                "id": row[1],
                                "cosine": score,
                                "sha256": row[0],
                                "embedding_sha256": row[3],
                            }
                            for score, row in ranked[:3]
                        ],
                    }
                )
            output = {
                "stored_count": before,
                "queries": queries,
                "excluded_failed_probes": excluded,
            }
    finally:
        db.close()
    return {
        "scope": SCOPE,
        "model_version": MODEL_VERSION,
        "dimension": DIMENSION,
        "db_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **output,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ingest", "query"])
    for name in ("probe", "cache-dir", "db", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        output = execute(args)
    except CorpusMismatch:
        parser.exit(
            2,
            "Stored SHA set differs from current verified probe set; "
            "use a matching probe or create a fresh smoke DB.\n",
        )
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"Smoke failed: {type(exc).__name__}; check local inputs/model/schema.\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
