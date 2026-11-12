"""Real CLIP preprocessing boundary; no weights, network, or paid providers."""

import numpy as np
import pytest
from PIL import Image


def test_mixed_tiny_and_regular_rgb_batch_has_unambiguous_channels(monkeypatch):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    from services.retrieval import encoder

    class Model:
        def get_image_features(self, pixel_values):
            # Use real processor pixels; the model weights are irrelevant to
            # the channel-inference failure exposed by public 1px images.
            return pixel_values.mean(dim=(2, 3))

    monkeypatch.setattr(
        encoder,
        "load_model",
        lambda: (Model(), transformers.CLIPImageProcessor(), torch.device("cpu")),
    )
    images = [
        Image.new("RGB", size, color)
        for size, color in [
            ((1, 1), "red"),
            ((64, 64), "red"),
            ((20, 1), "red"),
            ((1, 20), "red"),
            ((3, 3), "blue"),
            ((32, 32), "blue"),
        ]
    ]
    features = encoder.encode_images(images)
    assert features.shape == (6, 3) and np.isfinite(features).all()
    np.testing.assert_allclose(features[0], features[1], atol=1e-6)
    np.testing.assert_allclose(features[2], features[1], atol=1e-6)
    np.testing.assert_allclose(features[3], features[1], atol=1e-6)
    np.testing.assert_allclose(features[4], features[5], atol=1e-6)
    assert features[0, 0] > 0 and features[0, 2] < 0
    assert features[4, 2] > 0 and features[4, 0] < 0
