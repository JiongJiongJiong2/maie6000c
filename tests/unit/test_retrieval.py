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


def test_reference_index_rejects_zero_frame_vector_before_inference(tmp_path, monkeypatch):
    from types import SimpleNamespace

    path = tmp_path / "index.npz"
    embeddings = np.zeros((2, 512), dtype=np.float32)
    embeddings[0, 0] = 1.0
    np.savez(
        path,
        embeddings=embeddings,
        asset_ids=np.asarray(["asset", "asset"]),
        metadata=json.dumps(
            {
                "manifest_sha256": "matched",
                "model_version": retrieval.MODEL_VERSION,
                "index_format": retrieval.INDEX_FORMAT,
            }
        ),
    )
    manifest = SimpleNamespace(assets=[SimpleNamespace(reference_asset_id="asset")])
    monkeypatch.setattr(retrieval, "corpus", lambda: (manifest, "matched"))
    monkeypatch.setattr(retrieval, "index_path", lambda: path)
    with pytest.raises(ValueError, match="index does not match the corpus"):
        retrieval.search(tmp_path / "not-read.png")


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
        lambda: SimpleNamespace(
            media_root=tmp_path, max_candidate_bytes=100_000, vector_backend="npz"
        ),
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
        from services.retrieval import vector_store

        mirrors = []

        def unavailable(*args):
            mirrors.append(args)
            return False

        patch.setattr(
            saved_index,
            "get_settings",
            lambda: SimpleNamespace(
                media_root=tmp_path, max_candidate_bytes=100_000, vector_backend="pgvector"
            ),
        )
        patch.setattr(vector_store, "store_asset_vectors", unavailable)
        assert saved_index.index_saved_asset(asset.id) == version
        assert len(mirrors) == 1
        assert mirrors[0][0:2] == (asset, version)
        assert mirrors[0][2].tolist() == [0, 1, 2, 3, 5, 6, 7, 9]
        assert mirrors[0][3].shape == (8, 512)
        assert len(attempts) == 1 and index_file.read_bytes() == previous_index
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



@pytest.mark.parametrize(
    ("stored", "expected_backend"),
    [
        ([{"reference_asset_id": "best", "score": 0.98}], "pgvector"),
        (None, "npz_fallback"),
        ([{"reference_asset_id": "fixed", "score": 0.98}], "npz_fallback"),
        ([{"reference_asset_id": "best", "score": 0.90000001}], "npz_fallback"),
    ],
)
def test_mixed_backend_ranking_switches_or_rechecks_full_local_index(
    monkeypatch, stored, expected_backend
):
    from types import SimpleNamespace

    from services.retrieval import saved_index, vector_store

    monkeypatch.setattr(
        retrieval, "get_settings", lambda: SimpleNamespace(vector_backend="pgvector")
    )
    monkeypatch.setattr(vector_store, "rank_saved_vectors", lambda *args: stored)
    calls = []

    def npz_saved_frames():
        calls.append(True)
        return [("best", np.array([[0.98, 0.0]]))]

    monkeypatch.setattr(saved_index, "ready_vectors", npz_saved_frames)
    result, backend, reference_backend = retrieval.local_matches(
        np.array([[0.9, 0.0], [0.8, 0.0]]), ["fixed", "lower"], np.array([1.0, 0.0]), 2, 0.8
    )
    assert [row["reference_asset_id"] for row in result] == ["best", "fixed"]
    assert backend == expected_backend
    assert reference_backend == "npz_fallback"
    assert bool(calls) == (backend == "npz_fallback")


def test_backfill_only_mirrors_ready_valid_npz_and_never_marks_it_ready(monkeypatch):
    from types import SimpleNamespace

    from services.retrieval import saved_index, vector_store

    valid = SimpleNamespace(id="valid", index_version="trusted", frame_count=2)
    corrupt = SimpleNamespace(id="corrupt", index_version="stale", frame_count=2)
    embeddings = np.ones((2, 512), dtype=np.float32)
    mirrored = []

    def load(asset, version):
        if asset is corrupt:
            raise ValueError("Invalid version")
        assert version == valid.index_version
        return embeddings

    monkeypatch.setattr(
        saved_index, "get_settings", lambda: SimpleNamespace(vector_backend="pgvector")
    )
    monkeypatch.setattr(saved_index, "ready_assets", lambda: [valid, corrupt])
    monkeypatch.setattr(saved_index, "load_vectors", load)
    monkeypatch.setattr(saved_index, "read_saved_gif", lambda asset: b"known bytes")

    def mirror(asset, version, frames, vectors):
        mirrored.append((asset.id, version, frames.tolist(), vectors is embeddings))
        return True

    monkeypatch.setattr(vector_store, "store_asset_vectors", mirror)
    assert saved_index.backfill_saved_vectors() == {
        "ready": 2, "mirrored": 1, "unusable": 1, "unavailable": 0
    }
    assert mirrored == [("valid", "trusted", [0, 1], True)]
    assert valid.index_version == "trusted" and corrupt.index_version == "stale"
