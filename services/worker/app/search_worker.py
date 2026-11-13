from __future__ import annotations

import logging
import json
import signal
import shutil
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from services.common.config import configure_logging, get_settings
from services.common.db import get_engine, get_session_factory
from services.common.models import utcnow
from services.common.search_models import (
    Candidate,
    ReferenceAsset,
    SavedAsset,
    SearchJob,
    SearchExecution,
    SearchRequest,
    new_id,
)
from services.common.search_schemas import RetrievalResult, WebSearchResult
from services.common.storage import (
    MediaError,
    atomic_write,
    contained_path,
    prepare_storage,
    remove_file_after_failure,
    read_gif,
    sha256,
    validate_image,
)

logger = logging.getLogger("services.worker.search")
Retriever = Callable[[Path], RetrievalResult]
WebSearcher = Callable[[Path, str, Path], WebSearchResult]
IndexSavedAsset = Callable[[str], str]


def elapsed_seconds(started_at: datetime, finished_at: datetime) -> float:
    # SQLite fixtures can return naive UTC; PostgreSQL can return an offset.
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=finished_at.tzinfo)
    return (finished_at - started_at).total_seconds()


def register_shutdown_handlers(stop_event: threading.Event) -> None:
    def request_shutdown(_signum: int, _frame: object) -> None:
        del _signum, _frame
        logger.info("search_worker_shutdown_requested")
        stop_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)


class RetrievalError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _is_stale_regular_file(path: Path, cutoff: float, *, storage_class: str) -> bool:
    try:
        file_stat = path.stat()
    except FileNotFoundError:
        return False
    except OSError:
        logger.exception(
            "media_cleanup_stat_failed",
            extra={"file_name": path.name, "storage_class": storage_class},
        )
        return False
    return stat.S_ISREG(file_stat.st_mode) and file_stat.st_mtime < cutoff


def _is_stale_directory(path: Path, cutoff: float) -> bool:
    try:
        directory_stat = path.stat()
    except FileNotFoundError:
        return False
    except OSError:
        logger.exception("web_work_stat_failed", extra={"directory": path.name})
        return False
    return stat.S_ISDIR(directory_stat.st_mode) and directory_stat.st_mtime < cutoff


def invoke_retrieval(image_path: Path) -> RetrievalResult:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "services.worker.app.retrieval_runner", str(image_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=get_settings().retrieval_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RetrievalError("retrieval_timeout", "Retrieval exceeded its time limit") from exc
    if result.returncode == 2:
        raise RetrievalError(
            "retrieval_unavailable", "services.retrieval.search has not been installed"
        )
    if result.returncode != 0:
        logger.error("retrieval_subprocess_failed", extra={"return_code": result.returncode})
        raise RetrievalError("retrieval_failed", "Model or corpus processing failed")
    try:
        return RetrievalResult.model_validate_json(result.stdout)
    except ValidationError as exc:
        raise RetrievalError(
            "invalid_retrieval_result", "Retrieval returned an invalid result"
        ) from exc


class IndexingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def invoke_web_search(image_path: Path, description: str, work_dir: Path) -> WebSearchResult:
    settings = get_settings()
    payload = {
        "image_path": str(image_path),
        "description": description,
        "work_dir": str(work_dir),
        "max_downloads": settings.web_search_max_downloads,
        "timeout_seconds": settings.web_search_timeout_seconds,
        "call_timeout_seconds": settings.web_search_call_timeout_seconds,
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "services.worker.app.web_search_runner"],
            input=json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=settings.web_search_timeout_seconds + 5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RetrievalError("web_search_timeout", "Web search exceeded its time limit") from exc
    if result.returncode:
        try:
            error_code = json.loads(result.stdout).get("error_code")
        except (json.JSONDecodeError, AttributeError):
            error_code = None
        if error_code == "candidate_processor_unavailable":
            raise RetrievalError(
                error_code,
                "The GIF candidate-processing module is not installed",
            )
        logger.error("web_search_subprocess_failed", extra={"return_code": result.returncode})
        raise RetrievalError("web_search_failed", "Web search or candidate processing failed")
    try:
        return WebSearchResult.model_validate_json(result.stdout)
    except ValidationError as exc:
        raise RetrievalError(
            "invalid_web_search_result", "Web search returned invalid data"
        ) from exc


def invoke_saved_asset_index(asset_id: str) -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "services.worker.app.index_runner", asset_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=get_settings().saved_index_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise IndexingError(
            "index_timeout", "Saved asset indexing exceeded its time limit"
        ) from exc
    if result.returncode:
        try:
            error_code = json.loads(result.stdout).get("error_code")
        except (json.JSONDecodeError, AttributeError):
            error_code = None
        if error_code == "saved_asset_indexer_unavailable":
            raise IndexingError(error_code, "The saved-asset index module is not installed")
        raise IndexingError("index_failed", "Saved asset indexing failed")
    try:
        version = json.loads(result.stdout)["index_version"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise IndexingError("invalid_index_result", "Indexer returned an invalid result") from exc
    if not isinstance(version, str) or not version.strip() or len(version) > 100:
        raise IndexingError("invalid_index_result", "Indexer returned an invalid version")
    return version


def claim_next_search_job(db: Session) -> SearchJob | None:
    job = db.scalar(
        select(SearchJob)
        .where(SearchJob.status == "pending")
        .order_by(SearchJob.created_at, SearchJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is not None:
        job.status = "running"
        job.stage = "local_retrieval" if job.job_kind == "local" else "web_search"
        job.started_at = utcnow()
        db.commit()
        logger.info(
            "search_claimed",
            extra={"request_id": job.request_id, "job_id": job.id, "job_kind": job.job_kind},
        )
    return job


def release_claimed_search_job(db: Session, job_id: str) -> None:
    job = db.get(SearchJob, job_id)
    if job is None or job.status != "running":
        raise RuntimeError("Only a claimed search job can be released")
    job.status = "pending"
    job.stage = "pending"
    job.started_at = None
    db.commit()
    logger.info("search_claim_released", extra={"request_id": job.request_id, "job_id": job.id})


def fail_job(db: Session, job_id: str, code: str, message: str) -> bool:
    job = db.get(SearchJob, job_id)
    if job is None:
        raise RuntimeError(f"Search job missing: {job_id}")
    if job.status != "running":
        if job.status in {"completed", "failed"}:
            logger.warning(
                "search_failure_after_terminal_state",
                extra={
                    "request_id": job.request_id,
                    "job_id": job.id,
                    "status": job.status,
                    "error_code": code,
                },
            )
            return False
        raise RuntimeError(f"Cannot fail a job in state {job.status}")
    job.status = "failed"
    job.stage = "failed"
    job.error_code = code
    job.error_detail = message[:1000]
    job.finished_at = utcnow()
    db.commit()
    logger.error(
        "search_failed",
        extra={"request_id": job.request_id, "job_id": job.id, "error_code": code},
    )
    return True


def recover_interrupted_jobs(db: Session) -> int:
    jobs = list(db.scalars(select(SearchJob).where(SearchJob.status == "running")))
    for job in jobs:
        job.status = "failed"
        job.stage = "failed"
        job.error_code = "worker_interrupted"
        job.error_detail = "Worker stopped during execution; an explicit retry is required"
        job.finished_at = utcnow()
        logger.warning("search_interrupted", extra={"request_id": job.request_id, "job_id": job.id})
    db.commit()
    return len(jobs)


def process_search_job(job_id: str, retriever: Retriever = invoke_retrieval) -> None:
    settings = get_settings()
    factory = get_session_factory()
    with factory() as db:
        job = db.get(SearchJob, job_id)
        if job is None or job.status != "running":
            raise RuntimeError("Only a claimed search job can execute")
        request = db.get(SearchRequest, job.request_id)
        if request is None:
            raise RuntimeError("Search input record is missing")
        input_path = contained_path(settings.media_root, request.input_path)
        digest = request.input_sha256
    if not input_path.is_file():
        raise RetrievalError("input_unavailable", "Search input is missing from storage")
    if sha256(input_path.read_bytes()) != digest:
        raise RetrievalError("input_corrupted", "Stored input checksum does not match")
    result = retriever(input_path)
    written: list[Path] = []
    commit_started = False
    try:
        with factory() as db:
            job = db.get(SearchJob, job_id)
            if job is None or job.status != "running" or job.started_at is None:
                raise RuntimeError("Search job is no longer running")
            finished_at = utcnow()
            for rank, match in enumerate(result.matches, start=1):
                asset = db.get(ReferenceAsset, str(match.reference_asset_id))
                saved_asset = (
                    None if asset is not None else db.get(SavedAsset, str(match.reference_asset_id))
                )
                if asset is None and (saved_asset is None or saved_asset.index_status != "ready"):
                    raise RetrievalError(
                        "corpus_mismatch", "Retrieved asset is absent from the active index"
                    )
                if asset is not None and asset.corpus_version != result.corpus_version:
                    raise RetrievalError(
                        "corpus_mismatch", "Retrieved asset is absent from the declared corpus"
                    )
                if asset is not None:
                    data, frames = read_gif(asset.gif_path)
                    expected_sha = asset.sha256
                    expected_frames = asset.frame_count
                    saved_asset_id = None
                    source_url = image_url = provider = None
                else:
                    if saved_asset is None:
                        raise RuntimeError("Search match does not resolve to an asset")
                    path = contained_path(settings.media_root, saved_asset.gif_path)
                    if path.stat().st_size > settings.max_candidate_bytes:
                        raise RetrievalError(
                            "corpus_corrupted", "Saved GIF exceeds the configured size limit"
                        )
                    data = path.read_bytes()
                    frames = validate_image(data, animated_gif=True)
                    expected_sha = saved_asset.sha256
                    expected_frames = saved_asset.frame_count
                    saved_asset_id = saved_asset.id
                    source_url = saved_asset.source_url
                    image_url = saved_asset.image_url
                    provider = saved_asset.provider
                if sha256(data) != expected_sha or frames != expected_frames:
                    raise RetrievalError(
                        "corpus_corrupted", "Corpus media does not match its catalog"
                    )
                candidate_id = new_id()
                relative = f"candidates/{job.id}/{candidate_id}.gif"
                written.append(atomic_write(settings.media_root, relative, data))
                db.add(
                    Candidate(
                        id=candidate_id,
                        job_id=job.id,
                        reference_asset_id=asset.id if asset is not None else None,
                        saved_asset_id=saved_asset_id,
                        rank=rank,
                        similarity_score=match.score,
                        media_sha256=expected_sha,
                        source_url=source_url,
                        image_url=image_url,
                        provider=provider,
                        local_cache_path=relative,
                        frame_count=frames,
                        cache_expires_at=finished_at
                        + timedelta(days=settings.media_retention_days),
                    )
                )
            job.status = "completed"
            job.stage = "completed"
            job.result_kind = "candidates" if result.matches else "no_candidates"
            job.model_version = result.model_version
            job.corpus_version = result.corpus_version
            job.finished_at = finished_at
            commit_started = True
            db.commit()
            logger.info(
                "search_completed",
                extra={
                    "request_id": job.request_id,
                    "job_id": job.id,
                    "result_kind": job.result_kind,
                    "job_kind": job.job_kind,
                    "candidate_count": len(result.matches),
                    "duration_seconds": elapsed_seconds(job.started_at, finished_at),
                },
            )
    except BaseException:
        if commit_started:
            logger.warning(
                "candidate_files_retained_after_unconfirmed_commit",
                extra={"job_id": job_id, "candidate_file_count": len(written)},
            )
        else:
            for path in written:
                remove_file_after_failure(path, storage_class="candidate")
        raise


def _execution_row(job_id: str, result: WebSearchResult, duration_ms: int) -> SearchExecution:
    return SearchExecution(
        job_id=job_id,
        agent_version=result.agent_version,
        model_version=result.model_version,
        stop_reason=result.stop_reason,
        search_calls=result.search_calls,
        planner_calls=result.planner_calls,
        downloads_used=result.downloads_used,
        duration_ms=max(0, duration_ms),
        trace=result.trace,
        warnings=result.warnings,
    )


def _safe_web_error_code(reason: str) -> str:
    normalized = reason.lower()
    if (
        normalized
        and len(normalized) <= 45
        and all(character.isalnum() or character == "_" for character in normalized)
    ):
        return f"web_{normalized}"[:50]
    return "web_search_failed"


def _remove_web_work_dir(work_dir: Path) -> None:
    try:
        work_root = (get_settings().media_root / "web-search").resolve()
        resolved = work_dir.resolve()
        if resolved.parent == work_root and resolved.name:
            shutil.rmtree(resolved, ignore_errors=False)
    except FileNotFoundError:
        return
    except OSError:
        logger.exception("web_search_work_cleanup_failed", extra={"directory": work_dir.name})


def _validate_public_reference(value: str) -> None:
    from ipaddress import ip_address
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise RetrievalError(
            "invalid_candidate_source", "Candidate source is not a public URL"
        ) from exc
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username
        or parsed.password
        or host == "localhost"
        or host.endswith((".local", ".internal"))
        or "." not in host
    ):
        raise RetrievalError("invalid_candidate_source", "Candidate source is not a public URL")
    try:
        address = ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise RetrievalError("invalid_candidate_source", "Candidate source is not a public URL")


def process_web_search_job(
    job_id: str,
    searcher: WebSearcher = invoke_web_search,
) -> None:
    settings = get_settings()
    factory = get_session_factory()
    started = time.monotonic()
    with factory() as db:
        job = db.get(SearchJob, job_id)
        if job is None or job.status != "running" or job.job_kind != "web":
            raise RuntimeError("Only a claimed web search job can execute")
        if job.description is None:
            raise RuntimeError("Web search job has no description")
        request = db.get(SearchRequest, job.request_id)
        if request is None:
            raise RuntimeError("Search input record is missing")
        image_path = contained_path(settings.media_root, request.input_path)
        input_digest = request.input_sha256
        description = job.description
    if not image_path.is_file():
        raise RetrievalError("input_unavailable", "Search input is missing from storage")
    if sha256(image_path.read_bytes()) != input_digest:
        raise RetrievalError("input_corrupted", "Stored input checksum does not match")

    work_dir = settings.media_root / "web-search" / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    commit_started = False
    result: WebSearchResult | None = None
    try:
        result = WebSearchResult.model_validate(searcher(image_path, description, work_dir))
        elapsed_ms = int((time.monotonic() - started) * 1000)
        with factory() as db:
            job = db.get(SearchJob, job_id)
            if job is None or job.status != "running":
                raise RuntimeError("Web search job is no longer running")
            job.stage = "validating_candidates"
            db.commit()

        if result.status == "failed" or result.result_kind == "sources":
            error_code = (
                "candidate_processor_unavailable"
                if result.result_kind == "sources"
                else _safe_web_error_code(result.stop_reason)
            )
            error_message = (
                "Search found web sources but no validated animated GIF candidates"
                if result.result_kind == "sources"
                else f"Web search failed ({error_code})"
            )
            with factory() as db:
                job = db.get(SearchJob, job_id)
                if job is None or job.status != "running":
                    raise RuntimeError("Web search job is no longer running")
                job.status = "failed"
                job.stage = "failed"
                job.error_code = error_code
                job.error_detail = error_message[:1000]
                job.finished_at = utcnow()
                db.add(_execution_row(job_id, result, elapsed_ms))
                commit_started = True
                db.commit()
            logger.error(
                "web_search_failed",
                extra={
                    "request_id": job.request_id,
                    "job_id": job_id,
                    "error_code": error_code,
                },
            )
            return

        if result.result_kind == "no_results" and result.candidates:
            raise RetrievalError("invalid_web_search_result", "No-result response had candidates")
        if result.result_kind == "candidates":
            scores = [candidate.score for candidate in result.candidates]
            checksums = [candidate.sha256 for candidate in result.candidates]
            media_urls = [candidate.image_url for candidate in result.candidates]
            if (
                scores != sorted(scores, reverse=True)
                or len(set(checksums)) != len(checksums)
                or len(set(media_urls)) != len(media_urls)
            ):
                raise RetrievalError(
                    "invalid_web_search_result",
                    "Candidates must be ranked and unique",
                )

        with factory() as db:
            job = db.get(SearchJob, job_id)
            if job is None or job.status != "running" or job.started_at is None:
                raise RuntimeError("Web search job is no longer running")
            finished_at = utcnow()
            for rank, candidate in enumerate(result.candidates, start=1):
                source_path = contained_path(work_dir, candidate.relative_path)
                if (
                    not source_path.is_file()
                    or source_path.stat().st_size > settings.max_candidate_bytes
                ):
                    raise RetrievalError(
                        "invalid_candidate_media", "Candidate file is missing or too large"
                    )
                data = source_path.read_bytes()
                try:
                    frames = validate_image(data, animated_gif=True)
                except MediaError as exc:
                    raise RetrievalError(
                        "invalid_candidate_media", "Candidate is not a valid animated GIF"
                    ) from exc
                if sha256(data) != candidate.sha256 or frames != candidate.frame_count:
                    raise RetrievalError(
                        "candidate_checksum_mismatch",
                        "Candidate checksum or frame count does not match",
                    )
                _validate_public_reference(candidate.source_url)
                _validate_public_reference(candidate.image_url)
                candidate_id = new_id()
                relative = f"candidates/{job.id}/{candidate_id}.gif"
                written.append(atomic_write(settings.media_root, relative, data))
                db.add(
                    Candidate(
                        id=candidate_id,
                        job_id=job.id,
                        reference_asset_id=None,
                        saved_asset_id=None,
                        rank=rank,
                        similarity_score=candidate.score,
                        media_sha256=candidate.sha256,
                        source_url=candidate.source_url,
                        image_url=candidate.image_url,
                        provider=candidate.provider,
                        local_cache_path=relative,
                        frame_count=frames,
                        cache_expires_at=finished_at
                        + timedelta(days=settings.media_retention_days),
                    )
                )
            job.status = "completed"
            job.stage = "completed"
            job.result_kind = "candidates" if result.candidates else "no_candidates"
            job.model_version = result.model_version
            job.finished_at = finished_at
            db.add(_execution_row(job_id, result, elapsed_ms))
            commit_started = True
            db.commit()
            logger.info(
                "web_search_completed",
                extra={
                    "request_id": job.request_id,
                    "job_id": job.id,
                    "result_kind": job.result_kind,
                    "candidate_count": len(result.candidates),
                    "search_calls": result.search_calls,
                    "planner_calls": result.planner_calls,
                    "downloads_used": result.downloads_used,
                    "duration_ms": elapsed_ms,
                },
            )
    except BaseException as exc:
        if commit_started:
            logger.warning(
                "web_candidate_files_retained_after_unconfirmed_commit",
                extra={"job_id": job_id, "candidate_file_count": len(written)},
            )
        else:
            for path in written:
                remove_file_after_failure(path, storage_class="candidate")
        if isinstance(exc, (RetrievalError, MediaError, OSError, ValidationError)):
            if result is not None:
                code = exc.code if isinstance(exc, RetrievalError) else "invalid_candidate_media"
                message = (
                    str(exc) if isinstance(exc, RetrievalError) else "Candidate media is invalid"
                )
                with factory() as db:
                    job = db.get(SearchJob, job_id)
                    if job is not None and job.status == "running":
                        job.status = "failed"
                        job.stage = "failed"
                        job.error_code = code[:50]
                        job.error_detail = message[:1000]
                        job.finished_at = utcnow()
                        db.add(
                            _execution_row(
                                job_id,
                                result,
                                int((time.monotonic() - started) * 1000),
                            )
                        )
                        db.commit()
                logger.error(
                    "web_search_result_rejected",
                    extra={"job_id": job_id, "error_code": code},
                )
                return
        raise
    finally:
        _remove_web_work_dir(work_dir)


def claim_next_saved_asset_index(db: Session) -> SavedAsset | None:
    asset = db.scalar(
        select(SavedAsset)
        .where(SavedAsset.index_status == "pending")
        .order_by(SavedAsset.created_at, SavedAsset.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if asset is not None:
        asset.index_status = "running"
        asset.index_attempts += 1
        db.commit()
        logger.info("saved_asset_index_claimed", extra={"asset_id": asset.id})
    return asset


def process_saved_asset_index(
    asset_id: str,
    indexer: IndexSavedAsset = invoke_saved_asset_index,
) -> None:
    factory = get_session_factory()
    with factory() as db:
        asset = db.get(SavedAsset, asset_id)
        if asset is None or asset.index_status != "running":
            raise RuntimeError("Only a claimed saved asset can be indexed")
        relative_path = asset.gif_path
        digest = asset.sha256
        expected_frame_count = asset.frame_count
    try:
        settings = get_settings()
        asset_path = contained_path(settings.media_root, relative_path)
        if not asset_path.is_file():
            raise IndexingError("saved_asset_missing", "Saved GIF is missing from storage")
        with asset_path.open("rb") as source:
            data = source.read(settings.max_candidate_bytes + 1)
        if len(data) > settings.max_candidate_bytes:
            raise MediaError("Saved GIF exceeds the configured byte limit")
        if sha256(data) != digest:
            raise IndexingError("saved_asset_corrupted", "Saved GIF checksum does not match")
        frame_count = validate_image(data, animated_gif=True)
        if frame_count != expected_frame_count:
            raise IndexingError(
                "saved_asset_corrupted",
                "Saved GIF frame count does not match",
            )
        index_version = indexer(asset_id)
        if (
            not isinstance(index_version, str)
            or not index_version.strip()
            or len(index_version) > 100
        ):
            raise IndexingError("invalid_index_result", "Indexer returned an invalid version")
    except Exception as exc:
        if isinstance(exc, IndexingError):
            code = exc.code
        elif isinstance(exc, MediaError):
            code = "index_media_invalid"
        else:
            code = "index_failed"
        logger.exception("saved_asset_index_execution_failed", extra={"asset_id": asset_id})
        with factory() as db:
            asset = db.get(SavedAsset, asset_id)
            if asset is None or asset.index_status != "running":
                raise RuntimeError("Saved asset index state changed during execution")
            asset.index_status = "failed"
            asset.index_error = f"{code}: saved asset index update failed"
            db.commit()
        logger.error("saved_asset_index_failed", extra={"asset_id": asset_id, "error_code": code})
        return
    with factory() as db:
        asset = db.get(SavedAsset, asset_id)
        if asset is None or asset.index_status != "running":
            raise RuntimeError("Saved asset index state changed during execution")
        asset.index_status = "ready"
        asset.index_version = index_version
        asset.index_error = None
        asset.indexed_at = utcnow()
        db.commit()
    logger.info(
        "saved_asset_index_ready",
        extra={"asset_id": asset_id, "index_version": index_version},
    )


def recover_interrupted_saved_indexes(db: Session) -> int:
    assets = list(db.scalars(select(SavedAsset).where(SavedAsset.index_status == "running")))
    for asset in assets:
        asset.index_status = "failed"
        asset.index_error = "index_interrupted: Worker stopped during index update"
        logger.warning("saved_asset_index_interrupted", extra={"asset_id": asset.id})
    db.commit()
    return len(assets)


def cleanup_media(db: Session) -> None:
    settings = get_settings()
    now = utcnow()
    cutoff = now - timedelta(days=settings.media_retention_days)
    for candidate in db.scalars(select(Candidate).where(Candidate.cache_expires_at <= now)):
        remove_file_after_failure(
            contained_path(settings.media_root, candidate.local_cache_path),
            storage_class="candidate",
        )

    for request in db.scalars(
        select(SearchRequest)
        .where(SearchRequest.created_at < cutoff)
        .with_for_update(skip_locked=True)
    ):
        retained = db.scalar(
            select(SearchJob.id)
            .where(
                SearchJob.request_id == request.id,
                (SearchJob.status.in_(["pending", "running"])) | (SearchJob.finished_at > cutoff),
            )
            .limit(1)
        )
        if retained is None:
            remove_file_after_failure(
                contained_path(settings.media_root, request.input_path),
                storage_class="input",
            )

    referenced_inputs = set(db.scalars(select(SearchRequest.input_path)))
    orphan_cutoff = (now - timedelta(days=1)).timestamp()
    for path in (settings.media_root / "inputs").iterdir():
        relative = path.relative_to(settings.media_root).as_posix()
        if relative not in referenced_inputs and _is_stale_regular_file(
            path, orphan_cutoff, storage_class="orphan_input"
        ):
            remove_file_after_failure(path, storage_class="orphan_input")
    from services.common.search_models import MemeCandidateDraft

    active_jobs = set(
        db.scalars(select(SearchJob.id).where(SearchJob.status.in_(["pending", "running"])))
    )
    for draft in db.scalars(select(MemeCandidateDraft).where(MemeCandidateDraft.expires_at <= now)):
        if draft.job_id not in active_jobs:
            for relative in [draft.local_path, draft.preview_path]:
                remove_file_after_failure(
                    contained_path(settings.media_root, relative), storage_class="expired_draft"
                )
            db.delete(draft)
    db.commit()
    referenced_candidates = set(db.scalars(select(Candidate.local_cache_path)))
    referenced_candidates.update(
        db.scalars(select(Candidate.preview_path).where(Candidate.preview_path.is_not(None)))
    )
    for path in (settings.media_root / "candidates").glob("*/*"):
        relative = path.relative_to(settings.media_root).as_posix()
        if relative not in referenced_candidates and _is_stale_regular_file(
            path, orphan_cutoff, storage_class="orphan_candidate"
        ):
            remove_file_after_failure(path, storage_class="orphan_candidate")
    referenced_saved = set(db.scalars(select(SavedAsset.gif_path)))
    for path in (settings.media_root / "saved").iterdir():
        relative = path.relative_to(settings.media_root).as_posix()
        if relative not in referenced_saved and _is_stale_regular_file(
            path, orphan_cutoff, storage_class="orphan_saved_asset"
        ):
            remove_file_after_failure(path, storage_class="orphan_saved_asset")
    work_root = settings.media_root / "web-search"
    for path in work_root.iterdir():
        if _is_stale_directory(path, orphan_cutoff):
            _remove_web_work_dir(path)


def run_worker(stop_event: threading.Event | None = None) -> None:
    stop_event = stop_event or threading.Event()
    configure_logging()
    prepare_storage()
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        raise RuntimeError("The deployed search worker requires PostgreSQL for singleton locking")
    factory = get_session_factory()
    # Keep a dedicated session-level lock while recovering and processing jobs.
    with engine.connect() as ownership:
        if not ownership.scalar(text("SELECT pg_try_advisory_lock(6000, 7)")):
            raise RuntimeError("Another MemeRetrieve search worker is already running")
        ownership.commit()
        try:
            with factory() as db:
                recover_interrupted_jobs(db)
                recover_interrupted_saved_indexes(db)
                cleanup_media(db)
            last_cleanup = time.monotonic()
            logger.info("search_worker_started")
            while not stop_event.is_set():
                ownership.execute(text("SELECT 1"))
                ownership.commit()
                with factory() as db:
                    job = claim_next_search_job(db)
                    asset = None if job is not None else claim_next_saved_asset_index(db)
                    if job is not None and stop_event.is_set():
                        release_claimed_search_job(db, job.id)
                        job = None
                        break
                    if asset is not None and stop_event.is_set():
                        asset.index_status = "pending"
                        db.commit()
                        asset = None
                        break
                if job is not None:
                    try:
                        if job.search_profile == "meme50-v2":
                            from .meme_worker import process_meme_job

                            process_meme_job(job.id, factory=factory)
                        elif job.job_kind == "web":
                            process_web_search_job(job.id)
                        else:
                            process_search_job(job.id)
                    except (RetrievalError, MediaError, OSError, ValidationError) as exc:
                        logger.exception("search_processing_failed", extra={"job_id": job.id})
                        code = (
                            exc.code
                            if isinstance(exc, RetrievalError)
                            else "media_processing_failed"
                        )
                        message = (
                            str(exc)
                            if isinstance(exc, RetrievalError)
                            else ("Input or candidate media could not be validated or stored")
                        )
                        with factory() as db:
                            fail_job(db, job.id, code, message)
                    except Exception:
                        logger.exception("search_unexpected_failure", extra={"job_id": job.id})
                        with factory() as db:
                            fail_job(
                                db, job.id, "worker_error", "Unexpected worker execution failure"
                            )
                elif asset is not None:
                    process_saved_asset_index(asset.id)
                else:
                    stop_event.wait(get_settings().worker_poll_seconds)
                if not stop_event.is_set() and time.monotonic() - last_cleanup >= 3600:
                    with factory() as db:
                        cleanup_media(db)
                    last_cleanup = time.monotonic()
        finally:
            ownership.execute(text("SELECT pg_advisory_unlock(6000, 7)"))
            ownership.commit()


if __name__ == "__main__":
    shutdown_event = threading.Event()
    register_shutdown_handlers(shutdown_event)
    run_worker(shutdown_event)
