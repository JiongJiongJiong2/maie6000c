"""CLIP image features, based on YuanJian's W07 encoder.

Weights are prepared explicitly and inference never downloads files or sends images.
"""

from functools import lru_cache

import numpy as np
from PIL import Image

from services.common.config import get_settings

MODEL_NAME = "openai/clip-vit-base-patch32"
MODEL_REVISION = "37000f5cdccec47a3f6f83142bff131370757470"
MODEL_VERSION = f"clip-vit-base-patch32@{MODEL_REVISION}"


@lru_cache(maxsize=1)
def load_model():
    import torch
    from transformers import CLIPImageProcessor, CLIPModel

    path = get_settings().model_cache_root / "clip-vit-base-patch32"
    torch.set_num_threads(4)
    processor = CLIPImageProcessor.from_pretrained(path, local_files_only=True, use_fast=False)
    model = CLIPModel.from_pretrained(path, local_files_only=True, use_safetensors=True)
    model.eval()
    return model, processor, torch.device("cpu")


def on_white(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, "white")
    return Image.alpha_composite(background, rgba).convert("RGB")


def encode_images(images: list[Image.Image]) -> np.ndarray:
    import torch

    model, processor, device = load_model()
    inputs = processor(images=[on_white(image) for image in images], return_tensors="pt")
    with torch.inference_mode():
        features = model.get_image_features(pixel_values=inputs["pixel_values"].to(device))
        features = torch.nn.functional.normalize(features, p=2, dim=-1)
    return features.cpu().numpy().astype(np.float32)


def encode_image(image: Image.Image) -> np.ndarray:
    return encode_images([image])[0]
