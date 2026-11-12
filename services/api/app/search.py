from __future__ import annotations

import logging
import secrets
from datetime import timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from services.common.config import get_settings
from services.common.db import get_db
from services.common.models import utcnow
from services.common.search_models import (
    Candidate,
    CandidateSave,
    ReviewDecision,
    SavedAsset,
    SearchJob,
    SearchRequest,
)
from services.common.search_schemas import (
    AcceptedSearch,
    CandidateRead,
    RetryCreate,
    ReviewCreate,
    ReviewRead,
    SaveCreate,
    SavedAssetRead,
    SearchError,
    SearchRead,
    WebSearchCreate,
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
MEDIA_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


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


def latest_local_job(db: Session, request_id: str) -> SearchJob:
    job = db.scalar(
        select(SearchJob)
        .where(SearchJob.request_id == request_id, SearchJob.job_kind == "local")
        .order_by(SearchJob.attempt_no.desc())
        .limit(1)
    )
    if job is None:
        raise RuntimeError("Persisted search request has no local job")
    return job


def accepted(job: SearchJob) -> AcceptedSearch:
    return AcceptedSearch.model_validate(
        {
            "request_id": job.request_id,
            "job_id": job.id,
            "status": job.status,
            "search_profile": job.search_profile,
            "target_count": job.target_count,
            "contract_version": 2 if job.search_profile == "meme50-v2" else 1,
        }
    )


def replay_submission(
    db: Session,
    existing: SearchRequest,
    digest: str,
    keywords: str | None,
    item_id: str | None,
    profile="legacy",
    target_count=3,
) -> AcceptedSearch:
    if (
        existing.input_sha256,
        existing.user_keywords,
        existing.client_item_id,
        existing.search_profile,
        existing.target_count,
    ) != (digest, keywords, item_id, profile, target_count):
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
    description: Annotated[str | None, Form(max_length=500)] = None,
    search_profile: Annotated[Literal["legacy", "meme50-v2"], Form()] = "legacy",
    target_count: Annotated[int | None, Form(ge=1, le=50)] = None,
) -> AcceptedSearch:
    data = image.file.read(get_settings().max_upload_bytes + 1)
    if len(data) > get_settings().max_upload_bytes:
        raise fail(413, "upload_too_large", "Image exceeds the configured byte limit")
    normalized_description = (description or "").strip() or None
    normalized_keywords = (user_keywords or "").strip() or None
    if (
        description is not None
        and user_keywords is not None
        and normalized_description != normalized_keywords
    ):
        raise fail(422, "description_conflict", "description and user_keywords disagree")
    user_keywords = normalized_description if description is not None else normalized_keywords
    target_count = (
        target_count if target_count is not None else (50 if search_profile == "meme50-v2" else 3)
    )
    if search_profile == "legacy" and target_count != 3:
        raise fail(422, "legacy_target_count", "Legacy search returns at most three candidates")
    input_metadata = None
    try:
        if search_profile == "meme50-v2":
            from services.common.media import inspect_media

            input_metadata = inspect_media(data).model_dump()
        else:
            validate_image(data)
    except MediaError as exc:
        raise fail(422, "invalid_image", str(exc)) from exc
    digest = sha256(data)
    existing = db.scalar(
        select(SearchRequest).where(SearchRequest.client_submission_key == client_submission_key)
    )
    if existing is not None:
        return replay_submission(
            db, existing, digest, user_keywords, client_item_id, search_profile, target_count
        )

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
        search_profile=search_profile,
        target_count=target_count,
        input_metadata=input_metadata,
    )
    try:
        db.add(request)
        db.flush()
        job = SearchJob(
            request_id=request.id,
            search_profile=search_profile,
            target_count=target_count,
            job_kind="web" if search_profile == "meme50-v2" else "local",
            description=user_keywords if search_profile == "meme50-v2" else None,
            configuration={"profile": search_profile, "version": "meme50-dev-20261111"},
        )
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
        return replay_submission(
            db, existing, digest, user_keywords, client_item_id, search_profile, target_count
        )
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
    results = []
    for candidate in candidates:
        saved = db.get(SavedAsset, candidate.saved_asset_id) if candidate.saved_asset_id else None
        results.append(
            CandidateRead.model_validate(
                {
                    "candidate_id": candidate.id,
                    "rank": candidate.rank,
                    "contract_version": 2
                    if db.get(SearchJob, job_id).search_profile == "meme50-v2"
                    else 1,
                    "media_format": candidate.media_format,
                    "mime_type": candidate.mime_type,
                    "media_kind": candidate.media_kind,
                    "frame_count": candidate.frame_count,
                    "width": candidate.width,
                    "height": candidate.height,
                    "content_group_id": candidate.content_group_id,
                    "sha256": candidate.media_sha256,
                    "byte_size": candidate.byte_size,
                    "duration_ms": candidate.duration_ms,
                    "preview_url": f"/candidates/{candidate.id}/preview",
                    "score": candidate.similarity_score,
                    "media_url": f"/candidates/{candidate.id}/media",
                    "source_url": candidate.source_url or (saved.source_url if saved else None),
                    "image_url": candidate.image_url or (saved.image_url if saved else None),
                    "provider": candidate.provider or (saved.provider if saved else None),
                    "save_status": "saved" if saved else "not_saved",
                    "asset_id": saved.id if saved else None,
                    "index_status": saved.index_status if saved else None,
                }
            )
        )
    return results


def read_verified_gif(
    relative_path: str,
    *,
    expected_sha256: str | None,
    expected_frame_count: int,
) -> bytes:
    path = contained_path(get_settings().media_root, relative_path)
    with path.open("rb") as source:
        data = source.read(get_settings().max_candidate_bytes + 1)
    if len(data) > get_settings().max_candidate_bytes:
        raise MediaError("GIF exceeds the configured size limit")
    if expected_sha256 is not None and sha256(data) != expected_sha256:
        raise MediaError("GIF checksum does not match")
    frames = validate_image(data, animated_gif=True)
    if frames != expected_frame_count:
        raise MediaError("GIF frame count does not match")
    return data


def verify_saved_asset_media(asset: SavedAsset) -> bytes:
    try:
        return read_verified_gif(
            asset.gif_path,
            expected_sha256=asset.sha256,
            expected_frame_count=asset.frame_count,
        )
    except FileNotFoundError as exc:
        logger.error("saved_asset_media_missing", extra={"asset_id": asset.id})
        raise fail(503, "saved_asset_unavailable", "Saved GIF is missing from storage") from exc
    except OSError as exc:
        logger.exception("saved_asset_media_read_failed", extra={"asset_id": asset.id})
        raise fail(503, "saved_asset_unavailable", "Saved GIF could not be read") from exc
    except MediaError as exc:
        logger.error(
            "saved_asset_media_invalid",
            extra={"asset_id": asset.id, "reason": str(exc)},
        )
        raise fail(503, "saved_asset_corrupted", "Saved GIF failed integrity validation") from exc


def remove_unreferenced_saved_file(
    db: Session,
    stored_path: Path | None,
    digest: str,
) -> None:
    if stored_path is None:
        return
    try:
        referenced = db.scalar(select(SavedAsset.id).where(SavedAsset.sha256 == digest))
    except SQLAlchemyError:
        logger.exception("saved_asset_reference_check_failed")
        return
    if referenced is None:
        remove_file_after_failure(stored_path, storage_class="saved_asset")


@router.get("/search-requests/{request_id}", response_model=SearchRead)
def read_search(request_id: UUID, db: Database) -> SearchRead:
    request = require_request(db, str(request_id))
    job = latest_job(db, str(request_id))
    local_job = db.scalar(
        select(SearchJob)
        .where(SearchJob.request_id == str(request_id), SearchJob.job_kind == "local")
        .order_by(SearchJob.attempt_no.desc())
        .limit(1)
    )
    if local_job is None and request.search_profile == "legacy":
        raise RuntimeError("Persisted legacy search request has no local job")
    web_jobs = db.scalars(
        select(SearchJob)
        .where(SearchJob.request_id == str(request_id), SearchJob.job_kind == "web")
        .order_by(SearchJob.attempt_no)
    )
    error = None
    if job.error_code is not None:
        error = SearchError(code=job.error_code, message=job.error_detail or job.error_code)
    if job.result_kind not in (None, "candidates", "no_candidates"):
        raise RuntimeError(f"Persisted search job has invalid result kind: {job.result_kind}")
    return SearchRead.model_validate(
        {
            "request_id": job.request_id,
            "job_id": job.id,
            "status": job.status,
            "job_kind": job.job_kind,
            "stage": job.stage,
            "local_job_id": local_job.id if local_job else None,
            "search_profile": job.search_profile,
            "target_count": job.target_count,
            "contract_version": 2 if job.search_profile == "meme50-v2" else 1,
            "result_revision": job.result_revision,
            "progress": job.progress,
            "partial": job.partial,
            "web_searches": [
                {
                    "job_id": web_job.id,
                    "job_kind": web_job.job_kind,
                    "status": web_job.status,
                    "stage": web_job.stage,
                    "description": web_job.description,
                    "result_kind": web_job.result_kind,
                    "error": (
                        {
                            "code": web_job.error_code,
                            "message": web_job.error_detail or web_job.error_code,
                        }
                        if web_job.error_code
                        else None
                    ),
                }
                for web_job in web_jobs
            ],
            "result_kind": job.result_kind,
            "candidates": candidates_for_job(db, job.id),
            "error": (
                {"code": error.code, "message": error.message} if error is not None else None
            ),
        }
    )


@router.post(
    "/search-requests/{request_id}/web-search",
    response_model=AcceptedSearch,
    status_code=202,
)
def create_web_search(
    request_id: UUID,
    payload: WebSearchCreate,
    db: Database,
) -> AcceptedSearch:
    request = require_request(db, str(request_id), lock=True)
    existing = db.scalar(
        select(SearchJob).where(SearchJob.client_search_key == payload.client_search_key)
    )
    if existing is not None:
        if (
            existing.request_id != request.id
            or existing.description != payload.description.strip()
            or existing.job_kind != "web"
        ):
            raise fail(409, "search_key_conflict", "Search key has different content")
        return accepted(existing)
    input_path = contained_path(get_settings().media_root, request.input_path)
    if not input_path.is_file():
        raise fail(410, "input_expired", "Search input is unavailable")
    active = db.scalar(
        select(SearchJob).where(
            SearchJob.request_id == request.id,
            SearchJob.status.in_(["pending", "running"]),
        )
    )
    if active is not None:
        raise fail(409, "search_already_active", "Wait for the active job to finish")
    last_attempt = db.scalar(
        select(SearchJob.attempt_no)
        .where(SearchJob.request_id == request.id)
        .order_by(SearchJob.attempt_no.desc())
        .limit(1)
    )
    job = SearchJob(
        request_id=request.id,
        attempt_no=(last_attempt or 0) + 1,
        job_kind="web",
        stage="pending",
        description=payload.description.strip(),
        search_profile=request.search_profile if payload.description.strip() else "meme50-v2",
        target_count=request.target_count
        if request.search_profile == "meme50-v2"
        else (50 if not payload.description.strip() else 3),
        client_search_key=payload.client_search_key,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(SearchJob).where(SearchJob.client_search_key == payload.client_search_key)
        )
        if existing is not None and (
            existing.request_id == request.id
            and existing.description == payload.description.strip()
            and existing.job_kind == "web"
        ):
            return accepted(existing)
        raise fail(409, "search_conflict", "Another search is already active")
    logger.info(
        "web_search_accepted",
        extra={"request_id": request.id, "job_id": job.id},
    )
    return accepted(job)


@router.get("/search-jobs/{job_id}/candidates", response_model=list[CandidateRead])
def read_candidates(job_id: UUID, db: Database) -> list[CandidateRead]:
    if db.get(SearchJob, str(job_id)) is None:
        raise fail(404, "job_not_found", "Search job not found")
    return candidates_for_job(db, str(job_id))


@router.get("/candidates/{candidate_id}/media")
def read_media(candidate_id: UUID, db: Database) -> Response:
    candidate = db.get(Candidate, str(candidate_id))
    if candidate is None:
        raise fail(404, "candidate_not_found", "Candidate not found")
    if candidate.saved_asset_id is not None:
        asset = db.get(SavedAsset, candidate.saved_asset_id)
        if asset is None:
            logger.error("candidate_saved_asset_missing", extra={"candidate_id": candidate.id})
            raise fail(503, "saved_asset_unavailable", "Saved GIF is unavailable")
        data = verify_saved_asset_media(asset)
    else:
        expiry = candidate.cache_expires_at.replace(tzinfo=timezone.utc)
        if expiry <= utcnow():
            raise fail(410, "media_expired", "Candidate media has expired; submit a new search")
        try:
            from .meme_search import verified_candidate_bytes

            data = verified_candidate_bytes(candidate)

        except FileNotFoundError as exc:
            logger.error("candidate_media_missing", extra={"candidate_id": candidate.id})
            raise fail(503, "media_unavailable", "Candidate media is missing from storage") from exc
        except OSError as exc:
            logger.exception("candidate_media_read_failed", extra={"candidate_id": candidate.id})
            raise fail(503, "media_unavailable", "Candidate media could not be read") from exc
        except MediaError as exc:
            logger.error(
                "candidate_media_invalid",
                extra={"candidate_id": candidate.id, "reason": str(exc)},
            )
            raise fail(503, "media_corrupted", "Candidate GIF failed integrity validation") from exc
    from services.common.media import FORMATS

    suffix = FORMATS[candidate.media_format][1]
    return Response(
        content=data,
        media_type=candidate.mime_type,
        headers={
            **MEDIA_RESPONSE_HEADERS,
            "Content-Disposition": f'inline; filename="{candidate.id}.{suffix}"',
        },
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


def saved_asset_read(asset: SavedAsset) -> SavedAssetRead:
    return SavedAssetRead.model_validate(
        {
            "asset_id": asset.id,
            "save_status": "saved",
            "media_url": f"/saved-assets/{asset.id}/media",
            "index_status": asset.index_status,
            "index_error": asset.index_error,
        }
    )


@router.post(
    "/candidates/{candidate_id}/save",
    response_model=SavedAssetRead,
    status_code=202,
)
def save_candidate(
    candidate_id: UUID,
    payload: SaveCreate,
    db: Database,
) -> SavedAssetRead:
    existing_save = db.scalar(
        select(CandidateSave).where(CandidateSave.client_save_key == payload.client_save_key)
    )
    if existing_save is not None:
        if existing_save.candidate_id != str(candidate_id):
            raise fail(409, "save_key_conflict", "Save key belongs to a different candidate")
        asset = db.get(SavedAsset, existing_save.saved_asset_id)
        if asset is None:
            raise RuntimeError("Persisted candidate save has no saved asset")
        return saved_asset_read(asset)

    candidate = db.scalar(
        select(Candidate).where(Candidate.id == str(candidate_id)).with_for_update()
    )
    if candidate is None:
        raise fail(404, "candidate_not_found", "Candidate not found")
    if candidate.media_format != "GIF" or candidate.frame_count < 2:
        raise fail(
            409, "static_save_unavailable", "Only preview/download is available for this media"
        )
    existing_save = db.scalar(
        select(CandidateSave).where(CandidateSave.client_save_key == payload.client_save_key)
    )
    if existing_save is not None:
        if existing_save.candidate_id != candidate.id:
            raise fail(409, "save_key_conflict", "Save key belongs to a different candidate")
        asset = db.get(SavedAsset, existing_save.saved_asset_id)
        if asset is None:
            raise RuntimeError("Persisted candidate save has no saved asset")
        return saved_asset_read(asset)
    job = db.get(SearchJob, candidate.job_id)
    if job is None or job.job_kind != "web" or job.status != "completed":
        raise fail(409, "candidate_not_savable", "Only completed web candidates can be saved")
    accepted_review = db.scalar(
        select(ReviewDecision).where(
            ReviewDecision.job_id == job.id,
            ReviewDecision.candidate_id == candidate.id,
            ReviewDecision.decision == "accept",
        )
    )
    if accepted_review is None:
        raise fail(409, "candidate_not_accepted", "Accept the candidate before saving it")
    stored_path = None
    if candidate.saved_asset_id is not None:
        asset = db.get(SavedAsset, candidate.saved_asset_id)
        if asset is None:
            raise RuntimeError("Candidate references a missing saved asset")
        verify_saved_asset_media(asset)
        digest = asset.sha256
    else:
        expiry = candidate.cache_expires_at.replace(tzinfo=timezone.utc)
        if expiry <= utcnow():
            raise fail(410, "media_expired", "Candidate media has expired and cannot be saved")
        try:
            data = read_verified_gif(
                candidate.local_cache_path,
                expected_sha256=candidate.media_sha256,
                expected_frame_count=candidate.frame_count,
            )
        except FileNotFoundError as exc:
            logger.error("candidate_media_missing", extra={"candidate_id": candidate.id})
            raise fail(503, "media_unavailable", "Candidate media is missing from storage") from exc
        except OSError as exc:
            logger.exception("candidate_media_read_failed", extra={"candidate_id": candidate.id})
            raise fail(503, "media_unavailable", "Candidate media could not be read") from exc
        except MediaError as exc:
            logger.exception(
                "candidate_save_validation_failed",
                extra={"candidate_id": candidate.id},
            )
            raise fail(503, "media_corrupted", "Candidate GIF failed integrity validation") from exc
        digest = sha256(data)

        asset = db.scalar(select(SavedAsset).where(SavedAsset.sha256 == digest))
        if asset is None:
            relative = f"saved/{digest}.gif"
            try:
                stored_path = atomic_write(get_settings().media_root, relative, data)
            except OSError as exc:
                logger.exception("saved_asset_storage_failed")
                raise fail(503, "storage_unavailable", "GIF could not be saved") from exc
            asset = SavedAsset(
                id=str(uuid4()),
                sha256=digest,
                title=f"{candidate.provider or 'Recovered'} GIF",
                source_url=candidate.source_url or "",
                image_url=candidate.image_url or "",
                provider=candidate.provider or "unknown",
                gif_path=relative,
                frame_count=candidate.frame_count,
                index_status="pending",
            )
            db.add(asset)
        else:
            verify_saved_asset_media(asset)

    candidate.saved_asset_id = asset.id
    db.add(
        CandidateSave(
            candidate_id=candidate.id,
            saved_asset_id=asset.id,
            client_save_key=payload.client_save_key,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_save = db.scalar(
            select(CandidateSave).where(CandidateSave.client_save_key == payload.client_save_key)
        )
        if existing_save is not None:
            if existing_save.candidate_id != str(candidate_id):
                raise fail(409, "save_key_conflict", "Save key belongs to a different candidate")
            existing_asset = db.get(SavedAsset, existing_save.saved_asset_id)
            if existing_asset is None:
                raise RuntimeError("Persisted candidate save has no saved asset")
            return saved_asset_read(existing_asset)
        existing_asset = db.scalar(select(SavedAsset).where(SavedAsset.sha256 == digest))
        existing_candidate = db.get(Candidate, str(candidate_id))
        if existing_asset is not None and existing_candidate is not None:
            existing_candidate.saved_asset_id = existing_asset.id
            db.add(
                CandidateSave(
                    candidate_id=existing_candidate.id,
                    saved_asset_id=existing_asset.id,
                    client_save_key=payload.client_save_key,
                )
            )
            try:
                db.commit()
            except SQLAlchemyError as exc:
                db.rollback()
                remove_unreferenced_saved_file(db, stored_path, digest)
                logger.exception("saved_asset_recovery_commit_failed")
                raise fail(
                    503,
                    "database_unavailable",
                    "Save recovery could not be committed",
                ) from exc
            return saved_asset_read(existing_asset)
        remove_unreferenced_saved_file(db, stored_path, digest)
        raise fail(409, "save_conflict", "Candidate was saved concurrently")
    except SQLAlchemyError as exc:
        db.rollback()
        remove_unreferenced_saved_file(db, stored_path, digest)
        logger.exception("saved_asset_commit_failed")
        raise fail(503, "database_unavailable", "Save could not be committed") from exc
    logger.info(
        "candidate_saved",
        extra={
            "candidate_id": candidate.id,
            "asset_id": asset.id,
            "index_status": asset.index_status,
        },
    )
    return saved_asset_read(asset)


@router.get("/saved-assets/{asset_id}", response_model=SavedAssetRead)
def read_saved_asset(asset_id: UUID, db: Database) -> SavedAssetRead:
    asset = db.get(SavedAsset, str(asset_id))
    if asset is None:
        raise fail(404, "saved_asset_not_found", "Saved asset not found")
    return saved_asset_read(asset)


@router.get("/saved-assets/{asset_id}/media")
def read_saved_asset_media(asset_id: UUID, db: Database) -> Response:
    asset = db.get(SavedAsset, str(asset_id))
    if asset is None:
        raise fail(404, "saved_asset_not_found", "Saved asset not found")
    data = verify_saved_asset_media(asset)
    return Response(
        content=data,
        media_type="image/gif",
        headers={
            **MEDIA_RESPONSE_HEADERS,
            "Content-Disposition": f'inline; filename="{asset.id}.gif"',
        },
    )


@router.post("/saved-assets/{asset_id}/index-retry", response_model=SavedAssetRead, status_code=202)
def retry_saved_asset_index(asset_id: UUID, db: Database) -> SavedAssetRead:
    asset = db.scalar(select(SavedAsset).where(SavedAsset.id == str(asset_id)).with_for_update())
    if asset is None:
        raise fail(404, "saved_asset_not_found", "Saved asset not found")
    if asset.index_status == "failed":
        asset.index_status = "pending"
        asset.index_error = None
        db.commit()
        logger.info("saved_asset_index_retried", extra={"asset_id": asset.id})
    return saved_asset_read(asset)


def replay_retry(
    existing: SearchJob,
    request_id: str,
    previous_job_id: str | None = None,
) -> AcceptedSearch:
    if existing.request_id != request_id or (
        previous_job_id is not None and existing.retry_of_job_id != previous_job_id
    ):
        raise fail(409, "retry_key_conflict", "Retry key belongs to a different request")
    return accepted(existing)


@router.post("/search-requests/{request_id}/retry", response_model=AcceptedSearch, status_code=202)
def retry_search(request_id: UUID, payload: RetryCreate, db: Database) -> AcceptedSearch:
    request = require_request(db, str(request_id), lock=True)
    previous = latest_local_job(db, request.id)
    existing = db.scalar(
        select(SearchJob).where(SearchJob.client_retry_key == payload.client_retry_key)
    )
    if existing is not None:
        if existing.job_kind != "local":
            raise fail(409, "retry_key_conflict", "Retry key belongs to a different job")
        return replay_retry(existing, request.id)
    return create_retry(db, request, previous, payload)


@router.post("/search-jobs/{job_id}/retry", response_model=AcceptedSearch, status_code=202)
def retry_specific_search(job_id: UUID, payload: RetryCreate, db: Database) -> AcceptedSearch:
    previous = db.scalar(select(SearchJob).where(SearchJob.id == str(job_id)).with_for_update())
    if previous is None:
        raise fail(404, "job_not_found", "Search job not found")
    request = require_request(db, previous.request_id, lock=True)
    existing = db.scalar(
        select(SearchJob).where(SearchJob.client_retry_key == payload.client_retry_key)
    )
    if existing is not None:
        return replay_retry(existing, request.id, previous.id)
    return create_retry(db, request, previous, payload)


def create_retry(
    db: Session,
    request: SearchRequest,
    previous: SearchJob,
    payload: RetryCreate,
) -> AcceptedSearch:
    if previous.status != "failed":
        raise fail(409, "retry_not_allowed", "Only a failed request can be retried")
    active = db.scalar(
        select(SearchJob).where(
            SearchJob.request_id == request.id,
            SearchJob.status.in_(["pending", "running"]),
        )
    )
    if active is not None:
        raise fail(409, "retry_already_active", "Another job is already active for this request")
    if not contained_path(get_settings().media_root, request.input_path).is_file():
        raise fail(410, "input_expired", "Input is unavailable; submit a new search")
    job = SearchJob(
        request_id=request.id,
        attempt_no=(
            db.scalar(
                select(SearchJob.attempt_no)
                .where(SearchJob.request_id == request.id)
                .order_by(SearchJob.attempt_no.desc())
                .limit(1)
            )
            or 0
        )
        + 1,
        job_kind=previous.job_kind,
        stage="pending",
        description=previous.description,
        search_profile=previous.search_profile,
        target_count=previous.target_count,
        configuration=previous.configuration,
        retry_of_job_id=previous.id,
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
            return replay_retry(existing, request.id, previous.id)
        raise fail(409, "retry_conflict", "Another retry is already active")
    logger.info("search_retried", extra={"request_id": request.id, "job_id": job.id})
    return accepted(job)
