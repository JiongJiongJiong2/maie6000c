from __future__ import annotations

import logging
import secrets
from datetime import timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from services.common.config import get_settings
from services.common.db import get_db
from services.common.models import utcnow
from services.common.search_models import Candidate, ReviewDecision, SearchJob, SearchRequest
from services.common.search_schemas import (
    AcceptedSearch,
    CandidateRead,
    RetryCreate,
    ReviewCreate,
    ReviewRead,
    SearchError,
    SearchRead,
)
from services.common.storage import (
    MediaError,
    atomic_write,
    contained_path,
    prepare_storage,
    remove_file_after_failure,
    sha256,
    validate_image,
)

logger = logging.getLogger("services.api.search")


def fail(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def authorize(request: Request) -> None:
    token = get_settings().device_token
    if token and not secrets.compare_digest(
        request.headers.get("authorization", ""), f"Bearer {token}"
    ):
        raise fail(401, "unauthorized", "A valid device token is required")


router = APIRouter(dependencies=[Depends(authorize)])
Database = Annotated[Session, Depends(get_db)]
KeyForm = Annotated[str, Form(min_length=1, max_length=128, pattern=r"^\S+$")]


def require_request(db: Session, request_id: str, *, lock: bool = False) -> SearchRequest:
    statement = select(SearchRequest).where(SearchRequest.id == request_id)
    if lock:
        statement = statement.with_for_update()
    request = db.scalar(statement)
    if request is None:
        raise fail(404, "request_not_found", "Search request not found")
    return request


def latest_job(db: Session, request_id: str) -> SearchJob:
    job = db.scalar(
        select(SearchJob)
        .where(SearchJob.request_id == request_id)
        .order_by(SearchJob.attempt_no.desc())
        .limit(1)
    )
    if job is None:
        raise RuntimeError("Persisted search request has no job")
    return job


def accepted(job: SearchJob) -> AcceptedSearch:
    return AcceptedSearch.model_validate(
        {"request_id": job.request_id, "job_id": job.id, "status": job.status}
    )


def replay_submission(
    db: Session,
    existing: SearchRequest,
    digest: str,
    keywords: str | None,
    item_id: str | None,
) -> AcceptedSearch:
    if (existing.input_sha256, existing.user_keywords, existing.client_item_id) != (
        digest,
        keywords,
        item_id,
    ):
        raise fail(409, "submission_key_conflict", "Submission key has different content")
    job = db.scalar(
        select(SearchJob).where(SearchJob.request_id == existing.id, SearchJob.attempt_no == 1)
    )
    if job is None:
        raise RuntimeError("Persisted submission has no initial job")
    return accepted(job)


@router.post("/search-requests", status_code=202, response_model=AcceptedSearch)
def create_search(
    db: Database,
    client_submission_key: KeyForm,
    image: Annotated[UploadFile, File()],
    user_keywords: Annotated[str | None, Form(max_length=500)] = None,
    client_item_id: Annotated[str | None, Form(max_length=128)] = None,
) -> AcceptedSearch:
    data = image.file.read(get_settings().max_upload_bytes + 1)
    if len(data) > get_settings().max_upload_bytes:
        raise fail(413, "upload_too_large", "Image exceeds the configured byte limit")
    try:
        validate_image(data)
    except MediaError as exc:
        raise fail(422, "invalid_image", str(exc)) from exc
    digest = sha256(data)
    existing = db.scalar(
        select(SearchRequest).where(SearchRequest.client_submission_key == client_submission_key)
    )
    if existing is not None:
        return replay_submission(db, existing, digest, user_keywords, client_item_id)

    relative = f"inputs/{uuid4()}.image"
    try:
        prepare_storage()
        stored = atomic_write(get_settings().media_root, relative, data)
    except OSError as exc:
        logger.exception("upload_storage_failed")
        raise fail(503, "storage_unavailable", "Input could not be stored") from exc

    request = SearchRequest(
        client_submission_key=client_submission_key,
        client_item_id=client_item_id,
        input_path=relative,
        input_sha256=digest,
        user_keywords=user_keywords,
    )
    try:
        db.add(request)
        db.flush()
        job = SearchJob(request_id=request.id)
        db.add(job)
        db.commit()
    except IntegrityError:
        db.rollback()
        remove_file_after_failure(stored, storage_class="input")
        existing = db.scalar(
            select(SearchRequest).where(
                SearchRequest.client_submission_key == client_submission_key
            )
        )
        if existing is None:
            logger.exception("submission_integrity_failed")
            raise fail(503, "database_unavailable", "Submission could not be committed")
        return replay_submission(db, existing, digest, user_keywords, client_item_id)
    except SQLAlchemyError as exc:
        db.rollback()
        remove_file_after_failure(stored, storage_class="input")
        logger.exception("submission_commit_failed")
        raise fail(503, "database_unavailable", "Submission could not be committed") from exc
    logger.info("search_accepted", extra={"request_id": request.id, "job_id": job.id})
    return accepted(job)


def candidates_for_job(db: Session, job_id: str) -> list[CandidateRead]:
    candidates = db.scalars(
        select(Candidate).where(Candidate.job_id == job_id).order_by(Candidate.rank)
    )
    return [
        CandidateRead(
            candidate_id=UUID(candidate.id),
            rank=candidate.rank,
            score=candidate.similarity_score,
            media_url=f"/candidates/{candidate.id}/media",
        )
        for candidate in candidates
    ]


@router.get("/search-requests/{request_id}", response_model=SearchRead)
def read_search(request_id: UUID, db: Database) -> SearchRead:
    require_request(db, str(request_id))
    job = latest_job(db, str(request_id))
    error = None
    if job.error_code is not None:
        error = SearchError(code=job.error_code, message=job.error_detail or job.error_code)
    if job.result_kind not in (None, "candidates", "no_candidates"):
        raise RuntimeError(f"Persisted search job has invalid result kind: {job.result_kind}")
    return SearchRead(
        **accepted(job).model_dump(),
        result_kind=job.result_kind,
        candidates=candidates_for_job(db, job.id),
        error=error,
    )


@router.get("/search-jobs/{job_id}/candidates", response_model=list[CandidateRead])
def read_candidates(job_id: UUID, db: Database) -> list[CandidateRead]:
    if db.get(SearchJob, str(job_id)) is None:
        raise fail(404, "job_not_found", "Search job not found")
    return candidates_for_job(db, str(job_id))


@router.get("/candidates/{candidate_id}/media")
def read_media(candidate_id: UUID, db: Database) -> FileResponse:
    candidate = db.get(Candidate, str(candidate_id))
    if candidate is None:
        raise fail(404, "candidate_not_found", "Candidate not found")
    expiry = candidate.cache_expires_at.replace(tzinfo=timezone.utc)
    if expiry <= utcnow():
        raise fail(410, "media_expired", "Candidate media has expired; submit a new search")
    path = contained_path(get_settings().media_root, candidate.local_cache_path)
    if not path.is_file():
        logger.error("candidate_media_missing", extra={"candidate_id": candidate.id})
        raise fail(503, "media_unavailable", "Candidate media is missing from storage")
    return FileResponse(
        path,
        media_type="image/gif",
        filename=f"{candidate.id}.gif",
        content_disposition_type="inline",
    )


def replay_review(existing: ReviewDecision, job_id: str, payload: ReviewCreate) -> ReviewRead:
    candidate_id = str(payload.candidate_id) if payload.candidate_id is not None else None
    if (existing.job_id, existing.decision, existing.candidate_id) != (
        job_id,
        payload.decision,
        candidate_id,
    ):
        raise fail(409, "review_key_conflict", "Review key has different content")
    return ReviewRead(review_id=UUID(existing.id))


@router.post("/search-jobs/{job_id}/reviews", response_model=ReviewRead, status_code=201)
def create_review(job_id: UUID, payload: ReviewCreate, db: Database) -> ReviewRead:
    existing = db.scalar(
        select(ReviewDecision).where(ReviewDecision.client_review_key == payload.client_review_key)
    )
    if existing is not None:
        return replay_review(existing, str(job_id), payload)
    job = db.get(SearchJob, str(job_id))
    if job is None:
        raise fail(404, "job_not_found", "Search job not found")
    if job.status != "completed":
        raise fail(409, "job_not_completed", "Only completed jobs may be reviewed")
    candidate_id = str(payload.candidate_id) if payload.candidate_id is not None else None
    if candidate_id is not None:
        candidate = db.get(Candidate, candidate_id)
        if candidate is None or candidate.job_id != job.id:
            raise fail(422, "candidate_job_mismatch", "Candidate must belong to this job")
    review = ReviewDecision(
        job_id=job.id,
        candidate_id=candidate_id,
        decision=payload.decision,
        client_review_key=payload.client_review_key,
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(ReviewDecision).where(
                ReviewDecision.client_review_key == payload.client_review_key
            )
        )
        if existing is None:
            raise
        return replay_review(existing, str(job_id), payload)
    logger.info("review_recorded", extra={"job_id": job.id, "review_id": review.id})
    return ReviewRead(review_id=UUID(review.id))


def replay_retry(existing: SearchJob, request_id: str) -> AcceptedSearch:
    if existing.request_id != request_id:
        raise fail(409, "retry_key_conflict", "Retry key belongs to a different request")
    return accepted(existing)


@router.post("/search-requests/{request_id}/retry", response_model=AcceptedSearch, status_code=202)
def retry_search(request_id: UUID, payload: RetryCreate, db: Database) -> AcceptedSearch:
    request = require_request(db, str(request_id), lock=True)
    existing = db.scalar(
        select(SearchJob).where(SearchJob.client_retry_key == payload.client_retry_key)
    )
    if existing is not None:
        return replay_retry(existing, request.id)
    previous = latest_job(db, request.id)
    if previous.status != "failed":
        raise fail(409, "retry_not_allowed", "Only a failed request can be retried")
    if not contained_path(get_settings().media_root, request.input_path).is_file():
        raise fail(410, "input_expired", "Input is unavailable; submit a new search")
    job = SearchJob(
        request_id=request.id,
        attempt_no=previous.attempt_no + 1,
        client_retry_key=payload.client_retry_key,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(SearchJob).where(SearchJob.client_retry_key == payload.client_retry_key)
        )
        if existing is not None:
            return replay_retry(existing, str(request_id))
        raise fail(409, "retry_conflict", "Another retry is already active")
    logger.info("search_retried", extra={"request_id": request.id, "job_id": job.id})
    return accepted(job)
