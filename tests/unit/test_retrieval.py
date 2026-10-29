import importlib
import json

import pytest

import numpy as np
retrieval = importlib.import_module("services.retrieval.engine")


def test_ranking_deduplicates_frames_and_applies_the_no_match_threshold():
    features = np.array([[0.9, 0], [0.95, 0], [0.85, 0], [0.2, 0]], dtype=np.float32)
    ranked = retrieval.rank_assets(features, ["a", "a", "b", "c"], np.array([1, 0]), 3, 0.8)
    assert [item["reference_asset_id"] for item in ranked] == ["a", "b"]
    assert ranked[0]["score"] == pytest.approx(0.95)
    assert retrieval.rank_assets(features, ["a", "a", "b", "c"], np.array([0, 1]), 3, 0.8) == []


def test_stale_model_or_manifest_index_is_rejected_before_inference(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from services.retrieval.encoder import MODEL_VERSION

    path = tmp_path / "index.npz"
    np.savez(
        path,
        metadata=json.dumps(
            {"manifest_sha256": "old", "model_version": MODEL_VERSION, "index_format": 1}
        ),
    )
    monkeypatch.setattr(retrieval, "corpus", lambda: (SimpleNamespace(assets=[]), "new"))
    monkeypatch.setattr(retrieval, "index_path", lambda: path)
    with pytest.raises(ValueError, match="stale"):
        retrieval.search(tmp_path / "missing.png")


@pytest.mark.parametrize("top_k", [0, -1, 4, True, "3", 1.5])
def test_invalid_top_k_is_rejected_before_loading_index(tmp_path, top_k):
    with pytest.raises(ValueError, match="top_k"):
        retrieval.search(tmp_path / "missing.png", top_k=top_k)


@pytest.mark.parametrize("minimum", ["nan", "inf", "1.2", "-1.2", "invalid"])
def test_invalid_threshold_is_rejected_before_loading_index(tmp_path, monkeypatch, minimum):
    monkeypatch.setenv("RETRIEVAL_MIN_SIMILARITY", minimum)
    with pytest.raises(ValueError):
        retrieval.search(tmp_path / "missing.png")


def test_ranking_ties_are_stable_and_top_k_is_applied():
    features = np.array([[1, 0], [1, 0], [0, 1]], dtype=np.float32)
    result = retrieval.rank_assets(features, ["b", "a", "c"], np.array([1, 0]), 1, 0)
    assert result == [{"reference_asset_id": "a", "score": 1.0}]
