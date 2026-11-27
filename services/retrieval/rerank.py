"""Versioned development score. It is a relevance score, never a correctness rate."""

import re
import numpy as np


def score_candidate(query_vectors, candidate_vectors, text_vector, title, user_text, metadata):
    if (
        not np.isfinite(query_vectors).all()
        or not np.isfinite(candidate_vectors).all()
        or not np.isfinite(text_vector).all()
    ):
        raise ValueError("Nonfinite embedding")
    similarities = query_vectors @ candidate_vectors.T
    temporal = float(np.mean(np.max(similarities, axis=1)))
    visual = float(np.max(similarities))
    semantic = float(np.max(candidate_vectors @ text_vector))
    wanted = set(re.findall(r"\w+", user_text.casefold()))
    actual = set(re.findall(r"\w+", title.casefold()))
    text_overlap = len(wanted & actual) / max(1, len(wanted))
    quality = min(1.0, (metadata.width * metadata.height) ** 0.5 / 400)
    value = (
        0.60 * visual + 0.25 * semantic + 0.10 * temporal + 0.025 * quality + 0.025 * text_overlap
    )
    if not np.isfinite(value):
        raise ValueError("Nonfinite score")
    return float(value), dict(
        visual=visual,
        semantic=semantic,
        temporal_coverage=temporal,
        text_overlap=text_overlap,
        quality=quality,
    )


def picture_regions(frame):
    """Compare the full still and the photo inside a light/dark caption band."""
    from PIL import Image

    def thumbnail(image):
        small = np.asarray(image.resize((32, 32), Image.Resampling.BILINEAR), dtype=np.float32)
        return image.width / image.height, small / 255.0

    regions = [thumbnail(frame)]
    if min(frame.size) < 48:
        return regions
    pixels = np.asarray(frame.resize((96, 96), Image.Resampling.BILINEAR))[:, 2:-2]
    neutral = (pixels.max(axis=2) < 45) | (pixels.min(axis=2) > 210)
    flat = neutral.mean(axis=1) >= 0.67
    # Ignore a thin printed border. Require a sustained transition to artwork.
    top, bottom = 0, 96
    for reverse in (False, True):
        rows = flat[::-1] if reverse else flat
        if rows[2:6].mean() < 0.5:
            continue
        boundary = next(
            (i for i in range(6, 40) if not rows[i : i + 6].any() and rows[2:i].mean() >= 0.60),
            None,
        )
        if boundary is not None:
            if reverse:
                bottom = 96 - boundary
            else:
                top = boundary
    if (top or bottom != 96) and bottom - top >= 52:
        regions.append(
            thumbnail(
                frame.crop(
                    (
                        0,
                        round(frame.height * top / 96),
                        frame.width,
                        round(frame.height * bottom / 96),
                    )
                )
            )
        )
    return regions


def matching_picture(query_regions, candidate_frame):
    """Require local pixel agreement on textured artwork, including aspect ratio."""
    for index, (aspect, pixels) in enumerate(picture_regions(candidate_frame)):
        for query_index, (query_aspect, reference) in enumerate(query_regions):
            if abs(aspect / query_aspect - 1) > 0.055 or reference.std(axis=(0, 1)).mean() < 0.10:
                continue
            difference = np.abs(pixels - reference)
            tiles = difference.reshape(4, 8, 4, 8, 3).mean(axis=(1, 3, 4))
            if difference.mean() <= 0.038 and np.quantile(tiles, 0.9) <= 0.085:
                return "same_picture" if index or query_index else "near_copy"
    return ""
