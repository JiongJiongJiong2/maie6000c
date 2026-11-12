"""SHA plus conservative temporal fingerprints; source pages aren't content IDs."""

import re
from urllib.parse import unquote, urlsplit

import numpy as np

from services.common.media import representative_frames, inspect_media
from services.common.storage import sha256


def source_identity(url):
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
    if p.hostname in {"imgbin.com", "www.imgbin.com"}:
        match = re.fullmatch(r"/png/([A-Za-z0-9]{6,40})/[^/]+/?", path)
        if match:
            return "imgbin:" + match[1]
    return None


def fingerprint(data, metadata=None):
    metadata = metadata or inspect_media(data)
    frames, _ = representative_frames(
        data, count=16 if metadata.frame_count > 1 else 1, max_side=128, preserve_timeline=True
    )
    return np.stack(
        [np.asarray(frame.resize((64, 64)), dtype=np.float32) / 255 for frame in frames]
    )


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
        float(distances.min(axis=1).mean()) > 0.022 or float(distances.min(axis=1).max()) > 0.05
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
    if best > 0.022 or best_path is None:
        return False
    difference = np.stack([np.abs(a[i] - b[j]) for i, j in best_path])
    if float(difference.mean(axis=(1, 2, 3)).max()) > 0.05:
        return False
    size = difference.shape[1]
    tiles = difference.reshape(len(best_path), 8, size // 8, 8, size // 8, 3).mean(axis=(2, 4, 5))
    return bool(
        float(np.quantile(tiles, 0.15, axis=0).max()) < 0.05
        and float(np.quantile(tiles.max(axis=(1, 2)), 0.95)) < 0.10
    )


class ContentGroups:
    def __init__(self):
        self.groups = []
        self.shas = set()

    def add(self, metadata, data, embedding, source_url):
        if metadata.sha256 in self.shas:
            return None, False
        self.shas.add(metadata.sha256)
        embedding = np.asarray(embedding, dtype=np.float32)
        embedding = embedding / max(float(np.linalg.norm(embedding)), 1e-12)
        identity = source_identity(source_url)
        fp = fingerprint(data, metadata)
        for group in self.groups:
            same_source = identity and identity == group["source_identity"]
            aspect = metadata.width / metadata.height
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
                abs(aspect - group["aspect"]) < 0.025
                and metadata.media_kind == group["kind"]
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
                                and same_timeline(fp, group["fingerprint"])
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
                aspect=metadata.width / metadata.height,
                duration_ms=metadata.duration_ms,
                kind=metadata.media_kind,
                embedding=embedding,
                fingerprint=fp,
            )
        )
        return key, True
