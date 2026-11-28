"""Build a versioned frame index and query it with a live CLIP embedding."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
from pathlib import Path

import numpy as np
from PIL import Image

from services.common.config import get_settings
from services.common.reference_assets import Manifest
from services.common.storage import atomic_write, contained_path, read_gif, sha256
from services.retrieval.encoder import MODEL_VERSION, encode_image, encode_images

FRAMES_PER_GIF = 8
INDEX_FORMAT = 1
logger = logging.getLogger(__name__)


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
    with io.BytesIO() as output:
        np.savez_compressed(
            output,
            embeddings=embeddings,
            asset_ids=np.asarray(ids),
            frame_numbers=np.asarray(frame_numbers),
            metadata=json.dumps(metadata),
        )
        atomic_write(path.parent, path.name, output.getvalue())
    if get_settings().vector_backend == "pgvector":
        from services.retrieval.vector_store import mirror_reference_vectors

        mirrored = mirror_reference_vectors(manifest, digest, ids, frame_numbers, embeddings)
        if not mirrored:
            logger.warning("reference_vector_mirror_unavailable")
        metadata["pgvector_mirrored"] = mirrored
    return metadata


def rank_assets(embeddings, asset_ids, query, top_k: int, minimum: float) -> list[dict]:
    scores = np.empty(len(embeddings), dtype=np.float64)
    for start in range(0, len(embeddings), 1024):
        stop = start + 1024
        scores[start:stop] = np.sum(
            embeddings[start:stop] * query,
            axis=1,
            dtype=np.float64,
        )
    best = {}
    for asset_id, score in zip(asset_ids, scores, strict=True):
        best[str(asset_id)] = max(float(score), best.get(str(asset_id), -1.0))
    return [
        {"reference_asset_id": asset_id, "score": min(1.0, max(-1.0, score))}
        for asset_id, score in sorted(best.items(), key=lambda item: (-item[1], item[0]))[:top_k]
        if score >= minimum
    ]


def local_matches(embeddings, ids, query, top_k, minimum, *, reference_catalog=None):
    if get_settings().vector_backend == "pgvector":
        from services.retrieval.vector_store import rank_reference_vectors, rank_saved_vectors

        saved = rank_saved_vectors(query, top_k, minimum)
        if saved is not None:
            reference = (
                rank_reference_vectors(query, top_k, minimum, *reference_catalog)
                if reference_catalog is not None
                else None
            )
            reference_backend = "pgvector"
            if reference is None:
                reference = rank_assets(embeddings, ids, query, top_k, minimum)
                reference_backend = "npz_fallback"
            # Keep the original ordering if numeric rounding could change the
            # ranking across backends, or the two catalogs contain the same ID.
            overlap = {item["reference_asset_id"] for item in saved}.intersection(ids)
            close_scores = any(
                abs(left["score"] - right["score"]) <= 0.0002
                for left in reference
                for right in saved
            )
            if not overlap and not close_scores:
                matches = sorted(
                    reference + saved,
                    key=lambda item: (-item["score"], item["reference_asset_id"]),
                )[:top_k]
                return matches, "pgvector", reference_backend
        backend = "npz_fallback"
    else:
        backend = "npz"

    from services.retrieval.saved_index import ready_vectors

    batches = [embeddings]
    asset_ids = list(ids)
    for asset_id, vectors in ready_vectors():
        batches.append(vectors)
        asset_ids.extend([asset_id] * len(vectors))
    return rank_assets(np.concatenate(batches), asset_ids, query, top_k, minimum), backend, backend


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
            or not np.any(embeddings != 0, axis=1).all()
            or set(ids) != {str(asset.reference_asset_id) for asset in manifest.assets}
        ):
            raise ValueError("The GIF index does not match the corpus")
        with Image.open(image_path) as image:
            query = encode_image(image)
    matches, backend, reference_backend = local_matches(
        embeddings, ids, query, top_k, minimum, reference_catalog=(manifest, digest)
    )
    return {
        "matches": matches,
        "model_version": MODEL_VERSION,
        "corpus_version": manifest.corpus_version,
        "vector_backend": backend,
        "reference_vector_backend": reference_backend,
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
