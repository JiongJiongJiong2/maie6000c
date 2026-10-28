
"""Search the GIF corpus using CLIP image embeddings."""

import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from services.retrieval.encoder import MODEL_NAME, encode_image


def search(image_path, top_k=3):
    """Return ranked GIF matches for a screenshot."""

    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise ValueError("top_k must be a positive integer")

    index_dir = os.environ.get("MEMERETRIEVE_INDEX_DIR")
    if not index_dir:
        raise RuntimeError("MEMERETRIEVE_INDEX_DIR is not configured")

    index_dir = Path(index_dir)
    index_path = index_dir / "index.npz"
    metadata_path = index_dir / "index_metadata.json"

    if not index_path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError("GIF feature index is missing")

    with metadata_path.open("r", encoding="utf-8") as f:
        metadata = json.load(f)

    if metadata["model_version"] != MODEL_NAME:
        raise ValueError("Index model version does not match encoder")

    with np.load(index_path, allow_pickle=False) as data:
        embeddings = data["embeddings"].astype(np.float32)
        asset_ids = data["asset_ids"].astype(str)

    if (
        embeddings.ndim != 2
        or embeddings.shape[1] != 512
        or len(embeddings) == 0
        or len(asset_ids) != len(embeddings)
        or not np.isfinite(embeddings).all()
    ):
        raise ValueError("Invalid feature index")

    # Read query image
    image_path = Path(image_path)

    try:
        with Image.open(image_path) as im:
            image = im.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Cannot read query image: {image_path}") from exc

    # Extract query embedding using CLIP
    query = encode_image(image)

    # Cosine similarity
    norms = np.linalg.norm(embeddings, axis=1)
    if np.any(norms == 0):
        raise ValueError("Index contains zero vectors")

    embeddings = embeddings / norms[:, None]
    similarities = embeddings @ query

    # Keep the best matching frame from each GIF
    best_scores = {}

    for asset_id, score in zip(asset_ids, similarities):
        score = float(score)
        if asset_id not in best_scores or score > best_scores[asset_id]:
            best_scores[asset_id] = score

    ranked = sorted(
        best_scores.items(),
        key=lambda item: (-item[1], item[0]),
    )

    # Optional threshold: only enable after validation
    threshold_text = os.environ.get("MEMERETRIEVE_MIN_SCORE", "").strip()
    threshold = float(threshold_text) if threshold_text else None

    if threshold is not None and not -1 <= threshold <= 1:
        raise ValueError("Similarity threshold must be between -1 and 1")

    matches = [
        {
            "reference_asset_id": asset_id,
            "score": score,
        }
        for asset_id, score in ranked
        if threshold is None or score >= threshold
    ][:top_k]

    return {
        "matches": matches,
        "model_version": metadata["model_version"],
        "corpus_version": metadata["corpus_version"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    result = search(args.image, args.top_k)
    print(json.dumps(result, indent=2))
