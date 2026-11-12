"""SHA plus conservative temporal fingerprints; source pages aren't content IDs."""

import re
from urllib.parse import unquote, urlsplit

import numpy as np
from PIL import Image, ImageDraw

from services.common.media import representative_frames, inspect_media
from services.common.storage import sha256


def source_identity(url, media_url=None):
    p = urlsplit(url)
    path = unquote(p.path)
    if p.hostname == "tenor.com" and "/view/" in path:
        match = re.search(r"-(\d+)/?$", path)
        if match:
            return "tenor:" + match[1]
    if p.hostname in {"reactionstash.com", "www.reactionstash.com"}:
        match = re.fullmatch(
            r"/r/[^/]+-([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})/?", path, re.IGNORECASE
        )
        if match:
            return "reactionstash:" + match[1].lower()
    if p.hostname == "commons.wikimedia.org" and path.casefold().startswith("/wiki/file:"):
        return "commons:" + path.casefold()
    if p.hostname in {"gifdb.com", "www.gifdb.com"} and media_url:
        media = urlsplit(media_url)
        match = re.fullmatch(
            r"/images/(?:branded/high|thumbnail|high)/[^/]+-([a-z0-9]{12,20})\.gif", media.path
        )
        if match and media.hostname in {"gifdb.com", "www.gifdb.com"}:
            return "gifdb:" + match[1]
    if p.hostname in {"vectorseek.com", "www.vectorseek.com"} and media_url:
        media = urlsplit(media_url)
        if media.hostname in {"vectorseek.com", "www.vectorseek.com"} and media.path.startswith(
            "/wp-content/uploads/"
        ):
            return "vectorseek:" + re.sub(r"-\d+x\d+(?=\.[a-z]+$)", "", media.path)
    if p.hostname in {"meme.com", "www.meme.com"} and media_url:
        page = re.fullmatch(r"/memes/([a-z0-9-]+)/?", path)
        media = urlsplit(media_url)
        media_path = re.sub(r"/+", "/", media.path)
        if (
            page
            and media.hostname == "cdn-v2.meme.com"
            and re.fullmatch(
                rf"/memes/{re.escape(page[1])}/(?:og-card/)?\d{{4}}-\d{{2}}-\d{{2}}/\d+\.(?:webp|png|jpe?g)",
                media_path,
            )
        ):
            return "meme-hero:" + page[1]
    return None


def remove_checkerboard(frame):
    """Normalize a regular white/gray matte connected to the image boundary.

    Keep enclosed gray artwork and black caption ink. A random gray photo or
    a two-tone illustration does not satisfy the alternating-border check.
    """
    pixels = np.asarray(frame, dtype=np.float32) / 255
    border = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
    neutral = border[np.ptp(border, axis=1) < 0.03].mean(axis=1)
    if len(neutral) < len(border) / 2:
        return frame
    low, high = [float(v) for v in np.quantile(neutral, [0.2, 0.8])]
    if low < 0.65 or high - low < 0.08:
        return frame

    def regular(edge):
        gray = edge.mean(axis=1)
        if float((np.minimum(abs(gray - low), abs(gray - high)) < 0.04).mean()) < 0.85:
            return False
        labels = abs(gray - high) < abs(gray - low)
        transitions = np.flatnonzero(labels[1:] != labels[:-1])
        widths = np.diff(transitions)
        return len(widths) >= 5 and float(widths.std() / max(1, widths.mean())) < 0.35

    if not any(regular(edge) for edge in [pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]]):
        return frame
    gray = pixels.mean(axis=2)
    eligible = (np.ptp(pixels, axis=2) < 0.03) & (gray >= low - 0.06) & (gray <= high + 0.05)
    mask = Image.fromarray(eligible.astype(np.uint8) * 255).copy()
    for point in [
        (0, 0),
        (frame.width - 1, 0),
        (0, frame.height - 1),
        (frame.width - 1, frame.height - 1),
    ]:
        if mask.getpixel(point) == 255:
            ImageDraw.floodfill(mask, point, 128)
    result = pixels.copy()
    result[np.asarray(mask) == 128] = 1
    return Image.fromarray((result * 255).round().astype(np.uint8))


def fingerprint(data, metadata=None, *, include_aspect=False):
    metadata = metadata or inspect_media(data)
    frames, _ = representative_frames(
        data, count=16 if metadata.frame_count > 1 else 1, max_side=256, preserve_timeline=True
    )
    if len(frames) == 1:
        frames = [remove_checkerboard(frames[0])]
    # Remove only flat outer padding; every foreground pixel, including text,
    # participates in the union crop across all sampled frames.
    for _ in range(3):
        pixels = np.stack([np.asarray(frame, dtype=np.float32) / 255 for frame in frames])
        corners = pixels[:, [0, 0, -1, -1], [0, -1, 0, -1]]
        if float(np.ptp(corners, axis=(0, 1)).max()) > 0.04:
            break
        background = np.median(corners.reshape(-1, 3), axis=0)
        mask = (np.abs(pixels - background).max(axis=-1) > 0.08).any(axis=0)
        ys, xs = np.where(mask)
        if not len(xs):
            break
        box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        if (
            box == (0, 0, frames[0].width, frames[0].height)
            or min(box[2] - box[0], box[3] - box[1]) < 8
        ):
            break
        frames = [frame.crop(box) for frame in frames]
    aspect = frames[0].width / frames[0].height
    value = np.stack(
        [np.asarray(frame.resize((64, 64)), dtype=np.float32) / 255 for frame in frames]
    )
    return (value, aspect) if include_aspect else value


def same_animation(a, b, *, strict=False):
    """Compare full time sampling and local regions, including caption changes."""
    n = max(len(a), len(b))
    ai = np.linspace(0, len(a) - 1, n).round().astype(int)
    bi = np.linspace(0, len(b) - 1, n).round().astype(int)
    difference = np.abs(a[ai] - b[bi])
    frame_errors = difference.mean(axis=(1, 2, 3))
    size = difference.shape[1]
    # Local tiles prevent a small meaningful text edit being hidden by a large
    # unchanged background. A strong pixel match can override CLIP's sensitivity
    # to source resize/codec differences, but not a changed local region.
    tile_errors = difference.reshape(n, 8, size // 8, 8, size // 8, 3).mean(axis=(2, 4, 5))
    return bool(
        float(frame_errors.mean()) < (0.006 if strict else 0.012)
        and float(frame_errors.max()) < (0.012 if strict else 0.035)
        and float(tile_errors.max()) < (0.025 if strict else 0.05)
    )


def same_static(a, b):
    """Full-foreground codec tolerance after explicit matte normalization."""
    difference = np.abs(a - b)
    size = difference.shape[1]
    tiles = difference.reshape(len(a), 8, size // 8, 8, size // 8, 3).mean(axis=(2, 4, 5))
    return bool(float(difference.mean()) < 0.02 and float(tiles.max()) < 0.12)


def same_motion(a, b):
    """Conservatively match rephased/repeated clips with rich temporal evidence.

    Nearest frames alone would merge reversed actions and two-color animations.
    Require distinct observations, forward progression, symmetric coverage and
    no persistent local edit (for example a changed caption).
    """
    if min(len(a), len(b)) < 8:
        return False
    for frames in (a, b):
        distinct = []
        for frame in frames:
            if all(float(np.abs(frame - old).mean()) > 0.008 for old in distinct):
                distinct.append(frame)
        if len(distinct) < 8:
            return False
    errors = np.abs(a[:, None] - b[None, :]).mean(axis=(2, 3, 4))
    for left, right, distances in [(a, b, errors), (b, a, errors.T)]:
        nearest = distances.argmin(axis=1)
        best = distances[np.arange(len(left)), nearest]
        if float(best.mean()) >= 0.035 or float(best.max()) >= 0.065:
            return False
        steps = np.diff(nearest) % len(right)
        if float(np.mean(steps <= len(right) / 2)) < 0.7:
            return False
        difference = np.abs(left - right[nearest])
        persistent = np.quantile(difference, 0.15, axis=0)
        size = persistent.shape[0]
        tiles = persistent.reshape(8, size // 8, 8, size // 8, 3).mean(axis=(1, 3, 4))
        if float(tiles.max()) >= 0.04:
            return False
    return True


def same_timeline(a, b):
    """Match frame-rate/phase changes with ordered, full-clip pixel evidence.

    Nearest-frame matching alone discards action order; the old rich-motion
    guard also missed short nods and subtle facial reactions. A cyclic DTW
    alignment must cover both timelines, preserve forward order and satisfy
    global and local pixel limits. Four distinct poses exclude two-color and
    almost-static clips. Caption edits remain visible in persistent tiles.
    """
    if min(len(a), len(b)) < 8:
        return False
    for frames in (a, b):
        distinct = []
        for frame in frames:
            if all(float(np.abs(frame - old).mean()) > 0.008 for old in distinct):
                distinct.append(frame)
        if len(distinct) < 4:
            return False
    # Block means bound pixel error cheaply; most different clips fail here.
    size = a.shape[1]
    coarse = [
        frames.reshape(len(frames), 8, size // 8, 8, size // 8, 3).mean(axis=(2, 4))
        for frames in (a, b)
    ]
    lower = np.abs(coarse[0][:, None] - coarse[1][None, :]).mean(axis=(2, 3, 4))
    if any(
        float(distances.min(axis=1).mean()) > 0.035 or float(distances.min(axis=1).max()) > 0.065
        for distances in (lower, lower.T)
    ):
        return False
    errors = np.abs(a[:, None] - b[None, :]).mean(axis=(2, 3, 4))
    n, m = errors.shape
    best, best_path = float("inf"), None
    for shift in range(m):
        rotated = np.roll(errors, shift, axis=1)
        costs = np.full((n + 1, m + 1), np.inf)
        costs[0, 0] = 0
        parents = np.zeros((n, m), dtype=np.uint8)
        for i in range(n):
            for j in range(m):
                options = (costs[i, j], costs[i, j + 1] + 0.003, costs[i + 1, j] + 0.003)
                step = int(np.argmin(options))
                costs[i + 1, j + 1] = rotated[i, j] + options[step]
                parents[i, j] = step
        i, j, pairs = n - 1, m - 1, []
        while i >= 0 and j >= 0:
            pairs.append((i, (j - shift) % m))
            step = parents[i, j]
            if step in (0, 1):
                i -= 1
            if step in (0, 2):
                j -= 1
        value = float(np.mean([errors[i, j] for i, j in pairs]))
        if value < best:
            best, best_path = value, pairs
    if best > 0.035 or best_path is None:
        return False
    difference = np.stack([np.abs(a[i] - b[j]) for i, j in best_path])
    if float(difference.mean(axis=(1, 2, 3)).max()) > 0.065:
        return False
    size = difference.shape[1]
    tiles = difference.reshape(len(best_path), 8, size // 8, 8, size // 8, 3).mean(axis=(2, 4, 5))
    return bool(
        float(np.quantile(tiles, 0.15, axis=0).max()) < 0.05
        and float(np.quantile(tiles.max(axis=(1, 2)), 0.95)) < 0.15
    )


def same_registered(a, b):
    """Verify small spatial crops using registered full temporal pixel evidence.

    At most 8% of each border may be cropped. Registration is proposed from
    the temporal median, then validated against every sampled frame and local
    tiles; a similar background or matching CLIP vector alone cannot merge.
    """
    size = a.shape[1]
    margins = (0, round(size * 0.03), round(size * 0.05), round(size * 0.08))
    edges = [(0, 0)] + [(m, m) for m in margins[1:]]
    edges += [(0, m) for m in margins[1:]] + [(m, 0) for m in margins[1:]]
    candidates = []
    for left, right in ((a, b), (b, a)):
        coarse = [
            frames.reshape(len(frames), 8, 8, 8, 8, 3).mean(axis=(2, 4)) for frames in (left, right)
        ]
        distances = np.abs(coarse[0][:, None] - coarse[1][None, :]).mean(axis=(2, 3, 4))
        i, j = np.unravel_index(distances.argmin(), distances.shape)
        references = [(np.median(left, axis=0), np.median(right, axis=0)), (left[i], right[j])]
        for reference, target in references:
            image = Image.fromarray((reference * 255).round().astype(np.uint8))
            target = (
                np.asarray(
                    Image.fromarray((target * 255).round().astype(np.uint8)).resize((32, 32)),
                    dtype=np.float32,
                )
                / 255
            )
            for top, bottom in edges:
                for x, end in edges:
                    box = (x, top, size - end, size - bottom)
                    sample = np.asarray(image.crop(box).resize((32, 32)), dtype=np.float32) / 255
                    bias = np.clip(np.median(sample - target, axis=(0, 1)), -0.06, 0.06)
                    error = float(np.abs(np.clip(sample - bias, 0, 1) - target).mean())
                    candidates.append((error, box, bias, left, right))
    for error, box, bias, left, right in sorted(candidates, key=lambda item: item[0])[:4]:
        if error > 0.035:
            break
        warped = np.stack(
            [
                np.asarray(
                    Image.fromarray((frame * 255).round().astype(np.uint8))
                    .crop(box)
                    .resize((size, size)),
                    dtype=np.float32,
                )
                / 255
                for frame in left
            ]
        )
        warped = np.clip(warped - bias, 0, 1)
        if same_animation(warped, right, strict=True) or same_timeline(warped, right):
            return True
    return False


class ContentGroups:
    def __init__(self):
        self.groups = []
        self.shas = set()

    def add(self, metadata, data, embedding, source_url, media_url=None):
        if metadata.sha256 in self.shas:
            return None, False
        self.shas.add(metadata.sha256)
        embedding = np.asarray(embedding, dtype=np.float32)
        embedding = embedding / max(float(np.linalg.norm(embedding)), 1e-12)
        identity = source_identity(source_url, media_url)
        fp, aspect = fingerprint(data, metadata, include_aspect=True)
        for group in self.groups:
            same_source = identity and identity == group["source_identity"]
            duration_close = (
                (metadata.media_kind == "static" and group["kind"] == "static")
                or (not metadata.duration_ms and not group["duration_ms"])
                or (
                    min(metadata.duration_ms, group["duration_ms"])
                    / max(1, metadata.duration_ms, group["duration_ms"])
                    > 0.85
                )
            )
            if same_source or (
                metadata.media_kind == group["kind"]
                and (
                    (
                        metadata.media_kind == "static"
                        and float(embedding @ group["embedding"]) > 0.97
                        and same_static(fp, group["fingerprint"])
                    )
                    or (
                        abs(aspect - group["aspect"]) / max(aspect, group["aspect"]) < 0.04
                        and (
                            (
                                duration_close
                                and float(embedding @ group["embedding"]) > 0.94
                                and same_animation(fp, group["fingerprint"])
                            )
                            or (
                                metadata.media_kind == "animated"
                                and (
                                    (
                                        float(embedding @ group["embedding"]) > 0.94
                                        and same_motion(fp, group["fingerprint"])
                                    )
                                    or (
                                        float(embedding @ group["embedding"]) > 0.88
                                        and (
                                            same_timeline(fp, group["fingerprint"])
                                            or same_registered(fp, group["fingerprint"])
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            ):
                return group["id"], False
        key = sha256((identity or metadata.sha256).encode())[:32]
        self.groups.append(
            dict(
                id=key,
                source_identity=identity,
                aspect=aspect,
                duration_ms=metadata.duration_ms,
                kind=metadata.media_kind,
                embedding=embedding,
                fingerprint=fp,
            )
        )
        return key, True
