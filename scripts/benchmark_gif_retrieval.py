"""Evaluate first-frame and multi-frame retrieval on local, derived screenshots.

Run with the prepared local Noto corpus and CLIP weights:
    python -m scripts.benchmark_gif_retrieval --output-dir .cache/gif-retrieval-benchmark

Run a standalone fixture check:
    python -m scripts.benchmark_gif_retrieval --demo --encoder pixel --output-dir .cache/gif-demo

For custom input, --source-manifest points to a JSON object with an assets array.
Each asset has an id, family_id, gif_path, sha256, source, license, and optional title.
The analogous --distractor-manifest uses image instead of gif_path for static files.
Keep file paths relative to their manifests. Use a shared family_id for versions of a meme.
The output is self-contained. manifest.json freezes originals, query images and targets,
and results.json records both rankings and hashes the manifest's exact bytes.
"""

from __future__ import annotations

import argparse
import io
import json
import random
import sys
import time
from dataclasses import dataclass
from itertools import islice, zip_longest
from pathlib import Path

import numpy as np
import PIL
from PIL import Image, ImageDraw, ImageOps

from services.common.config import get_settings
from services.common.media import MAX_BYTES, inspect_media
from services.common.storage import atomic_write, contained_path, sha256
from services.retrieval.encoder import MODEL_VERSION, encode_images, on_white
from services.retrieval.engine import FRAMES_PER_GIF, rank_assets

ARMS = ("first_frame", "multi_frame")
TRANSFORMS = ("tight_crop", "light_chat", "dark_chat", "caption_occlusion")
DEFAULT_SEED = 6000
BATCH_SIZE = 16


@dataclass(frozen=True)
class Asset:
    id: str
    family_id: str
    title: str
    source: str
    license: str
    sha256: str
    source_file: Path | bytes
    frame_count: int
    media_suffix: str = "gif"


def checked_text(entry: dict, key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Corpus asset is missing {key}")
    return value.strip()


def source_bytes(path: Path) -> bytes:
    maximum = min(MAX_BYTES, get_settings().max_candidate_bytes)
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"Corpus media exceeds the file size limit: {path.name}")
    return data


def load_corpus(path: Path) -> tuple[list[Asset], str]:
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("assets"), list):
        raise ValueError("Corpus manifest must contain an assets array")
    noto = manifest.get("corpus_version") == "noto-reactions-v1"
    assets = []
    for entry in manifest["assets"]:
        if not isinstance(entry, dict):
            raise ValueError("Corpus assets must be objects")
        relative = checked_text(entry, "gif_path")
        expected_sha = checked_text(entry, "sha256")
        source_file = contained_path(path.parent, relative)
        data = source_bytes(source_file)
        if sha256(data) != expected_sha:
            raise ValueError(f"Corpus GIF checksum mismatch: {relative}")
        media = inspect_media(data)
        if media.format != "GIF" or media.frame_count < 2:
            raise ValueError(f"Corpus asset must be a multi-frame GIF: {relative}")
        asset_id = entry.get("id", entry.get("reference_asset_id", expected_sha))
        normalized = dict(entry, id=asset_id)
        # This repository's Noto input has one source animation per emoji codepoint.
        if noto:
            normalized.setdefault("family_id", f"noto-{Path(relative).stem}")
            normalized.setdefault("source", entry.get("source_reference"))
            normalized.setdefault("license", entry.get("permission_note"))
        assets.append(
            Asset(
                checked_text(normalized, "id"),
                checked_text(normalized, "family_id"),
                checked_text(normalized, "title") if "title" in normalized else Path(relative).stem,
                checked_text(normalized, "source"),
                checked_text(normalized, "license"),
                expected_sha,
                source_file,
                media.frame_count,
            )
        )
    return assets, sha256(raw)


def load_distractors(path: Path) -> tuple[list[Asset], str]:
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("assets"), list):
        raise ValueError("Distractor manifest must contain an assets array")
    assets = []
    for entry in manifest["assets"]:
        if not isinstance(entry, dict):
            raise ValueError("Distractor assets must be objects")
        relative = checked_text(entry, "image")
        expected_sha = checked_text(entry, "sha256")
        source_file = contained_path(path.parent, relative)
        data = source_bytes(source_file)
        if sha256(data) != expected_sha:
            raise ValueError(f"Distractor checksum mismatch: {relative}")
        media = inspect_media(data)
        if media.frame_count != 1:
            raise ValueError(f"Distractor must be a static image: {relative}")
        assets.append(
            Asset(
                checked_text(entry, "id"),
                checked_text(entry, "family_id"),
                checked_text(entry, "title") if "title" in entry else Path(relative).stem,
                checked_text(entry, "source"),
                checked_text(entry, "license"),
                expected_sha,
                source_file,
                1,
                media.suffix,
            )
        )
    return assets, sha256(raw)


def demo_corpus() -> list[Asset]:
    """Create abstract GIFs without third-party input or downloads."""
    colors = (
        "#1466ce",
        "#34814c",
        "#c73545",
        "#6b32b8",
        "#af6818",
        "#00828b",
        "#ac2b84",
        "#665b23",
    )
    assets = []
    for index, color in enumerate(colors):
        frames = []
        for frame_number in range(13):
            frame = Image.new("RGB", (112, 112), "#f0eddf")
            draw = ImageDraw.Draw(frame)
            x = 20 + (frame_number * 7) % 65
            y = 15 + (frame_number * (index + 2)) % 67
            draw.rectangle((9, 9, 102, 102), outline=color, width=3)
            draw.ellipse((x, y, x + 25, y + 25), fill=color)
            draw.regular_polygon(
                (56, 58, 24), index + 3, rotation=frame_number * 11, outline="#202938", width=3
            )
            frames.append(frame)
        with io.BytesIO() as output:
            frames[0].save(
                output, format="GIF", save_all=True, append_images=frames[1:], duration=90, loop=0
            )
            data = output.getvalue()
        name = f"procedural-{index + 1:02d}"
        assets.append(
            Asset(
                name,
                name,
                f"Procedural animation {index + 1}",
                "Generated by this script from geometric shapes",
                "Original procedural fixture, CC0 1.0",
                sha256(data),
                data,
                13,
            )
        )
    return assets


def assign_families(assets: list[Asset], seed: int) -> dict[str, tuple[str, bool]]:
    families = sorted({asset.family_id for asset in assets})
    if len(families) < 4:
        raise ValueError("Provide at least four source families for two splits with corpus misses")
    random.Random(seed).shuffle(families)
    final_count = max(2, len(families) // 3)
    assignments = {}
    for split, group in (
        ("development", families[final_count:]),
        ("final", families[:final_count]),
    ):
        miss_count = max(1, len(group) // 3)
        assignments.update(
            {family_id: (split, index >= miss_count) for index, family_id in enumerate(group)}
        )
    return assignments


def indexed_frames(frame_count: int) -> list[int]:
    return np.linspace(0, frame_count - 1, min(FRAMES_PER_GIF, frame_count), dtype=int).tolist()


def query_subset(
    assets: list[Asset], assignments: dict[str, tuple[str, bool]], seed: int, limit: int | None
) -> set[str]:
    if limit is None or limit >= len(assets):
        return {asset.id for asset in assets}
    shuffled = sorted(assets, key=lambda asset: asset.id)
    random.Random(f"{seed}:query-assets").shuffle(shuffled)
    groups = {assignment: [] for assignment in sorted(set(assignments.values()))}
    for asset in shuffled:
        groups[assignments[asset.family_id]].append(asset.id)
    balanced_order = (
        asset_id
        for row in zip_longest(*groups.values())
        for asset_id in row
        if asset_id is not None
    )
    return set(islice(balanced_order, limit))


def screenshot(frame: Image.Image, transform: str, rng: random.Random) -> tuple[Image.Image, dict]:
    width, height = frame.size
    if transform == "tight_crop":
        left = int(width * rng.uniform(0.04, 0.13))
        top = int(height * rng.uniform(0.02, 0.10))
        box = (left, top, max(left + 1, width - left // 2), max(top + 1, height - top // 2))
        size = rng.randint(146, 186)
        image = ImageOps.contain(on_white(frame.crop(box)), (size, size), Image.Resampling.LANCZOS)
        return image, {"crop_box": box, "max_edge": size}

    dark = transform == "dark_chat"
    background = "#232733" if dark else "#e7ebf0"
    panel = "#303746" if dark else "#fcfcff"
    text = "#e5e9f0" if dark else "#293644"
    dimension = rng.randint(132, 172)
    tile = ImageOps.contain(frame, (dimension, dimension), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (dimension + 74, dimension + 77), background)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((15, 30, canvas.width - 15, canvas.height - 12), radius=11, fill=panel)
    draw.text((18, 9), "Shared animation", fill=text)
    x = (canvas.width - tile.width) // 2 + rng.randint(-8, 8)
    y = 39 + (dimension - tile.height) // 2
    canvas.alpha_composite(tile, (x, y))
    draw.text((26, canvas.height - 29), "Image preview", fill=text)
    if transform == "caption_occlusion":
        cover_y = y + int(tile.height * 0.75)
        draw.rectangle((x, cover_y, x + tile.width - 1, y + tile.height), fill="#283646")
        draw.text((x + 4, cover_y + 2), "That moment", fill="white")
    return canvas.convert("RGB"), {"image_box": [x, y, x + tile.width, y + tile.height]}


def write_json(directory: Path, name: str, value: dict) -> bytes:
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    atomic_write(directory, name, raw)
    return raw


def prepare_queries(
    assets: list[Asset],
    output_dir: Path,
    seed: int,
    source_sha: str | None,
    max_query_assets: int | None = None,
    distractors: list[Asset] | None = None,
    distractor_sha: str | None = None,
    focus_families: set[str] | None = None,
) -> dict:
    combined = [*assets, *(distractors or [])]
    if len({asset.id for asset in combined}) != len(combined):
        raise ValueError("Corpus asset IDs must be unique")
    if len({asset.sha256 for asset in combined}) != len(combined):
        raise ValueError("Corpus files must have distinct SHA-256 values")
    assignments = assign_families(assets, seed)
    selected = query_subset(assets, assignments, seed, max_query_assets)
    focus = focus_families or set()
    missing = focus - {asset.family_id for asset in combined}
    if missing:
        raise ValueError(f"Focus family has no media: {', '.join(sorted(missing))}")
    manifest = {
        "version": 1,
        "kind": "synthetic_screenshot_offline_gif_retrieval",
        "seed": seed,
        "source_manifest_sha256": source_sha,
        "distractor_manifest_sha256": distractor_sha,
        "corpus_kind": "local_gifs_with_source_metadata" if source_sha else "procedural_demo",
        "catalog_mode": "gif_plus_static_stress_test" if distractors else "gif_only",
        "query_asset_limit": max_query_assets,
        "focus_families": sorted(focus),
        "notes": [
            "Query images are derived from the target GIFs, with controlled transformations.",
            "Development and final query groups use disjoint source families. Both query groups "
            "search the same frozen catalog. Corpus-miss families are fully excluded from it.",
            "The manifest records whether each query frame is also sampled in the index. "
            "These cases do not measure independent user accuracy or web retrieval.",
            "Static distractors, when included, enter both arms once each. "
            "This mixed-media stress test differs from the product's GIF-only index.",
            "Optional focus cases search the full catalog, with animated and static targets "
            "scored separately. The ordinary animated cohort still uses its frozen catalog.",
        ],
        "assets": [],
        "cases": [],
    }
    for position, asset in enumerate(sorted(combined, key=lambda item: item.id), start=1):
        is_focus = asset.family_id in focus
        split, in_corpus = assignments.get(asset.family_id, ("final" if is_focus else None, True))
        animated = asset.frame_count > 1
        media_path = f"assets/{position:06d}.{asset.media_suffix}"
        data = (
            source_bytes(asset.source_file)
            if isinstance(asset.source_file, Path)
            else (asset.source_file)
        )
        if sha256(data) != asset.sha256:
            raise ValueError(f"Corpus file changed after validation: {asset.id}")
        original = atomic_write(output_dir, media_path, data)
        manifest["assets"].append(
            {
                "id": asset.id,
                "family_id": asset.family_id,
                "title": asset.title,
                "gif_path" if animated else "media_path": media_path,
                "media_kind": "animated" if animated else "static",
                "sha256": asset.sha256,
                "frame_count": asset.frame_count,
                "source": asset.source,
                "license": asset.license,
                "split": split,
                "in_corpus": in_corpus,
                "in_focus_corpus": bool(focus),
            }
        )
        cohorts = []
        if asset.id in selected:
            cohorts.append("animated_original")
        if is_focus:
            cohorts.append("animated_focus" if animated else "static_focus")
        if not cohorts:
            continue
        sampled_frames = set(indexed_frames(asset.frame_count))
        unsampled_frames = sorted(set(range(asset.frame_count)) - sampled_frames)
        possible_frames = unsampled_frames or list(range(1, asset.frame_count)) or [0]
        with Image.open(original) as gif:
            for cohort in cohorts:
                included = in_corpus or cohort != "animated_original"
                cohort_seed = f"{seed}:{asset.sha256}"
                if cohort != "animated_original":
                    cohort_seed = f"{cohort_seed}:{cohort}"
                rng = random.Random(cohort_seed)
                selectable = possible_frames.copy()
                rng.shuffle(selectable)
                for index, transform in enumerate(TRANSFORMS):
                    query_frame = selectable[index % len(selectable)]
                    gif.seek(query_frame)
                    image, parameters = screenshot(gif.convert("RGBA"), transform, rng)
                    case_id = sha256(f"v1:{cohort_seed}:{transform}".encode("ascii"))[:24]
                    image_format, suffix, options = {
                        "tight_crop": ("PNG", "png", {}),
                        "light_chat": ("JPEG", "jpg", {"quality": 72}),
                        "dark_chat": ("JPEG", "jpg", {"quality": 58}),
                        "caption_occlusion": ("WEBP", "webp", {"quality": 68}),
                    }[transform]
                    with io.BytesIO() as encoded:
                        image.save(encoded, format=image_format, **options)
                        data = encoded.getvalue()
                    image_path = f"queries/{case_id}.{suffix}"
                    atomic_write(output_dir, image_path, data)
                    manifest["cases"].append(
                        {
                            "id": case_id,
                            "split": split,
                            "family_id": asset.family_id,
                            "category": "in_library" if included else "out_of_library",
                            "cohort": cohort,
                            "target_media_kind": "animated" if animated else "static",
                            "transform": transform,
                            "transform_parameters": parameters | options,
                            "image": image_path,
                            "image_sha256": sha256(data),
                            "target_asset_id": asset.id,
                            "target_sha256": asset.sha256,
                            "query_frame": query_frame,
                            "query_frame_is_index_sample": included
                            and query_frame in sampled_frames,
                        }
                    )
    return manifest


def encode_pixels(images: list[Image.Image]) -> np.ndarray:
    """A model-free baseline for exercising the benchmark, separate from CLIP."""
    pixels = np.stack(
        [
            np.asarray(
                on_white(image).resize((16, 16), Image.Resampling.LANCZOS), dtype=np.float32
            ).reshape(-1)
            for image in images
        ]
    )
    pixels = pixels / 127.5 - 1
    return pixels / np.linalg.norm(pixels, axis=1, keepdims=True)


def focus_summary(cases: list[dict], runs: list[dict], top_k: int) -> dict:
    targets = {case["id"]: case for case in cases if case["cohort"] != "animated_original"}
    report = {}
    for run in runs:
        case = targets.get(run["case_id"])
        if case is None:
            continue
        cohort = report.setdefault(case["cohort"], {})
        family = cohort.setdefault(case["family_id"], {})
        arm = family.setdefault(
            run["arm"],
            {
                "attempts": 0,
                "failed": 0,
                "exact_top1_hits": 0,
                "exact_topk_hits": 0,
                "top_k": top_k,
            },
        )
        arm["attempts"] += 1
        arm["failed"] += run["status"] == "failed"
        matches = [candidate["sha256"] == case["target_sha256"] for candidate in run["candidates"]]
        arm["exact_top1_hits"] += bool(matches and matches[0])
        arm["exact_topk_hits"] += any(matches)
    return report


def run_benchmark(
    directory: Path,
    manifest: dict,
    manifest_sha: str,
    encoder: str,
    threshold: float,
    top_k: int,
) -> dict:
    encode = encode_images if encoder == "clip" else encode_pixels
    originals = {asset["id"]: asset for asset in manifest["assets"]}
    normal_member = []
    ids, first_frame, image_batch, embedding_batches = [], [], [], []
    started = time.perf_counter()
    for entry in originals.values():
        if not (entry["in_corpus"] or entry["in_focus_corpus"]):
            continue
        path = contained_path(directory, entry.get("gif_path") or entry["media_path"])
        with Image.open(path) as gif:
            for frame_number in indexed_frames(entry["frame_count"]):
                gif.seek(frame_number)
                image_batch.append(gif.convert("RGBA"))
                ids.append(entry["id"])
                first_frame.append(frame_number == 0)
                normal_member.append(entry["in_corpus"])
                if len(image_batch) == BATCH_SIZE:
                    embedding_batches.append(encode(image_batch))
                    image_batch.clear()
                    if len(ids) % 1024 == 0:
                        print(f"Encoded {len(ids)} catalog frames", file=sys.stderr, flush=True)
    if image_batch:
        embedding_batches.append(encode(image_batch))
    embeddings = np.concatenate(embedding_batches)
    if embeddings.shape[0] != len(ids) or not np.isfinite(embeddings).all():
        raise ValueError("Index embedding matrix does not match the corpus")

    index_encode_seconds = time.perf_counter() - started
    print(f"Catalog ready with {len(ids)} frame vectors", file=sys.stderr, flush=True)
    asset_ids = np.asarray(ids)
    first = np.asarray(first_frame)
    normal = np.asarray(normal_member)
    normal_first = first & normal
    normal_indexes = (
        (embeddings[normal_first], asset_ids[normal_first]),
        (embeddings[normal], asset_ids[normal]),
    )
    focus_indexes = ((embeddings[first], asset_ids[first]), (embeddings, asset_ids))

    runs = []
    for position, case in enumerate(manifest["cases"], start=1):
        if position % 200 == 0:
            print(f"Ranking query {position}/{len(manifest['cases'])}", file=sys.stderr, flush=True)
        case_id = case["id"]
        started = time.perf_counter()
        try:
            with Image.open(contained_path(directory, case["image"])) as image:
                query_vector = encode([image])[0]
            if not np.isfinite(query_vector).all():
                raise ValueError("Query embedding contains non-finite values")
        except (OSError, RuntimeError, ValueError) as exc:
            runs.extend(
                {
                    "case_id": case_id,
                    "arm": arm,
                    "status": "failed",
                    "candidates": [],
                    "elapsed_seconds": time.perf_counter() - started,
                    "failure_code": type(exc).__name__,
                }
                for arm in ARMS
            )
            continue
        query_seconds = time.perf_counter() - started
        indexes = normal_indexes if case["cohort"] == "animated_original" else focus_indexes
        for arm, (vectors, arm_ids) in zip(ARMS, indexes, strict=True):
            started = time.perf_counter()
            matches = rank_assets(vectors, arm_ids, query_vector, top_k, threshold)
            elapsed = query_seconds + (time.perf_counter() - started)
            candidates = []
            for rank, match in enumerate(matches, start=1):
                asset_id = match["reference_asset_id"]
                candidates.append(
                    {
                        "asset_id": asset_id,
                        "sha256": originals[asset_id]["sha256"],
                        "rank": rank,
                        "score": match["score"],
                    }
                )
            runs.append(
                {
                    "case_id": case_id,
                    "arm": arm,
                    "status": "completed",
                    "candidates": candidates,
                    "elapsed_seconds": elapsed,
                }
            )
    return {
        "version": 1,
        "manifest_sha256": manifest_sha,
        "encoder": encoder,
        "encoder_version": MODEL_VERSION if encoder == "clip" else "centered-rgb-16x16-v1",
        "threshold": threshold,
        "top_k": top_k,
        "arms": ARMS,
        "runtime": {
            "python": sys.version.split()[0],
            "pillow": PIL.__version__,
            "numpy": np.__version__,
        },
        "index_encode_seconds": index_encode_seconds,
        "index_frame_counts": dict(
            zip(ARMS, [int(normal_first.sum()), int(normal.sum())], strict=True)
        ),
        "index_media_counts": {
            kind: sum(
                asset["media_kind"] == kind and asset["in_corpus"] for asset in originals.values()
            )
            for kind in ("animated", "static")
        },
        "timing_scope": "Per-query file read, decode, warm encoding, and local ranking. "
        "Excludes queue and browser time.",
        "focus_index_frame_counts": dict(zip(ARMS, [int(first.sum()), len(ids)], strict=True))
        if manifest["focus_families"]
        else None,
        "focus_summary": focus_summary(manifest["cases"], runs, top_k),
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--source-manifest", type=Path, help="Local permitted GIF manifest")
    source.add_argument("--demo", action="store_true", help="Generate local procedural fixtures")
    parser.add_argument(
        "--distractor-manifest",
        type=Path,
        help="Optional local static images included in both arms",
    )
    parser.add_argument(
        "--focus-family",
        action="append",
        default=[],
        help="Extra full-catalog queries for this family; repeat for others",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="New or empty directory")
    parser.add_argument("--encoder", choices=("clip", "pixel"), default="clip")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--max-query-assets",
        type=int,
        help="Deterministic query subset across both splits and labels",
    )
    parser.add_argument(
        "--threshold", type=float, help="Defaults to .82 for CLIP and .60 for pixel"
    )
    parser.add_argument("--top-k", type=int, choices=range(1, 4), default=3)
    args = parser.parse_args()
    threshold = (
        args.threshold if args.threshold is not None else (0.82 if args.encoder == "clip" else 0.60)
    )
    if not -1 <= threshold <= 1:
        parser.error("--threshold must be a finite number between -1 and 1")
    if args.max_query_assets is not None and args.max_query_assets < 4:
        parser.error("--max-query-assets must be at least 4 to cover both splits and labels")
    output = args.output_dir.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("--output-dir must be new or empty")
    if args.encoder == "clip":
        weights = get_settings().model_cache_root / "clip-vit-base-patch32" / "model.safetensors"
        if not weights.is_file():
            parser.error(
                "Pinned CLIP weights are missing from the model cache. "
                "Prepare local weights or select --encoder pixel for the baseline."
            )

    try:
        if args.demo:
            assets, source_sha = demo_corpus(), None
        else:
            source_path = args.source_manifest or get_settings().reference_root / "manifest.json"
            if not source_path.is_file():
                parser.error(
                    "Local GIF corpus is missing. Supply --source-manifest, "
                    "prepare the Noto reference corpus, or use --demo."
                )
            assets, source_sha = load_corpus(source_path)
        distractors, distractor_sha = (
            load_distractors(args.distractor_manifest) if args.distractor_manifest else ([], None)
        )
        manifest = prepare_queries(
            assets,
            output,
            args.seed,
            source_sha,
            args.max_query_assets,
            distractors,
            distractor_sha,
            set(args.focus_family),
        )
        raw_manifest = write_json(output, "manifest.json", manifest)
        print(
            f"Frozen {len(manifest['cases'])} queries and {len(manifest['assets'])} source files",
            file=sys.stderr,
            flush=True,
        )
        results = run_benchmark(
            output, manifest, sha256(raw_manifest), args.encoder, threshold, args.top_k
        )
        write_json(output, "results.json", results)
    except ImportError as exc:
        parser.error(f"{exc}. Install the retrieval dependencies or choose --encoder pixel.")
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    failures = sum(run["status"] == "failed" for run in results["runs"])
    print(f"Wrote {len(manifest['cases'])} cases and {len(results['runs'])} runs to {output}")
    if failures:
        print(f"{failures} failed runs are recorded in results.json", file=sys.stderr)
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
