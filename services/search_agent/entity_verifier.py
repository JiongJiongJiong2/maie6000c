from concurrent.futures import ThreadPoolExecutor
import re

import numpy as np

from services.common.media import representative_frames
from services.retrieval import encoder
from .captions import caption_phrases, generic_subject
from .meme_deepseek import DeepSeekWeb
from .meme_fetch import FetchClient
from .meme_providers import vision_client
from .meme_types import MediaSource, PipelineError
from .page_media import page_sources

REFERENCE_SIMILARITY = 0.88


def verification_queries(analysis):
    composite = next((q.text for q in analysis.queries if q.angle == "composite"), "")
    uncertain = any(
        e.status in {"uncertain", "unknown"} or e.confidence < 0.8
        for e in analysis.entity_hypotheses
    )
    if (
        not composite
        and caption_phrases(analysis.ocr_text)
        and all(generic_subject(e.name) for e in analysis.entity_hypotheses)
    ):
        return []
    if not (composite or uncertain):
        return []
    names = " ".join(e.name for e in analysis.entity_hypotheses)[:64]
    observed = " ".join([*analysis.observations[:3], analysis.ocr_text]).strip()
    general = composite or " ".join([names, observed]).strip()
    description = next(
        (q.text for q in analysis.queries if q.angle == "visual_description"), observed
    )
    if not description:
        return [general[:128]] if general else []
    # Search a captioned archive by visible details as well as the unrestricted
    # web. This can recover when the initial guess about the subject is wrong.
    # Merge distinct cues across facets before applying the provider's length
    # limit, so a long description of one part cannot displace the others.
    ignored = set("a an and as at image in is of on the to with shows appears its wearing".split())
    cues = [*analysis.visual_keywords, description, observed]
    words = dict.fromkeys(
        word
        for cue in cues
        for word in re.findall(r"[\w&'-]+", cue.casefold())
        if word not in ignored
    )
    archive = ("site:thememedex.com " + " ".join(words))[:128].strip()
    probes = [archive, general[:128]] if composite else [general[:128], archive]
    return list(dict.fromkeys(q for q in probes if q))


def compare_reference_images(evidence, frames, settings, ledger, fetcher, embeddings, media_cache):
    # Reserve full-media retrieval for normal ranking. Only examine a few lead
    # images of retrieved pages, never their unrelated recommendations.
    count = min(6, len(evidence), settings.max_pages // 2, settings.max_previews)
    if not count or not frames:
        return

    def preview(row):
        try:
            source = MediaSource(source_url=row["url"], provider="deepseek", title=row["title"])
            data, url = fetcher.get(source.source_url, "page_attempts", 2 * 1024**2)
            try:
                sampled, _ = representative_frames(data, count=1, max_side=384)
                return row, url, sampled[0], data
            except (OSError, ValueError):
                clues = page_sources(source, data, url)
                if not clues:
                    return None
            row["lead_media_url"] = clues[0].media_url
            media, url = fetcher.get(clues[0].media_url, "preview_attempts", 2 * 1024**2)
            sampled, _ = representative_frames(media, count=1, max_side=384)
            return row, url, sampled[0], media
        except (OSError, ValueError, PipelineError) as exc:
            ledger.note(
                "reference_preview_unavailable",
                id=row["id"],
                code=exc.code if isinstance(exc, PipelineError) else "invalid_preview",
            )
            return None

    with ThreadPoolExecutor(max_workers=min(count, settings.concurrency)) as pool:
        references = [r for r in pool.map(preview, evidence[:count]) if r is not None]
    if not references:
        return
    try:
        vectors = embeddings.encode_images([*frames, *(r[2] for r in references)])
    except (OSError, RuntimeError, ValueError, ImportError):
        return  # The main ranking step reports encoder failures.
    scores = np.max(vectors[len(frames) :] @ vectors[: len(frames)].T, axis=1)
    for (row, media_url, _, data), score in zip(references, scores, strict=True):
        if np.isfinite(score):
            row["image_similarity"] = round(float(score), 4)
            if score >= REFERENCE_SIMILARITY:
                row["matching_media_url"] = media_url
                if media_cache is not None:
                    media_cache[media_url] = data


def verify_entities(
    analysis, frames, settings, ledger, *, fetcher=None, embeddings=None, media_cache=None
):
    queries = verification_queries(analysis) if settings.verify_entities else []
    # Reserve a query and a search call for actual media recall.
    budget = min(
        settings.max_queries - ledger.counts["queries"],
        settings.max_search_calls - ledger.counts["search_calls"],
    )
    if not queries or budget <= 1:
        return analysis, []
    web = DeepSeekWeb(settings, ledger)
    warnings, evidence = [], []
    seen = set()
    for query in queries[: budget - 1]:
        try:
            rows = web.verify(query)
        except PipelineError as exc:
            warnings.append(exc.code)
            continue
        ledger.note("verification_search", query=query, sources=len(rows))
        for rank, row in enumerate(rows):
            if row["url"] not in seen:
                seen.add(row["url"])
                evidence.append((rank, {**row, "id": f"ds-e{len(seen)}"}))
    evidence = [row for _, row in sorted(evidence, key=lambda item: item[0])]
    if not evidence:
        return analysis, warnings
    if len(queries) > 1:
        compare_reference_images(
            evidence,
            frames,
            settings,
            ledger,
            fetcher or FetchClient(ledger),
            embeddings or encoder,
            media_cache,
        )
        evidence.sort(key=lambda row: row.get("image_similarity", 0), reverse=True)
    try:
        corrected = vision_client(settings, ledger).analyze(frames, analysis.user_text, evidence)
        corrected.sampled_frames = analysis.sampled_frames
        ledger.note(
            "entity_verification",
            before=[e.model_dump() for e in analysis.entity_hypotheses],
            after=[e.model_dump() for e in corrected.entity_hypotheses],
            evidence=corrected.evidence,
        )
        return corrected, warnings
    except PipelineError as exc:
        analysis.evidence = evidence
        return analysis, [*warnings, exc.code]
