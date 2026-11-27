"""Persist and validate the frame embeddings for a single saved GIF."""

import io
import json
import logging
from uuid import UUID
from zipfile import BadZipFile

import numpy as np
from PIL import Image
from sqlalchemy import select

from services.common.config import get_settings
from services.common.db import get_session_factory
from services.common.search_models import SavedAsset
from services.common.storage import atomic_write, contained_path, sha256, validate_image
from services.retrieval.encoder import MODEL_VERSION, encode_images
from services.retrieval.engine import FRAMES_PER_GIF

logger = logging.getLogger(__name__)
INDEX_FORMAT = 1
SAMPLING_VERSION = "uniform-inclusive-v1"


def identity(asset):
    metadata = json.dumps(
        {
            "asset_id": str(UUID(asset.id)),
            "sha256": asset.sha256,
            "model_version": MODEL_VERSION,
            "index_format": INDEX_FORMAT,
            "sampling_version": SAMPLING_VERSION,
            "frame_count": asset.frame_count,
        },
        sort_keys=True,
    )
    return metadata, sha256(metadata.encode())


def frame_numbers(count):
    return np.linspace(0, count - 1, min(FRAMES_PER_GIF, count), dtype=int)


def index_location(asset, version):
    return f"saved-index/{UUID(asset.id)}/{version}.npz"


def validate_vectors(vectors, count):
    if (
        vectors.shape != (count, 512)
        or vectors.dtype.kind != "f"
        or not np.isfinite(vectors).all()
        or not np.any(vectors != 0, axis=1).all()
    ):
        raise ValueError("Invalid saved GIF frame embeddings")


def load_vectors(asset, version):
    metadata, expected = identity(asset)
    if version != expected:
        raise ValueError("Saved GIF index version mismatch")
    path = contained_path(get_settings().media_root, index_location(asset, expected))
    frames = frame_numbers(asset.frame_count)
    with np.load(path, allow_pickle=False) as index:
        if str(index["metadata"]) != metadata or not np.array_equal(index["frames"], frames):
            raise ValueError("Saved GIF index metadata mismatch")
        vectors = index["embeddings"]
    validate_vectors(vectors, len(frames))
    return vectors


INVALID_INDEX = (OSError, ValueError, KeyError, EOFError, BadZipFile)


def read_saved_gif(asset):
    settings = get_settings()
    path = contained_path(settings.media_root, asset.gif_path)
    with path.open("rb") as source:
        data = source.read(settings.max_candidate_bytes + 1)
    if len(data) > settings.max_candidate_bytes or sha256(data) != asset.sha256:
        raise ValueError("Saved GIF exceeds the size limit or has a checksum mismatch")
    return data


def index_saved_asset(asset_id: str) -> str:
    with get_session_factory()() as db:
        asset = db.get(SavedAsset, str(UUID(asset_id)))
        if asset is None or asset.index_status != "running":
            raise ValueError("Only a claimed saved asset can be indexed")
        db.expunge(asset)
    data = read_saved_gif(asset)
    if validate_image(data, animated_gif=True) != asset.frame_count:
        raise ValueError("Saved GIF frame count mismatch")
    metadata, version = identity(asset)
    try:
        load_vectors(asset, version)
    except INVALID_INDEX:
        frames = frame_numbers(asset.frame_count)
        images = []
        with Image.open(io.BytesIO(data)) as gif:
            for frame in frames:
                gif.seek(int(frame))
                images.append(gif.convert("RGBA"))
        vectors = encode_images(images)
        validate_vectors(vectors, len(frames))
        output = io.BytesIO()
        np.savez_compressed(output, metadata=metadata, frames=frames, embeddings=vectors)
        atomic_write(
            get_settings().media_root, index_location(asset, version), output.getvalue()
        )
        load_vectors(asset, version)
    return version


def ready_vectors():
    with get_session_factory()() as db:
        assets = db.scalars(
            select(SavedAsset).where(
                SavedAsset.index_status == "ready", SavedAsset.index_version.is_not(None)
            )
        ).all()
        db.expunge_all()
    for asset in assets:
        try:
            vectors = load_vectors(asset, asset.index_version)
            read_saved_gif(asset)
            yield asset.id, vectors
        except INVALID_INDEX:
            logger.warning(
                "saved_asset_index_unusable", extra={"asset_id": asset.id}, exc_info=True
            )
