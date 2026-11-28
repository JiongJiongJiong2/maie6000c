"""Score frozen local retrieval runs and prepare an anonymous pool for Label Studio."""

import argparse
import hashlib
import json
import math
import shutil
import statistics
import tempfile
from collections import Counter, defaultdict
from itertools import zip_longest
from pathlib import Path


def fingerprint(value):
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize(rows):
    counts = Counter(row["status"] for row in rows)
    hits = [r["exact_rank"] for r in rows]
    times = sorted(r["seconds"] for r in rows if r["seconds"] is not None)
    by_family = defaultdict(list)
    for row in rows:
        by_family[row["family"]].append(row["exact_rank"] is not None)
    return dict(
        planned=len(rows),
        distinct_families=len(by_family),
        macro_family_top3_rate=statistics.mean(map(statistics.mean, by_family.values())),
        statuses=dict(counts),
        top1=sum(rank == 1 for rank in hits),
        top3=sum(rank is not None and rank <= 3 for rank in hits),
        returned_any=sum(row["returned"] > 0 for row in rows),
        abstained=sum(row["returned"] == 0 and row["status"] == "completed" for row in rows),
        p50_seconds=statistics.median(times) if times else None,
        p95_seconds=times[math.ceil(len(times) * 0.95) - 1] if times else None,
    )


def select_review_cases(groups, max_cases):
    # Round robin gives small, named focus cohorts a place in a limited human queue.
    ordered = [sorted(group, key=lambda item: item["priority"]) for _, group in sorted(groups)]
    return [item for batch in zip_longest(*ordered) for item in batch if item][:max_cases]


def build(source, destination, max_cases=60):
    if destination.exists() or max_cases < 1:
        raise ValueError("Choose a new output directory and a positive review case limit")
    raw = (source / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    raw_runs = (source / "results.json").read_bytes()
    results = json.loads(raw_runs)
    if results["manifest_sha256"] != fingerprint(raw) or results["top_k"] != 3:
        raise ValueError("Expected Top-3 results from this exact frozen manifest")
    assets = {a["id"]: a for a in manifest["assets"]}
    cases = {c["id"]: c for c in manifest["cases"]}
    arms = results["arms"]
    if (
        len(assets) != len(manifest["assets"])
        or len(cases) != len(manifest["cases"])
        or not arms
        or len(arms) != len(set(arms))
    ):
        raise ValueError("Duplicate or missing asset/case/arm identity")
    runs = {}
    for run in results["runs"]:
        key = run["case_id"], run["arm"]
        if key in runs or key[0] not in cases or key[1] not in arms:
            raise ValueError("Duplicate or unexpected run")
        runs[key] = run
    evidence, groups, queues = [], defaultdict(list), defaultdict(list)
    for case_id, case in cases.items():
        target = assets[case["target_asset_id"]]
        if target["sha256"] != case["target_sha256"]:
            raise ValueError("Target identity mismatch")
        cohort = case.get("cohort", "animated_original")
        pool, top1 = {}, []
        for arm in arms:
            run = runs.get((case_id, arm), {"status": "missing", "candidates": []})
            candidates = run["candidates"]
            if (
                run["status"] not in {"completed", "failed", "missing"}
                or len(candidates) > 3
                or (run["status"] != "completed" and candidates)
            ):
                raise ValueError("Invalid run status or candidate list")
            ranks, seen = [], set()
            for rank, candidate in enumerate(candidates, 1):
                aid = candidate["asset_id"]
                if (
                    aid in seen
                    or assets[aid]["sha256"] != candidate["sha256"]
                    or candidate.get("rank", rank) != rank
                ):
                    raise ValueError("Candidate identity or rank mismatch")
                seen.add(aid)
                pool.setdefault(aid, {})[arm] = rank
                if candidate["sha256"] == target["sha256"]:
                    ranks.append(rank)
            top1.append(candidates[0]["asset_id"] if candidates else None)
            record = dict(
                case_id=case_id,
                arm=arm,
                cohort=cohort,
                split=case["split"],
                family=case["family_id"],
                category=case["category"],
                transform=case["transform"],
                status=run["status"],
                returned=len(candidates),
                exact_rank=min(ranks, default=None),
                seconds=run.get("elapsed_seconds"),
            )
            evidence.append(record)
            groups[(cohort, case["split"], case["category"], arm)].append(record)
        if pool:
            interest = (
                "disagreement"
                if len(set(top1)) > 1
                else ("miss" if top1[0] != target["id"] else "exact_control")
            )
            # Sort by the case hash within strata, independent of corpus/list order.
            priority = fingerprint(case_id.encode())
            theme = case["family_id"] if cohort in {"static_focus", "animated_focus"} else ""
            queues[(cohort, theme, interest)].append(
                dict(case=case, candidates=pool, interest=interest, priority=priority)
            )
    selected = select_review_cases(queues.items(), max_cases)
    destination.parent.mkdir(parents=True, exist_ok=True)
    dataset_id = fingerprint(raw_runs + str(max_cases).encode())[:24]
    with tempfile.TemporaryDirectory(dir=destination.parent) as work:
        root = Path(work) / "bundle"
        media = root / "site" / "media"
        media.mkdir(parents=True)

        def copy_checked(relative, expected):
            path = (source / relative).resolve()
            if not path.is_relative_to(source.resolve()):
                raise ValueError("Media path outside benchmark directory")
            name = expected + path.suffix.lower()
            out = media / name
            if not out.exists():
                if fingerprint(path.read_bytes()) != expected:
                    raise ValueError("Media SHA does not match manifest")
                shutil.copyfile(path, out)
            return "media/" + name

        blinded, key_rows = [], []

        def asset_url(asset):
            return copy_checked(asset.get("media_path") or asset["gif_path"], asset["sha256"])

        for row in selected:
            case = row["case"]
            cid = case["id"]
            pool = []
            for aid, arm_ranks in row["candidates"].items():
                opaque = fingerprint(f"{dataset_id}/{cid}/{aid}".encode())[:20]
                pool.append(dict(candidate_id=opaque, media_url=asset_url(assets[aid])))
                key_rows.append(
                    dict(
                        case_id=cid,
                        candidate_id=opaque,
                        asset_id=aid,
                        ranks=arm_ranks,
                        stratum=row["interest"],
                    )
                )
            blinded.append(
                dict(
                    case_id=cid,
                    query_url=copy_checked(case["image"], case["image_sha256"]),
                    reference_url=asset_url(assets[case["target_asset_id"]]),
                    candidates=sorted(pool, key=lambda c: c["candidate_id"]),
                )
            )
        report = dict(
            manifest_sha256=fingerprint(raw),
            results_sha256=fingerprint(raw_runs),
            encoder=results["encoder"],
            encoder_version=results["encoder_version"],
            threshold=results["threshold"],
            seed=manifest["seed"],
            source_manifest_sha256=manifest.get("source_manifest_sha256"),
            distractor_manifest_sha256=manifest.get("distractor_manifest_sha256"),
            timing_scope=results.get("timing_scope"),
            eligible_cases=len(cases),
            assets=len(assets),
            arms=arms,
            index_media_counts=results.get("index_media_counts"),
            focus_index_frame_counts=results.get("focus_index_frame_counts"),
            focus_summary=results.get("focus_summary"),
            catalog_frame_counts=results.get("index_frame_counts"),
            review_cases=len(blinded),
            review_pairs=len(key_rows),
            review_case_limit=max_cases,
            note="Known targets are scored by exact frozen file SHA. Human labels "
            "are separate; the capped review pool is not a random user sample.",
            groups=[
                dict(cohort=k[0], split=k[1], category=k[2], arm=k[3], **summarize(rows))
                for k, rows in groups.items()
            ],
        )
        write_json(root / "site" / "review.json", dict(dataset_id=dataset_id, cases=blinded))
        write_json(root / "review-key.json", dict(dataset_id=dataset_id, pairs=key_rows))
        write_json(root / "scores.json", report)
        write_json(root / "case-scores.json", evidence)
        root.rename(destination)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-cases", type=int, default=60)
    args = parser.parse_args()
    report = build(args.source, args.output, args.max_cases)
    print(
        f"{report['eligible_cases']} queries scored, {report['review_cases']} cases / "
        f"{report['review_pairs']} unique candidate pairs queued for blind rating"
    )
