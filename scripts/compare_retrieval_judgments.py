"""Join two independent Label Studio JSON exports to the private review key."""

import argparse
import json
from collections import Counter
from pathlib import Path

LABELS = {"exact", "variant", "wrong", "unsure", "broken"}


def read_labels(tasks, dataset_id, known):
    labels, seen, annotators = {}, set(), set()
    for task in tasks:
        data = task["data"]
        pair = data["case_id"], data["candidate_id"]
        if data["dataset_id"] != dataset_id or pair not in known or pair in seen:
            raise ValueError("Export contains an unknown, duplicate or different-dataset pair")
        seen.add(pair)
        active = [a for a in task.get("annotations", []) if not a.get("was_cancelled")]
        if not active:
            continue
        if len(active) != 1:
            raise ValueError("Expected one independent judgment per pair per export")
        result = [r for r in active[0]["result"] if r.get("from_name") == "gif_match"]
        if (
            len(result) != 1
            or len(result[0]["value"].get("choices", [])) != 1
            or result[0]["value"]["choices"][0] not in LABELS
        ):
            raise ValueError("Missing or invalid gif_match choice")
        labels[pair] = result[0]["value"]["choices"][0]
        operator = active[0].get("completed_by")
        if isinstance(operator, dict):
            operator = operator.get("id")
        if operator is not None:
            annotators.add(operator)
    return labels, annotators


def compare(key, first, second):
    projects_a = {task["project"] for task in first if isinstance(task.get("project"), int)}
    projects_b = {task["project"] for task in second if isinstance(task.get("project"), int)}
    if projects_a & projects_b:
        raise ValueError("Use exports from two separately assigned review projects")
    known = {(row["case_id"], row["candidate_id"]): row for row in key["pairs"]}
    if len(known) != len(key["pairs"]):
        raise ValueError("Duplicate pair in private key")
    left, people_left = read_labels(first, key["dataset_id"], known)
    right, people_right = read_labels(second, key["dataset_id"], known)
    paired = left.keys() & right.keys()
    matched = sum(left[p] == right[p] for p in paired)
    rows = [
        dict(known[p], label_a=left.get(p), label_b=right.get(p))
        for p in sorted(known)
        if p in left or p in right
    ]
    return dict(
        dataset_id=key["dataset_id"],
        total_pairs=len(known),
        labeled_a=len(left),
        labeled_b=len(right),
        paired=len(paired),
        identical_labels=matched,
        disagreements=len(paired) - matched,
        agreement_rate=matched / len(paired) if paired else None,
        unpaired=len(left.keys() ^ right.keys()),
        pending_both=len(known.keys() - (left.keys() | right.keys())),
        same_label_studio_account_seen=bool(people_left & people_right),
        confusion=dict(Counter(f"{left[p]} / {right[p]}" for p in paired)),
        needs_adjudication=[
            r
            for r in rows
            if r["label_a"]
            and r["label_b"]
            and (r["label_a"] != r["label_b"] or r["label_a"] in {"unsure", "broken"})
        ],
        judgments=rows,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("key", "export_a", "export_b", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    if args.export_a.samefile(args.export_b):
        parser.error("Provide two independently produced exports")
    docs = [p.read_text(encoding="utf-8-sig") for p in (args.key, args.export_a, args.export_b)]
    report = compare(*(json.loads(s) for s in docs))
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
    print(f"{report['paired']} double-rated; {report['disagreements']} disagreements")
