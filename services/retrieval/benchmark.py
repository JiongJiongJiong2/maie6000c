"""Validate frozen screenshot cases and summarize A/B/C evidence without network calls."""

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from services.common.storage import validate_image


def checked_file(root, relative, digest, animated=False):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Sample file missing or outside manifest directory")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Sample checksum mismatch")
    validate_image(data, animated_gif=animated)


def validate_manifest(manifest, root):
    if manifest.get("version") != 1 or not manifest.get("frozen_at"):
        raise ValueError("Version 1 and freeze date required")
    cases = manifest["cases"]
    if not cases:
        raise ValueError("No eligible samples; collect real screenshots first")
    seen, families, targets, screenshots = set(), {}, {}, set()
    for case in cases:
        if case["id"] in seen:
            raise ValueError("Duplicate case id")
        seen.add(case["id"])
        if case["split"] not in {"development", "final"}:
            raise ValueError("Invalid split")
        if case["category"] not in {"in_library", "out_of_library", "unknown"}:
            raise ValueError("Invalid category")
        if case.get("origin") != "real_screenshot" or not case.get("reviewer"):
            raise ValueError("Real screenshot provenance and human reviewer required")
        family = case["family_id"]
        if not family or families.setdefault(family, case["split"]) != case["split"]:
            raise ValueError("Family leakage across splits")
        if case["image_sha256"] in screenshots:
            raise ValueError("Duplicate screenshot")
        screenshots.add(case["image_sha256"])
        checked_file(root, case["image"], case["image_sha256"])
        target = case.get("target_sha256")
        if case["category"] == "unknown":
            if target or case.get("target"):
                raise ValueError("Unknown target must remain unlabeled")
        else:
            if not target or targets.setdefault(target, case["split"]) != case["split"]:
                raise ValueError("Missing target or target leakage across splits")
            checked_file(root, case["target"], target, animated=True)
    return cases


def summarize(cases, runs):
    """Failures stay in denominator; unknown targets never become negative labels."""
    lookup = {case["id"]: case for case in cases}
    seen = set()
    groups = {}
    for run in runs:
        case = lookup[run["case_id"]]
        arm = run["arm"]
        if arm not in {"A", "B", "C"} or (case["id"], arm) in seen:
            raise ValueError("Invalid arm or duplicate case/arm attempt")
        seen.add((case["id"], arm))
        if run["status"] not in {"completed", "failed"}:
            raise ValueError("Unfinished run")
        elapsed = run["elapsed_seconds"]
        if isinstance(elapsed, bool) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("Invalid duration")
        for field in ("search_calls", "planner_calls", "downloads_used"):
            if type(run[field]) is not int or run[field] < 0:
                raise ValueError("Invalid counter")
        if run["search_calls"] > 2 or run["planner_calls"] > 2 or run["downloads_used"] > 6:
            raise ValueError("Task budget exceeded")
        if arm == "A" and any(run[k] for k in
                              ("search_calls", "planner_calls", "downloads_used")):
            raise ValueError("Local arm used external calls")
        candidates = run["candidates"]
        if len(candidates) > 3 or (run["status"] == "failed" and candidates):
            raise ValueError("Invalid candidate result")
        if len({c["sha256"] for c in candidates}) != len(candidates):
            raise ValueError("Duplicate candidates")
        group = groups.setdefault((case["split"], case["category"], arm), [])
        group.append((case, run))
    reports = []
    for (split, category, arm), rows in sorted(groups.items()):
        hits = sum(any(c["sha256"] == case.get("target_sha256") and
                       c.get("decoded_multiframe") is True for c in run["candidates"])
                   for case, run in rows)
        candidates = [c for _, run in rows for c in run["candidates"]]
        durations = [run["elapsed_seconds"] for _, run in rows]
        reports.append({
            "split": split, "category": category, "arm": arm, "attempts": len(rows),
            "exact_sha_top3_hits": hits if category != "unknown" else None,
            "exact_sha_top3_rate": hits / len(rows) if category != "unknown" else None,
            "candidate_count": len(candidates),
            "decoded_multiframe_count": sum(c.get("decoded_multiframe") is True
                                             for c in candidates),
            "p50_seconds": float(np.percentile(durations, 50)),
            "p95_seconds": float(np.percentile(durations, 95)),
            "failures": dict(Counter(run.get("failure_code", "unspecified")
                                     for _, run in rows if run["status"] == "failed")),
            "calls": {key: sum(run[key] for _, run in rows) for key in
                      ("search_calls", "planner_calls", "downloads_used")},
        })
    missing = [{"case_id": case["id"], "arm": arm} for case in cases for arm in "ABC"
               if (case["id"], arm) not in seen]
    return {"complete_matrix": not missing, "missing": missing, "groups": reports,
            "note": "Exact SHA only; equivalent encodings require separate human review. "
                    "Counts describe supplied evidence, not independent media verification."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--runs", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    cases = validate_manifest(json.loads(raw), args.manifest.parent)
    result = {"eligible_cases": len(cases), "manifest_sha256": hashlib.sha256(raw).hexdigest()}
    if args.runs:
        result.update(summarize(cases, json.loads(args.runs.read_text(encoding="utf-8"))))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
