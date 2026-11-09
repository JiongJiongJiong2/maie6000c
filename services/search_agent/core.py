"""Two-round search/observe/revise loop. No database writes or implicit downloads."""

import hashlib
import time
from pathlib import Path

from pydantic import ValidationError

from .models import (
    CandidateBudget,
    PreparedBatch,
    SearchBudget,
    SearchResult,
    Source,
    TraceEvent,
)
from .planner import PlannerError, QueryPlanner
from .providers import (
    BraveProvider,
    DDGSProvider,
    DeepSeekProvider,
    ProviderError,
    SearxngProvider,
    TavilyProvider,
)
from .settings import SearchAgentSettings


def build_provider(settings):
    mode = settings.search_agent_mode
    if settings.search_agent_provider == "deepseek" or (
        settings.search_agent_provider == "auto"
        and mode == "web"
        and settings.deepseek_api_key.get_secret_value()
    ):
        return DeepSeekProvider(settings.deepseek_api_key.get_secret_value(), mode=mode)
    if settings.search_agent_provider == "auto" and mode == "images" and settings.brave_api_key:
        return BraveProvider(settings.brave_api_key.get_secret_value(), mode=mode)
    if settings.search_agent_provider == "brave":
        return BraveProvider(settings.brave_api_key.get_secret_value(), mode=mode)
    if settings.search_agent_provider == "tavily":
        return TavilyProvider(settings.tavily_api_key.get_secret_value(), mode=mode)
    if settings.search_agent_provider == "searxng":
        return SearxngProvider(settings.searxng_url, mode=mode)
    return DDGSProvider(mode=mode)


def search_web(
    image_path=None,
    description="",
    work_dir=None,
    budget=None,
    *,
    settings=None,
    provider=None,
    planner=None,
    prepare_candidates=None,
):
    """Run bounded discovery; injected providers and processors remain caller-owned."""
    settings = settings or SearchAgentSettings()
    owned = provider is None
    provider = provider or build_provider(settings)
    try:
        return _run_search(
            image_path,
            description,
            work_dir,
            budget,
            settings=settings,
            provider=provider,
            planner=planner,
            prepare_candidates=prepare_candidates,
        )
    finally:
        if owned:
            provider.close()


def _run_search(
    image_path=None,
    description="",
    work_dir=None,
    budget=None,
    *,
    settings=None,
    provider=None,
    planner=None,
    prepare_candidates=None,
):
    """Discover sources or call an injected GIF processor to produce verified candidates.

    The processor receives (image_path, sources, work_dir, CandidateBudget) and returns
    PreparedBatch. It must honor the deadline and account for every attempted download.
    Network/callback deadlines are cooperative; the worker owns process-level cancellation.
    No processor means discovery only: sources are NEVER reported as recovered GIFs.
    """
    description = description.strip()
    if not description or len(description) > 500:
        raise ValueError("Provide a description of 1 to 500 characters")
    budget = SearchBudget.model_validate(budget or {})
    settings = settings or SearchAgentSettings()
    provider = provider or build_provider(settings)
    planner = planner or QueryPlanner(settings)
    if prepare_candidates is not None:
        if image_path is None or not Path(image_path).is_file() or work_dir is None:
            raise ValueError("Candidate processing requires an input image and job work directory")
        image_path, work_dir = Path(image_path), Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    deadline = started + budget.timeout_seconds
    trace, warnings, sources, candidates = [], [], [], []
    seen, queries = set(), []
    downloads = search_calls = planner_calls = successful_calls = 0
    model_version = None
    feedback = {"new_sources": 0, "valid_candidates": 0, "rejected": 0}
    stop_reason = "round_limit"
    fatal = operational_failure = False

    def event(round_no, step, **details):
        trace.append(
            TraceEvent(
                round=round_no,
                step=step,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                details=details,
            )
        )

    def timeout():
        return min(budget.call_timeout_seconds, max(0.001, deadline - time.monotonic()))

    for round_no in range(1, budget.max_rounds + 1):
        if time.monotonic() >= deadline:
            stop_reason = "deadline"
            break
        if prepare_candidates is not None and downloads >= budget.max_downloads:
            stop_reason = "download_limit"
            break
        # No retrieved prose or arbitrary failure strings are fed back into the model.
        before = getattr(planner, "model_calls", 0)
        try:
            query = planner.next_query(description, round_no, feedback, list(queries), timeout())
        except PlannerError:
            warnings.append("planner_unavailable_using_original_description")
            query = description if round_no == 1 else description + " GIF 动态表情 原图"
        planner_calls += max(0, getattr(planner, "model_calls", 0) - before)
        if query is None:
            stop_reason = "planner_stopped"
            break
        if not isinstance(query, str) or not query.strip():
            stop_reason, fatal = "invalid_planner_output", True
            break
        query_limit = 128 if provider.name == "deepseek" else 300
        query = " ".join(query.split()[:50])[:query_limit]
        if query in queries:
            query = (description[: query_limit - 25] + " GIF 动态表情 原图")[:query_limit]
        if query in queries:
            stop_reason = "repeated_query"
            break
        queries.append(query)
        event(round_no, "plan", query=query)
        if time.monotonic() >= deadline:
            stop_reason = "deadline"
            break
        search_calls += 1
        try:
            raw_hits = provider.search(query, limit=6, timeout=timeout())
            successful_calls += 1
        except ProviderError as exc:
            # Errors contain a code only, never provider response bodies or request headers.
            warnings.append("search_" + exc.code)
            operational_failure = True
            event(round_no, "search_error", provider=provider.name, code=exc.code)
            feedback = {"new_sources": 0, "valid_candidates": len(candidates), "rejected": 0}
            continue
        new_sources, rejected = [], 0
        for raw in raw_hits[:6]:
            try:
                source = Source.model_validate(raw)
                if settings.search_agent_mode == "images" and source.image_url is None:
                    rejected += 1
                    continue
            except (ValidationError, ValueError, TypeError):
                rejected += 1
                continue
            key = source.image_url or source.source_url
            if key not in seen:
                seen.add(key)
                new_sources.append(source)
        sources.extend(new_sources)
        event(
            round_no,
            "search",
            provider=provider.name,
            new_sources=len(new_sources),
            rejected=rejected,
        )
        if time.monotonic() >= deadline:
            stop_reason = "deadline"
            break
        if prepare_candidates is None:
            feedback = {
                "new_sources": len(new_sources),
                "valid_candidates": 0,
                "rejected": rejected,
            }
            if len(sources) >= budget.max_results:
                stop_reason = "sources_found"
                break
            continue

        available = budget.max_downloads - downloads
        to_process = [s for s in new_sources if s.image_url is not None][:available]
        if to_process:
            try:
                round_dir = work_dir / f"round-{round_no}"
                round_dir.mkdir(parents=True, exist_ok=True)
                batch = PreparedBatch.model_validate(
                    prepare_candidates(
                        image_path,
                        [s.model_dump() for s in to_process],
                        round_dir,
                        CandidateBudget(remaining_downloads=available, deadline=deadline),
                    )
                )
                if batch.downloads_used > available or len(batch.candidates) > 3:
                    raise ValueError("Processor exceeded its budget")
                if batch.candidates and batch.downloads_used == 0:
                    raise ValueError("Processor returned unaccounted candidates")
                if (
                    batch.candidates
                    and model_version is not None
                    and batch.model_version != model_version
                ):
                    raise ValueError("Processor changed ranking model between rounds")
                for candidate in batch.candidates:
                    if candidate.image_url not in {s.image_url for s in to_process}:
                        raise ValueError("Processor returned an unrelated candidate")
                    path = candidate.contained_file(round_dir)
                    if path.stat().st_size > 12 * 1024 * 1024:
                        raise ValueError("Candidate too large")
                    if hashlib.sha256(path.read_bytes()).hexdigest() != candidate.sha256:
                        raise ValueError("Candidate checksum mismatch")
                batch.candidates = [
                    candidate.model_copy(
                        update={
                            "relative_path": f"round-{round_no}/" + candidate.relative_path,
                        }
                    )
                    for candidate in batch.candidates
                ]
            except Exception:
                # Unknown work consumption: conservatively exhaust the remaining allowance.
                downloads += available
                event(round_no, "processor_error", code="candidate_processor_failed")
                warnings.append("candidate_processor_failed")
                stop_reason, fatal = "processor_error", True
                break
            downloads += batch.downloads_used
            if batch.candidates:
                model_version = batch.model_version
            for failure in batch.failures:
                warnings.append("candidate_" + failure)
                if failure in {
                    "download_failed",
                    "download_timeout",
                    "source_unavailable",
                    "model_unavailable",
                    "embedding_failed",
                    "storage_failed",
                }:
                    operational_failure = True
            candidates.extend(batch.candidates)
            by_hash = {}
            for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
                by_hash.setdefault(candidate.sha256, candidate)
            candidates = list(by_hash.values())[: budget.max_results]
            rejected += len(batch.failures)
            event(
                round_no,
                "prepare_candidates",
                candidates=len(candidates),
                downloads_used=batch.downloads_used,
                rejected=len(batch.failures),
                failure_codes=list(dict.fromkeys(batch.failures)),
            )
        feedback = {
            "new_sources": len(new_sources),
            "valid_candidates": len(candidates),
            "rejected": rejected,
        }
        if time.monotonic() >= deadline:
            stop_reason = "deadline"
            break
        if len(candidates) >= budget.desired_candidates:
            stop_reason = "candidates_found"
            break
    else:
        if successful_calls == 0:
            stop_reason = "provider_unavailable"

    # Source discovery and verified media retrieval have deliberately distinct outcomes.
    is_verified = prepare_candidates is not None
    useful = bool(candidates) if is_verified else bool(sources)
    failed = (
        fatal
        or (operational_failure and not useful)
        or (stop_reason == "deadline" and not useful)
        or (search_calls > 0 and successful_calls == 0)
    )
    if failed and stop_reason == "round_limit":
        stop_reason = "media_processing_failed" if is_verified else "search_failed"
    event(
        0,
        "stop",
        reason=stop_reason,
        search_calls=search_calls,
        planner_calls=planner_calls,
        downloads_used=downloads,
    )
    return SearchResult(
        status="failed" if failed else "completed",
        result_kind="candidates"
        if candidates
        else ("sources" if sources and not is_verified else "no_results"),
        stop_reason=stop_reason,
        sources=sources,
        candidates=candidates,
        trace=trace,
        warnings=list(dict.fromkeys(warnings)),
        search_calls=search_calls,
        planner_calls=planner_calls,
        downloads_used=downloads,
        model_version=model_version,
    )
