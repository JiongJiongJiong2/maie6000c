"""Real, local CLIP frame-to-GIF retrieval for the W07 integration."""

from pathlib import Path


def search(image_path: Path, top_k: int = 3) -> dict:
    from services.retrieval.engine import search as run_search

    return run_search(image_path, top_k=top_k)


def prepare_candidates(image_path, sources, work_dir, budget):
    from .candidates import prepare_candidates as prepare

    return prepare(image_path, sources, work_dir, budget)


def index_saved_asset(asset_id: str) -> str:
    from .saved_index import index_saved_asset as index

    return index(asset_id)
