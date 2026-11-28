from __future__ import annotations

import io
import os
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from services.api.app.meme_search import candidate_preview, draft_preview, previews
from services.api.app.search import (
    create_review,
    create_search,
    read_media,
    retry_search,
    save_candidate,
)
from services.common.config import get_settings
from services.common.db import make_session_factory
from services.common.models import utcnow
from services.common.search_models import (
    Candidate,
    MemeCandidateDraft,
    ReferenceAsset,
    ReviewDecision,
    SearchExecution,
    SearchJob,
    SearchRequest,
)
from services.common.search_schemas import RetryCreate, ReviewCreate, SaveCreate
from services.common.storage import atomic_write, sha256
from services.worker.app.meme_worker import finalize
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


def test_postgres_meme_duration_preserves_session_timezone(postgres_backend, monkeypatch):
    _, factory, _ = postgres_backend
    started = datetime(2026, 11, 28, 4, 20, tzinfo=timezone.utc)
    finished = started + timedelta(seconds=21, milliseconds=250)
    monkeypatch.setattr("services.worker.app.meme_worker.utcnow", lambda: finished)

    with factory() as db:
        request = new_request(db)
        job = SearchJob(
            request_id=request.id,
            search_profile="meme50-v2",
            job_kind="web",
            status="running",
            started_at=started,
            analysis={},
        )
        db.add(job)
        db.flush()
        job_id = job.id
        db.commit()

    with factory() as db:
        db.execute(text("SET LOCAL TIME ZONE 'Asia/Shanghai'"))
        assert db.get(SearchJob, job_id).started_at.utcoffset() == timedelta(hours=8)
        finalize(db, job_id, {"status": "completed", "candidate_keys": []})

    with factory() as db:
        assert db.get(SearchExecution, job_id).duration_ms == 21_250


def test_postgres_candidate_and_draft_expiry(postgres_backend, monkeypatch):
    _, factory, _ = postgres_backend
    now = datetime(2026, 11, 28, 4, 20, tzinfo=timezone.utc)
    expired = now - timedelta(seconds=1)
    monkeypatch.setattr("services.api.app.search.utcnow", lambda: now)
    monkeypatch.setattr("services.api.app.meme_search.utcnow", lambda: now)

    with factory() as db:
        job = SearchJob(
            request_id=new_request(db).id,
            job_kind="web",
            status="completed",
            result_kind="candidates",
            started_at=expired,
            finished_at=expired,
        )
        db.add(job)
        db.flush()
        candidate = Candidate(
            job_id=job.id,
            rank=1,
            similarity_score=0.9,
            frame_count=2,
            media_format="GIF",
            source_url="https://example.org/animation",
            local_cache_path="candidate.gif",
            cache_expires_at=expired,
        )
        drafts = [
            MemeCandidateDraft(
                job_id=job.id,
                draft_key=key,
                local_path="draft.gif",
                preview_path="draft.png",
                data={"content_group_id": key, "score": 0.9, "metadata": {}},
                expires_at=when,
            )
            for key, when in [("expired", expired), ("current", now + timedelta(seconds=1))]
        ]
        db.add_all([candidate, *drafts])
        db.commit()
        job_id, candidate_id = UUID(job.id), UUID(candidate.id)
        expired_id, current_id = (UUID(draft.id) for draft in drafts)
        create_review(
            job_id,
            ReviewCreate(candidate_id=candidate_id, decision="accept", client_review_key="review"),
            db,
        )

    with factory() as db:
        db.execute(text("SET LOCAL TIME ZONE 'Asia/Shanghai'"))
        stored_expiry = db.get(Candidate, str(candidate_id)).cache_expires_at
        assert stored_expiry.utcoffset() == timedelta(hours=8)
        for read in (read_media, candidate_preview):
            with pytest.raises(HTTPException) as error:
                read(candidate_id, db)
            assert error.value.status_code == 410 and error.value.detail["code"] == "media_expired"
        with pytest.raises(HTTPException) as error:
            save_candidate(candidate_id, SaveCreate(client_save_key="expired-save"), db)
        assert error.value.status_code == 410 and error.value.detail["code"] == "media_expired"
        with pytest.raises(HTTPException) as error:
            draft_preview(job_id, expired_id, db)
        assert error.value.status_code == 410 and error.value.detail["code"] == "preview_expired"
        assert [item["draft_id"] for item in previews(job_id, db)["items"]] == [str(current_id)]


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


def test_private_import_and_candidate_save_share_one_asset(postgres_backend):
    from services.api.app.library import Manifest, create_import, upload_item
    from services.common.search_models import SavedAsset

    _, factory, config = postgres_backend
    command.downgrade(config, "20261111_0004")
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), "green").save(
        buffer, format="GIF", save_all=True, append_images=[Image.new("RGB", (12, 12), "blue")]
    )
    legacy = buffer.getvalue()
    path = f"saved/{sha256(legacy)}.gif"
    atomic_write(get_settings().media_root, path, legacy)
    with factory() as db:
        old = SavedAsset(sha256=sha256(legacy), title="Legacy", source_url="", image_url="",
                         provider="test", gif_path=path, frame_count=2, index_status="ready")
        db.add(old)
        db.commit()
        old_id = old.id

    command.upgrade(config, "head")
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), "red").save(
        buffer, format="GIF", save_all=True, append_images=[Image.new("RGB", (12, 12), "blue")]
    )
    data = buffer.getvalue()
    atomic_write(get_settings().media_root, "candidate.gif", data)
    with factory() as db:
        assert db.get(SavedAsset, old_id).index_status == "ready"
        assert (get_settings().media_root / path).read_bytes() == legacy
        job = SearchJob(request_id=new_request(db).id, job_kind="web", status="completed",
                        result_kind="candidates", started_at=utcnow(), finished_at=utcnow())
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
        create_review(UUID(job.id), ReviewCreate(candidate_id=candidate_id, decision="accept",
                      client_review_key="library-race-review"), db)
        batches = []
        for _ in range(2):
            item_id = str(uuid4())
            batch = create_import(Manifest(client_batch_key=str(uuid4()), items=[{
                "client_item_id": item_id, "filename": "same.gif",
                "byte_size": len(data), "sha256": sha256(data),
            }]), db)
            batches.append((UUID(batch["batch_id"]), item_id))

    barrier = Barrier(3)

    def run(index):
        with factory() as db:
            barrier.wait(timeout=5)
            if index == 2:
                asset = save_candidate(candidate_id, SaveCreate(client_save_key="library-race"), db)
                return str(asset.asset_id), "saved"
            receipt = upload_item(*batches[index], db, data)
            return receipt["asset_id"], receipt["status"]

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(run, range(3)))
    assert len({asset_id for asset_id, _ in results}) == 1
    assert {status for _, status in results[:2]} <= {"imported", "duplicate"}
    with factory() as db:
        saved = db.scalar(select(SavedAsset).where(SavedAsset.sha256 == sha256(data)))
        assert saved.id == results[0][0]
        assert (get_settings().media_root / saved.gif_path).read_bytes() == data


def test_upgrade_backfills_existing_import_batches_without_changing_replay(postgres_backend):
    from services.api.app.library import Manifest, create_import
    from services.common.library_models import ImportBatch

    engine, factory, config = postgres_backend
    payload = Manifest(
        client_batch_key="legacy-replay",
        items=[{
            "client_item_id": "pending",
            "filename": "old.gif",
            "byte_size": 42,
            "sha256": "a" * 64,
        }],
    )
    with factory() as db:
        initial = create_import(payload, db)
    command.downgrade(config, "20261117_0006")
    assert "purpose" not in {
        column["name"] for column in inspect(engine).get_columns("library_import_batches")
    }
    command.upgrade(config, "head")
    with factory() as db:
        assert db.get(ImportBatch, initial["batch_id"]).purpose == "upload"
        assert create_import(payload, db) == initial


def test_account_workspaces_and_migrations(postgres_backend, monkeypatch):
    from services.common import db as database
    from test_library_accounts import verify_account_libraries

    engine, factory, config = postgres_backend
    monkeypatch.setenv("PRIVATE_LIBRARY_ENABLED", "true")
    monkeypatch.setenv("ACCOUNT_LOGIN_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(database, "_ENGINE", engine)
    monkeypatch.setattr(database, "_SESSION_FACTORY", factory)
    verify_account_libraries(engine)
    command.upgrade(config, "head")


def test_pgvector_exact_frames_rollback_and_workspace_isolation(postgres_backend, monkeypatch):
    from services.common.accounts import provision_workspace
    from services.common.config import use_workspace
    from services.common.search_models import SavedAsset
    from services.retrieval import vector_store
    from services.retrieval.saved_index import frame_numbers, identity

    engine, factory, config = postgres_backend
    with engine.connect() as conn:
        if not conn.scalar(text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")):
            pytest.skip("PostgreSQL vector extension is not installed")
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")
    get_settings.cache_clear()
    command.downgrade(config, "20261121_0008")
    command.upgrade(config, "head")
    command.check(config)

    workspace = "acct_0123456789abcdef0123456789abcdef"
    with factory() as db:
        provision_workspace(db, workspace)
        db.commit()
    scoped_url = engine.url.update_query_dict({"options": f"-csearch_path={workspace}"})
    scoped_engine = create_engine(scoped_url)
    scoped_factory = make_session_factory(scoped_engine)
    monkeypatch.setattr(vector_store, "get_session_factory", lambda: factory)
    clip_query = [1.0] + [0.0] * 511
    orthogonal = [0.0, 1.0] + [0.0] * 510

    def saved_gif(session_factory):
        gif = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(
            gif, format="GIF", save_all=True, append_images=[Image.new("RGB", (8, 8), "blue")]
        )
        data = gif.getvalue()
        digest = sha256(data)
        gif_path = f"saved/{digest}.gif"
        atomic_write(get_settings().media_root, gif_path, data)
        asset = SavedAsset(
            id=str(uuid4()),
            title="Fixture",
            source_url="",
            image_url="",
            provider="local_upload",
            sha256=digest,
            gif_path=gif_path,
            frame_count=2,
            index_status="ready",
        )
        asset.index_version = identity(asset)[1]
        with session_factory() as db:
            db.add(asset)
            db.commit()
        return asset

    try:
        asset = saved_gif(factory)
        frames = frame_numbers(asset.frame_count)
        assert vector_store.rank_saved_vectors(clip_query, 3, 0.82) is None
        assert vector_store.store_asset_vectors(
            asset, asset.index_version, frames, [orthogonal, clip_query]
        )
        exact = [{"reference_asset_id": asset.id, "score": 1.0}]
        assert vector_store.rank_saved_vectors(clip_query, 3, 0.82) == exact
        assert not vector_store.store_asset_vectors(
            asset, asset.index_version, frames, [orthogonal, [0.0] * 512]
        )
        assert vector_store.rank_saved_vectors(clip_query, 3, 0.82) == exact
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM saved_frame_vectors WHERE frame_no = 0"))
        assert vector_store.rank_saved_vectors(clip_query, 3, 0.82) is None
        assert vector_store.store_asset_vectors(
            asset, asset.index_version, frames, [orthogonal, clip_query]
        )
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE saved_vector_versions SET media_sha256 = :sha"), {"sha": "0" * 64}
            )
        assert vector_store.rank_saved_vectors(clip_query, 3, 0.82) is None

        monkeypatch.setattr(vector_store, "get_session_factory", lambda: scoped_factory)
        with use_workspace(workspace):
            assert vector_store.rank_saved_vectors(clip_query, 3, 0.82) == []
            private = saved_gif(scoped_factory)
            assert vector_store.store_asset_vectors(
                private, private.index_version, frames, [orthogonal, orthogonal]
            )
            assert vector_store.rank_saved_vectors(clip_query, 3, 0.82) == []
            assert vector_store.rank_saved_vectors(orthogonal, 3, 0.82) == [
                {"reference_asset_id": private.id, "score": 1.0}
            ]
    finally:
        scoped_engine.dispose()


def test_pgvector_reference_manifest_shared_read_and_atomic_replace(postgres_backend, monkeypatch):
    from services.common.accounts import provision_workspace
    from services.common.config import use_workspace
    from services.common.reference_assets import Manifest
    from services.retrieval import vector_store

    engine, factory, config = postgres_backend
    with engine.connect() as conn:
        if not conn.scalar(text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")):
            pytest.skip("PostgreSQL vector extension is not installed")
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")
    get_settings.cache_clear()
    command.downgrade(config, "20261121_0008")
    command.upgrade(config, "head")
    command.check(config)

    asset_id = str(uuid4())
    manifest = Manifest.model_validate({
        "corpus_version": "test-reference-v1",
        "assets": [{
            "reference_asset_id": asset_id,
            "title": "Fixture",
            "source_reference": "test",
            "permission_note": "Generated in test",
            "gif_path": "reference.gif",
            "sha256": "a" * 64,
        }],
    })
    workspace = "acct_9876543210fedcba9876543210fedcba"
    with factory() as db:
        db.add(ReferenceAsset(id=asset_id, frame_count=2, corpus_version=manifest.corpus_version,
            **manifest.assets[0].model_dump(exclude={"reference_asset_id"})))
        db.flush()
        provision_workspace(db, workspace)
        db.commit()
    scoped_url = engine.url.update_query_dict({"options": f"-csearch_path={workspace}"})
    scoped_engine = create_engine(scoped_url)
    scoped_factory = make_session_factory(scoped_engine)
    monkeypatch.setattr(vector_store, "get_session_factory", lambda: factory)
    query = [1.0] + [0.0] * 511
    orthogonal = [0.0, 1.0] + [0.0] * 510
    digest = "b" * 64
    matches = [{"reference_asset_id": asset_id, "score": 1.0}]
    frames = [0, 1]
    ids = [asset_id, asset_id]
    try:
        assert vector_store.rank_reference_vectors(query, 3, 0.82, manifest, digest) is None
        assert vector_store.mirror_reference_vectors(
            manifest, digest, ids, frames, [orthogonal, query]
        )
        assert vector_store.rank_reference_vectors(query, 3, 0.82, manifest, digest) == matches
        assert vector_store.rank_reference_vectors(query, 3, 0.82, manifest, "c" * 64) is None
        assert not vector_store.mirror_reference_vectors(
            manifest, "d" * 64, ids, frames, [orthogonal, [0.0] * 512]
        )
        assert vector_store.rank_reference_vectors(query, 3, 0.82, manifest, digest) == matches
        monkeypatch.setattr(vector_store, "get_session_factory", lambda: scoped_factory)
        with use_workspace(workspace):
            assert vector_store.rank_reference_vectors(query, 3, 0.82, manifest, digest) == matches
            assert not vector_store.mirror_reference_vectors(
                manifest, digest, ids, frames, [query, query]
            )
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM public.reference_frame_vectors WHERE frame_no = 0"))
        assert vector_store.rank_reference_vectors(query, 3, 0.82, manifest, digest) is None
    finally:
        scoped_engine.dispose()
