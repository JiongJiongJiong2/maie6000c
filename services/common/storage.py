from __future__ import annotations

import hashlib
import io
import logging
import os
import warnings
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from services.common.config import get_settings


class MediaError(ValueError):
    pass


logger = logging.getLogger("services.common.storage")


def remove_file_after_failure(path: Path, *, storage_class: str) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception(
            "stored_file_cleanup_failed",
            extra={"file_name": path.name, "storage_class": storage_class},
        )
        return False
    return True


def prepare_storage() -> None:
    settings = get_settings()
    for path in (
        settings.media_root / "inputs",
        settings.media_root / "candidates",
        settings.reference_root,
        settings.model_cache_root,
    ):
        path.mkdir(parents=True, exist_ok=True)


def contained_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise MediaError("Media path is outside its storage directory")
    return path


def validate_image(data: bytes, *, animated_gif: bool = False) -> int:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 20_000_000:
                    raise MediaError("Image exceeds the 20 megapixel limit")
                if animated_gif:
                    frame_count = getattr(image, "n_frames", 1)
                    if image.format != "GIF" or frame_count < 2:
                        raise MediaError("Candidate must be an animated GIF")
                    frames = frame_count
                    if frames > 1000:
                        raise MediaError("GIF exceeds the 1000 frame limit")
                    if frames * image.width * image.height > 100_000_000:
                        raise MediaError("GIF exceeds the 100 megapixel total decoding limit")
                    for frame in range(frames):
                        image.seek(frame)
                        image.load()
                    return frames
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise MediaError("Upload must be a JPEG, PNG, or WebP image")
                image.verify()
            with Image.open(io.BytesIO(data)) as decoded:
                decoded.load()
        return 1
    except (
        UnidentifiedImageError,
        OSError,
        EOFError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise MediaError("Image cannot be decoded safely") from exc


def atomic_write(root: Path, relative: str, data: bytes) -> Path:
    target = contained_path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(target)
        if os.name == "posix":
            directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        remove_file_after_failure(temporary, storage_class="temporary")
        raise
    return target


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_gif(relative: str) -> tuple[bytes, int]:
    path = contained_path(get_settings().reference_root, relative)
    with path.open("rb") as source:
        data = source.read(get_settings().max_candidate_bytes + 1)
    if len(data) > get_settings().max_candidate_bytes:
        raise MediaError("Candidate exceeds the configured byte limit")
    return data, validate_image(data, animated_gif=True)
