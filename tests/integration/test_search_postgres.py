from __future__ import annotations

import io
import os
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import UploadFile
from PIL import Image
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from services.api.app.search import create_review, create_search, retry_search, save_candidate
from services.common.config import get_settings
from services.common.db import make_session_factory
from services.common.models import utcnow
from services.common.search_models import (
    Candidate,
    ReferenceAsset,
    ReviewDecision,
    SearchJob,
    SearchRequest,
)
from services.common.search_schemas import RetryCreate, ReviewCreate, SaveCreate
from services.common.storage import atomic_write, sha256
from services.worker.app.search_worker import claim_next_search_job


@pytest.fixture()
def postgres_backend(monkeypatch):
    base_url = os.environ.get("TEST_POSTGRES_URL")
    if not base_url:
        pytest.skip("Set TEST_POSTGRES_URL to a disposable PostgreSQL admin connection")
    name = f"backend_test_{uuid4().hex}"
    url = make_url(base_url).set(database=name)
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url)
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "error",
            category=DeprecationWarning,
            module=r"alembic\.config",
        )
        try:
            command.upgrade(config, "head")
            yield engine, make_session_factory(engine), config
        finally:
            engine.dispose()
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
            admin.dispose()
            get_settings.cache_clear()


def new_request(db) -> SearchRequest:
    request = SearchRequest(
        client_submission_key=str(uuid4()),
        input_path="inputs/test.png",
        input_sha256="a" * 64,
    )
    db.add(request)
    db.flush()
    return request


def test_postgres_migration_round_trip_and_metadata(postgres_backend):
    engine, _, config = postgres_backend
    expected = {
        "reference_assets",
        "search_requests",
        "search_jobs",
        "candidates",
        "review_decisions",
    }
    assert expected <= set(inspect(engine).get_table_names())
    command.check(config)
    command.downgrade(config, "20260713_0001")
    assert not expected.intersection(inspect(engine).get_table_names())
    assert {"cases", "jobs"} <= set(inspect(engine).get_table_names())
    command.upgrade(config, "head")
    command.check(config)


def test_concurrent_submission_and_retry_keys(postgres_backend):
    _, factory, _ = postgres_backend
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, "PNG")
    content = buffer.getvalue()
    barrier = Barrier(8)

    def submit(_):
        with factory() as db:
            barrier.wait(timeout=20)
            return create_search(
                db=db,
                client_submission_key="concurrent-upload",
                image=UploadFile(io.BytesIO(content), filename="crop.png"),
            )

    with ThreadPoolExecutor(max_workers=8) as executor:
        submissions = list(executor.map(submit, range(8)))
    assert len({response.job_id for response in submissions}) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(SearchRequest)) == 1
        job = db.get(SearchJob, str(submissions[0].job_id))
        job.started_at = utcnow()
        job.status = "failed"
        job.error_code = "test_failure"
        job.error_detail = "Test failure"
        job.finished_at = utcnow()
        db.commit()

    barrier = Barrier(8)

    def retry(_):
        with factory() as db:
            barrier.wait(timeout=20)
            return retry_search(
                submissions[0].request_id,
                RetryCreate(client_retry_key="retry"),
                db,
            )

    with ThreadPoolExecutor(max_workers=8) as executor:
        retries = list(executor.map(retry, range(8)))
    assert len({response.job_id for response in retries}) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(SearchJob)) == 2
        assert db.scalar(select(SearchJob).where(SearchJob.status == "pending")).attempt_no == 2

    with factory() as db:
        review_request = new_request(db)
        review_job = SearchJob(
            request_id=review_request.id,
            status="completed",
            result_kind="no_candidates",
            started_at=utcnow(),
            finished_at=utcnow(),
        )
        db.add(review_job)
        db.commit()
        completed_job_id = review_job.id

    barrier = Barrier(8)

    def review(_):
        with factory() as db:
            barrier.wait(timeout=20)
            return create_review(
                job_id=UUID(completed_job_id),
                payload=ReviewCreate(
                    decision="reject_all",
                    client_review_key="concurrent-review",
                ),
                db=db,
            )

    with ThreadPoolExecutor(max_workers=8) as executor:
        reviews = list(executor.map(review, range(8)))
    assert len({response.review_id for response in reviews}) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ReviewDecision)) == 1


def test_atomic_claim_skips_locked_job(postgres_backend):
    _, factory, _ = postgres_backend
    with factory() as db:
        first = SearchJob(request_id=new_request(db).id)
        second = SearchJob(request_id=new_request(db).id)
        db.add_all([first, second])
        db.commit()
        first_id, second_id = first.id, second.id
    with factory() as owner, factory() as competitor:
        owner.execute(select(SearchJob).where(SearchJob.id == first_id).with_for_update())
        claimed = claim_next_search_job(competitor)
        assert claimed is not None
        assert claimed.id == second_id
    with factory() as db:
        claimed = claim_next_search_job(db)
        assert claimed is not None
        assert claimed.id == first_id
        assert claim_next_search_job(db) is None


def test_database_constraints_reject_invalid_states_and_cross_job_review(postgres_backend):
    _, factory, _ = postgres_backend
    with factory() as db:
        request = new_request(db)
        job = SearchJob(request_id=request.id)
        db.add(job)
        db.commit()
        request_id, job_id = request.id, job.id
        db.add(SearchJob(request_id=request_id, attempt_no=2))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        job = db.get(SearchJob, job_id)
        assert job is not None
        job.status = "completed"
        job.started_at = utcnow()
        job.finished_at = utcnow()
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        job = db.get(SearchJob, job_id)
        assert job is not None
        job.status = "running"
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        job = db.get(SearchJob, job_id)
        assert job is not None
        job.status = "failed"
        job.error_code = "interrupted"
        job.error_detail = "Test interrupted"
        job.started_at = utcnow()
        job.finished_at = job.started_at - timedelta(seconds=1)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        job = db.get(SearchJob, job_id)
        assert job is not None
        job.status = "failed"
        job.error_code = "interrupted"
        job.error_detail = "Test interrupted"
        job.started_at = utcnow()
        job.finished_at = utcnow()
        db.commit()
        other = SearchJob(request_id=new_request(db).id)
        asset = ReferenceAsset(
            id=str(uuid4()),
            sha256="a" * 64,
            title="Test",
            source_reference="test",
            permission_note="Generated in test",
            gif_path="test.gif",
            frame_count=2,
            corpus_version="test",
        )
        db.add_all([other, asset])
        db.commit()
        candidate = Candidate(
            job_id=job_id,
            reference_asset_id=asset.id,
            rank=1,
            similarity_score=float("inf"),
            local_cache_path="test.gif",
            frame_count=2,
            cache_expires_at=utcnow(),
        )
        db.add(candidate)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        candidate = Candidate(
            job_id=job_id,
            reference_asset_id=asset.id,
            rank=1,
            similarity_score=0.9,
            local_cache_path="test.gif",
            frame_count=2,
            cache_expires_at=utcnow(),
        )
        db.add(candidate)
        db.flush()
        db.add(
            ReviewDecision(
                job_id=other.id,
                candidate_id=candidate.id,
                decision="accept",
                client_review_key="cross-job",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_meme50_upgrade_preserves_old_review_fk_and_accepts_fifty_static(postgres_backend):
    engine, factory, config = postgres_backend
    # Seed real legacy candidate and composite review FK before the new upgrade.
    with factory() as db:
        request = new_request(db)
        job = SearchJob(
            request_id=request.id,
            status="completed",
            result_kind="candidates",
            started_at=utcnow(),
            finished_at=utcnow(),
        )
        db.add(job)
        db.flush()
        candidate = Candidate(
            job_id=job.id,
            rank=1,
            similarity_score=0.8,
            source_url="https://example.org/legacy",
            local_cache_path="legacy.gif",
            frame_count=2,
            media_sha256="a" * 64,
            cache_expires_at=utcnow() + timedelta(days=1),
        )
        db.add(candidate)
        db.flush()
        review = ReviewDecision(
            job_id=job.id,
            candidate_id=candidate.id,
            decision="accept",
            client_review_key=str(uuid4()),
        )
        db.add(review)
        db.commit()
        job_id, candidate_id, review_id = job.id, candidate.id, review.id
    command.downgrade(config, "20261109_0003")
    command.upgrade(config, "head")
    with factory() as db:
        assert db.get(Candidate, candidate_id).media_sha256 == "a" * 64
        assert db.get(Candidate, candidate_id).media_kind == "animated"
        assert db.get(ReviewDecision, review_id).candidate_id == candidate_id
        assert db.get(SearchJob, job_id).result_count == 1
        request = new_request(db)
        request.search_profile = "meme50-v2"
        job = SearchJob(
            request_id=request.id, search_profile="meme50-v2", job_kind="web", target_count=50
        )
        db.add(job)
        db.flush()
        for rank in range(1, 51):
            db.add(
                Candidate(
                    job_id=job.id,
                    rank=rank,
                    similarity_score=0.7,
                    source_url=f"https://example.org/{rank}",
                    local_cache_path=f"{rank}.png",
                    frame_count=1,
                    media_format="PNG",
                    mime_type="image/png",
                    media_kind="static",
                    content_group_id=str(rank),
                    cache_expires_at=utcnow() + timedelta(days=1),
                )
            )
        db.commit()
        assert (
            db.scalar(select(func.count()).select_from(Candidate).where(Candidate.job_id == job.id))
            == 50
        )
    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        command.downgrade(config, "20261109_0003")
    assert "meme_candidate_drafts" in inspect(engine).get_table_names()
    command.check(config)


def test_save_first_gif_and_replay_with_immediate_foreign_keys(postgres_backend):
    _, factory, _ = postgres_backend
    gif = io.BytesIO()
    Image.new("RGB", (12, 12), "red").save(
        gif, format="GIF", save_all=True, append_images=[Image.new("RGB", (12, 12), "blue")]
    )
    data = gif.getvalue()
    atomic_write(get_settings().media_root, "candidate.gif", data)
    with factory() as db:
        job = SearchJob(
            request_id=new_request(db).id, job_kind="web",
            status="completed", result_kind="candidates",
            started_at=utcnow(), finished_at=utcnow(),
        )
        db.add(job)
        db.flush()
        candidate = Candidate(
            job_id=job.id, rank=1, similarity_score=0.95, frame_count=2,
            source_url="https://example.org/gif", local_cache_path="candidate.gif",
            media_sha256=sha256(data), cache_expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(candidate)
        db.commit()
        candidate_id = UUID(candidate.id)
        create_review(
            UUID(job.id),
            ReviewCreate(candidate_id=candidate_id, decision="accept", client_review_key="review"),
            db,
        )
        payload = SaveCreate(client_save_key="save")
        saved = save_candidate(candidate_id, payload, db)
        assert saved.index_status == "pending"
        assert save_candidate(candidate_id, payload, db).asset_id == saved.asset_id
        assert db.get(Candidate, str(candidate_id)).saved_asset_id == str(saved.asset_id)
