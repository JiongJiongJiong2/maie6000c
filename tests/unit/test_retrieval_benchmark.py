import hashlib

import pytest
from PIL import Image

from services.retrieval.benchmark import checked_file, summarize, validate_manifest


def run(case_id="known", **changes):
    result = dict(case_id=case_id, arm="A", status="completed", elapsed_seconds=1,
                  search_calls=0, planner_calls=0, downloads_used=0,
                  candidates=[{"sha256": "target", "decoded_multiframe": True}])
    return result | changes


def cases():
    return [dict(id="known", split="development", category="in_library",
                 target_sha256="target"),
            dict(id="unknown", split="development", category="unknown")]


def test_unknown_not_scored_and_missing_runs_explicit():
    report = summarize(cases(), [run(), run("unknown")])
    assert not report["complete_matrix"]
    assert len(report["missing"]) == 4
    known, unknown = report["groups"]
    assert known["exact_sha_top3_rate"] == 1
    assert unknown["exact_sha_top3_rate"] is None


def test_failed_and_static_results_are_not_hits():
    report = summarize(cases()[:1], [run(status="failed", candidates=[], failure_code="timeout")])
    assert report["groups"][0]["exact_sha_top3_rate"] == 0
    assert report["groups"][0]["failures"] == {"timeout": 1}
    report = summarize(cases()[:1], [run(candidates=[{"sha256": "target"}])])
    assert report["groups"][0]["exact_sha_top3_hits"] == 0


@pytest.mark.parametrize("changes", [dict(elapsed_seconds=float("nan")),
                                    dict(search_calls=1), dict(arm="D"),
                                    dict(arm="B", downloads_used=7)])
def test_invalid_measurements_rejected(changes):
    with pytest.raises(ValueError):
        summarize(cases(), [run(**changes)])


def test_duplicate_attempts_not_cherry_picked():
    with pytest.raises(ValueError, match="duplicate"):
        summarize(cases(), [run(), run()])


def test_empty_manifest_is_not_eligible(tmp_path):
    with pytest.raises(ValueError, match="No eligible"):
        validate_manifest(dict(version=1, frozen_at="2026-11-15", cases=[]), tmp_path)


def test_files_checked_for_hash_format_and_containment(tmp_path):
    path = tmp_path / "query.png"
    Image.new("RGB", (8, 8), "red").save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checked_file(tmp_path, "query.png", digest)
    with pytest.raises(ValueError):
        checked_file(tmp_path, "query.png", "wrong")
    with pytest.raises(ValueError):
        checked_file(tmp_path, "query.png", digest, animated=True)
    with pytest.raises(ValueError):
        checked_file(tmp_path, "../escape.png", digest)


def test_family_split_leakage_rejected(tmp_path):
    Image.new("RGB", (8, 8), "red").save(tmp_path / "query.png")
    digest = hashlib.sha256((tmp_path / "query.png").read_bytes()).hexdigest()
    case = dict(id="one", split="development", category="unknown", family_id="family",
                origin="real_screenshot", reviewer="tester", image="query.png",
                image_sha256=digest)
    manifest = dict(version=1, frozen_at="2026-11-15",
                    cases=[case, case | dict(id="two", split="final")])
    with pytest.raises(ValueError, match="Family leakage"):
        validate_manifest(manifest, tmp_path)
