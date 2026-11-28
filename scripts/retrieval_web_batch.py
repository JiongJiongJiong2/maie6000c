"""Freeze anonymous image-only web queries or score existing run-suite receipts offline."""

import argparse
import hashlib
import json
import tempfile
from collections import Counter, defaultdict
from itertools import zip_longest
from pathlib import Path

from scripts import meme50_acceptance as acceptance
from scripts.prepare_chinese_meme_corpus import LICENSE, REPO, REV, write_json
from services.common.media import inspect_media


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_bytes(root, name, expected):
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("Media path escapes dataset")
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError("Frozen media SHA mismatch")
    return data


def permitted(asset):
    primary = asset["source"].startswith(f"{REPO}/blob/{REV}/public/meme/")
    noto = asset["source"].startswith("https://fonts.gstatic.com/s/e/notoemoji/")
    return (primary and asset["license"] == LICENSE) or (noto and "CC BY 4.0" in asset["license"])


def freeze(manifest_path, output, limit):
    if limit < 1 or output.exists():
        raise ValueError("Select a positive case limit and a new output directory")
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    assets = {a["id"]: a for a in manifest["assets"]}
    groups, seen = defaultdict(list), set()
    for case in sorted(manifest["cases"], key=lambda c: c["id"]):
        asset = assets[case["target_asset_id"]]
        if (
            case["split"] != "development"
            or asset["split"] != "development"
            or case.get("cohort", "animated_original") != "animated_original"
            or asset["frame_count"] < 2
            or not permitted(asset)
            or asset["sha256"] in seen
        ):
            continue
        if case["target_sha256"] != asset["sha256"] or case["family_id"] != asset["family_id"]:
            raise ValueError("Source manifest target mismatch")
        seen.add(asset["sha256"])
        groups[asset["family_id"]].append((case, asset))
    if len(seen) < limit:
        raise ValueError(f"Requested {limit} distinct targets; only {len(seen)} are eligible")
    order = sorted(groups, key=lambda s: digest(s.encode()))
    selected = [p for cycle in zip_longest(*(groups[f] for f in order)) for p in cycle if p]
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        staging = Path(tmp) / "bundle"
        (staging / "queries").mkdir(parents=True)
        private = staging / "private"
        private.mkdir()
        public_cases, answers = [], {}
        for index, (case, asset) in enumerate(selected[:limit], 1):
            case_id = f"web-{index:04}"
            query = checked_bytes(manifest_path.parent, case["image"], case["image_sha256"])
            meta = inspect_media(query)
            query_name = f"queries/{case_id}.{meta.suffix}"
            (staging / query_name).write_bytes(query)
            # The existing suite resolves input_path from repository root.
            query_path = output / query_name
            if query_path.is_relative_to(acceptance.ROOT):
                query_path = query_path.relative_to(acceptance.ROOT)
            public_cases.append(
                dict(
                    case_id=case_id,
                    split="development",
                    family=f"f{order.index(case['family_id']) + 1:04}",
                    input_path=query_path.as_posix(),
                    sha256=meta.sha256,
                    format=meta.format,
                    media_kind=meta.media_kind,
                )
            )
            target = checked_bytes(manifest_path.parent, asset["gif_path"], asset["sha256"])
            target_meta = inspect_media(target)
            if target_meta.format != "GIF" or target_meta.media_kind != "animated":
                raise ValueError("Expected a decoded multiframe GIF as the private target")
            original = f"{case_id}.gif"
            (private / original).write_bytes(target)
            answers[case_id] = dict(
                query_sha256=meta.sha256,
                target_sha256=asset["sha256"],
                original=original,
                family=asset["family_id"],
                source=asset["source"],
                license=asset["license"],
                local_case_id=case["id"],
                transform=case["transform"],
            )
        public = {"version": "image-only-web-pilot-v1", "cases": public_cases}
        # ASCII escapes keep the legacy runner's locale-dependent reader portable.
        (staging / "manifest.json").write_text(
            json.dumps(public, indent=2) + "\n", encoding="ascii"
        )
        write_json(
            private / "answers.json",
            dict(
                source_manifest_sha256=digest(raw),
                query_manifest_sha256=digest((staging / "manifest.json").read_bytes()),
                cases=answers,
            ),
        )
        staging.rename(output)
    return len(answers)


def score(batch, runs=None):
    path = batch / "manifest.json"
    manifest_hash = digest(path.read_bytes())
    manifest, cases = acceptance.load_manifest(path, "development")
    key = json.loads((batch / "private" / "answers.json").read_bytes())
    expected = key["cases"]
    if key["query_manifest_sha256"] != manifest_hash or {case["case_id"] for case in cases} != set(
        expected
    ):
        raise ValueError("Query manifest does not match its private answer key")
    for case in cases:
        _, meta = acceptance.input_bytes(case)
        answer = expected[case["case_id"]]
        if meta.sha256 != answer["query_sha256"]:
            raise ValueError("Query and answer binding differs")
        checked_bytes(batch / "private", answer["original"], answer["target_sha256"])

    rows = {
        cid: dict(case_id=cid, status="missing", exact_rank=None, animation_rank=None)
        for cid in expected
    }
    if runs is not None:
        suite, entries = acceptance.suite_records(runs)
        if (
            suite["manifest_sha256"] != manifest_hash
            or suite["split"] != "development"
            or suite["manifest_version"] != manifest["version"]
        ):
            raise ValueError("Run suite was executed with a different query manifest or split")
        attempts = {item["case_id"]: item for item in suite["cases"]}
        for cid, directory, evidence in entries:
            if cid not in expected:
                raise ValueError("Unplanned case in suite")
            answer = expected[cid]
            checked_bytes(directory, evidence["review_input_file"], answer["query_sha256"])
            if (
                evidence.get("input_sha256", answer["query_sha256"]) != answer["query_sha256"]
                or evidence["configuration_fingerprint"] != suite["configuration_fingerprint"]
                or evidence["code_fingerprint"] != suite["code_fingerprint"]
            ):
                raise ValueError("Case receipt differs from frozen inputs or suite configuration")
            job = evidence.get("job", {})
            rows[cid].update(
                status="failed",
                elapsed_seconds=attempts[cid]["elapsed_seconds"],
                error_type=evidence.get("error_type") or job.get("error_code"),
                ledger=(job.get("progress") or {}).get("ledger"),
            )
            if evidence.get("machine_status") != "passed" or attempts[cid]["exit_code"] != 0:
                continue
            if (
                not evidence.get("input_sha256")
                or job.get("status") != "completed"
                or not job.get("result_revision")
                or not job.get("job_id")
            ):
                raise ValueError("Incomplete success receipt")
            published = acceptance.bound_rows([(cid, directory, evidence)])
            ranks = [int(binding["rank"]) for binding, _, _ in published]
            hashes = [binding["sha256"] for binding, _, _ in published]
            if (
                ranks != list(range(1, len(ranks) + 1))
                or len(set(hashes)) != len(hashes)
                or job["result_count"] != len(ranks)
            ):
                raise ValueError("Incomplete or inconsistent final ranking")
            animated = [
                binding["sha256"]
                for binding, _, item in published
                if item["media_kind"] == "animated"
            ]
            target = answer["target_sha256"]
            rows[cid].update(
                status="completed",
                returned=len(hashes),
                animated=len(animated),
                exact_rank=hashes.index(target) + 1 if target in hashes else None,
                animation_rank=animated.index(target) + 1 if target in animated else None,
            )
    metrics = {}
    for field in ["exact_rank", "animation_rank"]:
        metrics[field] = {
            f"top{k}": sum(r[field] is not None and r[field] <= k for r in rows.values())
            for k in (1, 3)
        }
    return dict(
        query_manifest_sha256=manifest_hash,
        planned=len(rows),
        statuses=dict(Counter(r["status"] for r in rows.values())),
        exact_hits_among_all_planned=metrics,
        cases=list(rows.values()),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    make = commands.add_parser("freeze", help="Prepare a source-blind development pilot offline")
    make.add_argument("manifest", type=Path)
    make.add_argument("output", type=Path)
    make.add_argument("--limit", type=int, default=3)
    check = commands.add_parser("score", help="Score local run-suite receipts offline")
    check.add_argument("batch", type=Path)
    check.add_argument("--runs", type=Path, help="Omit to report the pre-run denominator")
    check.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "freeze":
        count = freeze(args.manifest, args.output, args.limit)
        print(f"Prepared {count} image-only queries and separate private reference files")
    else:
        report = score(args.batch, args.runs)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps(report["statuses"]))


if __name__ == "__main__":
    main()
