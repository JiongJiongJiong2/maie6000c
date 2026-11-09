from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from services.common.db import Base
from services.common.models import utcnow


def new_id() -> str:
    return str(uuid.uuid4())


class ReferenceAsset(Base):
    __tablename__ = "reference_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    source_reference: Mapped[str] = mapped_column(Text)
    permission_note: Mapped[str] = mapped_column(Text)
    gif_path: Mapped[str] = mapped_column(Text)
    frame_count: Mapped[int] = mapped_column(Integer)
    corpus_version: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (CheckConstraint("frame_count > 1", name="ck_reference_animated"),)


class SearchRequest(Base):
    __tablename__ = "search_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    client_submission_key: Mapped[str] = mapped_column(String(128), unique=True)
    client_item_id: Mapped[str | None] = mapped_column(String(128))
    input_path: Mapped[str] = mapped_column(Text)
    input_sha256: Mapped[str] = mapped_column(String(64))
    user_keywords: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchJob(Base):
    __tablename__ = "search_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("search_requests.id"))
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    job_kind: Mapped[str] = mapped_column(String(20), default="local")
    stage: Mapped[str] = mapped_column(String(30), default="pending")
    description: Mapped[str | None] = mapped_column(String(500))
    client_search_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    retry_of_job_id: Mapped[str | None] = mapped_column(ForeignKey("search_jobs.id"))
    client_retry_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    result_kind: Mapped[str | None] = mapped_column(String(20))
    model_version: Mapped[str | None] = mapped_column(String(100))
    corpus_version: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_detail: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("request_id", "attempt_no", name="uq_search_attempt"),
        CheckConstraint("attempt_no > 0", name="ck_search_attempt"),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND result_kind IS NULL "
            "AND error_code IS NULL AND error_detail IS NULL AND finished_at IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND result_kind IS NULL "
            "AND error_code IS NULL AND error_detail IS NULL AND finished_at IS NULL) OR "
            "(status = 'completed' AND result_kind IS NOT NULL "
            "AND result_kind IN ('candidates', 'no_candidates') "
            "AND error_code IS NULL AND error_detail IS NULL "
            "AND started_at IS NOT NULL AND finished_at IS NOT NULL "
            "AND started_at <= finished_at) OR "
            "(status = 'failed' AND result_kind IS NULL AND error_code IS NOT NULL "
            "AND error_detail IS NOT NULL AND started_at IS NOT NULL "
            "AND finished_at IS NOT NULL AND started_at <= finished_at)",
            name="ck_search_state",
        ),
        Index(
            "uq_search_active_request",
            "request_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
            sqlite_where=text("status IN ('pending', 'running')"),
        ),
        Index("ix_search_jobs_queue", "status", "created_at"),
    )


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("search_jobs.id"))
    reference_asset_id: Mapped[str | None] = mapped_column(ForeignKey("reference_assets.id"))
    saved_asset_id: Mapped[str | None] = mapped_column(ForeignKey("saved_assets.id"))
    rank: Mapped[int] = mapped_column(Integer)
    similarity_score: Mapped[float] = mapped_column(Float)
    media_sha256: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(50))
    local_cache_path: Mapped[str] = mapped_column(Text)
    frame_count: Mapped[int] = mapped_column(Integer)
    cache_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("job_id", "rank", name="uq_candidate_rank"),
        UniqueConstraint("id", "job_id", name="uq_candidate_membership"),
        CheckConstraint("rank BETWEEN 1 AND 3", name="ck_candidate_rank"),
        CheckConstraint("frame_count > 1", name="ck_candidate_animated"),
        CheckConstraint(
            "(reference_asset_id IS NOT NULL AND source_url IS NULL) OR "
            "(reference_asset_id IS NULL AND source_url IS NOT NULL)",
            name="ck_candidate_origin",
        ),
        CheckConstraint(
            "abs(similarity_score) < 1.0e308",
            name="ck_candidate_score_finite",
        ),
    )


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("search_jobs.id"), index=True)
    candidate_id: Mapped[str | None] = mapped_column(String(36))
    client_review_key: Mapped[str] = mapped_column(String(128), unique=True)
    decision: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "job_id"],
            ["candidates.id", "candidates.job_id"],
            name="fk_review_candidate_job",
        ),
        CheckConstraint(
            "(decision = 'accept' AND candidate_id IS NOT NULL) OR "
            "(decision = 'reject_all' AND candidate_id IS NULL)",
            name="ck_review_decision",
        ),
    )


class SearchExecution(Base):
    __tablename__ = "search_executions"

    job_id: Mapped[str] = mapped_column(ForeignKey("search_jobs.id"), primary_key=True)
    agent_version: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(100))
    stop_reason: Mapped[str] = mapped_column(String(100))
    search_calls: Mapped[int] = mapped_column(Integer)
    planner_calls: Mapped[int] = mapped_column(Integer)
    downloads_used: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    trace: Mapped[list[dict]] = mapped_column(JSON)
    warnings: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SavedAsset(Base):
    __tablename__ = "saved_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(Text)
    image_url: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(50))
    gif_path: Mapped[str] = mapped_column(Text)
    frame_count: Mapped[int] = mapped_column(Integer)
    index_status: Mapped[str] = mapped_column(String(20), default="pending")
    index_version: Mapped[str | None] = mapped_column(String(100))
    index_error: Mapped[str | None] = mapped_column(String(1000))
    index_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("frame_count > 1", name="ck_saved_asset_animated"),
        CheckConstraint(
            "index_status IN ('pending', 'running', 'ready', 'failed')",
            name="ck_saved_asset_index_status",
        ),
        CheckConstraint("index_attempts >= 0", name="ck_saved_asset_index_attempts"),
        Index(
            "ix_saved_assets_index_queue",
            "index_status",
            "created_at",
            postgresql_where=text("index_status = 'pending'"),
            sqlite_where=text("index_status = 'pending'"),
        ),
    )


class CandidateSave(Base):
    __tablename__ = "candidate_saves"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"))
    saved_asset_id: Mapped[str] = mapped_column(ForeignKey("saved_assets.id"))
    client_save_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("candidate_id", "client_save_key"),)
