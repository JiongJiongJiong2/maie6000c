"""Paired CLIP retrieval from full images, pixel-only proposed crops and reference boxes."""

from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from scripts.benchmark_gif_retrieval import BATCH_SIZE, indexed_frames, write_json
from services.common.storage import contained_path, sha256
from services.retrieval.encoder import MODEL_VERSION, encode_images
from services.retrieval.engine import rank_assets

THRESHOLD = 0.82
TOP_K = 3
DEV_ASSETS_PER_CATEGORY = 20
STRESS_ASSETS_PER_CATEGORY = 12
ARMS = ("full", "auto", "oracle")


def build_index(root: Path, cache: Path) -> None:
    raw = (root / "manifest.json").read_bytes()
    cache.parent.mkdir(parents=True, exist_ok=True)
    batches, ids, images = [], [], []
    for asset in json.loads(raw)["assets"]:
        if not asset["in_corpus"]:
            continue
        data = contained_path(root, asset.get("gif_path") or asset["media_path"]).read_bytes()
        if sha256(data) != asset["sha256"]:
            raise ValueError("Catalog original SHA mismatch")
        with Image.open(io.BytesIO(data)) as src:
            for frame in indexed_frames(asset["frame_count"]):
                src.seek(frame)
                images.append(src.convert("RGBA"))
                ids.append(asset["id"])
                if len(images) == BATCH_SIZE:
                    batches.append(encode_images(images))
                    images.clear()
    if images:
        batches.append(encode_images(images))
    vectors = np.concatenate(batches)
    if not np.isfinite(vectors).all():
        raise ValueError("Nonfinite CLIP features")
    with tempfile.NamedTemporaryFile(dir=cache.parent, suffix=".npz", delete=False) as tmp:
        np.savez(
            tmp,
            model=np.array(MODEL_VERSION),
            manifest_sha=np.array(sha256(raw)),
            ids=np.array(ids),
            vectors=vectors,
        )
    os.replace(tmp.name, cache)
    print(f"Cached {len(vectors)} frames, {len(set(ids))} distinct assets", flush=True)


def sampled_cases(cases: list[dict], limit: int) -> list[dict]:
    """Round-robin over packs within each category, keeping all variants of an asset."""
    families = defaultdict(lambda: defaultdict(set))
    for c in cases:
        families[c["category"]][c["family_id"]].add(c["target_asset_id"])
    selected = set()
    for family in families.values():
        packs = [sorted(family[name]) for name in sorted(family)]
        ordered = [pack[i] for i in range(max(map(len, packs))) for pack in packs if i < len(pack)]
        selected.update(ordered[:limit])
    return [c for c in cases if c["target_asset_id"] in selected]


def read_image(root: Path, case: dict) -> Image.Image:
    data = contained_path(root, case["image"]).read_bytes()
    if sha256(data) != case["image_sha256"]:
        raise ValueError(f"Query bytes changed: {case['id']}")
    with Image.open(io.BytesIO(data)) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def stress_cases(root: Path, cases: list[dict], out: Path) -> list[dict]:
    """Render paired PNG/JPEG/background/occlusion variants of a second, tall messenger UI."""
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in sampled_cases(
        [c for c in cases if c["transform"] == "tight_crop"], STRESS_ASSETS_PER_CATEGORY
    ):
        tile = read_image(root, case)
        seed = int(case["id"][:8], 16)
        width, height = 360, 560 + seed % 48
        edge = 130 + seed % 47
        tile = ImageOps.contain(tile, (edge, edge))
        x = width - 48 - tile.width if seed % 2 else 48
        y = 185 + seed % 65
        box = (x, y, x + tile.width, y + tile.height)
        canvas = Image.new("RGB", (width, height), "#e8ede7")
        draw = ImageDraw.Draw(canvas)
        for row in range(48, height - 48, 24):
            for col in range((row // 24 % 2) * 12, width, 24):
                draw.arc((col, row, col + 8, row + 8), 20, 140, fill="#cfd9d2")
        draw.rectangle((0, 0, width, 46), fill="#2f4d52")
        draw.text((18, 17), "<    Project group", fill="white")
        draw.rounded_rectangle((50, 66, 178, 96), radius=9, fill="white")
        draw.text((60, 75), "The draft is ready", fill="#162d35")
        draw.rounded_rectangle((176, 112, 310, 146), radius=9, fill="#c4efcf")
        draw.text((186, 123), "Which one was it?", fill="#162d35")
        for cx, cy in [(26, 78), (332, 129), (332 if seed % 2 else 26, y + 12)]:
            draw.ellipse((cx - 12, cy - 12, cx + 12, cy + 12), fill="#9579b3")
        draw.rounded_rectangle((40, height - 134, 190, height - 102), radius=9, fill="white")
        draw.text((51, height - 125), "I remember this one", fill="#162d35")
        draw.rectangle((0, height - 52, width, height), fill="#fafafa")
        draw.rounded_rectangle(
            (24, height - 44, width - 24, height - 11), radius=15, outline="#929c95"
        )
        canvas.paste(tile, (x, y))
        occluded = canvas.copy()
        cover = ImageDraw.Draw(occluded)
        cover.rectangle((x, y + int(tile.height * 0.70), box[2] - 1, box[3] - 1), fill="#3a4663")
        cover.text((x + 4, y + int(tile.height * 0.70) + 2), "Forwarded", fill="white")
        variants = [
            ("tile_png", tile, "PNG", None),
            ("wallpaper_png", canvas, "PNG", box),
            ("wallpaper_jpeg", canvas, "JPEG", box),
            ("occluded_jpeg", occluded, "JPEG", box),
        ]
        for variant, image, fmt, query_box in variants:
            row_id = f"{case['id']}-{variant}"
            filename = row_id + (".jpg" if fmt == "JPEG" else ".png")
            image.save(out / filename, format=fmt, **({"quality": 52} if fmt == "JPEG" else {}))
            rows.append(
                {
                    **case,
                    "id": row_id,
                    "transform": variant,
                    "image": filename,
                    "image_sha256": sha256((out / filename).read_bytes()),
                    "transform_parameters": {"image_box": query_box},
                }
            )
    return rows


def iou(first, second) -> float:
    def area(box):
        return max(0, box[2] - box[0]) * max(0, box[3] - box[1])

    overlap = area(
        (
            max(first[0], second[0]),
            max(first[1], second[1]),
            min(first[2], second[2]),
            min(first[3], second[3]),
        )
    )
    return overlap / (area(first) + area(second) - overlap)


def paired_rows(root, cases, propose, vectors, ids, encode=encode_images):
    """Estimator sees one decoded image only. All three arms rank against one index."""
    result = []
    # Limit resident memory and reuse identical crops within each query.
    for start in range(0, len(cases), BATCH_SIZE):
        pending, images = [], []
        for case in cases[start : start + BATCH_SIZE]:
            image = read_image(root, case)
            suggested = propose(image)
            full = (0, 0, *image.size)
            oracle = tuple(case["transform_parameters"].get("image_box") or full)
            auto = tuple(suggested) if suggested is not None else full
            slots = {}
            for box in (full, auto, oracle):
                if not (
                    0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height
                ):
                    raise ValueError(f"Invalid crop {box} for {image.size}")
                if box not in slots:
                    slots[box] = len(images)
                    images.append(image if box == full else image.crop(box))
            row = {
                key: case[key]
                for key in (
                    "id",
                    "target_asset_id",
                    "family_id",
                    "transform",
                    "category",
                    "image_sha256",
                )
            }
            row.update(
                proposed_box=suggested,
                oracle_box=oracle,
                proposal_iou=iou(auto, oracle) if suggested is not None else None,
            )
            pending.append((row, [slots[box] for box in (full, auto, oracle)]))
        features = np.concatenate(
            [encode(images[i : i + BATCH_SIZE]) for i in range(0, len(images), BATCH_SIZE)]
        )
        if len(features) != len(images) or not np.isfinite(features).all():
            raise ValueError("Invalid query features")
        ranked = [rank_assets(vectors, ids, vector, TOP_K, THRESHOLD) for vector in features]
        for row, slots in pending:
            for arm, pos in zip(ARMS, slots, strict=True):
                row[arm] = [match["reference_asset_id"] for match in ranked[pos]]
            result.append(row)
        if (start // BATCH_SIZE) % 8 == 7:
            print(f"Scored {len(result)}/{len(cases)}", flush=True)
    return result


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        for name in ("all", row["transform"]):
            groups[(row["category"], name)].append(row)
    output = {}
    for (category, name), group in groups.items():
        positive = category == "in_library"
        baseline = [
            r["target_asset_id"] in r["full"] if positive else bool(r["full"]) for r in group
        ]
        stats = {"n": len(group), "proposed": sum(r["proposed_box"] is not None for r in group)}
        for arm in ARMS:
            selected = [r["target_asset_id"] in r[arm] if positive else bool(r[arm]) for r in group]
            stats[arm] = {
                "exact_top3" if positive else "false_candidate": sum(selected),
                "gained_vs_full": sum(b and not a for a, b in zip(baseline, selected, strict=True)),
                "lost_vs_full": sum(a and not b for a, b in zip(baseline, selected, strict=True)),
            }
            if positive:
                stats[arm]["exact_top1"] = sum(r[arm][:1] == [r["target_asset_id"]] for r in group)
        output.setdefault(category, {})[name] = stats
    return output


def run(args, parser):
    from services.retrieval import chat_crop

    if args.out is None:
        parser.error("run needs --out")
    raw = (args.source / "manifest.json").read_bytes()
    manifest_sha = sha256(raw)
    with np.load(args.cache, allow_pickle=False) as cache:
        if cache["manifest_sha"].item() != manifest_sha or cache["model"].item() != MODEL_VERSION:
            raise ValueError("Index model or manifest mismatch")
        vectors, ids = cache["vectors"], cache["ids"]
    config = {
        "detector_sha256": sha256(Path(chat_crop.__file__).read_text(encoding="utf8").encode()),
        "evaluation_script_sha256": sha256(Path(__file__).read_text(encoding="utf8").encode()),
        "manifest_sha256": manifest_sha,
        "encoder": MODEL_VERSION,
        "threshold": THRESHOLD,
        "top_k": TOP_K,
        "index_assets": len(set(ids)),
        "index_frames": len(ids),
        "index_sha256": sha256(args.cache.read_bytes()),
        "fallback": "whole image",
        "development_asset_limit_per_category": DEV_ASSETS_PER_CATEGORY,
        "stress_asset_limit_per_category": STRESS_ASSETS_PER_CATEGORY,
        "stress_tile_source": "resized tight_crop; same pixels pasted into an additional tall UI",
    }
    dev_sha = None
    if args.split != "development":
        if args.dev_report is None:
            parser.error("held-out evaluation requires a completed frozen --dev-report")
        dev_raw = args.dev_report.read_bytes()
        dev = json.loads(dev_raw)
        if dev["split"] != "development" or dev["config"] != config:
            raise ValueError("Frozen development report and current configuration disagree")
        dev_sha = sha256(dev_raw)
    args.out.mkdir(parents=True, exist_ok=True)
    split = "final" if args.split == "stress" else args.split
    cases = [
        c
        for c in json.loads(raw)["cases"]
        if c["split"] == split and c["cohort"] == "animated_original"
    ]
    image_root = args.source
    if args.split == "development":
        cases = sampled_cases(cases, DEV_ASSETS_PER_CATEGORY)
    elif args.split == "stress":
        image_root = args.out / "images"
        cases = stress_cases(args.source, cases, image_root)
    rows = paired_rows(image_root, cases, chat_crop.propose_chat_crop, vectors, ids)
    # Compare identities for the full arm to the historical run, independent of crop quality.
    archived = args.source / "results.json"
    mismatches = None
    if args.split != "stress" and archived.exists():
        past = json.loads(archived.read_bytes())
        if (past["manifest_sha256"], past["threshold"], past["top_k"], past["encoder_version"]) != (
            manifest_sha,
            THRESHOLD,
            TOP_K,
            MODEL_VERSION,
        ):
            raise ValueError("Archived baseline used a different retrieval setup")
        baseline = {
            r["case_id"]: [x["asset_id"] for x in r["candidates"]]
            for r in past["runs"]
            if r["arm"] == "multi_frame" and r["status"] == "completed"
        }
        mismatches = [r["id"] for r in rows if baseline[r["id"]] != r["full"]]
    report = {
        "split": args.split,
        "config": config,
        "development_report_sha256": dev_sha,
        "archived_full_arm_mismatches": mismatches,
        "summary": summarize(rows),
        "case_count": len(rows),
        "asset_count": len({r["target_asset_id"] for r in rows}),
        "rows": rows,
    }
    write_json(args.out, "report.json", report)
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["index", "run"])
    parser.add_argument("source", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--split", choices=["development", "final", "stress"], default="development"
    )
    parser.add_argument("--dev-report", type=Path)
    args = parser.parse_args()
    if args.action == "index":
        build_index(args.source, args.cache)
    else:
        run(args, parser)
