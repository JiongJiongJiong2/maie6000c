"""Prepare the pinned CLIP weights once; runtime inference stays offline."""

from pathlib import Path

from huggingface_hub import snapshot_download

MODEL_REVISION = "37000f5cdccec47a3f6f83142bff131370757470"

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    snapshot_download(
        "openai/clip-vit-base-patch32",
        revision=MODEL_REVISION,
        allow_patterns=["config.json", "preprocessor_config.json", "model.safetensors"],
        local_dir=root / "data/models/clip-vit-base-patch32",
    )
    print("CLIP weights are ready for local inference.")
