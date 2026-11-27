"""Decode original GIF bytes and rank sampled frames with the local CLIP model."""

import io
import os
import time
import warnings
from pathlib import Path

import numpy as np
from PIL import Image

from services.common.config import get_settings
from services.common.storage import MediaError, atomic_write, sha256, validate_image
from services.search_agent.models import Candidate, PreparedBatch, Source
from . import encoder
from .download import MEDIA_HOSTS, DownloadError, canonical_url, fetch


def prepare_candidates(image_path, sources, work_dir, budget):
    batch = PreparedBatch(downloads_used=0, model_version=encoder.MODEL_VERSION)
    minimum = float(os.environ.get("RETRIEVAL_MIN_SIMILARITY", "0.82"))
    if not np.isfinite(minimum) or not -1 <= minimum <= 1:
        raise ValueError("Invalid similarity threshold")
    root = Path(work_dir).resolve()
    if Path(work_dir).is_symlink():
        batch.failures.append("storage_failed")
        return batch
    seen_urls, seen_hashes = set(), set()
    query = None
    for raw in sources:
        if batch.downloads_used >= budget.remaining_downloads:
            break
        if time.monotonic() >= budget.deadline:
            batch.failures.append("download_timeout")
            break
        try:
            source = Source.model_validate(raw)
            url = canonical_url(source.image_url or source.source_url)
        except ValueError:
            batch.failures.append("unsupported_source")
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            data, _, redirects = fetch(
                url,
                hosts=MEDIA_HOSTS,
                max_bytes=min(12 * 1024 * 1024, get_settings().max_candidate_bytes),
                deadline=budget.deadline,
            )
            batch.downloads_used += 1
            batch.redirects += redirects
        except DownloadError as exc:
            batch.downloads_used += int(exc.attempted)
            batch.redirects += exc.redirects
            batch.failures.append(exc.code)
            batch.diagnostics.append(
                dict(code=exc.code, reason=exc.reason, stage=exc.stage, http_status=exc.http_status)
            )
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as probe:
                    fmt, count = probe.format, getattr(probe, "n_frames", 1)
            if fmt in {"JPEG", "PNG"} or (fmt == "GIF" and count == 1):
                batch.failures.append("static_image")
                continue
            if fmt != "GIF":
                batch.failures.append("not_gif")
                continue
            count = validate_image(data, animated_gif=True)
        except (
            ValueError,
            OSError,
            EOFError,
            SyntaxError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            batch.failures.append("invalid_media")
            continue
        digest = sha256(data)
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        if time.monotonic() >= budget.deadline:
            batch.failures.append("download_timeout")
            break
        if query is None:
            try:
                encoder.load_model()
            except Exception:
                batch.failures.append("model_unavailable")
                break
        if time.monotonic() >= budget.deadline:
            batch.failures.append("download_timeout")
            break
        try:
            if query is None:
                with Image.open(image_path) as image:
                    query = encoder.encode_image(image)
            frames = []
            with Image.open(io.BytesIO(data)) as gif:
                for frame in np.linspace(0, count - 1, min(8, count), dtype=int):
                    gif.seek(int(frame))
                    frames.append(gif.convert("RGBA").copy())
            vectors = encoder.encode_images(frames)
            if (
                vectors.ndim != 2
                or vectors.shape[0] != len(frames)
                or query.ndim != 1
                or vectors.shape[1] != query.shape[0]
                or not np.isfinite(vectors).all()
                or not np.isfinite(query).all()
            ):
                raise ValueError("Invalid embeddings")
            norms = np.linalg.norm(vectors, axis=1)
            qnorm = np.linalg.norm(query)
            if (
                not np.isfinite(qnorm)
                or not np.isfinite(norms).all()
                or qnorm <= 0
                or (norms <= 0).any()
            ):
                raise ValueError("Zero embedding")
            score = float(np.max((vectors / norms[:, None]) @ (query / qnorm)))
            if not np.isfinite(score):
                raise ValueError("Invalid score")
        except Exception:
            batch.failures.append("embedding_failed")
            break
        if time.monotonic() >= budget.deadline:
            batch.failures.append("download_timeout")
            break
        if score < minimum:
            batch.rejected_low_score += 1
            continue
        relative = digest + ".gif"
        try:
            atomic_write(root, relative, data)
        except (OSError, MediaError):
            batch.failures.append("storage_failed")
            continue
        batch.candidates.append(
            Candidate(
                relative_path=relative,
                sha256=digest,
                source_url=source.source_url,
                image_url=source.image_url or source.source_url,
                provider=source.provider,
                format="GIF",
                frame_count=count,
                score=min(1.0, max(-1.0, score)),
            )
        )
    batch.candidates = sorted(batch.candidates, key=lambda c: (-c.score, c.sha256))[:3]
    return batch
