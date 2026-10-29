from __future__ import annotations

import logging
import signal
import threading

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from services.common.config import configure_logging, get_settings
from services.common.db import get_engine, get_session_factory
from services.common.models import Case, CaseStatus, Job, JobStatus, utcnow
from services.common.schemas import TriageResponse

configure_logging()
logger = logging.getLogger("services.worker.main")
settings = get_settings()
STARTER_WORKER_LOCK_ID = 8


def claim_next_pending_job(db: Session) -> Job | None:
    stmt = (
        select(Job)
        .where(Job.status == JobStatus.PENDING.value)
        .order_by(Job.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = db.execute(stmt).scalars().first()
    if job is None:
        return None

    job.status = JobStatus.CLAIMED.value
    job.claimed_at = utcnow()
    job.attempts += 1
    db.commit()
    db.refresh(job)
    return job


def recover_interrupted_jobs(db: Session) -> int:
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.status == JobStatus.CLAIMED.value)
            .with_for_update(skip_locked=True)
        )
    )
    for job in jobs:
        job.status = JobStatus.PENDING.value
        job.claimed_at = None
        job.error = None
        job.completed_at = None
        case = db.get(Case, job.case_id)
        if case is not None:
            case.status = CaseStatus.QUEUED.value
        logger.warning("job_requeued_after_interruption", extra={"job_id": job.id})
    db.commit()
    return len(jobs)


def mark_job_failed(job_id: int, error_message: str) -> None:
    session_factory = get_session_factory()
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        case = db.get(Case, job.case_id)
        job.status = JobStatus.FAILED.value
        job.error = error_message[:1000]
        job.completed_at = utcnow()

        if case is not None:
            case.status = CaseStatus.FAILED.value

        db.commit()


def process_job(job_id: int) -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        case = db.get(Case, job.case_id)
        if case is None:
            raise RuntimeError(f"Case not found for job {job_id}")

        payload = {
            "case_id": case.id,
            "title": case.title,
            "description": case.description,
        }

    response = httpx.post(
        f"{settings.ai_service_url}/triage",
        json=payload,
        timeout=settings.worker_request_timeout_seconds,
    )
    response.raise_for_status()
    triage = TriageResponse.model_validate(response.json())

    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        case = db.get(Case, job.case_id)
        if case is None:
            raise RuntimeError(f"Case not found while completing job {job_id}")

        case.status = CaseStatus.TRIAGED.value
        case.ai_label = triage.label
        case.ai_summary = triage.summary
        case.ai_confidence = triage.confidence

        job.status = JobStatus.COMPLETED.value
        job.error = None
        job.completed_at = utcnow()
        db.commit()

    logger.info("job_completed", extra={"job_id": job_id, "label": triage.label})


def run_worker(stop_event: threading.Event | None = None) -> None:
    stop_event = stop_event or threading.Event()
    session_factory = get_session_factory()
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        raise RuntimeError("The deployed starter worker requires PostgreSQL for singleton locking")
    logger.info(
        "worker_started",
        extra={
            "poll_seconds": settings.worker_poll_seconds,
            "ai_service_url": settings.ai_service_url,
        },
    )

    with engine.connect() as ownership:
        acquired = ownership.scalar(
            text("SELECT pg_try_advisory_lock(6000, :lock_id)"),
            {"lock_id": STARTER_WORKER_LOCK_ID},
        )
        if not acquired:
            raise RuntimeError("Another starter case/AI worker is already running")
        ownership.commit()
        try:
            with session_factory() as db:
                recover_interrupted_jobs(db)

            while not stop_event.is_set():
                job = None
                try:
                    with session_factory() as db:
                        job = claim_next_pending_job(db)

                    if job is None:
                        stop_event.wait(settings.worker_poll_seconds)
                        continue

                    logger.info("job_claimed", extra={"job_id": job.id, "case_id": job.case_id})
                    process_job(job.id)

                except Exception as exc:
                    logger.exception("job_processing_failed")
                    if job is not None:
                        mark_job_failed(job.id, str(exc))
                    stop_event.wait(settings.worker_poll_seconds)
        finally:
            ownership.execute(
                text("SELECT pg_advisory_unlock(6000, :lock_id)"),
                {"lock_id": STARTER_WORKER_LOCK_ID},
            )
            ownership.commit()
    logger.info("worker_stopped")


if __name__ == "__main__":
    shutdown_event = threading.Event()

    def request_shutdown(_signum: int, _frame: object) -> None:
        del _signum, _frame
        shutdown_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    run_worker(shutdown_event)
