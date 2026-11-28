import json

import pytest

from scripts import benchmark_gif_retrieval as benchmark
from scripts.compare_retrieval_judgments import compare
from scripts.prepare_retrieval_review import build


def test_missing_result_is_counted_and_reviewers_get_no_arm_names(tmp_path):
    run_dir = tmp_path / "frozen"
    manifest = benchmark.prepare_queries(benchmark.demo_corpus(), run_dir, 27, None, 4)
    raw = benchmark.write_json(run_dir, "manifest.json", manifest)
    results = benchmark.run_benchmark(run_dir, manifest, benchmark.sha256(raw), "pixel", -1, 3)
    results["runs"].pop()
    benchmark.write_json(run_dir, "results.json", results)
    dest = tmp_path / "review"
    report = build(run_dir, dest, max_cases=3)
    assert sum(g["planned"] for g in report["groups"]) == len(manifest["cases"]) * 2
    assert sum(g["statuses"].get("missing", 0) for g in report["groups"]) == 1
    document = json.loads((dest / "site/review.json").read_bytes())
    assert len(document["cases"]) == 3
    assert "first_frame" not in json.dumps(document)
    assert all((dest / "site" / c["reference_url"]).is_file() for c in document["cases"])
    key = json.loads((dest / "review-key.json").read_bytes())
    assert len(key["pairs"]) == report["review_pairs"]


def test_disagreements_and_uncertain_agreement_need_adjudication():
    key = {
        "dataset_id": "v1",
        "pairs": [{"case_id": "q", "candidate_id": str(i)} for i in range(4)],
    }

    def task(idx, label):
        return {
            "data": dict(key["pairs"][idx], dataset_id="v1"),
            "annotations": [
                {"result": [{"from_name": "gif_match", "value": {"choices": [label]}}]}
            ],
        }

    first = [task(0, "unsure"), task(1, "wrong"), task(2, "exact")]
    second = [task(0, "unsure"), task(1, "variant")]
    result = compare(key, first, second)
    assert result["disagreements"] == result["pending_both"] == result["unpaired"] == 1
    assert result["agreement_rate"] == 0.5
    assert len(result["needs_adjudication"]) == 2
    second[0]["data"]["dataset_id"] = "different"
    with pytest.raises(ValueError, match="different-dataset"):
        compare(key, first, second)
