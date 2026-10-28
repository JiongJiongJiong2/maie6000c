
"""Unit tests for the MemeRetrieve GIF retrieval module."""

import importlib
import json

import numpy as np
import pytest
from PIL import Image

from services.retrieval.prepare_corpus import sampled_frames


search_module = importlib.import_module("services.retrieval.search")

GIF_A = "00000000-0000-4000-8000-000000000001"
GIF_B = "00000000-0000-4000-8000-000000000002"
GIF_C = "00000000-0000-4000-8000-000000000003"


def vector(x=0.0, y=0.0, z=0.0):
    """Create a synthetic 512-dimensional image embedding."""
    result = np.zeros(512, dtype=np.float32)
    result[:3] = [x, y, z]
    return result


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    """Create a temporary search index without loading CLIP."""

    index_dir = tmp_path / "index"
    index_dir.mkdir()

    # Two frames belong to GIF_A; other GIFs have one frame.
    embeddings = np.stack([
        vector(0.6, 0.8),
        vector(1.0, 0.0),
        vector(0.8, 0.6),
        vector(0.0, 1.0),
    ])

    np.savez_compressed(
        index_dir / "index.npz",
        embeddings=embeddings,
        asset_ids=np.array([GIF_A, GIF_A, GIF_B, GIF_C]),
        frame_indices=np.array([0, 3, 0, 0]),
    )

    metadata = {
        "model_version": search_module.MODEL_NAME,
        "corpus_version": "test-v1",
    }

    (index_dir / "index_metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )

    query_path = tmp_path / "query.png"
    Image.new("RGB", (32, 32), "orange").save(query_path)

    monkeypatch.setenv("MEMERETRIEVE_INDEX_DIR", str(index_dir))
    monkeypatch.delenv("MEMERETRIEVE_MIN_SCORE", raising=False)

    # Simulate CLIP output so tests are fast and deterministic.
    monkeypatch.setattr(
        search_module, "encode_image", lambda image: vector(1.0, 0.0)
    )

    return query_path, index_dir


def test_top3_ranking_and_deduplication(dataset):
    query_path, _ = dataset

    result = search_module.search(query_path, top_k=3)

    ids = [m["reference_asset_id"] for m in result["matches"]]

    assert ids == [GIF_A, GIF_B, GIF_C]
    assert len(ids) == len(set(ids))
    assert result["matches"][0]["score"] == pytest.approx(1.0)
    assert result["matches"][1]["score"] == pytest.approx(0.8)
    assert result["corpus_version"] == "test-v1"
    assert result["model_version"] == search_module.MODEL_NAME


def test_top_k_limit(dataset):
    query_path, _ = dataset

    result = search_module.search(query_path, top_k=1)

    assert len(result["matches"]) == 1
    assert result["matches"][0]["reference_asset_id"] == GIF_A


def test_threshold_filter(dataset, monkeypatch):
    query_path, _ = dataset
    monkeypatch.setenv("MEMERETRIEVE_MIN_SCORE", "0.82")

    result = search_module.search(query_path, top_k=3)

    assert len(result["matches"]) == 1
    assert result["matches"][0]["reference_asset_id"] == GIF_A


def test_no_match(dataset, monkeypatch):
    query_path, _ = dataset
    monkeypatch.setenv("MEMERETRIEVE_MIN_SCORE", "0.82")

    # An unrelated query vector.
    monkeypatch.setattr(
        search_module,
        "encode_image",
        lambda image: vector(0.0, 0.0, 1.0),
    )

    result = search_module.search(query_path)

    assert result["matches"] == []


@pytest.mark.parametrize("top_k", [0, -1, True, "3"])
def test_invalid_top_k(dataset, top_k):
    query_path, _ = dataset

    with pytest.raises(ValueError):
        search_module.search(query_path, top_k=top_k)


def test_missing_index(dataset, monkeypatch, tmp_path):
    query_path, _ = dataset

    monkeypatch.setenv(
        "MEMERETRIEVE_INDEX_DIR", str(tmp_path / "missing")
    )

    with pytest.raises(FileNotFoundError):
        search_module.search(query_path)


def test_missing_configuration(dataset, monkeypatch):
    query_path, _ = dataset
    monkeypatch.delenv("MEMERETRIEVE_INDEX_DIR")

    with pytest.raises(RuntimeError):
        search_module.search(query_path)


def test_invalid_image(dataset):
    query_path, _ = dataset
    missing_image = query_path.parent / "not_found.png"

    with pytest.raises(ValueError):
        search_module.search(missing_image)


def test_model_version_mismatch(dataset):
    query_path, index_dir = dataset
    metadata_path = index_dir / "index_metadata.json"

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["model_version"] = "incompatible-model"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError):
        search_module.search(query_path)


def test_invalid_threshold(dataset, monkeypatch):
    query_path, _ = dataset
    monkeypatch.setenv("MEMERETRIEVE_MIN_SCORE", "1.2")

    with pytest.raises(ValueError):
        search_module.search(query_path)


def test_gif_frame_sampling(tmp_path):
    gif_path = tmp_path / "sample.gif"

    frames = [
        Image.new("RGB", (32, 32), (i * 60, 0, 0))
        for i in range(4)
    ]

    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )

    sampled = list(sampled_frames(gif_path, max_frames=3))

    assert [index for index, frame in sampled] == [0, 1, 3]
    assert len(sampled) == 3
    assert all(frame.mode == "RGB" for _, frame in sampled)


def test_static_image_rejected(tmp_path):
    path = tmp_path / "static.png"
    Image.new("RGB", (32, 32), "red").save(path)

    with pytest.raises(ValueError):
        list(sampled_frames(path))
