import importlib
import json

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("torch")
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
