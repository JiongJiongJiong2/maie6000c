"""Stable job-bound pagination and previews for verified meme50 media."""

import base64
import json
from datetime import timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select

from services.common.config import get_settings
from services.common.media import inspect_media, preview_bytes
from services.common.models import utcnow
from services.common.search_models import Candidate, MemeCandidateDraft, SearchExecution, SearchJob
from services.common.storage import MediaError, contained_path
from .search import Database, MEDIA_RESPONSE_HEADERS, authorize, candidates_for_job, fail

router = APIRouter(dependencies=[Depends(authorize)])


def require_job(db, job_id):
    job = db.get(SearchJob, str(job_id))
    if not job:
        raise fail(404, "job_not_found", "Search job not found")
    return job


def summary(db, job):
    execution = db.get(SearchExecution, job.id)
    return dict(
        request_id=job.request_id,
        job_id=job.id,
        status=job.status,
        job_kind=job.job_kind,
        search_profile=job.search_profile,
        contract_version=2 if job.search_profile == "meme50-v2" else 1,
        target_count=job.target_count,
        stage=job.stage,
        configuration=job.configuration,
        execution=(
            dict(
                model_version=execution.model_version,
                search_calls=execution.search_calls,
                model_calls=execution.planner_calls,
                downloads_used=execution.downloads_used,
                duration_ms=execution.duration_ms,
                trace=execution.trace,
            )
            if execution
            else None
        ),
        analysis=job.analysis,
        progress=job.progress,
        verified_count=job.progress.get("verified_count", 0),
        result_count=job.result_count,
        result_kind=job.result_kind,
        result_revision=job.result_revision,
        partial=job.partial,
        stop_reason=execution.stop_reason if execution else None,
        warnings=execution.warnings if execution else [],
        error={"code": job.error_code, "message": job.error_detail} if job.error_code else None,
    )


@router.get("/search-jobs/{job_id}")
def read_job(job_id: UUID, db: Database):
    return summary(db, require_job(db, job_id))


def verified_candidate_bytes(candidate):
    path = contained_path(get_settings().media_root, candidate.local_cache_path)
    with path.open("rb") as f:
        data = f.read(min(get_settings().max_candidate_bytes, 12 * 1024 * 1024) + 1)
    metadata = inspect_media(data)
    if (
        candidate.media_sha256
        and metadata.sha256 != candidate.media_sha256
        or metadata.frame_count != candidate.frame_count
        or metadata.format != candidate.media_format
        or metadata.mime_type != candidate.mime_type
        or metadata.media_kind != candidate.media_kind
    ):
        raise MediaError("Candidate integrity metadata differs")
    return data


@router.get("/candidates/{candidate_id}/preview")
def candidate_preview(candidate_id: UUID, db: Database):
    row = db.get(Candidate, str(candidate_id))
    if not row:
        raise fail(404, "candidate_not_found", "Candidate not found")
    if row.cache_expires_at.replace(tzinfo=timezone.utc) <= utcnow() and not row.saved_asset_id:
        raise fail(410, "media_expired", "Preview expired")
    try:
        if row.preview_path:
            data = contained_path(get_settings().media_root, row.preview_path).read_bytes()
            meta = inspect_media(data)
            if meta.format != "PNG" or meta.frame_count != 1 or max(meta.width, meta.height) > 384:
                raise MediaError("Invalid preview")
        else:
            data = preview_bytes(verified_candidate_bytes(row))
    except (OSError, ValueError):
        raise fail(503, "media_corrupted", "Preview is unavailable") from None
    return Response(data, media_type="image/png", headers=MEDIA_RESPONSE_HEADERS)


@router.get("/search-jobs/{job_id}/previews")
def previews(job_id: UUID, db: Database):
    job = require_job(db, job_id)
    by_group = {}
    for draft in db.scalars(
        select(MemeCandidateDraft)
        .where(MemeCandidateDraft.job_id == job.id)
        .order_by(MemeCandidateDraft.created_at)
    ):
        if draft.expires_at.replace(tzinfo=timezone.utc) > utcnow():
            by_group[draft.data["content_group_id"]] = draft
    items = []
    for draft in sorted(by_group.values(), key=lambda d: -d.data["score"])[:50]:
        items.append(
            dict(
                draft_id=draft.id,
                preview_url=f"/search-jobs/{job.id}/previews/{draft.id}/media",
                metadata=draft.data["metadata"],
                score=draft.data["score"],
                provisional=True,
            )
        )
    return dict(
        job_id=job.id,
        status=job.status,
        provisional=True,
        items=items,
        verified_count=len(by_group),
        progress=job.progress,
    )


@router.get("/search-jobs/{job_id}/previews/{draft_id}/media")
def draft_preview(job_id: UUID, draft_id: UUID, db: Database):
    require_job(db, job_id)
    draft = db.get(MemeCandidateDraft, str(draft_id))
    if not draft or draft.job_id != str(job_id):
        raise fail(404, "draft_not_found", "Preview not found")
    if draft.expires_at.replace(tzinfo=timezone.utc) <= utcnow():
        raise fail(410, "preview_expired", "Preview expired")
    try:
        data = contained_path(get_settings().media_root, draft.preview_path).read_bytes()
        meta = inspect_media(data)
        if meta.format != "PNG" or meta.frame_count != 1 or max(meta.width, meta.height) > 384:
            raise MediaError("Invalid preview")
    except (OSError, ValueError):
        raise fail(503, "preview_corrupted", "Preview unavailable") from None
    return Response(data, media_type="image/png", headers=MEDIA_RESPONSE_HEADERS)


@router.get("/search-jobs/{job_id}/results")
def results(
    job_id: UUID,
    db: Database,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    media_kind: str = Query(default="all", pattern="^(all|static|animated)$"),
    revision: str | None = None,
):
    job = require_job(db, job_id)
    if job.status != "completed":
        raise fail(409, "results_not_final", "Final results are not published")
    actual = job.result_revision or "legacy"
    if revision is not None and revision != actual:
        raise fail(409, "revision_conflict", "Result revision changed")
    offset = 0
    if cursor:
        try:
            if len(cursor) > 1024:
                raise ValueError
            c = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if (c.get("j"), c.get("r"), c.get("k"), c.get("l")) != (
                str(job_id),
                actual,
                media_kind,
                limit,
            ):
                raise ValueError
            offset = c["o"]
            if type(offset) is not int or not 0 <= offset <= 50:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise fail(422, "invalid_cursor", "Cursor belongs to another result/filter") from None
    all_items = candidates_for_job(db, str(job_id))
    counts = {kind: sum(c.media_kind == kind for c in all_items) for kind in ["static", "animated"]}
    filtered = [c for c in all_items if media_kind == "all" or c.media_kind == media_kind]
    page = filtered[offset : offset + limit]
    next_cursor = None
    if offset + limit < len(filtered):
        value = dict(j=str(job_id), r=actual, k=media_kind, l=limit, o=offset + limit)
        next_cursor = (
            base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
            .decode()
            .rstrip("=")
        )
    return dict(
        job_id=job.id,
        search_profile=job.search_profile,
        contract_version=2 if job.search_profile == "meme50-v2" else 1,
        revision=actual,
        media_kind=media_kind,
        total=len(filtered),
        total_all=len(all_items),
        counts=counts,
        items=[item.model_dump(mode="json") for item in page],
        next_cursor=next_cursor,
        partial=job.partial,
        stop_reason=(
            db.get(SearchExecution, job.id).stop_reason if db.get(SearchExecution, job.id) else None
        ),
    )
