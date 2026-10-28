
"""Build a CLIP feature index for animated GIFs."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
from uuid import UUID

import numpy as np
from PIL import Image

from services.retrieval.encoder import MODEL_NAME, encode_image


def sampled_frames(gif_path: Path, max_frames: int = 8):
    """Uniformly sample frames from an animated GIF."""
    with Image.open(gif_path) as gif:
        if gif.format != "GIF" or getattr(gif, "n_frames", 1) < 2:
            raise ValueError(f"Not an animated GIF: {gif_path}")

        count = gif.n_frames
        indices = np.linspace(
            0, count - 1, min(count, max_frames), dtype=int
        )

        for index in indices:
            gif.seek(int(index))
            yield int(index), gif.convert("RGB").copy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gif-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--corpus-version", default="w07-v1")
    parser.add_argument("--max-frames", type=int, default=8)
    args = parser.parse_args()

    if args.max_frames < 1:
        parser.error("--max-frames must be >= 1")

    gif_dir = args.gif_dir.resolve(strict=True)
    embeddings = []
    asset_ids = []
    frame_indices = []
    assets = []
    seen_ids = set()
    seen_hashes = set()

    with args.manifest.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)
        required = {
            "reference_asset_id",
            "filename",
            "source_reference",
            "permission_note",
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Missing required manifest columns")

        for row in reader:
            asset_id = str(UUID(row["reference_asset_id"].strip()))
            filename = row["filename"].strip()

            if not row["source_reference"].strip() or not row["permission_note"].strip():
                raise ValueError(f"Missing source or permission: {filename}")

            gif_path = (gif_dir / filename).resolve(strict=True)
            if not gif_path.is_relative_to(gif_dir) or gif_path.suffix.lower() != ".gif":
                raise ValueError(f"Invalid GIF path: {filename}")

            sha256 = hashlib.sha256(gif_path.read_bytes()).hexdigest()
            if asset_id in seen_ids or sha256 in seen_hashes:
                raise ValueError(f"Duplicate GIF or ID: {filename}")

            seen_ids.add(asset_id)
            seen_hashes.add(sha256)
            selected = []

            for index, frame in sampled_frames(gif_path, args.max_frames):
                feature = encode_image(frame)

                if feature.shape != (512,) or not np.isfinite(feature).all():
                    raise ValueError(f"Invalid feature: {filename}")

                embeddings.append(feature)
                asset_ids.append(asset_id)
                frame_indices.append(index)
                selected.append(index)

            assets.append({
                "reference_asset_id": asset_id,
                "filename": filename,
                "source_reference": row["source_reference"].strip(),
                "permission_note": row["permission_note"].strip(),
                "sha256": sha256,
                "sampled_frames": selected,
            })

            print(f"Indexed {filename}: {len(selected)} frames")

    if not embeddings:
        raise ValueError("No valid GIFs found")

    args.index_dir.mkdir(parents=True, exist_ok=True)

    np.savez_compressed(
        args.index_dir / "index.npz",
        embeddings=np.stack(embeddings).astype(np.float32),
        asset_ids=np.asarray(asset_ids, dtype="U36"),
        frame_indices=np.asarray(frame_indices, dtype=np.int32),
    )

    metadata = {
        "model_version": MODEL_NAME,
        "corpus_version": args.corpus_version,
        "sampling_version": f"uniform-max{args.max_frames}-v1",
        "assets": assets,
    }

    (args.index_dir / "index_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Done: {len(assets)} GIFs, {len(embeddings)} frame embeddings")


if __name__ == "__main__":
    main()
