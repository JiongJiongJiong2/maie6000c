
"""CLIP image feature extraction for MemeRetrieve."""

from functools import lru_cache

import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor


# Pretrained CLIP ViT-B/32
MODEL_NAME = "openai/clip-vit-base-patch32"


@lru_cache(maxsize=1)
def load_model():
    """Load CLIP once and reuse it for subsequent requests."""

    device = torch.device(
        "cuda" if torch.cuda.is_available() else "cpu"
    )

    print(f"Loading CLIP on {device}...")

    processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    model = CLIPModel.from_pretrained(MODEL_NAME)

    model = model.to(device)
    model.eval()

    return model, processor, device


def encode_image(image: Image.Image) -> np.ndarray:
    """Return a normalized 512-dimensional CLIP embedding."""

    model, processor, device = load_model()

    # Preprocess the input image
    inputs = processor(
        images=image.convert("RGB"),
        return_tensors="pt",
    )

    pixel_values = inputs["pixel_values"].to(device)

    # Run inference on GPU when available
    with torch.inference_mode():
        features = model.get_image_features(
            pixel_values=pixel_values
        )

        # L2 normalization for cosine similarity
        features = torch.nn.functional.normalize(
            features, p=2, dim=-1
        )

    return features[0].cpu().numpy().astype(np.float32)
