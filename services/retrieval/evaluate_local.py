"""Offline demo-corpus ablation; deliberately not a held-out screenshot benchmark."""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from services.common.config import get_settings
from services.common.storage import contained_path, read_gif, sha256
from services.retrieval.encoder import MODEL_VERSION, encode_image
from services.retrieval.engine import corpus, index_path, rank_assets


def evaluate():
    manifest, digest = corpus()
    with np.load(index_path(), allow_pickle=False) as index:
        metadata = json.loads(str(index["metadata"]))
        if metadata["manifest_sha256"] != digest or metadata["model_version"] != MODEL_VERSION:
            raise ValueError("Stale index; rebuild before evaluation")
        vectors, ids, frames = index["embeddings"], index["asset_ids"], index["frame_numbers"]
    first = frames == 0
    rows = []
    for asset in manifest.assets:
        data, count = read_gif(asset.gif_path)
        if sha256(data) != asset.sha256:
            raise ValueError("Corpus checksum mismatch")
        with Image.open(contained_path(get_settings().reference_root, asset.gif_path)) as gif:
            gif.seek(count // 3)
            start = time.perf_counter()
            query = encode_image(gif.convert("RGBA"))
        rankings = {}
        for name, mask in [("first_frame", first), ("multi_frame", np.ones(len(ids), bool))]:
            matches = rank_assets(vectors[mask], ids[mask], query, 3, 0.82)
            rankings[name] = {
                "matches": matches,
                "top3_hit": str(asset.reference_asset_id) in
                [item["reference_asset_id"] for item in matches],
            }
        rows.append({"asset_id": str(asset.reference_asset_id), "sha256": asset.sha256,
                     "frame_count": count, "query_frame": count // 3,
                     "elapsed_seconds": time.perf_counter() - start, "rankings": rankings})
    return {
        "kind": "derived_frame_demo_ablation_not_held_out",
        "model_version": MODEL_VERSION, "manifest_sha256": digest, "threshold": 0.82,
        "sample_count": len(rows), "includes_cold_model_load": True,
        "top3_hits": {name: sum(row["rankings"][name]["top3_hit"] for row in rows)
                      for name in ("first_frame", "multi_frame")},
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}))


if __name__ == "__main__":
    main()
