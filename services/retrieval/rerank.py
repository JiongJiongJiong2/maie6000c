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
