import io
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from services.retrieval import engine
from services.common.storage import sha256


def test_failed_publication_keeps_previous_index(tmp_path, monkeypatch):
    image = Image.new("RGB", (8, 8), "red")
    buffer = io.BytesIO()
    image.save(buffer, format="GIF")
    data = buffer.getvalue()
    gif_path = tmp_path / "input.gif"
    gif_path.write_bytes(data)
    asset = SimpleNamespace(gif_path="input.gif", sha256=sha256(data), reference_asset_id="a")
    manifest = SimpleNamespace(assets=[asset], corpus_version="test")
    monkeypatch.setattr(engine, "corpus", lambda: (manifest, "digest"))
    monkeypatch.setattr(engine, "read_gif", lambda _: (data, 1))
    monkeypatch.setattr(
        engine, "get_settings", lambda: SimpleNamespace(reference_root=tmp_path, vector_backend="npz")
    )
    monkeypatch.setattr(engine, "encode_images", lambda images: np.ones((len(images), 512)))
    index = tmp_path / "index.npz"
    monkeypatch.setattr(engine, "index_path", lambda: index)
    engine.build_index()
    original = index.read_bytes()
    with np.load(index, allow_pickle=False) as archive:
        assert archive["embeddings"].shape == (1, 512)

    def fail(*args):
        raise OSError("publication interrupted")

    monkeypatch.setattr(engine, "atomic_write", fail)
    with pytest.raises(OSError, match="publication interrupted"):
        engine.build_index()
    assert index.read_bytes() == original
