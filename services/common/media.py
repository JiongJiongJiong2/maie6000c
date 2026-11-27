"""Decoded media identity and time-based representatives, without loading models."""

import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .storage import MediaError, sha256

FORMATS = {
    "PNG": ("image/png", "png"),
    "JPEG": ("image/jpeg", "jpg"),
    "WEBP": ("image/webp", "webp"),
    "GIF": ("image/gif", "gif"),
}
MAX_BYTES = 12 * 1024 * 1024


class MediaMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: str
    mime_type: str
    media_kind: str
    frame_count: int = Field(ge=1, le=1000)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    byte_size: int = Field(gt=0, le=MAX_BYTES)
    duration_ms: int = Field(default=0, ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def consistency(self):
        if self.format not in FORMATS or FORMATS[self.format][0] != self.mime_type:
            raise ValueError("Format/MIME mismatch")
        if self.media_kind != ("animated" if self.frame_count > 1 else "static"):
            raise ValueError("Frame count/kind mismatch")
        if (
            self.width * self.height > 20_000_000
            or self.width * self.height * self.frame_count > 100_000_000
        ):
            raise ValueError("Decode quota exceeded")
        return self

    @property
    def suffix(self):
        return FORMATS[self.format][1]


def inspect_media(data: bytes) -> MediaMetadata:
    if not data or len(data) > MAX_BYTES:
        raise MediaError("Media byte limit exceeded")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                count = getattr(image, "n_frames", 1)
                if image.format not in FORMATS:
                    raise MediaError("Unsupported image format")
                meta = MediaMetadata(
                    format=image.format,
                    mime_type=FORMATS[image.format][0],
                    media_kind="animated" if count > 1 else "static",
                    frame_count=count,
                    width=image.width,
                    height=image.height,
                    byte_size=len(data),
                    sha256=sha256(data),
                )
                duration = 0
                for frame in range(count):
                    image.seek(frame)
                    image.load()
                    duration += max(0, int(image.info.get("duration", 0)))
                meta.duration_ms = duration
                return meta
    except (
        ValueError,
        OSError,
        EOFError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise MediaError("Media cannot be decoded within limits") from exc


def representative_frames(data: bytes, count=4, max_side=768, preserve_timeline=False):
    """Sample by playback time, deduplicate frames, preserve GIF composition/disposal."""
    meta = inspect_media(data)
    with Image.open(io.BytesIO(data)) as image:
        durations = []
        for i in range(meta.frame_count):
            image.seek(i)
            image.load()
            durations.append(max(10, int(image.info.get("duration", 100))))
        total = sum(durations)
        # Midpoints avoid only an empty first/last frame. Include distinct later frames.
        sample_count = count if preserve_timeline else min(count, meta.frame_count)
        times = [total * (i + 0.5) / sample_count for i in range(sample_count)]
        frames, records, hashes = [], [], set()
        elapsed, index = 0, 0
        for timestamp in times:
            while index < meta.frame_count - 1 and elapsed + durations[index] <= timestamp:
                elapsed += durations[index]
                index += 1
            image.seek(index)
            rgba = ImageOps.exif_transpose(image).convert("RGBA")
            white = Image.new("RGBA", rgba.size, "white")
            rgb = Image.alpha_composite(white, rgba).convert("RGB")
            rgb.thumbnail((max_side, max_side))
            fingerprint = sha256(rgb.resize((32, 32)).tobytes())
            if not preserve_timeline and fingerprint in hashes:
                continue
            hashes.add(fingerprint)
            frames.append(rgb.copy())
            records.append({"frame_index": index, "time_ms": int(timestamp)})
    return frames, records


def png_bytes(image):
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def preview_bytes(data):
    frames, _ = representative_frames(data, count=1, max_side=384)
    return png_bytes(frames[0])


def safe_file(root: Path, relative: str):
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise MediaError("Media path escapes its job")
    return path
