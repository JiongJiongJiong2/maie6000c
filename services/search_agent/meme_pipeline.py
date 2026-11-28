"""Image-first bounded orchestration for meme50-v2; no business DB writes."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
import traceback

import numpy as np

from services.common.media import MAX_BYTES, inspect_media, representative_frames, preview_bytes
from services.common.storage import atomic_write
from services.retrieval import encoder
from services.retrieval.dedup import ContentGroups, source_identity, unique_post_previews
from services.retrieval.download import canonical_url
from services.retrieval.rerank import matching_picture, picture_regions, score_candidate
from .caption_review import review_scores
from .captions import caption_overlap, caption_phrases, product_listing, wants_products
from .entity_verifier import REFERENCE_SIMILARITY, verify_entities
from .meme_fetch import FetchClient
from .meme_deepseek import (
    GIF_INTENT,
    SITE_OPERATOR,
    DeepSeekWeb,
    DeepSeekQueryPlanner,
    explicit_user_source,
    prioritize_user_source,
    recover_hakimi_spelling,
    retrieval_queries,
    source_description,
)
from .meme_providers import vision_client
from .meme_types import Ledger, MediaSource, MemeSettings, PipelineError, PreparedMedia, Query
from .page_media import page_sources
from .resolvers import is_commons_file_page
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
    saved_analysis=None,
    emit=None,
    analyze=None,
    reverse=None,
    keywords=None,
    fetcher=None,
    embeddings=None,
):
    """Injectable boundaries for CI; the production runner supplies none of them."""
    settings = settings or MemeSettings.for_online_search()
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
    reference_media = {}
    analysis = None
    review_enabled = False
    query_frames = []
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
        ranked = sorted(prepared.values(), key=lambda p: (-p.score, p.content_group_id))
        revisions = {}
        if review_enabled and ranked and status == "completed":
            try:
                ledger.remaining()
                revisions = review_scores(ranked, query_frames[0], analysis, work, ledger)
            except PipelineError as exc:
                ledger.note("caption_review_skipped", code=exc.code)
        chosen = []
        for item in ranked if status == "completed" else []:
            score = revisions.get(item.key, item.score)
            if score is not None and score >= settings.minimum_score:
                chosen.append(item.model_copy(update={"score": score}))
        chosen.sort(key=lambda item: (-item.score, item.content_group_id))
        chosen = unique_post_previews(chosen)[:target_count]
        if status == "completed" and len(chosen) < target_count:
            warnings.append("insufficient_distinct_relevant_media")
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
        if revisions:
            result["final_scores"] = {item.key: item.score for item in chosen}
        event("final", **result)
        return result

    try:
        stage("preprocessing")
        data = Path(image_path).read_bytes()
        input_meta = inspect_media(data)
        vision = None if analyze else vision_client(settings, ledger)
        if saved_analysis is not None:
            analysis = saved_analysis.model_copy(deep=True)
            query_frames, _ = representative_frames(data, count=4)
            ledger.note("retry_analysis_reused", query_count=len(analysis.queries))
        else:
            stage("understanding")
            analysis, query_frames = (analyze or analyze_image)(data, user_text, settings, ledger)
            stage("verifying")
            if not analyze:
                analysis, verify_warnings = verify_entities(
                    analysis,
                    query_frames,
                    settings,
                    ledger,
                    fetcher=fetcher,
                    embeddings=embeddings,
                    media_cache=reference_media,
                )
                warnings.extend(verify_warnings)
        stage("recalling")
        if not analyze and (saved_analysis is None or analysis.planner_version == "unavailable"):
            try:
                analysis.queries = DeepSeekQueryPlanner(settings, ledger).plan(analysis)
                analysis.planner_version = (
                    "deepseek/" + settings.deepseek_model + "/" + DeepSeekQueryPlanner.version
                )
            except PipelineError as exc:
                warnings.append(exc.code)
                ledger.note("query_planning_failed", provider="deepseek", code=exc.code)
        if not analyze:
            remaining_queries = max(
                0,
                min(
                    settings.max_queries - ledger.counts["queries"],
                    settings.max_search_calls - ledger.counts["search_calls"],
                ),
            )
            analysis.queries = retrieval_queries(analysis)
            joint = next((q for q in analysis.queries if q.angle == "composite"), None)
            if (
                joint
                and remaining_queries >= 2
                and not any(row.get("matching_media_url") for row in analysis.evidence)
                and not any(q.angle == "template_catalog" for q in analysis.queries)
            ):
                # Editorial coverage can mention both components but illustrate just
                # one. Reserve an independent lookup specifically for blank templates.
                prefix = "site:imgflip.com/memetemplate "
                template = Query(
                    text=prefix + joint.text[: 128 - len(prefix)],
                    angle="template_catalog",
                    language=joint.language,
                )
                analysis.queries = [joint, template, *(q for q in analysis.queries if q != joint)]
            analysis.queries = prioritize_user_source(
                analysis.queries, user_text, remaining_queries, ledger
            )
            # Both actual providers share one finite query ledger.
            analysis.queries = [
                q.model_copy(update={"text": q.text.strip()[:128]})
                for q in analysis.queries[:remaining_queries]
                if q.text.strip()
            ]
        reverse_ok = False
        if reverse is None:
            ledger.note(
                "reverse_image_disabled", reason="provider_policy", policy=settings.provider_policy
            )
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
        phrases = caption_phrases(analysis.ocr_text)
        filter_products = bool(phrases) and not wants_products(user_text)
        query_regions = picture_regions(query_frames[0]) if input_meta.frame_count == 1 else []
        review_enabled = bool(
            phrases
            and input_meta.frame_count == 1
            and vision is not None
            and vision.api_key
            and ledger.counts["model_calls"] < settings.max_model_calls
        )
        shortlist_floor = (
            min(settings.minimum_score, 0.40) if review_enabled else settings.minimum_score
        )
        event("analysis_ready", analysis=analysis.model_dump(mode="json"))
        try:
            embeddings.load_model()
            query_vectors = embeddings.encode_images(query_frames)
            intent = " ".join(
                [
                    user_text,
                    analysis.ocr_text,
                    *analysis.observations,
                    *analysis.action_tags,
                    *analysis.emotion_tags,
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
                cached = reference_media.get(url)
                if cached is not None:
                    ledger.take("media_attempts")
                    return cached, url
                return fetcher.get(url, "media_attempts", MAX_BYTES)

            try:
                content, final_url = get_original(source.media_url)
                if content.lstrip()[:32].lower().startswith((b"<html", b"<!doctype html")):
                    # Some actual media URLs return an HTML embed wrapper. Read
                    # its real clues once; never invent CDN aliases/extensions.
                    ledger.take("page_attempts")
                    ledger.note("media_html_wrapper", host=urlsplit(final_url).hostname)
                    for clue in page_sources(
                        source, content[: 2 * 1024 * 1024], final_url, phrases
                    ):
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

        composite_search = any(q.angle == "composite" for q in analysis.queries)

        def enough_results():
            if sum(p.score >= settings.minimum_score for p in prepared.values()) < target_count:
                return False
            return not (composite_search or phrases) or any(
                item.signals["visual"] >= REFERENCE_SIMILARITY for item in prepared.values()
            )

        lookup_ids = {}

        def lookup_detail(source):
            ref = lookup_ids.get(source.source_url)
            return {"lookup_path": ref} if ref is not None else {}

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
                                **lookup_detail(source),
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
                                **lookup_detail(source),
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
                    match = ""
                    if metadata.sha256 == input_meta.sha256:
                        match = "identical_bytes"
                    elif query_regions and metadata.frame_count == 1:
                        match = matching_picture(query_regions, samples[0])
                    if match:
                        score = {"identical_bytes": 1.0, "near_copy": 0.99, "same_picture": 0.96}[
                            match
                        ]
                    elif filter_products and (
                        source.product_page or product_listing(source.source_url, source.title)
                    ):
                        counts["product_listings"] = counts.get("product_listings", 0) + 1
                        ledger.note("product_listing_skipped", sha256=metadata.sha256)
                        continue
                    else:
                        # Only image-specific captions can boost the final rank. A roundup's
                        # headline or search snippet can describe a different image.
                        label = source.image_caption or (
                            source.title if source.source_type == "direct" else ""
                        )
                        agreement = caption_overlap(phrases, label)
                        score = min(0.95, score + 0.09 * agreement)
                        signals["caption_overlap"] = agreement
                    signals["picture_match"] = match
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
                    if score < shortlist_floor:
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
                    if old and (
                        old.score if old.signals.get("picture_match") else 0,
                        old.metadata.width * old.metadata.height,
                        old.score,
                    ) >= (
                        score if match else 0,
                        metadata.width * metadata.height,
                        score,
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
                if enough_results():
                    stop = "target_reached"
                    break

        reference_sources = []
        matches = []
        for row in analysis.evidence:
            if row.get("relation") != "supports" and not row.get("matching_media_url"):
                continue
            try:
                source = MediaSource(
                    source_url=row.get("url"),
                    media_url=row.get("matching_media_url") or row.get("lead_media_url"),
                    title=row.get("title", ""),
                    provider="deepseek",
                    source_rank=1,
                ).checked()
            except ValueError:
                continue
            reference_sources.append(source)
            if row.get("matching_media_url"):
                matches.append(source)
            if len(reference_sources) >= settings.max_sources:
                break
        all_sources.extend(reference_sources)
        counts["metadata_returned"] += len(reference_sources)
        counts["channel_recall"]["keyword"] += len(reference_sources)
        if matches:
            stage("fetching")
            counts["metadata"] = len(matches)
            process_direct(matches)
            seen_media.update(canonical_url(url) for url in reference_media)
            reference_media.clear()
            keyword_ok = True
        queries = analysis.queries[: settings.max_queries]
        commons = "commons.wikimedia.org"
        description = source_description(user_text, commons)
        wants_commons_gif = (
            explicit_user_source(user_text) == commons
            and GIF_INTENT.search(description)
            and not re.search(
                r"(?:\b(?:not|no|without|avoid|exclude)\s+(?:(?:a|an|any|animated)\s+)*|(?:不要|不是|排除)\s*)gifs?\b",
                description,
                re.I,
            )
        )
        spelling_retry_scheduled = False
        for query_index, query in enumerate(queries):
            if enough_results():
                break
            if (
                review_enabled
                and prepared
                and ledger.deadline - ledger.clock() < settings.call_timeout_seconds + 4
            ):
                stop = "review_time_reserved"
                break
            ledger.remaining()
            fresh_urls = set()
            lookup_routes = {}
            file_pages = set()
            scopes = [m[0].lower() for m in SITE_OPERATOR.finditer(query.text)]
            trace_lookup = (
                wants_commons_gif
                and len(scopes) == 1
                and scopes[0] in {f"site:{commons}", f"site:www.{commons}"}
            )
            try:
                sources = keywords.search(query.text, limit=min(200, settings.max_sources))
                keyword_ok = True
                counts["metadata_returned"] += len(sources)
                counts["channel_recall"]["keyword"] += len(sources)
                all_sources.extend(sources)
                fresh_urls = {s.source_url for s in sources}
                if trace_lookup:
                    for source in sources[:50]:
                        url = urlsplit(source.source_url)
                        if url.hostname == commons:
                            # Locale, tracking parameters and fragments do not identify a file.
                            path = unquote(url.path).replace(" ", "_")
                            lookup_ids[source.source_url] = sha256(path.encode()).hexdigest()[:16]
                            lookup_routes[source.source_url] = "fused_out"
                            if is_commons_file_page(url) and unquote(url.path).lower().endswith(
                                ".gif"
                            ):
                                file_pages.add(source.source_url)
                ledger.note(
                    "keyword_web",
                    provider="deepseek",
                    query=query.model_dump(),
                    sources=len(sources),
                )
                if not sources and not prepared and not spelling_retry_scheduled:
                    spelling_retry_scheduled = recover_hakimi_spelling(
                        queries, query_index, user_text, analysis.ocr_text, ledger
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
                if source.source_url in lookup_routes:
                    lookup_routes[source.source_url] = "coarse_filtered"
                unread_file_page = (
                    source.source_url in file_pages and source.source_url not in seen_pages
                )
                if (key in seen_media or key in seen_pages) and not unread_file_page:
                    if source.source_url in lookup_routes:
                        lookup_routes[source.source_url] = "seen"
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

            def discovery_priority(item):
                relevance, source = item
                agreement = caption_overlap(phrases, source.title + " " + source.snippet)
                return (
                    source.source_url not in file_pages,
                    filter_products and product_listing(source.source_url, source.title),
                    bool(phrases) and source.source_url not in fresh_urls,
                    -relevance - 0.18 * agreement,
                    source.source_rank,
                    source.source_url,
                )

            ordered = [s for _, s in sorted(coarse, key=discovery_priority)]
            direct, pages = [], []
            direct_keys = set()
            # Fair-share the remaining page allowance across query angles. A
            # slow first query must not consume the entire job before originals
            # are fetched or before a second query can contribute.
            remaining_pages = max(0, settings.max_pages - ledger.counts["page_attempts"])
            remaining_queries = max(1, len(queries) - query_index)
            page_allowance = (remaining_pages + remaining_queries - 1) // remaining_queries
            for source in ordered:
                if source.source_url in lookup_routes:
                    lookup_routes[source.source_url] = (
                        "seen" if source.source_url in seen_pages else "page_quota"
                    )
                selected_page = (
                    (not source.media_url or source.source_url in file_pages)
                    and source.source_url not in seen_pages
                    and len(pages) < page_allowance
                )
                if selected_page:
                    seen_pages.add(source.source_url)
                    pages.append(source)
                    if source.source_url in lookup_routes:
                        lookup_routes[source.source_url] = "page"
                if source.media_url:
                    key = canonical_url(source.media_url)
                    if key not in seen_media and key not in direct_keys:
                        direct_keys.add(key)
                        direct.append(source)
                        if source.source_url in lookup_routes and not selected_page:
                            lookup_routes[source.source_url] = "direct"
            if trace_lookup:
                ledger.note(
                    "commons_source_routes",
                    paths=[[lookup_ids[url], route] for url, route in lookup_routes.items()],
                )
            preferred = [page for page in pages if page.source_url in file_pages]
            if not preferred:
                seen_media.update(direct_keys)
                process_direct(direct)
            if not enough_results():
                # Finish a small page wave before starting media I/O: global
                # request concurrency remains <= configured concurrency.
                # A collection can have one generic cover and many individually captioned
                # images. Spend more of the existing original budget on likely source pages.
                gallery_pages = (
                    {p.source_url for p in pages[:2]}
                    if query.angle == "publisher_lookup"
                    else set()
                )

                def read_page(source):
                    try:
                        page, final_url = fetcher.get(
                            source.source_url, "page_attempts", 2 * 1024 * 1024
                        )
                        extracted = page_sources(
                            source,
                            page,
                            final_url,
                            phrases,
                            gallery_limit=12 if source.source_url in gallery_pages else 4,
                        )
                        with ledger.lock:
                            counts["page_clues"] += len(extracted)
                        ledger.note(
                            "page_extracted",
                            host=urlsplit(final_url).hostname,
                            path=urlsplit(final_url).path[:250],
                            clues=len(extracted),
                            **lookup_detail(source),
                        )
                        return extracted
                    except (PipelineError, ValueError, OSError) as exc:
                        code = exc.code if isinstance(exc, PipelineError) else "invalid_source_page"
                        with ledger.lock:
                            counts["page_failures"] += 1
                        ledger.note(
                            "page_failure",
                            code=code,
                            host=urlsplit(source.source_url).hostname,
                            **lookup_detail(source),
                        )
                        return code

                def process_pages(batch):
                    for offset in range(0, len(batch), 4):
                        if enough_results():
                            break
                        ledger.remaining()
                        stage("fetching")
                        extracted_media = []
                        with ThreadPoolExecutor(max_workers=min(4, settings.concurrency)) as pool:
                            for extracted in pool.map(read_page, batch[offset : offset + 4]):
                                if isinstance(extracted, str):
                                    warnings.append(extracted)
                                    continue
                                for item in extracted:
                                    key = canonical_url(item.media_url)
                                    if key not in seen_media:
                                        seen_media.add(key)
                                        extracted_media.append(item)
                        process_direct(extracted_media)

                if preferred:
                    process_pages(preferred)
                    if not enough_results():
                        direct = [s for s in direct if canonical_url(s.media_url) not in seen_media]
                        seen_media.update(direct_keys)
                        process_direct(direct)
                process_pages([page for page in pages if page.source_url not in file_pages])
            if enough_results():
                break
            if ledger.counts["media_attempts"] >= settings.max_originals:
                stop = "media_attempts_limit"
                break
        if not keyword_ok and not reverse_ok:
            raise PipelineError("recall_providers_unavailable")
        stage("finalizing")
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
