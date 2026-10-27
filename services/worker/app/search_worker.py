from __future__ import annotations

import logging
import signal
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import timedelta
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
    SearchJob,
    SearchRequest,
    new_id,
)
from services.common.search_schemas import RetrievalResult
from services.common.storage import (
    MediaError,
    atomic_write,
    contained_path,
    prepare_storage,
    remove_file_after_failure,
    read_gif,
    sha256,
)

logger = logging.getLogger("services.worker.search")
Retriever = Callable[[Path], RetrievalResult]


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
        job.started_at = utcnow()
        db.commit()
        logger.info("search_claimed", extra={"request_id": job.request_id, "job_id": job.id})
    return job


def release_claimed_search_job(db: Session, job_id: str) -> None:
    job = db.get(SearchJob, job_id)
    if job is None or job.status != "running":
        raise RuntimeError("Only a claimed search job can be released")
    job.status = "pending"
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
                if asset is None or asset.corpus_version != result.corpus_version:
                    raise RetrievalError(
                        "corpus_mismatch", "Retrieved asset is absent from the declared corpus"
                    )
                data, frames = read_gif(asset.gif_path)
                if sha256(data) != asset.sha256 or frames != asset.frame_count:
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
                        reference_asset_id=asset.id,
                        rank=rank,
                        similarity_score=match.score,
                        local_cache_path=relative,
                        frame_count=frames,
                        cache_expires_at=finished_at
                        + timedelta(days=settings.media_retention_days),
                    )
                )
            job.status = "completed"
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
                    "candidate_count": len(result.matches),
                    "duration_seconds": (
                        finished_at - job.started_at.replace(tzinfo=finished_at.tzinfo)
                    ).total_seconds(),
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
    referenced_candidates = set(db.scalars(select(Candidate.local_cache_path)))
    for path in (settings.media_root / "candidates").glob("*/*"):
        relative = path.relative_to(settings.media_root).as_posix()
        if relative not in referenced_candidates and _is_stale_regular_file(
            path, orphan_cutoff, storage_class="orphan_candidate"
        ):
            remove_file_after_failure(path, storage_class="orphan_candidate")


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
                cleanup_media(db)
            last_cleanup = time.monotonic()
            logger.info("search_worker_started")
            while not stop_event.is_set():
                ownership.execute(text("SELECT 1"))
                ownership.commit()
                with factory() as db:
                    job = claim_next_search_job(db)
                    if job is not None and stop_event.is_set():
                        release_claimed_search_job(db, job.id)
                        job = None
                        break
                if job is not None:
                    try:
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
