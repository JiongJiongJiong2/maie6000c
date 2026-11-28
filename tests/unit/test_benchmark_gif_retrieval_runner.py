import hashlib
import json
import sys

import pytest
from PIL import Image

from scripts import benchmark_gif_retrieval as benchmark


def test_demo_repeats_identical_manifest_and_keeps_full_distractor_index(tmp_path, monkeypatch):
    manifests = []
    for output in (tmp_path / "a", tmp_path / "b"):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "benchmark",
                "--demo",
                "--encoder",
                "pixel",
                "--max-query-assets",
                "4",
                "--output-dir",
                str(output),
            ],
        )
        assert benchmark.main() == 0
        raw_manifest = (output / "manifest.json").read_bytes()
        manifest = json.loads(raw_manifest)
        manifests.append(raw_manifest)
        results = json.loads((output / "results.json").read_bytes())
        assert results["manifest_sha256"] == hashlib.sha256(raw_manifest).hexdigest()
        assert results["encoder"] == "pixel"
        assets = {asset["id"]: asset for asset in manifest["assets"]}
        cases = {case["id"]: case for case in manifest["cases"]}
        assert len(assets) == 8
        assert len(cases) == 16
        assert len(results["runs"]) == 2 * len(cases)
        assert {(case["split"], case["category"]) for case in cases.values()} == {
            (split, category)
            for split in ("development", "final")
            for category in ("in_library", "out_of_library")
        }
        assert (
            results["index_frame_counts"]["first_frame"]
            == sum(asset["in_corpus"] for asset in assets.values())
            > len({case["target_asset_id"] for case in cases.values()})
        )
        for case in cases.values():
            target = assets[case["target_asset_id"]]
            assert target["family_id"] == case["family_id"]
            assert target["split"] == case["split"]
            assert target["sha256"] == case["target_sha256"]
            assert not case["query_frame_is_index_sample"]
            assert target["in_corpus"] == (case["category"] == "in_library")
            assert (
                hashlib.sha256((output / case["image"]).read_bytes()).hexdigest()
                == (case["image_sha256"])
            )
        for run in results["runs"]:
            assert run["status"] == "completed"
            for candidate in run["candidates"]:
                asset = assets[candidate["asset_id"]]
                assert asset["in_corpus"]
                assert asset["sha256"] == candidate["sha256"]
    assert manifests[0] == manifests[1]


def test_custom_corpus_requires_matching_original_digest(tmp_path):
    source = tmp_path / "known.gif"
    fixture = benchmark.demo_corpus()[0]
    source.write_bytes(fixture.source_file)
    manifest = tmp_path / "source.json"
    asset = {
        "family_id": "custom-family",
        "gif_path": source.name,
        "sha256": fixture.sha256,
        "source": "Test procedural fixture",
        "license": "CC0 1.0",
    }
    manifest.write_text(json.dumps({"assets": [asset]}), encoding="utf-8")
    loaded, _ = benchmark.load_corpus(manifest)
    assert loaded[0].source_file == source
    assert loaded[0].frame_count == fixture.frame_count
    source.write_bytes(b"not the original")
    with pytest.raises(ValueError, match="checksum mismatch"):
        benchmark.load_corpus(manifest)


def test_family_assignment_never_leaks_between_splits_or_corpus_membership():
    from dataclasses import replace

    assets = benchmark.demo_corpus()
    same_family = replace(assets[0], id="same-family-another-version")
    combined = [*assets, same_family]
    assignments = benchmark.assign_families(combined, 7)
    assert assignments == benchmark.assign_families(list(reversed(combined)), 7)
    assert len(assignments) == len(assets)
    assert set(assignments.values()) == {
        (split, in_corpus) for split in ("development", "final") for in_corpus in (True, False)
    }


@pytest.mark.parametrize("suffix", ["gif", "webp"])
def test_focus_uses_full_catalog(tmp_path, suffix):
    gifs = benchmark.demo_corpus()
    seed = 6000
    family = next(
        family
        for family, (_, included) in benchmark.assign_families(gifs, seed).items()
        if not included
    )
    source = tmp_path / f"still.{suffix}"
    Image.new("RGB", (80, 64), "#df4509").save(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    distractor_manifest = tmp_path / "stills.json"
    distractor_manifest.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "id": "focus-static",
                        "family_id": family,
                        "image": source.name,
                        "sha256": source_sha,
                        "source": "Test procedural fixture",
                        "license": "CC0 1.0",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    stills, stills_manifest_sha = benchmark.load_distractors(distractor_manifest)
    output = tmp_path / "benchmark"
    manifest = benchmark.prepare_queries(
        gifs, output, seed, None, 4, stills, stills_manifest_sha, {family}
    )
    results = benchmark.run_benchmark(output, manifest, "test", "pixel", -1, 3)
    static = next(asset for asset in manifest["assets"] if asset["id"] == "focus-static")
    assert static["media_path"].endswith(f".{suffix}")
    assert static["media_kind"] == "static"
    assert static["frame_count"] == 1
    assert not static["in_corpus"]
    assert static["in_focus_corpus"]
    assert results["focus_index_frame_counts"]["first_frame"] == len(gifs) + 1
    assert results["index_media_counts"]["static"] == 0
    assert results["focus_summary"]["static_focus"][family]["first_frame"]["attempts"] == 4
    assert results["focus_summary"]["animated_focus"][family]["multi_frame"]["attempts"] == 4
    cases = {case["id"]: case for case in manifest["cases"]}
    for run in results["runs"]:
        if cases[run["case_id"]]["cohort"] == "animated_original":
            assert not any(
                candidate["asset_id"] == "focus-static" for candidate in run["candidates"]
            )
