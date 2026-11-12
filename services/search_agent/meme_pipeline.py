"""Image-first bounded orchestration for meme50-v2; no business DB writes."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
import traceback

import numpy as np

from services.common.media import MAX_BYTES, inspect_media, representative_frames, preview_bytes
from services.common.storage import atomic_write
from services.retrieval import encoder
from services.retrieval.dedup import ContentGroups, source_identity
from services.retrieval.download import canonical_url
from services.retrieval.rerank import score_candidate
from .entity_verifier import verify_entities
from .meme_fetch import FetchClient
from .meme_deepseek import DeepSeekWeb, DeepSeekQueryPlanner
from .meme_types import Ledger, MemeSettings, PipelineError, PreparedMedia
from .page_media import page_sources
from .visual_analysis import analyze_image


def fuse_sources(sources, maximum):
    by_url = {}
    for source in sources:
        try:
            source.checked()
            key = canonical_url(source.media_url or source.source_url)
            if not source.media_url:
                key = source_identity(source.source_url) or key
        except ValueError:
            continue
        rank_score = 1 / (60 + source.source_rank)
        if key in by_url:
            by_url[key].fusion_score += rank_score
            by_url[key].recall_channels = sorted(
                set(by_url[key].recall_channels + [source.channel])
            )
        else:
            by_url[key] = source.model_copy(
                update={"fusion_score": rank_score, "recall_channels": [source.channel]}
            )
    return sorted(by_url.values(), key=lambda s: (-s.fusion_score, s.media_url or s.source_url))[
        :maximum
    ]


def search_memes(
    image_path,
    user_text,
    work_dir,
    target_count=50,
    *,
    settings=None,
    emit=None,
    analyze=None,
    reverse=None,
    keywords=None,
    fetcher=None,
    embeddings=None,
):
    """Injectable boundaries for CI; the production runner supplies none of them."""
    settings = settings or MemeSettings()
    if not 1 <= target_count <= 50:
        raise ValueError("target_count must be 1..50")
    user_text = (user_text or "").strip()
    if len(user_text) > 500:
        raise ValueError("description limit")
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(settings)
    fetcher = fetcher or FetchClient(ledger)
    # The active profile has no pixel reverse-search service. An injected reverse
    # boundary remains useful for deterministic regression tests, never production.
    keywords = keywords or DeepSeekWeb(settings, ledger)
    embeddings = embeddings or encoder
    warnings = []
    prepared = {}
    groups = ContentGroups()
    seen_media, seen_pages, seen_previews = set(), set(), set()
    all_sources = []
    analysis = None
    stop = "query_limit"
    counts = dict(metadata=0, valid_media=0, low_score=0, sha_duplicates=0, content_duplicates=0)
    counts.update(
        page_failures=0,
        page_clues=0,
        media_decode_failures=0,
        metadata_returned=0,
        channel_recall={"reverse-image": 0, "keyword": 0},
        channel_download_attempts={"reverse-image": 0, "keyword": 0},
    )
    emit = emit or (lambda *_: None)

    def event(kind, **payload):
        emit(kind, payload)

    def stage(name):
        ledger.note("stage", stage=name)
        event("stage", stage=name)

    def finish(status):
        chosen = sorted(prepared.values(), key=lambda p: (-p.score, p.content_group_id))[
            :target_count
        ]
        if status == "failed":
            chosen = []
        result = dict(
            status=status,
            stop_reason=stop,
            candidate_keys=[p.key for p in chosen],
            partial=bool(warnings),
            warnings=list(dict.fromkeys(warnings)),
            ledger=ledger.counts.copy(),
            trace=ledger.trace,
            counts={**counts, "content_groups": len(prepared)},
            model_version=encoder.MODEL_VERSION,
            scoring_version=settings.scoring_version,
            dedup_version=settings.dedup_version,
        )
        event("final", **result)
        return result

    try:
        stage("preprocessing")
        data = Path(image_path).read_bytes()
        inspect_media(data)
        stage("understanding")
        if analyze:
            analysis, query_frames = analyze(data, user_text, settings, ledger)
        else:
            analysis, query_frames = analyze_image(data, user_text, settings, ledger)
        stage("verifying")
        if not analyze:
            analysis, verify_warnings = verify_entities(analysis, query_frames, settings, ledger)
            warnings.extend(verify_warnings)
        stage("recalling")
        if not analyze:
            try:
                analysis.queries = DeepSeekQueryPlanner(settings, ledger).plan(analysis)
                analysis.planner_version = (
                    "deepseek/" + settings.deepseek_model + "/" + DeepSeekQueryPlanner.version
                )
            except PipelineError as exc:
                warnings.append(exc.code)
                ledger.note("query_planning_failed", provider="deepseek", code=exc.code)
            # Both actual providers share one finite query ledger.
            analysis.queries = [
                q.model_copy(update={"text": q.text.strip()[:128]})
                for q in analysis.queries[: max(0, settings.max_queries - ledger.counts["queries"])]
                if q.text.strip()
            ]
        reverse_ok = False
        if reverse is None:
            ledger.note("reverse_image_disabled", reason="hkust-deepseek-only")
        for frame in query_frames[:2] if reverse is not None else []:
            try:
                sources, ocr, entities = reverse.search(frame)
                reverse_ok = True
                all_sources.extend(sources)
                counts["metadata_returned"] += len(sources)
                counts["channel_recall"]["reverse-image"] += len(sources)
                if ocr:
                    analysis.ocr_text = ocr
                    analysis.ocr_provider = "google-vision/TEXT_DETECTION"
                ledger.note(
                    "reverse_image",
                    sources=len(sources),
                    web_entities=[
                        {
                            "description": str(e.get("description", ""))[:120],
                            "score": e.get("score"),
                        }
                        for e in entities[:12]
                    ],
                )
            except PipelineError as exc:
                warnings.append(exc.code)
                break
        if reverse is not None and not reverse_ok:
            warnings.append("reverse_image_unavailable")
        event("analysis_ready", analysis=analysis.model_dump(mode="json"))
        try:
            embeddings.load_model()
            query_vectors = embeddings.encode_images(query_frames)
            intent = " ".join(
                [
                    *analysis.observations,
                    *analysis.action_tags,
                    *analysis.emotion_tags,
                    user_text,
                    analysis.ocr_text,
                ]
            )[:1200]
            text_vector = embeddings.encode_texts([intent])[0]
        except Exception:
            raise PipelineError("model_unavailable") from None
        keyword_ok = False
        queued = []

        def download(source):
            def get_original(url):
                with ledger.lock:
                    for channel in source.recall_channels or [source.channel]:
                        counts["channel_download_attempts"][channel] = (
                            counts["channel_download_attempts"].get(channel, 0) + 1
                        )
                return fetcher.get(url, "media_attempts", MAX_BYTES)

            try:
                content, final_url = get_original(source.media_url)
                if content.lstrip()[:32].lower().startswith((b"<html", b"<!doctype html")):
                    # Some actual media URLs return an HTML embed wrapper. Read
                    # its real clues once; never invent CDN aliases/extensions.
                    ledger.take("page_attempts")
                    ledger.note("media_html_wrapper", host=urlsplit(final_url).hostname)
                    for clue in page_sources(source, content[: 2 * 1024 * 1024], final_url):
                        if clue.media_url in {source.media_url, final_url}:
                            continue
                        try:
                            original, _ = get_original(clue.media_url)
                            inspect_media(original)
                            return clue, original, None
                        except (PipelineError, ValueError, OSError):
                            continue
                    return source, None, "html_wrapper_no_valid_media"
                return source, content, None
            except PipelineError as exc:
                return source, None, exc.code
            except (ValueError, OSError):
                return source, None, "invalid_media_source"

        def process_direct(direct):
            nonlocal stop
            for start in range(0, len(direct), 12):
                ledger.remaining()
                batch = direct[
                    start : start
                    + min(12, settings.max_originals - ledger.counts["media_attempts"])
                ]
                if not batch:
                    break
                accepted = []
                with ThreadPoolExecutor(max_workers=settings.concurrency) as pool:
                    for source, content, failure in pool.map(download, batch):
                        if failure:
                            warnings.append(failure)
                            ledger.note(
                                "media_failure",
                                code=failure,
                                host=urlsplit(source.media_url).hostname,
                                path=urlsplit(source.media_url).path[:250],
                            )
                            continue
                        try:
                            metadata = inspect_media(content)
                            frames, _ = representative_frames(content, count=8, max_side=384)
                            accepted.append((source, content, metadata, frames))
                        except (ValueError, OSError):
                            counts["media_decode_failures"] += 1
                            ledger.note(
                                "media_rejected",
                                reason="invalid_media",
                                host=urlsplit(source.media_url).hostname,
                            )
                            warnings.append("invalid_media")
                if not accepted:
                    continue
                stage("reranking")
                frames = [f for _, _, _, sample in accepted for f in sample]
                vectors = embeddings.encode_images(frames)
                offset = 0
                for source, content, metadata, samples in accepted:
                    sample_vectors = vectors[offset : offset + len(samples)]
                    offset += len(samples)
                    if metadata.sha256 in groups.shas:
                        counts["sha_duplicates"] += 1
                        continue
                    counts["valid_media"] += 1
                    score, signals = score_candidate(
                        query_vectors,
                        sample_vectors,
                        text_vector,
                        source.title,
                        user_text,
                        metadata,
                    )
                    ledger.note(
                        "media_ranked",
                        sha256=metadata.sha256,
                        score=score,
                        signals=signals,
                        accepted=score >= settings.minimum_score,
                        kind=metadata.media_kind,
                        width=metadata.width,
                        height=metadata.height,
                        source_host=urlsplit(source.source_url).hostname,
                        source_path=urlsplit(source.source_url).path[:250],
                    )
                    if score < settings.minimum_score:
                        counts["low_score"] += 1
                        continue
                    group, is_new = groups.add(
                        metadata,
                        content,
                        sample_vectors.mean(axis=0),
                        source.source_url,
                        source.media_url,
                    )
                    if not group:
                        counts["sha_duplicates"] += 1
                        continue
                    if not is_new:
                        counts["content_duplicates"] += 1
                    old = prepared.get(group)
                    # Prefer useful resolution for the same content group, with
                    # score as a deterministic tiebreaker. Groups never fill slots twice.
                    if (
                        old
                        and old.metadata.width * old.metadata.height
                        >= metadata.width * metadata.height
                    ):
                        continue
                    relative = f"originals/{metadata.sha256}.{metadata.suffix}"
                    preview = f"previews/{metadata.sha256}.png"
                    poster = preview_bytes(content)
                    # Conservatively reserve all three copies: runner, verified
                    # draft and final result (including superseded group versions).
                    ledger.take("disk_bytes", 3 * (len(content) + len(poster)))
                    atomic_write(work, relative, content)
                    atomic_write(work, preview, poster)
                    item = PreparedMedia(
                        key=metadata.sha256,
                        relative_path=relative,
                        preview_relative_path=preview,
                        metadata=metadata,
                        source_url=source.source_url,
                        media_url=source.media_url,
                        provider=source.provider,
                        score=score,
                        content_group_id=group,
                        signals=signals,
                    ).validate_paths()
                    prepared[group] = item
                    event("candidate_ready", candidate=item.model_dump(mode="json"))
                event(
                    "progress",
                    verified_count=len(prepared),
                    counts=counts.copy(),
                    ledger=ledger.counts.copy(),
                )
                if len(prepared) >= target_count:
                    stop = "target_reached"
                    break

        queries = analysis.queries[: settings.max_queries]
        for query_index, query in enumerate(queries):
            ledger.remaining()
            try:
                sources = keywords.search(query.text, limit=min(200, settings.max_sources))
                keyword_ok = True
                counts["metadata_returned"] += len(sources)
                counts["channel_recall"]["keyword"] += len(sources)
                all_sources.extend(sources)
                ledger.note(
                    "keyword_web",
                    provider="deepseek",
                    query=query.model_dump(),
                    sources=len(sources),
                )
            except PipelineError as exc:
                warnings.append(exc.code)
            all_sources = fuse_sources(all_sources, settings.max_sources)
            counts["metadata"] = len(all_sources)
            if not all_sources:
                continue
            stage("fetching")
            # Thumbnail coarse pass precedes full media. The same global fetch
            # ledger includes previews, pages and originals across every query.
            coarse = []
            for source in all_sources:
                key = canonical_url(source.media_url or source.source_url)
                if key in seen_media or key in seen_pages:
                    continue
                if source.preview_url and source.preview_url not in seen_previews:
                    seen_previews.add(source.preview_url)
                    queued.append(source)
                else:
                    coarse.append((source.fusion_score, source))
            preview_batch = queued[
                : min(48, settings.max_previews - ledger.counts["preview_attempts"])
            ]
            queued = queued[len(preview_batch) :]
            preview_data = []

            def preview_download(source):
                try:
                    image, _ = fetcher.get(source.preview_url, "preview_attempts", 2 * 1024 * 1024)
                    frame, _ = representative_frames(image, count=1, max_side=384)
                    return source, frame[0]
                except (PipelineError, ValueError, OSError):
                    return source, None

            with ThreadPoolExecutor(max_workers=settings.concurrency) as pool:
                for source, frame in pool.map(preview_download, preview_batch):
                    if frame is not None:
                        preview_data.append((source, frame))
                    else:
                        coarse.append((source.fusion_score, source))
            if preview_data:
                vectors = embeddings.encode_images([f for _, f in preview_data])
                for (source, _), vector in zip(preview_data, vectors, strict=True):
                    coarse.append((float(np.max(query_vectors @ vector)), source))
            ordered = [s for _, s in sorted(coarse, key=lambda x: (-x[0], x[1].source_url))]
            direct, pages = [], []
            # Fair-share the remaining page allowance across query angles. A
            # slow first query must not consume the entire job before originals
            # are fetched or before a second query can contribute.
            remaining_pages = max(0, settings.max_pages - ledger.counts["page_attempts"])
            remaining_queries = max(1, len(queries) - query_index)
            page_allowance = (remaining_pages + remaining_queries - 1) // remaining_queries
            for source in ordered:
                if source.media_url:
                    key = canonical_url(source.media_url)
                    if key not in seen_media:
                        seen_media.add(key)
                        direct.append(source)
                elif source.source_url not in seen_pages and len(pages) < page_allowance:
                    seen_pages.add(source.source_url)
                    pages.append(source)
            process_direct(direct)
            if len(prepared) < target_count:
                # Finish a small page wave before starting media I/O: global
                # request concurrency remains <= configured concurrency.
                def read_page(source):
                    try:
                        page, final_url = fetcher.get(
                            source.source_url, "page_attempts", 2 * 1024 * 1024
                        )
                        extracted = page_sources(source, page, final_url)
                        with ledger.lock:
                            counts["page_clues"] += len(extracted)
                        ledger.note(
                            "page_extracted",
                            host=urlsplit(final_url).hostname,
                            path=urlsplit(final_url).path[:250],
                            clues=len(extracted),
                        )
                        return extracted
                    except (PipelineError, ValueError, OSError) as exc:
                        code = exc.code if isinstance(exc, PipelineError) else "invalid_source_page"
                        with ledger.lock:
                            counts["page_failures"] += 1
                        ledger.note(
                            "page_failure", code=code, host=urlsplit(source.source_url).hostname
                        )
                        return code

                for offset in range(0, len(pages), 4):
                    ledger.remaining()
                    stage("fetching")
                    direct = []
                    with ThreadPoolExecutor(max_workers=min(4, settings.concurrency)) as pool:
                        for extracted in pool.map(read_page, pages[offset : offset + 4]):
                            if isinstance(extracted, str):
                                warnings.append(extracted)
                                continue
                            for item in extracted:
                                key = canonical_url(item.media_url)
                                if key not in seen_media:
                                    seen_media.add(key)
                                    direct.append(item)
                    process_direct(direct)
                    if len(prepared) >= target_count:
                        break
            if len(prepared) >= target_count:
                break
            if ledger.counts["media_attempts"] >= settings.max_originals:
                stop = "media_attempts_limit"
                break
        if not keyword_ok and not reverse_ok:
            raise PipelineError("recall_providers_unavailable")
        stage("finalizing")
        if len(prepared) < target_count:
            warnings.append("insufficient_distinct_relevant_media")
        return finish("completed")
    except PipelineError as exc:
        stop = exc.code
        if prepared:
            warnings.append(exc.code)
            return finish("completed")
        event("error", code=exc.code)
        return finish("failed")
    except Exception as exc:
        # Keep bounded, enum/stack-only diagnostics. Exception strings can contain
        # untrusted provider bodies or credentials and are never serialized.
        stop = "pipeline_internal_error"
        frames = [
            dict(file=Path(f.filename).name, function=f.name, line=f.lineno)
            for f in traceback.extract_tb(exc.__traceback__)
            if "/services/" in f.filename
        ][-8:]
        ledger.note("internal_error", error_type=type(exc).__name__, frames=frames)
        event("error", code=stop, error_type=type(exc).__name__)
        return finish("failed")
