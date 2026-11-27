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


def test_saved_indexes_validate_media_and_join_fixed_ranking(tmp_path, monkeypatch):
    import io
    from types import SimpleNamespace
    from uuid import uuid4

    from PIL import Image

    from services.common.storage import sha256
    from services.retrieval import saved_index

    monkeypatch.setattr(
        saved_index, "get_settings",
        lambda: SimpleNamespace(media_root=tmp_path, max_candidate_bytes=100_000),
    )
    images = [Image.new("RGB", (16, 16), (i * 20, 0, 0)) for i in range(10)]
    gif = io.BytesIO()
    images[0].save(gif, format="GIF", save_all=True, append_images=images[1:])
    data = gif.getvalue()
    (tmp_path / "saved.gif").write_bytes(data)
    asset = SimpleNamespace(
        id=str(uuid4()), gif_path="saved.gif", sha256=sha256(data), frame_count=10,
        index_status="running", index_version=None,
    )
    attempts = []

    def encode(frames):
        attempts.append([image.getpixel((0, 0))[0] for image in frames])
        vectors = np.zeros((len(frames), 512), dtype=np.float32)
        vectors[:, 0] = 1
        return vectors

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def get(self, _model, asset_id):
            assert asset_id == asset.id
            return asset

        def expunge(self, _asset):
            pass

        def expunge_all(self):
            pass

        def scalars(self, statement):
            assert "saved_assets.index_status" in str(statement)
            return SimpleNamespace(all=lambda: [asset] if asset.index_status == "ready" else [])

    monkeypatch.setattr(saved_index, "get_session_factory", lambda: Session)
    monkeypatch.setattr(saved_index, "encode_images", encode)
    version = saved_index.index_saved_asset(asset.id)
    assert saved_index.index_saved_asset(asset.id) == version
    assert attempts == [[0, 20, 40, 60, 100, 120, 140, 180]]
    index_file = tmp_path / saved_index.index_location(asset, version)
    previous_index = index_file.read_bytes()
    with monkeypatch.context() as patch:
        load_vectors = saved_index.load_vectors

        def interrupted_read(*_args):
            raise OSError("Transient index read failure")

        def interrupted_write(*_args):
            raise OSError("Index write failed")

        patch.setattr(saved_index, "load_vectors", interrupted_read)
        patch.setattr(saved_index, "atomic_write", interrupted_write)
        with pytest.raises(OSError, match="write failed"):
            saved_index.index_saved_asset(asset.id)
        assert index_file.read_bytes() == previous_index
        assert load_vectors(asset, version).shape == (8, 512)
    (tmp_path / "saved.gif").write_bytes(b"bad GIF")
    with pytest.raises(ValueError, match="checksum"):
        saved_index.index_saved_asset(asset.id)
    asset.sha256 = sha256(b"bad GIF")
    with pytest.raises(ValueError, match="decoded"):
        saved_index.index_saved_asset(asset.id)
    asset.sha256 = sha256(data)
    (tmp_path / "saved.gif").write_bytes(data)

    fixed_id = str(uuid4())
    manifest = SimpleNamespace(
        assets=[SimpleNamespace(reference_asset_id=fixed_id)], corpus_version="fixed",
    )
    index = tmp_path / "fixed.npz"
    fixed_vector = np.zeros((1, 512), dtype=np.float32)
    fixed_vector[0, 0] = 0.9
    np.savez(
        index, embeddings=fixed_vector, asset_ids=[fixed_id], metadata=json.dumps(
            {"manifest_sha256": "fixed", "model_version": saved_index.MODEL_VERSION,
             "index_format": retrieval.INDEX_FORMAT},
        ),
    )
    screenshot = tmp_path / "query.png"
    images[0].save(screenshot)
    monkeypatch.setattr(retrieval, "corpus", lambda: (manifest, "fixed"))
    monkeypatch.setattr(retrieval, "index_path", lambda: index)
    monkeypatch.setattr(retrieval, "encode_image", lambda _image: np.eye(1, 512)[0])
    asset.index_version = version

    def best():
        return retrieval.search(screenshot, top_k=1)["matches"][0]["reference_asset_id"]

    for state in ("pending", "running", "failed"):
        asset.index_status = state
        assert best() == fixed_id
    asset.index_status = "ready"
    assert best() == asset.id
    asset.index_version = "stale"
    assert best() == fixed_id
    asset.index_version = version
    (tmp_path / saved_index.index_location(asset, version)).write_bytes(b"invalid npz")
    assert best() == fixed_id
