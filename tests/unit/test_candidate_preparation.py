import io
import time

import numpy as np
import pytest
from PIL import Image

from services.retrieval import candidates as module
from services.retrieval.download import DownloadError
from services.search_agent.models import CandidateBudget


def gif_bytes(color="blue", frames=2, fmt="GIF"):
    out = io.BytesIO()
    Image.new("RGB", (3, 3), "red").save(
        out,
        format=fmt,
        save_all=frames > 1,
        append_images=[Image.new("RGB", (3, 3), color)] if frames > 1 else [],
    )
    return out.getvalue()


def source(name="a"):
    return dict(
        source_url="https://commons.wikimedia.org/wiki/File:" + name,
        image_url="https://upload.wikimedia.org/" + name,
        provider="fixture",
    )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    image = tmp_path / "input.png"
    Image.new("RGB", (3, 3)).save(image)
    monkeypatch.setattr(module.encoder, "load_model", lambda: None)
    monkeypatch.setattr(module.encoder, "encode_image", lambda _: np.array([1.0, 0.0]))
    monkeypatch.setattr(
        module.encoder, "encode_images", lambda images: np.array([[1.0, 0.0]] * len(images))
    )
    monkeypatch.setenv("RETRIEVAL_MIN_SIMILARITY", "0.82")
    return (
        image,
        tmp_path / "round",
        CandidateBudget(remaining_downloads=6, deadline=time.monotonic() + 30),
    )


def run(setup, monkeypatch, data, sources=None):
    monkeypatch.setattr(module, "fetch", lambda *a, **k: (data, a[0], 0))
    return module.prepare_candidates(setup[0], sources or [source()], setup[1], setup[2])


def test_real_multiframe_bytes_hash_and_batch_dedup(setup, monkeypatch):
    batch = run(setup, monkeypatch, gif_bytes(), [source(), source(), source("b")])
    assert batch.downloads_used == 2 and len(batch.candidates) == 1
    candidate = batch.candidates[0]
    assert candidate.frame_count == 2 and candidate.score == 1
    assert (setup[1] / candidate.relative_path).read_bytes() == gif_bytes()


@pytest.mark.parametrize(
    "data,code",
    [
        (gif_bytes(frames=1), "static_image"),
        (gif_bytes(frames=1, fmt="JPEG"), "static_image"),
        (gif_bytes(fmt="WEBP"), "not_gif"),
        (b"<html>not GIF</html>", "invalid_media"),
        (gif_bytes()[:20], "invalid_media"),
    ],
)
def test_actual_format_not_suffix(setup, monkeypatch, data, code):
    batch = run(setup, monkeypatch, data)
    assert batch.failures == [code] and batch.downloads_used == 1
    assert not batch.candidates


def test_max_frame_similarity_and_low_score(setup, monkeypatch):
    monkeypatch.setattr(
        module.encoder, "encode_images", lambda _: np.array([[0.0, 1.0], [1.0, 0.0]])
    )
    assert run(setup, monkeypatch, gif_bytes()).candidates[0].score == 1
    monkeypatch.setattr(
        module.encoder, "encode_images", lambda _: np.array([[0.0, 1.0], [0.0, 1.0]])
    )
    batch = run(setup, monkeypatch, gif_bytes())
    assert not batch.candidates and batch.rejected_low_score == 1 and not batch.failures


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0.0])
def test_invalid_embedding(setup, monkeypatch, value):
    monkeypatch.setattr(module.encoder, "encode_images", lambda _: np.full((2, 2), value))
    assert run(setup, monkeypatch, gif_bytes()).failures == ["embedding_failed"]


def test_model_failure(setup, monkeypatch):
    def missing():
        raise OSError("sensitive local path")

    monkeypatch.setattr(module.encoder, "load_model", missing)
    assert run(setup, monkeypatch, gif_bytes()).failures == ["model_unavailable"]


def test_failed_get_consumes_budget(setup, monkeypatch):
    def fail(*a, **k):
        raise DownloadError("download_failed", attempted=True)

    monkeypatch.setattr(module, "fetch", fail)
    budget = setup[2].model_copy(update={"remaining_downloads": 1})
    batch = module.prepare_candidates(setup[0], [source(), source("b")], setup[1], budget)
    assert batch.downloads_used == 1 and batch.failures == ["download_failed"]


def test_symlink_write_rejected(setup, monkeypatch, tmp_path):
    from services.common.storage import sha256

    data = gif_bytes()
    setup[1].mkdir()
    outside = tmp_path / "outside.gif"
    outside.write_bytes(b"unchanged")
    (setup[1] / (sha256(data) + ".gif")).symlink_to(outside)
    batch = run(setup, monkeypatch, data)
    assert batch.failures == ["storage_failed"] and outside.read_bytes() == b"unchanged"


def test_storage_error_no_candidate(setup, monkeypatch):
    def fail(*a):
        raise OSError("disk full")

    monkeypatch.setattr(module, "atomic_write", fail)
    assert run(setup, monkeypatch, gif_bytes()).failures == ["storage_failed"]


def test_top_three_stable_order(setup, monkeypatch):
    payloads = [gif_bytes(c) for c in ["blue", "green", "yellow", "black"]]

    def download(url, **kwargs):
        return payloads[int(url.rsplit("/", 1)[-1])], url, 0

    monkeypatch.setattr(module, "fetch", download)
    batch = module.prepare_candidates(
        setup[0], [source(str(i)) for i in range(4)], setup[1], setup[2]
    )
    assert len(batch.candidates) == 3
    assert [c.sha256 for c in batch.candidates] == sorted(c.sha256 for c in batch.candidates)
