"""Validate and index the approved public sticker collection."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal

from PIL import Image, ImageChops, ImageOps, ImageStat
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from services.common.media import MAX_BYTES, MediaMetadata, inspect_media, png_bytes, safe_file
from services.common.storage import MediaError, validate_image

Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=60)]
Label = Annotated[str, Field(min_length=1, max_length=120)]
MAX_ARCHIVE_BYTES = 24 * 1024 * 1024
MIN_DISTANCE_MARGIN = 0.035
MAX_MATCH_DISTANCE = 0.19
FRAME_SAMPLES = 10
MATTES = ("#ffffff", "#202124")


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Sticker(Entry):
    id: Slug
    name: Label
    file: str = Field(min_length=1, max_length=250)


class Channel(Entry):
    id: Slug
    label: Label
    url: HttpUrl

    @field_validator("url")
    @classmethod
    def official_https_url(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https" or value.username is not None or value.password is not None:
            raise ValueError("Claim channels must use HTTPS without embedded credentials")
        return value


class Pack(Entry):
    id: Slug
    name: Label
    publisher: Label
    creator: Label
    description: str = Field(min_length=1, max_length=300)
    permission_note: str = Field(min_length=1, max_length=500)
    color: Literal["green", "lilac", "peach"] = "green"
    stickers: list[Sticker] = Field(min_length=1, max_length=40)
    channels: list[Channel] = Field(default_factory=list, max_length=6)
    archive: bool = False

    @model_validator(mode="after")
    def unique_pack_entries(self):
        if len({sticker.id for sticker in self.stickers}) != len(self.stickers):
            raise ValueError("Sticker IDs must be unique within a pack")
        if len({channel.id for channel in self.channels}) != len(self.channels):
            raise ValueError("Claim channel IDs must be unique within a pack")
        if any(channel.id == "archive" for channel in self.channels):
            raise ValueError("The archive channel ID is reserved")
        if not self.channels and not self.archive:
            raise ValueError("Every pack must have a claim channel or an archive")
        return self


class Manifest(Entry):
    packs: list[Pack] = Field(min_length=1, max_length=30)
    example: str | None = Field(default=None, min_length=1, max_length=250)
    demo: bool = False

    @model_validator(mode="after")
    def bounded_catalog(self):
        if len({pack.id for pack in self.packs}) != len(self.packs):
            raise ValueError("Pack IDs must be unique")
        if sum(len(pack.stickers) for pack in self.packs) > 400:
            raise ValueError("A catalog can contain at most 400 stickers")
        return self


@dataclass(frozen=True)
class IndexedSticker:
    path: Path
    metadata: MediaMetadata
    poster: bytes
    keys: tuple[Image.Image, ...]


@dataclass(frozen=True)
class Catalog:
    manifest: Manifest
    packs: dict[str, Pack]
    stickers: dict[tuple[str, str], IndexedSticker]
    example: tuple[Path, str] | None


def color_delta(left: Image.Image, right: Image.Image) -> Image.Image:
    red, green, blue = ImageChops.difference(left, right).split()
    return ImageChops.lighter(ImageChops.lighter(red, green), blue)


def visual_key(rgb: Image.Image) -> Image.Image:
    """Remove a uniform margin before comparing low-resolution colors and shapes."""
    rgb.thumbnail((256, 256), Image.Resampling.LANCZOS)
    right_edge, bottom_edge = rgb.width - 1, rgb.height - 1
    corners = [
        rgb.getpixel(point)
        for point in [(0, 0), (right_edge, 0), (0, bottom_edge), (right_edge, bottom_edge)]
    ]
    matte = tuple(sorted(channel)[1] for channel in zip(*corners, strict=True))
    similar_corners = sum(
        max(abs(x - y) for x, y in zip(corner, matte, strict=True)) < 24 for corner in corners
    )
    if similar_corners >= 3:
        delta = color_delta(rgb, Image.new("RGB", rgb.size, matte))
        # Ignore JPEG ringing and isolated speckles at the crop boundary.
        smooth = delta.resize((64, 64), Image.Resampling.BOX)
        bounds = smooth.point(lambda value: 255 if value > 26 else 0).getbbox()
        if bounds:
            left, top, right, bottom = bounds
            rgb = rgb.crop(
                (
                    left * rgb.width // 64,
                    top * rgb.height // 64,
                    (right * rgb.width + 63) // 64,
                    (bottom * rgb.height + 63) // 64,
                )
            )
    else:
        matte = (127, 127, 127)
    return ImageOps.pad(rgb, (32, 32), Image.Resampling.LANCZOS, matte)


def frame_keys(frame: Image.Image) -> list[Image.Image]:
    rgba = ImageOps.exif_transpose(frame).convert("RGBA")
    rgba.thumbnail((320, 320), Image.Resampling.LANCZOS)
    if rgba.getchannel("A").getextrema()[0] == 255:
        return [visual_key(rgba.convert("RGB"))]
    return [
        visual_key(Image.alpha_composite(Image.new("RGBA", rgba.size, matte), rgba).convert("RGB"))
        for matte in MATTES
    ]


def read_bounded(path: Path, limit: int = MAX_BYTES) -> bytes:
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise MediaError(f"{path.name} exceeds its byte limit")
    return data


def index_sticker(path: Path) -> IndexedSticker:
    data = read_bounded(path)
    metadata = inspect_media(data)
    with Image.open(BytesIO(data)) as image:
        poster = ImageOps.exif_transpose(image).convert("RGBA")
        poster.thumbnail((256, 256), Image.Resampling.LANCZOS)
        count = min(FRAME_SAMPLES, metadata.frame_count)
        keys = []
        for index in range(count):
            image.seek(round(index * (metadata.frame_count - 1) / max(1, count - 1)))
            keys.extend(frame_keys(image))
    return IndexedSticker(path, metadata, png_bytes(poster), tuple(keys))


@lru_cache(maxsize=2)
def load_catalog(root: Path) -> Catalog:
    manifest = Manifest.model_validate_json(read_bounded(safe_file(root, "manifest.json"), 512_000))
    stickers = {}
    for pack in manifest.packs:
        total_bytes = 0
        for sticker in pack.stickers:
            media = index_sticker(safe_file(root, sticker.file))
            stickers[pack.id, sticker.id] = media
            total_bytes += media.metadata.byte_size
        if pack.archive and total_bytes > MAX_ARCHIVE_BYTES:
            raise MediaError(f"{pack.id} exceeds the archive byte limit")
    example = None
    if manifest.example:
        path = safe_file(root, manifest.example)
        data = read_bounded(path, 5 * 1024 * 1024)
        validate_image(data)
        with Image.open(BytesIO(data)) as image:
            if getattr(image, "is_animated", False):
                raise MediaError("The example must be a single screenshot")
            example = (path, Image.MIME[image.format])
    return Catalog(manifest, {pack.id: pack for pack in manifest.packs}, stickers, example)


def image_distance(left: Image.Image, right: Image.Image) -> float:
    delta = ImageStat.Stat(ImageChops.difference(left, right))
    mean_squared = sum(value**2 for value in delta.rms)
    return (mean_squared / 3) ** 0.5 / 255


def find_packs(catalog: Catalog, data: bytes) -> list[tuple[str, str]]:
    validate_image(data)
    with Image.open(BytesIO(data)) as image:
        if getattr(image, "is_animated", False):
            raise MediaError("Use a single screenshot from the animation")
        queries = [key for key in frame_keys(image) if max(ImageStat.Stat(key).stddev) >= 8]
    if not queries:
        return []
    scores = {}
    for (pack_id, sticker_id), media in catalog.stickers.items():
        distance = min(image_distance(query, target) for query in queries for target in media.keys)
        candidate = (distance, sticker_id)
        if pack_id not in scores or candidate < scores[pack_id]:
            scores[pack_id] = candidate
    ranked = sorted(
        (distance, pack_id, sticker_id) for pack_id, (distance, sticker_id) in scores.items()
    )
    cutoff = min(MAX_MATCH_DISTANCE, ranked[0][0] + MIN_DISTANCE_MARGIN)
    return [
        (pack_id, sticker_id) for distance, pack_id, sticker_id in ranked[:3] if distance <= cutoff
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    args = parser.parse_args()
    catalog = load_catalog(args.catalog.resolve())
    print(f"Validated {len(catalog.packs)} packs with {len(catalog.stickers)} stickers")
