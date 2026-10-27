from __future__ import annotations

import io
import os
import subprocess
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

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
from services.common.search_schemas import RetrievalMatch, RetrievalResult
from services.common.storage import atomic_write, prepare_storage, sha256
from services.worker.app import search_worker


def image_bytes(color: str = "red", *, gif: bool = False) -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (8, 8), color=color)
    if gif:
        image.save(
            output,
            format="GIF",
            save_all=True,
            append_images=[Image.new("RGB", (8, 8), color="blue")],
            duration=100,
            loop=0,
        )
    else:
        image.save(output, format="PNG")
    return output.getvalue()


def submit(client, key: str = "submission", color: str = "red"):
    return client.post(
        "/search-requests",
        data={"client_submission_key": key},
        files={"image": ("crop.png", image_bytes(color), "image/png")},
    )


@pytest.fixture()
def worker_factory(db_session, monkeypatch):
    factory = make_session_factory(db_session.get_bind())
    monkeypatch.setattr(search_worker, "get_session_factory", lambda: factory)
    return factory


def complete(client, db_session, worker_factory, *, key="submission", matches=True):
    response = submit(client, key)
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    with worker_factory() as db:
        claimed = search_worker.claim_next_search_job(db)
        assert claimed is not None
        assert claimed.id == job_id
    asset_id = str(uuid4())
    if matches:
        prepare_storage()
        data = image_bytes(gif=True)
        atomic_write(get_settings().reference_root, f"{asset_id}.gif", data)
        db_session.add(
            ReferenceAsset(
                id=asset_id,
                sha256=sha256(data),
                title="Test animation",
                source_reference="test-generated",
                permission_note="Generated in test",
                gif_path=f"{asset_id}.gif",
                frame_count=2,
                corpus_version="test-corpus",
            )
        )
        db_session.commit()
    result = RetrievalResult(
        matches=[RetrievalMatch(reference_asset_id=UUID(asset_id), score=0.9)] if matches else [],
        model_version="test-model",
        corpus_version="test-corpus",
    )
    search_worker.process_search_job(job_id, lambda _: result)
    db_session.expire_all()
    return client.get(f"/search-requests/{response.json()['request_id']}").json()


def test_submission_contract_idempotency_and_conflict(client, db_session):
    first = submit(client)
    assert first.status_code == 202
    assert set(first.json()) == {"request_id", "job_id", "status"}
    assert first.json()["status"] == "pending"
    assert submit(client).json() == first.json()
    assert submit(client, color="green").status_code == 409
    changed_keywords = client.post(
        "/search-requests",
        data={"client_submission_key": "submission", "user_keywords": "changed"},
        files={"image": ("crop.png", image_bytes(), "image/png")},
    )
    assert changed_keywords.status_code == 409
    assert db_session.scalar(select(func.count()).select_from(SearchJob)) == 1
    assert len(list((get_settings().media_root / "inputs").iterdir())) == 1
    state = client.get(f"/search-requests/{first.json()['request_id']}").json()
    assert state == {**first.json(), "result_kind": None, "candidates": [], "error": None}


@pytest.mark.parametrize("data", [b"", b"not an image", image_bytes()[:30], image_bytes(gif=True)])
def test_invalid_image_rejected(client, data):
    response = client.post(
        "/search-requests",
        data={"client_submission_key": "invalid"},
        files={"image": ("crop.png", data, "image/png")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_image"


def test_upload_byte_limit_exact_threshold(client, monkeypatch):
    data = image_bytes()
    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(len(data)))
    get_settings.cache_clear()
    assert submit(client).status_code == 202
    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(len(data) - 1))
    get_settings.cache_clear()
    assert submit(client, key="oversized").status_code == 413


def test_failed_commit_cleanup_failure_is_logged_and_recovered(
    client, db_session, monkeypatch, caplog
):
    def broken_commit():
        raise OperationalError("commit", {}, RuntimeError("database down"))

    original_unlink = Path.unlink

    def fail_upload_cleanup(path, *args, **kwargs):
        if path.suffix == ".image":
            raise PermissionError("test cleanup failure")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as cleanup_patch:
        cleanup_patch.setattr(db_session, "commit", broken_commit)
        cleanup_patch.setattr(Path, "unlink", fail_upload_cleanup)
        response = submit(client)
    assert response.status_code == 503
    stored = list((get_settings().media_root / "inputs").iterdir())
    assert len(stored) == 1
    assert stored[0].exists()
    assert any(
        record.getMessage() == "stored_file_cleanup_failed" and record.storage_class == "input"
        for record in caplog.records
    )
    old = (utcnow() - timedelta(days=2)).timestamp()
    os.utime(stored[0], (old, old))
    search_worker.cleanup_media(db_session)
    assert not stored[0].exists()


def test_completed_candidates_media_and_review(client, db_session, worker_factory):
    state = complete(client, db_session, worker_factory)
    assert state["status"] == "completed"
    assert state["result_kind"] == "candidates"
    assert state["error"] is None
    assert len(state["candidates"]) == 1
    candidate = state["candidates"][0]
    assert set(candidate) == {"candidate_id", "rank", "score", "media_url"}
    media = client.get(candidate["media_url"])
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/gif"
    with Image.open(io.BytesIO(media.content)) as gif:
        assert getattr(gif, "n_frames", 1) == 2
    payload = {
        "decision": "accept",
        "candidate_id": candidate["candidate_id"],
        "client_review_key": "review",
    }
    route = f"/search-jobs/{state['job_id']}/reviews"
    review = client.post(route, json=payload)
    assert review.status_code == 201
    assert client.post(route, json=payload).json() == review.json()
    assert (
        client.post(
            route,
            json={
                "decision": "reject_all",
                "candidate_id": None,
                "client_review_key": "review",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            route,
            json={
                "decision": "reject_all",
                "candidate_id": None,
                "client_review_key": "correction",
            },
        ).status_code
        == 201
    )
    assert db_session.scalar(select(func.count()).select_from(ReviewDecision)) == 2
    assert (
        client.post(
            f"/search-requests/{state['request_id']}/retry",
            json={"client_retry_key": "not-failed"},
        ).status_code
        == 409
    )


def test_no_candidates_is_completed_not_failed(client, db_session, worker_factory):
    state = complete(client, db_session, worker_factory, matches=False)
    assert state["status"] == "completed"
    assert state["result_kind"] == "no_candidates"
    assert state["candidates"] == []
    assert state["error"] is None


@pytest.mark.parametrize(
    "decision,candidate",
    [
        ("accept", None),
        ("reject_all", str(uuid4())),
        ("unknown", None),
    ],
)
def test_review_payload_validation(client, decision, candidate):
    response = client.post(
        f"/search-jobs/{uuid4()}/reviews",
        json={
            "decision": decision,
            "candidate_id": candidate,
            "client_review_key": "review",
        },
    )
    assert response.status_code == 422


def test_review_must_reference_same_completed_job(client, db_session, worker_factory):
    first = complete(client, db_session, worker_factory)
    second = complete(client, db_session, worker_factory, key="other", matches=False)
    assert (
        client.post(
            f"/search-jobs/{second['job_id']}/reviews",
            json={
                "decision": "accept",
                "candidate_id": first["candidates"][0]["candidate_id"],
                "client_review_key": "wrong-job",
            },
        ).status_code
        == 422
    )
    pending = submit(client, key="pending").json()
    assert (
        client.post(
            f"/search-jobs/{pending['job_id']}/reviews",
            json={
                "decision": "reject_all",
                "client_review_key": "pending-review",
            },
        ).status_code
        == 409
    )


def test_restart_recovery_and_retry_preserve_history(client, db_session, worker_factory):
    first = submit(client).json()
    with worker_factory() as db:
        claimed = search_worker.claim_next_search_job(db)
        assert claimed is not None
        assert claimed.id == first["job_id"]
        assert search_worker.claim_next_search_job(db) is None
        assert search_worker.recover_interrupted_jobs(db) == 1
        assert search_worker.recover_interrupted_jobs(db) == 0
    state = client.get(f"/search-requests/{first['request_id']}").json()
    assert state["error"]["code"] == "worker_interrupted"
    route = f"/search-requests/{first['request_id']}/retry"
    retry = client.post(route, json={"client_retry_key": "retry"})
    assert retry.status_code == 202
    assert retry.json()["job_id"] != first["job_id"]
    assert client.post(route, json={"client_retry_key": "retry"}).json() == retry.json()
    assert client.post(route, json={"client_retry_key": "another-retry"}).status_code == 409
    assert submit(client).json()["job_id"] == first["job_id"]
    db_session.expire_all()
    assert db_session.get(SearchJob, first["job_id"]).status == "failed"
    assert (
        client.get(f"/search-requests/{first['request_id']}").json()["job_id"]
        == (retry.json()["job_id"])
    )


def test_expiry_keeps_metadata_and_active_files(client, db_session, worker_factory):
    state = complete(client, db_session, worker_factory)
    candidate = db_session.get(Candidate, state["candidates"][0]["candidate_id"])
    candidate.cache_expires_at = utcnow() - timedelta(seconds=1)
    job = db_session.get(SearchJob, state["job_id"])
    job.started_at = utcnow() - timedelta(days=9)
    job.finished_at = utcnow() - timedelta(days=8)
    request = db_session.get(SearchRequest, state["request_id"])
    request.created_at = utcnow() - timedelta(days=8)
    db_session.commit()
    active = submit(client, key="active").json()
    active_request = db_session.get(SearchRequest, active["request_id"])
    active_request.created_at = utcnow() - timedelta(days=8)
    db_session.commit()
    prepare_storage()
    orphan = atomic_write(get_settings().media_root, "inputs/orphan.image", b"orphan")
    old = (utcnow() - timedelta(days=2)).timestamp()
    os.utime(orphan, (old, old))
    search_worker.cleanup_media(db_session)
    assert not orphan.exists()
    assert not (get_settings().media_root / candidate.local_cache_path).exists()
    assert not (get_settings().media_root / request.input_path).exists()
    assert (get_settings().media_root / active_request.input_path).exists()
    assert client.get(state["candidates"][0]["media_url"]).status_code == 410
    assert client.get(f"/search-requests/{state['request_id']}").json()["status"] == "completed"


def test_cleanup_continues_after_one_file_cannot_be_removed(
    client,
    db_session,
    worker_factory,
    monkeypatch,
    caplog,
):
    state = complete(client, db_session, worker_factory)
    candidate = db_session.get(Candidate, state["candidates"][0]["candidate_id"])
    candidate.cache_expires_at = utcnow() - timedelta(seconds=1)
    request = db_session.get(SearchRequest, state["request_id"])
    request.created_at = utcnow() - timedelta(days=8)
    job = db_session.get(SearchJob, state["job_id"])
    job.started_at = utcnow() - timedelta(days=9)
    job.finished_at = utcnow() - timedelta(days=8)
    db_session.commit()

    media_root = get_settings().media_root
    candidate_path = media_root / candidate.local_cache_path
    input_path = media_root / request.input_path
    original_unlink = Path.unlink

    def fail_candidate_cleanup(path, *args, **kwargs):
        if path == candidate_path:
            raise PermissionError("test cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_candidate_cleanup)
    search_worker.cleanup_media(db_session)

    assert candidate_path.exists()
    assert not input_path.exists()
    assert any(
        record.getMessage() == "stored_file_cleanup_failed"
        and record.storage_class == "candidate"
        for record in caplog.records
    )

    monkeypatch.setattr(Path, "unlink", original_unlink)
    search_worker.cleanup_media(db_session)
    assert not candidate_path.exists()


def test_orphan_cleanup_continues_after_one_file_cannot_be_removed(
    db_session,
    monkeypatch,
    caplog,
):
    prepare_storage()
    media_root = get_settings().media_root
    orphan_input = atomic_write(media_root, "inputs/orphan.image", b"orphan input")
    orphan_candidate = atomic_write(
        media_root,
        "candidates/orphan/orphan.gif",
        b"orphan candidate",
    )
    old = (utcnow() - timedelta(days=2)).timestamp()
    os.utime(orphan_input, (old, old))
    os.utime(orphan_candidate, (old, old))
    original_unlink = Path.unlink

    def fail_orphan_input_cleanup(path, *args, **kwargs):
        if path == orphan_input:
            raise PermissionError("test orphan cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_orphan_input_cleanup)
    search_worker.cleanup_media(db_session)

    assert orphan_input.exists()
    assert not orphan_candidate.exists()
    assert any(
        record.getMessage() == "stored_file_cleanup_failed"
        and record.storage_class == "orphan_input"
        for record in caplog.records
    )

    monkeypatch.setattr(Path, "unlink", original_unlink)
    search_worker.cleanup_media(db_session)
    assert not orphan_input.exists()


def test_orphan_cleanup_continues_after_stat_permission_error(
    db_session,
    monkeypatch,
    caplog,
):
    prepare_storage()
    media_root = get_settings().media_root
    inaccessible_input = atomic_write(media_root, "inputs/inaccessible.image", b"inaccessible")
    removable_candidate = atomic_write(
        media_root,
        "candidates/orphan/removable.gif",
        b"orphan candidate",
    )
    old = (utcnow() - timedelta(days=2)).timestamp()
    os.utime(inaccessible_input, (old, old))
    os.utime(removable_candidate, (old, old))
    original_stat = Path.stat

    def fail_one_stat(path, *args, **kwargs):
        if path == inaccessible_input:
            raise PermissionError("test stat failure")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_one_stat)
    search_worker.cleanup_media(db_session)
    monkeypatch.setattr(Path, "stat", original_stat)

    assert inaccessible_input.exists()
    assert not removable_candidate.exists()
    assert any(
        record.getMessage() == "media_cleanup_stat_failed"
        and record.storage_class == "orphan_input"
        for record in caplog.records
    )


def test_device_token_and_unknown_records(client, monkeypatch):
    monkeypatch.setenv("DEVICE_TOKEN", "test-token")
    get_settings.cache_clear()
    assert submit(client).status_code == 401
    assert client.get("/health/live").status_code == 200
    response = client.get(
        f"/search-requests/{uuid4()}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 404


def test_readiness_checks_writable_storage(client, monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("blocked", encoding="ascii")
    monkeypatch.setenv("MEDIA_ROOT", str(blocker))
    get_settings.cache_clear()
    assert client.get("/health/ready").status_code == 503
    assert client.get("/health/live").status_code == 200


def test_missing_retrieval_is_an_explicit_failure(tmp_path, monkeypatch):
    def retrieval_unavailable(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(args=[], returncode=2, stdout="")

    monkeypatch.setattr(
        search_worker.subprocess,
        "run",
        retrieval_unavailable,
    )
    with pytest.raises(search_worker.RetrievalError, match="has not been installed") as error:
        search_worker.invoke_retrieval(tmp_path / "input.png")
    assert error.value.code == "retrieval_unavailable"


def test_candidate_failure_rolls_back_results_and_removes_copies(
    client,
    db_session,
    worker_factory,
):
    submission = submit(client).json()
    with worker_factory() as db:
        search_worker.claim_next_search_job(db)
    settings = get_settings()
    good_id, bad_id = str(uuid4()), str(uuid4())
    good = image_bytes(gif=True)
    atomic_write(settings.reference_root, "good.gif", good)
    atomic_write(settings.reference_root, "bad.gif", good)
    for asset_id, digest, path in [
        (good_id, sha256(good), "good.gif"),
        (bad_id, "0" * 64, "bad.gif"),
    ]:
        db_session.add(
            ReferenceAsset(
                id=asset_id,
                sha256=digest,
                title="Test",
                source_reference="test",
                permission_note="Generated in test",
                gif_path=path,
                frame_count=2,
                corpus_version="test",
            )
        )
    db_session.commit()
    result = RetrievalResult(
        matches=[
            RetrievalMatch(reference_asset_id=UUID(good_id), score=0.9),
            RetrievalMatch(reference_asset_id=UUID(bad_id), score=0.8),
        ],
        model_version="test",
        corpus_version="test",
    )
    with pytest.raises(search_worker.RetrievalError) as error:
        search_worker.process_search_job(submission["job_id"], lambda _: result)
    assert error.value.code == "corpus_corrupted"
    assert db_session.scalar(select(func.count()).select_from(Candidate)) == 0
    assert not list((settings.media_root / "candidates").glob("*/*.gif"))
    with worker_factory() as db:
        search_worker.fail_job(db, submission["job_id"], error.value.code, str(error.value))
    state = client.get(f"/search-requests/{submission['request_id']}").json()
    assert state["status"] == "failed"
    assert state["error"]["code"] == "corpus_corrupted"
    assert state["candidates"] == []


def test_ambiguous_commit_keeps_durable_candidate_media(
    client,
    db_session,
    worker_factory,
    monkeypatch,
):
    submission = submit(client).json()
    with worker_factory() as db:
        search_worker.claim_next_search_job(db)
    settings = get_settings()
    asset_id = str(uuid4())
    data = image_bytes(gif=True)
    atomic_write(settings.reference_root, f"{asset_id}.gif", data)
    db_session.add(
        ReferenceAsset(
            id=asset_id,
            sha256=sha256(data),
            title="Test animation",
            source_reference="test-generated",
            permission_note="Generated in test",
            gif_path=f"{asset_id}.gif",
            frame_count=2,
            corpus_version="test",
        )
    )
    db_session.commit()
    result = RetrievalResult(
        matches=[RetrievalMatch(reference_asset_id=UUID(asset_id), score=0.9)],
        model_version="test",
        corpus_version="test",
    )
    original_factory = worker_factory

    class CommitAcknowledgementLost:
        def __init__(self, session):
            self.session = session

        def __enter__(self):
            self.session.__enter__()
            return self

        def __exit__(self, _exc_type, _exc_value, _traceback):
            return self.session.__exit__(_exc_type, _exc_value, _traceback)

        def __getattr__(self, name):
            return getattr(self.session, name)

        def commit(self):
            self.session.commit()
            raise OperationalError(
                "commit acknowledgement",
                {},
                RuntimeError("connection lost after commit"),
            )

    monkeypatch.setattr(
        search_worker,
        "get_session_factory",
        lambda: lambda: CommitAcknowledgementLost(original_factory()),
    )
    with pytest.raises(OperationalError, match="connection lost after commit"):
        search_worker.process_search_job(
            submission["job_id"],
            lambda _: result,
        )

    db_session.expire_all()
    state = client.get(f"/search-requests/{submission['request_id']}").json()
    assert state["status"] == "completed"
    assert len(state["candidates"]) == 1
    media_path = settings.media_root / (
        db_session.get(Candidate, state["candidates"][0]["candidate_id"]).local_cache_path
    )
    assert media_path.is_file()
    assert client.get(state["candidates"][0]["media_url"]).status_code == 200
    assert (
        search_worker.fail_job(db_session, submission["job_id"], "worker_error", "late error")
        is False
    )
    assert db_session.get(SearchJob, submission["job_id"]).status == "completed"


def test_missing_input_fails_and_requires_new_submission(
    client,
    db_session,
    worker_factory,
):
    submission = submit(client).json()
    request = db_session.get(SearchRequest, submission["request_id"])
    (get_settings().media_root / request.input_path).unlink()
    with worker_factory() as db:
        search_worker.claim_next_search_job(db)
    with pytest.raises(search_worker.RetrievalError) as error:
        search_worker.process_search_job(submission["job_id"])
    assert error.value.code == "input_unavailable"
    with worker_factory() as db:
        search_worker.fail_job(db, submission["job_id"], error.value.code, str(error.value))
    retry = client.post(
        f"/search-requests/{submission['request_id']}/retry",
        json={"client_retry_key": "missing-input"},
    )
    assert retry.status_code == 410


def test_readiness_handles_database_failure(client, db_session, monkeypatch):
    def broken_execute(*_args, **_kwargs):
        del _args, _kwargs
        raise OperationalError("select", {}, RuntimeError("database down"))

    monkeypatch.setattr(db_session, "execute", broken_execute)
    assert client.get("/health/ready").status_code == 503
    assert client.get("/health/live").status_code == 200


def test_http_metrics_use_bounded_route_templates(client):
    first_id, second_id = str(uuid4()), str(uuid4())
    assert client.get(f"/search-requests/{first_id}").status_code == 404
    assert client.get(f"/search-requests/{second_id}").status_code == 404
    metrics = client.get("/metrics").text
    metric_lines = [
        line
        for line in metrics.splitlines()
        if line.startswith("api_http_requests_total{")
        and 'path="/search-requests/{request_id}"' in line
        and 'status="404"' in line
    ]
    assert metric_lines
    assert str(first_id) not in "\n".join(metric_lines)
    assert str(second_id) not in "\n".join(metric_lines)
