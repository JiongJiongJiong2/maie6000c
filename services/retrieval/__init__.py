"""Real, local CLIP frame-to-GIF retrieval for the W07 integration."""

from pathlib import Path


def search(image_path: Path, top_k: int = 3) -> dict:
    from services.retrieval.engine import search as run_search

    return run_search(image_path, top_k=top_k)
