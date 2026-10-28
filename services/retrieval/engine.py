"""Build a versioned frame index and query it with a live CLIP embedding."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

from services.common.config import get_settings
from services.common.reference_assets import Manifest
from services.common.storage import contained_path, read_gif, sha256
from services.retrieval.encoder import MODEL_VERSION, encode_image, encode_images

FRAMES_PER_GIF = 8
INDEX_FORMAT = 1


def corpus():
    root = get_settings().reference_root
    raw = (root / "manifest.json").read_bytes()
    return Manifest.model_validate_json(raw), hashlib.sha256(raw).hexdigest()


def index_path() -> Path:
    return get_settings().model_cache_root / "gif-frames.npz"


def build_index() -> dict:
    manifest, digest = corpus()
    images, ids, frame_numbers = [], [], []
    for asset in manifest.assets:
        data, count = read_gif(asset.gif_path)
        if sha256(data) != asset.sha256:
            raise ValueError(f"Corpus checksum mismatch: {asset.reference_asset_id}")
        with Image.open(contained_path(get_settings().reference_root, asset.gif_path)) as gif:
            for frame in np.linspace(0, count - 1, min(FRAMES_PER_GIF, count), dtype=int):
                gif.seek(int(frame))
                images.append(gif.convert("RGBA"))
                ids.append(str(asset.reference_asset_id))
                frame_numbers.append(int(frame))
    embeddings = np.concatenate(
        [encode_images(images[start : start + 16]) for start in range(0, len(images), 16)]
    )
    metadata = {
        "index_format": INDEX_FORMAT,
        "model_version": MODEL_VERSION,
        "corpus_version": manifest.corpus_version,
        "manifest_sha256": digest,
        "asset_count": len(manifest.assets),
        "frame_count": len(images),
    }
    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as output:
        np.savez_compressed(
            output,
            embeddings=embeddings,
            asset_ids=np.asarray(ids),
            frame_numbers=np.asarray(frame_numbers),
            metadata=json.dumps(metadata),
        )
    temporary.replace(path)
    return metadata


def rank_assets(embeddings, asset_ids, query, top_k: int, minimum: float) -> list[dict]:
    scores = np.sum(embeddings * query, axis=1, dtype=np.float64)
    best = {}
    for asset_id, score in zip(asset_ids, scores, strict=True):
        best[str(asset_id)] = max(float(score), best.get(str(asset_id), -1.0))
    return [
        {"reference_asset_id": asset_id, "score": min(1.0, max(-1.0, score))}
        for asset_id, score in sorted(best.items(), key=lambda item: (-item[1], item[0]))[:top_k]
        if score >= minimum
    ]


def search(image_path: Path, top_k: int = 3) -> dict:
    if type(top_k) is not int or not 1 <= top_k <= 3:
        raise ValueError("top_k must be between 1 and 3")
    minimum = float(os.environ.get("RETRIEVAL_MIN_SIMILARITY", "0.82"))
    if not np.isfinite(minimum) or not -1 <= minimum <= 1:
        raise ValueError("RETRIEVAL_MIN_SIMILARITY must be between -1 and 1")
    manifest, digest = corpus()
    with np.load(index_path(), allow_pickle=False) as index:
        metadata = json.loads(str(index["metadata"]))
        if (
            metadata["manifest_sha256"] != digest
            or metadata["model_version"] != MODEL_VERSION
            or metadata["index_format"] != INDEX_FORMAT
        ):
            raise ValueError("The GIF index is stale. Rebuild it before searching.")
        embeddings, ids = index["embeddings"], index["asset_ids"]
        if (
            embeddings.shape != (len(ids), 512)
            or not np.isfinite(embeddings).all()
            or set(ids) != {str(asset.reference_asset_id) for asset in manifest.assets}
        ):
            raise ValueError("The GIF index does not match the corpus")
        with Image.open(image_path) as image:
            query = encode_image(image)
        matches = rank_assets(embeddings, ids, query, top_k, minimum)
    return {
        "matches": matches,
        "model_version": MODEL_VERSION,
        "corpus_version": manifest.corpus_version,
    }


def main():
    parser = argparse.ArgumentParser(description="Build or query the local CLIP GIF index")
    parser.add_argument("action", choices=["index", "search"])
    parser.add_argument("image", nargs="?", type=Path)
    args = parser.parse_args()
    if args.action == "search" and args.image is None:
        parser.error("search requires an image path")
    print(json.dumps(build_index() if args.action == "index" else search(args.image), indent=2))


if __name__ == "__main__":
    main()
