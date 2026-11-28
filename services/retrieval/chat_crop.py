"""Suggest one visible sticker in a flat chat interface using only image pixels."""

import math

import numpy as np
from PIL import Image, ImageOps


def _intervals(active, gap):
    positions = np.flatnonzero(active)
    if not positions.size:
        return []
    groups = np.split(positions, np.flatnonzero(np.diff(positions) > gap + 1) + 1)
    return [(int(group[0]), int(group[-1]) + 1) for group in groups]


def _foreground(pixels):
    height, width, _ = pixels.shape
    band = max(2, min(height, width) // 8)
    margin = np.concatenate(
        [
            pixels[:band].reshape(-1, 3),
            pixels[-band:].reshape(-1, 3),
            pixels[band:-band, :band].reshape(-1, 3),
            pixels[band:-band, -band:].reshape(-1, 3),
        ]
    )
    # Find colors that occupy broad, flat surfaces in the screen margins.
    quantized = margin // 8
    keys = (quantized[:, 0] * 1024 + quantized[:, 1] * 32 + quantized[:, 2]).astype(np.int32)
    counts = np.bincount(keys, minlength=32768)
    colors = []
    for index in counts.argsort()[-6:][::-1]:
        if counts[index] < len(margin) * 0.045:
            break
        color = np.median(margin[keys == index], axis=0).astype(np.int16)
        if all(np.abs(color - other).max() > 10 for other in colors):
            colors.append(color)
    if not colors:
        return None
    edge = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
    if np.mean(np.min([np.abs(edge - c).max(axis=1) for c in colors], axis=0) < 16) < 0.7:
        return None
    foreground = np.ones((height, width), dtype=bool)
    for color in colors:
        foreground &= np.abs(pixels - color).max(axis=2) > 19
    return foreground


def _is_picture(patch):
    height, width = patch.shape[:2]
    horizontal_edges = np.abs(np.diff(patch, axis=1)).max(axis=2) > 23
    vertical_edges = np.abs(np.diff(patch, axis=0)).max(axis=2) > 23
    detailed_rows = horizontal_edges.sum(axis=1) >= max(2, width // 36)
    detailed_cols = vertical_edges.sum(axis=0) >= max(2, height // 36)
    return detailed_rows.mean() >= 0.35 and detailed_cols.mean() >= 0.35


def propose_chat_crop(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Return a crop in EXIF-transposed pixel coordinates, or abstain.

    Requires a dominant picture and separated text-like chrome on a flat surface.
    Never crops an image with transparency or guesses between comparable pictures.
    """
    if min(image.size) < 48:
        return None
    preview = ImageOps.exif_transpose(image)
    oriented_width, oriented_height = preview.size
    if preview.has_transparency_data:
        if preview.convert("RGBA").getchannel("A").getextrema()[0] < 255:
            return None
    preview.thumbnail((360, 420), Image.Resampling.BILINEAR)
    if min(preview.size) < 24:
        return None
    pixels = np.asarray(preview.convert("RGB"), dtype=np.int16)
    height, width, _ = pixels.shape
    short = min(height, width)
    foreground = _foreground(pixels)
    if foreground is None:
        return None
    regions = []
    for top, bottom in _intervals(foreground.sum(axis=1) >= max(3, width // 75), short // 38):
        stripe = foreground[top:bottom]
        for left, right in _intervals(stripe.sum(axis=0) >= max(1, len(stripe) // 50), short // 32):
            regions.append((left, top, right, bottom))
    pictures, labels = [], []
    for left, top, right, bottom in regions:
        w, h = right - left, bottom - top
        if h <= 0.14 * short and w > 2 * h and w >= 0.12 * short:
            labels.append((top, bottom))
        elif (
            min(w, h) >= 0.18 * short
            and 0.28 < w / h < 3.1
            and w * h >= 0.022 * height * width
            and w * h <= 0.8 * height * width
            and min(left, top, width - right, height - bottom) >= max(2, short // 35)
            and _is_picture(pixels[top:bottom, left:right])
        ):
            pictures.append((w * h, (left, top, right, bottom)))
    if not pictures or not labels:
        return None
    pictures.sort(reverse=True)
    if len(pictures) > 1 and pictures[1][0] >= pictures[0][0] * 0.45:
        return None
    left, top, right, bottom = pictures[0][1]
    gap = max(2, short // 60)
    above = any(end <= top - gap for _, end in labels)
    below = any(start >= bottom + gap for start, _ in labels)
    if not (above and below):
        return None

    pad = max(2, round(0.035 * max(right - left, bottom - top)))
    xscale, yscale = oriented_width / width, oriented_height / height
    return (
        max(0, math.floor((left - pad) * xscale)),
        max(0, math.floor((top - pad) * yscale)),
        min(oriented_width, math.ceil((right + pad) * xscale)),
        min(oriented_height, math.ceil((bottom + pad) * yscale)),
    )
