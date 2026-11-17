from __future__ import annotations

import io
import subprocess
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from services.common.config import get_settings
from services.common.db import make_session_factory
from services.common.models import utcnow
from services.common.search_models import (
    Candidate,
    CandidateSave,
    SavedAsset,
    SearchExecution,
    SearchJob,
)
from services.common.search_schemas import (
    RetrievalMatch,
    RetrievalResult,
    WebCandidate,
    WebSearchResult,
)
from services.common.storage import atomic_write, sha256
from services.worker.app import search_worker


def image_bytes(*, gif: bool = False) -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (8, 8), "red")
    if gif:
        image.save(
            output,
            format="GIF",
            save_all=True,
            append_images=[Image.new("RGB", (8, 8), "blue")],
            duration=100,
            loop=0,
        )
    else:
        image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture()
def worker_factory(db_session, monkeypatch):
    factory = make_session_factory(db_session.get_bind())
    monkeypatch.setattr(search_worker, "get_session_factory", lambda: factory)
    return factory


def finish_local_job(client, db_session, worker_factory) -> dict:
    accepted = client.post(
        "/search-requests",
        data={"client_submission_key": "web-flow-submission"},
        files={"image": ("crop.png", image_bytes(), "image/png")},
    ).json()
    with worker_factory() as db:
        job = search_worker.claim_next_search_job(db)
        assert job is not None
        assert job.id == accepted["job_id"]
    search_worker.process_search_job(
        accepted["job_id"],
        lambda _: RetrievalResult(
            matches=[],
            model_version="test-model",
            corpus_version="test-corpus",
        ),
    )
    db_session.expire_all()
    return accepted


def create_web_job(client, request_id: str) -> dict:
    response = client.post(
        f"/search-requests/{request_id}/web-search",
        json={"description": "dancing cat gif", "client_search_key": "web-search-1"},
    )
    assert response.status_code == 202
    return response.json()


def web_candidate_searcher(image_path: Path, description: str, work_dir: Path):
    assert image_path.is_file()
    assert description == "dancing cat gif"
    data = image_bytes(gif=True)
    relative = "round-1/candidate.gif"
    atomic_write(work_dir, relative, data)
    return WebSearchResult(
        status="completed",
        result_kind="candidates",
        stop_reason="candidates_found",
        candidates=[
            WebCandidate(
                relative_path=relative,
                sha256=sha256(data),
                source_url="https://example.com/meme",
                image_url="https://cdn.example.com/meme.gif",
                provider="test-provider",
                format="GIF",
                frame_count=2,
                score=0.93,
            )
        ],
        search_calls=1,
        planner_calls=1,
        downloads_used=1,
        model_version="test-vision-model",
    )


def run_web_job(client, worker_factory, job_id: str, searcher=web_candidate_searcher):
    with worker_factory() as db:
        job = search_worker.claim_next_search_job(db)
        assert job is not None
        assert job.id == job_id
        assert job.job_kind == "web"
    search_worker.process_web_search_job(job_id, searcher)


def test_web_search_lifecycle_save_index_and_local_reuse(
    client,
    db_session,
    worker_factory,
    monkeypatch,
):
    request = finish_local_job(client, db_session, worker_factory)
    first = create_web_job(client, request["request_id"])
    assert create_web_job(client, request["request_id"]) == first
    conflict = client.post(
        f"/search-requests/{request['request_id']}/web-search",
        json={"description": "different query", "client_search_key": "web-search-1"},
    )
    assert conflict.status_code == 409

    run_web_job(client, worker_factory, first["job_id"])
    db_session.expire_all()
    state = client.get(f"/search-requests/{request['request_id']}").json()
    assert state["local_job_id"] == request["job_id"]
    assert state["job_kind"] == "web"
    assert state["stage"] == "completed"
    assert state["web_searches"][0]["job_id"] == first["job_id"]
    assert state["web_searches"][0]["status"] == "completed"
    assert len(state["candidates"]) == 1
    candidate = state["candidates"][0]
    assert candidate["source_url"] == "https://example.com/meme"
    assert candidate["provider"] == "test-provider"
    assert candidate["save_status"] == "not_saved"
    assert db_session.get(SearchExecution, first["job_id"]).downloads_used == 1
    candidate_media_path = get_settings().media_root / db_session.get(
        Candidate, candidate["candidate_id"]
    ).local_cache_path
    candidate_media = client.get(candidate["media_url"])
    assert candidate_media.status_code == 200
    assert candidate_media.content == image_bytes(gif=True)
    assert candidate_media.headers["cache-control"] == "no-store"
    assert candidate_media.headers["x-content-type-options"] == "nosniff"
    assert candidate_media.headers["referrer-policy"] == "no-referrer"
    atomic_write(get_settings().media_root, str(candidate_media_path.relative_to(
        get_settings().media_root
    )), b"tampered")
    corrupted_candidate_media = client.get(candidate["media_url"])
    assert corrupted_candidate_media.status_code == 503
    assert corrupted_candidate_media.json()["detail"]["code"] == "media_corrupted"
    atomic_write(get_settings().media_root, str(candidate_media_path.relative_to(
        get_settings().media_root
    )), image_bytes(gif=True))
    candidate_row = db_session.get(Candidate, candidate["candidate_id"])
    assert candidate_row is not None
    candidate_relative_path = candidate_row.local_cache_path
    candidate_row.local_cache_path = "../outside.gif"
    db_session.commit()
    escaped_candidate_media = client.get(candidate["media_url"])
    assert escaped_candidate_media.status_code == 503
    assert escaped_candidate_media.json()["detail"]["code"] == "media_corrupted"

    review = client.post(
        f"/search-jobs/{first['job_id']}/reviews",
        json={
            "decision": "accept",
            "candidate_id": candidate["candidate_id"],
            "client_review_key": "web-review-1",
        },
    )
    assert review.status_code == 201
    escaped_candidate_save = client.post(
        f"/candidates/{candidate['candidate_id']}/save",
        json={"client_save_key": "web-save-path-escape"},
    )
    assert escaped_candidate_save.status_code == 503
    assert escaped_candidate_save.json()["detail"]["code"] == "media_corrupted"
    candidate_row.local_cache_path = candidate_relative_path
    db_session.commit()

    with monkeypatch.context() as patch:
        patch.setattr(get_settings(), "max_candidate_bytes", 1)
        oversized_save = client.post(
            f"/candidates/{candidate['candidate_id']}/save",
            json={"client_save_key": "web-save-oversized"},
        )
    assert oversized_save.status_code == 503
    assert oversized_save.json()["detail"]["code"] == "media_corrupted"

    saved = client.post(
        f"/candidates/{candidate['candidate_id']}/save",
        json={"client_save_key": "web-save-1"},
    )
    assert saved.status_code == 202
    assert saved.json()["save_status"] == "saved"
    assert saved.json()["index_status"] == "pending"
    assert saved.json()["media_url"] == f"/saved-assets/{saved.json()['asset_id']}/media"
    assert client.post(
        f"/candidates/{candidate['candidate_id']}/save",
        json={"client_save_key": "web-save-1"},
    ).json() == saved.json()
    new_key_save = client.post(
        f"/candidates/{candidate['candidate_id']}/save",
        json={"client_save_key": "web-save-2"},
    )
    assert new_key_save.json()["asset_id"] == saved.json()["asset_id"]
    assert db_session.scalar(select(SavedAsset.sha256)) == sha256(image_bytes(gif=True))
    assert db_session.scalar(select(CandidateSave.client_save_key).where(
        CandidateSave.client_save_key == "web-save-2"
    )) == "web-save-2"

    asset = db_session.get(SavedAsset, saved.json()["asset_id"])
    assert asset is not None
    atomic_write(get_settings().media_root, asset.gif_path, b"tampered")
    corrupted_asset_save = client.post(
        f"/candidates/{candidate['candidate_id']}/save",
        json={"client_save_key": "web-save-corrupted-asset"},
    )
    assert corrupted_asset_save.status_code == 503
    assert corrupted_asset_save.json()["detail"]["code"] == "saved_asset_corrupted"
    assert db_session.scalar(
        select(CandidateSave.id).where(
            CandidateSave.client_save_key == "web-save-corrupted-asset"
        )
    ) is None
    atomic_write(get_settings().media_root, asset.gif_path, image_bytes(gif=True))

    commits = 0

    def fail_recovery_commit():
        nonlocal commits
        commits += 1
        if commits == 1:
            raise IntegrityError("simulated race", {}, Exception("unique"))
        raise SQLAlchemyError("simulated recovery failure")

    with monkeypatch.context() as patch:
        patch.setattr(db_session, "commit", fail_recovery_commit)
        failed_recovery = client.post(
            f"/candidates/{candidate['candidate_id']}/save",
            json={"client_save_key": "web-save-recovery-failure"},
        )
    assert failed_recovery.status_code == 503
    assert failed_recovery.json()["detail"]["code"] == "database_unavailable"
    assert db_session.scalar(
        select(CandidateSave.id).where(
            CandidateSave.client_save_key == "web-save-recovery-failure"
        )
    ) is None

    def fail_commit():
        raise SQLAlchemyError("simulated commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(db_session, "commit", fail_commit)
        failed_save = client.post(
            f"/candidates/{candidate['candidate_id']}/save",
            json={"client_save_key": "web-save-db-failure"},
        )
    assert failed_save.status_code == 503
    assert failed_save.json()["detail"]["code"] == "database_unavailable"
    assert db_session.scalar(
        select(CandidateSave.id).where(
            CandidateSave.client_save_key == "web-save-db-failure"
        )
    ) is None

    asset_id = saved.json()["asset_id"]
    with worker_factory() as db:
        claimed = search_worker.claim_next_saved_asset_index(db)
        assert claimed is not None
        assert claimed.id == asset_id
    search_worker.process_saved_asset_index(asset_id, lambda _: "index-v1")
    assert client.get(f"/saved-assets/{asset_id}").json()["index_status"] == "ready"

    candidate_row = db_session.get(Candidate, candidate["candidate_id"])
    candidate_row.cache_expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()
    search_worker.cleanup_media(db_session)
    expired_candidate_media = client.get(candidate["media_url"])
    assert expired_candidate_media.status_code == 200
    assert expired_candidate_media.content == image_bytes(gif=True)
    assert expired_candidate_media.headers["cache-control"] == "no-store"
    asset = db_session.get(SavedAsset, asset_id)
    assert asset is not None
    assert (get_settings().media_root / asset.gif_path).is_file()
    saved_media = client.get(saved.json()["media_url"])
    assert saved_media.status_code == 200
    assert saved_media.headers["content-type"] == "image/gif"
    assert saved_media.content == image_bytes(gif=True)
    assert saved_media.headers["cache-control"] == "no-store"
    assert saved_media.headers["x-content-type-options"] == "nosniff"
    atomic_write(get_settings().media_root, asset.gif_path, b"tampered")
    corrupted_saved_media = client.get(saved.json()["media_url"])
    assert corrupted_saved_media.status_code == 503
    assert corrupted_saved_media.json()["detail"]["code"] == "saved_asset_corrupted"
    atomic_write(get_settings().media_root, asset.gif_path, image_bytes(gif=True))
    saved_relative_path = asset.gif_path
    asset.gif_path = "../outside.gif"
    db_session.commit()
    escaped_saved_media = client.get(saved.json()["media_url"])
    assert escaped_saved_media.status_code == 503
    assert escaped_saved_media.json()["detail"]["code"] == "saved_asset_corrupted"
    asset.gif_path = saved_relative_path
    db_session.commit()

    reuse = client.post(
        "/search-requests",
        data={"client_submission_key": "saved-asset-reuse"},
        files={"image": ("crop.png", image_bytes(), "image/png")},
    )
    assert reuse.status_code == 202
    with worker_factory() as db:
        claimed = search_worker.claim_next_search_job(db)
        assert claimed is not None
        assert claimed.id == reuse.json()["job_id"]
    search_worker.process_search_job(
        reuse.json()["job_id"],
        lambda _: RetrievalResult(
            matches=[
                RetrievalMatch(reference_asset_id=UUID(asset_id), score=0.91),
            ],
            model_version="test-model",
            corpus_version="test-corpus",
        ),
    )
    reused_candidate = client.get(
        f"/search-requests/{reuse.json()['request_id']}"
    ).json()["candidates"][0]
    assert reused_candidate["save_status"] == "saved"
    assert reused_candidate["asset_id"] == asset_id
    assert reused_candidate["index_status"] == "ready"


def test_web_search_failure_is_distinct_from_no_match_and_retryable(
    client,
    db_session,
    worker_factory,
):
    request = finish_local_job(client, db_session, worker_factory)
    accepted = create_web_job(client, request["request_id"])

    def sources_only(_image_path, _description, _work_dir):
        return WebSearchResult(
            status="completed",
            result_kind="sources",
            stop_reason="sources_found",
            search_calls=1,
            planner_calls=1,
            downloads_used=0,
        )

    run_web_job(client, worker_factory, accepted["job_id"], sources_only)
    db_session.expire_all()
    state = client.get(f"/search-requests/{request['request_id']}").json()
    assert state["status"] == "failed"
    assert state["error"]["code"] == "candidate_processor_unavailable"
    assert db_session.get(SearchExecution, accepted["job_id"]) is not None

    retried = client.post(
        f"/search-jobs/{accepted['job_id']}/retry",
        json={"client_retry_key": "web-search-retry"},
    )
    assert retried.status_code == 202
    assert retried.json()["job_id"] != accepted["job_id"]
    assert client.post(
        f"/search-jobs/{accepted['job_id']}/retry",
        json={"client_retry_key": "web-search-retry"},
    ).json() == retried.json()
    jobs = db_session.scalars(
        select(SearchJob).where(
            SearchJob.request_id == request["request_id"],
            SearchJob.job_kind == "web",
        )
    ).all()
    assert len(jobs) == 2
    assert jobs[1].retry_of_job_id == accepted["job_id"]


def test_web_search_interruption_preserves_local_result_and_supports_retry(
    client,
    db_session,
    worker_factory,
):
    request = finish_local_job(client, db_session, worker_factory)
    accepted = create_web_job(client, request["request_id"])
    with worker_factory() as db:
        claimed = search_worker.claim_next_search_job(db)
        assert claimed is not None
        assert claimed.id == accepted["job_id"]
    with worker_factory() as db:
        assert search_worker.recover_interrupted_jobs(db) == 1
    state = client.get(f"/search-requests/{request['request_id']}").json()
    assert state["local_job_id"] == request["job_id"]
    assert state["web_searches"][0]["error"]["code"] == "worker_interrupted"
    retry = client.post(
        f"/search-jobs/{accepted['job_id']}/retry",
        json={"client_retry_key": "interrupted-web-retry"},
    )
    assert retry.status_code == 202
    jobs = db_session.scalars(
        select(SearchJob).where(
            SearchJob.request_id == request["request_id"],
            SearchJob.job_kind == "web",
        )
    ).all()
    assert len(jobs) == 2
    assert jobs[1].retry_of_job_id == accepted["job_id"]


def test_web_search_runner_enforces_process_timeout(monkeypatch, tmp_path):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("web-search", 1)

    monkeypatch.setattr(search_worker.subprocess, "run", timeout)
    with pytest.raises(search_worker.RetrievalError, match="time limit"):
        search_worker.invoke_web_search(
            tmp_path / "input.png",
            "description",
            tmp_path / "work",
        )


def test_save_requires_explicit_acceptance(client, db_session, worker_factory):
    request = finish_local_job(client, db_session, worker_factory)
    accepted = create_web_job(client, request["request_id"])
    run_web_job(client, worker_factory, accepted["job_id"])
    db_session.expire_all()
    state = client.get(f"/search-requests/{request['request_id']}").json()
    candidate_id = state["candidates"][0]["candidate_id"]
    response = client.post(
        f"/candidates/{candidate_id}/save",
        json={"client_save_key": "not-accepted"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_not_accepted"
    assert db_session.scalar(select(SavedAsset.id)) is None


def test_saved_index_failure_is_persisted_and_can_be_retried(
    client,
    db_session,
    worker_factory,
):
    request = finish_local_job(client, db_session, worker_factory)
    accepted = create_web_job(client, request["request_id"])
    run_web_job(client, worker_factory, accepted["job_id"])
    state = client.get(f"/search-requests/{request['request_id']}").json()
    candidate = state["candidates"][0]
    client.post(
        f"/search-jobs/{accepted['job_id']}/reviews",
        json={
            "decision": "accept",
            "candidate_id": candidate["candidate_id"],
            "client_review_key": "index-review",
        },
    )
    saved = client.post(
        f"/candidates/{candidate['candidate_id']}/save",
        json={"client_save_key": "index-save"},
    ).json()
    with worker_factory() as db:
        claimed = search_worker.claim_next_saved_asset_index(db)
        assert claimed is not None
    search_worker.process_saved_asset_index(
        saved["asset_id"],
        failing_indexer,
    )
    failed = client.get(f"/saved-assets/{saved['asset_id']}").json()
    assert failed["index_status"] == "failed"
    assert failed["index_error"].startswith("index_failed:")
    assert client.post(f"/saved-assets/{saved['asset_id']}/index-retry").json()[
        "index_status"
    ] == "pending"
    with worker_factory() as db:
        claimed = search_worker.claim_next_saved_asset_index(db)
        assert claimed is not None
    asset = db_session.get(SavedAsset, saved["asset_id"])
    assert asset is not None
    asset.frame_count += 1
    db_session.commit()
    search_worker.process_saved_asset_index(
        saved["asset_id"],
        lambda _: pytest.fail("Corrupt GIF must not be sent to the indexer"),
    )
    db_session.expire_all()
    failed = client.get(f"/saved-assets/{saved['asset_id']}").json()
    assert failed["index_status"] == "failed"
    assert failed["index_error"].startswith("saved_asset_corrupted:")

    assert client.post(f"/saved-assets/{saved['asset_id']}/index-retry").json()[
        "index_status"
    ] == "pending"
    asset.frame_count -= 1
    db_session.commit()
    with worker_factory() as db:
        claimed = search_worker.claim_next_saved_asset_index(db)
        assert claimed is not None
    search_worker.process_saved_asset_index(saved["asset_id"], lambda _: "index-v2")
    db_session.expire_all()
    assert client.get(f"/saved-assets/{saved['asset_id']}").json()["index_status"] == "ready"


def failing_indexer(_asset_id: str) -> str:
    raise search_worker.IndexingError("index_failed", "test failure")


def test_real_processor_agent_conversion_worker_and_media(
    client, db_session, worker_factory, monkeypatch,
):
    """Offline transport/embeddings; actual preparation, serialization, worker and API."""
    from services.retrieval import candidates as preparation
    from services.retrieval import prepare_candidates
    from services.search_agent import SearchBudget, search_web
    from services.search_agent.resolvers import resolve_sources
    from services.search_agent.settings import SearchAgentSettings
    from services.worker.app.web_search_runner import to_worker_result

    data = image_bytes(gif=True)
    monkeypatch.setattr(preparation, "fetch", lambda *a, **k: (data, a[0], 0))
    monkeypatch.setattr(preparation.encoder, "load_model", lambda: None)
    monkeypatch.setattr(preparation.encoder, "encode_image", lambda _: np.array([1., 0.]))
    monkeypatch.setattr(preparation.encoder, "encode_images",
                        lambda images: np.array([[1., 0.]] * len(images)))
    class Provider:
        name = "fixture"
        def search(self, *args, **kwargs):
            return [dict(source_url="https://upload.wikimedia.org/example.gif", provider=self.name)]
    def searcher(image_path, description, work_dir):
        result = search_web(image_path, description, work_dir,
                            budget=SearchBudget(max_rounds=1), provider=Provider(),
                            settings=SearchAgentSettings(
                                _env_file=None, search_agent_use_model=False),
                            prepare_candidates=prepare_candidates, resolver=resolve_sources)
        return WebSearchResult.model_validate_json(to_worker_result(result).model_dump_json())
    request = finish_local_job(client, db_session, worker_factory)
    accepted = create_web_job(client, request["request_id"])
    run_web_job(client, worker_factory, accepted["job_id"], searcher)
    state = client.get(f"/search-requests/{request['request_id']}").json()
    assert state["status"] == "completed"
    candidate = state["candidates"][0]
    response = client.get(candidate["media_url"])
    assert response.status_code == 200 and response.headers["content-type"] == "image/gif"
    assert sha256(response.content) == sha256(data)
    from services.common.storage import validate_image
    assert validate_image(response.content, animated_gif=True) == 2


def test_default_index_subprocess_publishes_saved_gif_vectors(
    client, db_session, worker_factory, monkeypatch, tmp_path,
):
    import os
    import sys


    from services.retrieval import saved_index

    # Substitute only CLIP inference in the child; use the normal runner, storage and DB.
    (tmp_path / "sitecustomize.py").write_text(
        "import numpy as np\n"
        "from services.retrieval import saved_index\n"
        "saved_index.encode_images = lambda images: "
        "np.tile(np.eye(1, 512, dtype=np.float32), (len(images), 1))\n"
    )
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(tmp_path), *sys.path]))
    monkeypatch.setenv("DATABASE_URL", str(db_session.bind.url))
    monkeypatch.setattr(saved_index, "get_session_factory", lambda: worker_factory)
    request = finish_local_job(client, db_session, worker_factory)
    accepted = create_web_job(client, request["request_id"])
    run_web_job(client, worker_factory, accepted["job_id"])
    candidate = client.get(f"/search-jobs/{accepted['job_id']}/candidates").json()[0]
    candidate_id = candidate["candidate_id"]
    assert client.post(
        f"/search-jobs/{accepted['job_id']}/reviews",
        json={
            "decision": "accept", "candidate_id": candidate_id,
            "client_review_key": "subprocess-review",
        },
    ).status_code == 201
    save_url = f"/candidates/{candidate_id}/save"
    payload = {"client_save_key": "subprocess-save"}
    response = client.post(save_url, json=payload)
    assert response.status_code == 202
    saved = response.json()
    assert client.post(save_url, json=payload).json()["asset_id"] == saved["asset_id"]
    with worker_factory() as db:
        assert search_worker.claim_next_saved_asset_index(db).id == saved["asset_id"]
    search_worker.process_saved_asset_index(saved["asset_id"])
    db_session.expire_all()
    asset = db_session.get(SavedAsset, saved["asset_id"])
    assert asset.index_status == "ready"
    assert asset.index_attempts == 1
    [(asset_id, vectors)] = list(saved_index.ready_vectors())
    assert asset_id == asset.id
    assert vectors.shape == (asset.frame_count, 512)
    assert client.get(saved["media_url"]).content == image_bytes(gif=True)


@pytest.mark.parametrize("description", ["", "  dancing cat  "])
def test_explicit_linked_v2_reuses_upload_and_preserves_local_job(
    client, db_session, worker_factory, description,
):
    local = finish_local_job(client, db_session, worker_factory)
    path = f"/search-requests/{local['request_id']}"
    payload = {
        "description": description,
        "search_profile": "meme50-v2",
        "client_search_key": "explicit-online",
    }
    response = client.post(f"{path}/web-search", json=payload)
    assert response.status_code == 202
    web = response.json()
    assert web["request_id"] == local["request_id"]
    assert web["job_id"] != local["job_id"]
    assert web["search_profile"] == "meme50-v2"
    assert web["target_count"] == 50
    normalized = {**payload, "description": description.strip()}
    assert client.post(f"{path}/web-search", json=normalized).json() == web
    conflicting = {**payload, "description": "changed"}
    assert client.post(f"{path}/web-search", json=conflicting).json()["detail"]["code"] == (
        "search_key_conflict"
    )
    if description:
        omitted = {key: value for key, value in payload.items() if key != "search_profile"}
        assert client.post(f"{path}/web-search", json=omitted).json()["detail"]["code"] == (
            "search_key_conflict"
        )
    state = client.get(path).json()
    assert state["local_job_id"] == local["job_id"]
    assert state["web_searches"][0]["job_id"] == web["job_id"]
    assert state["web_searches"][0]["description"] == description.strip()
    local_summary = client.get(f"/search-jobs/{local['job_id']}").json()
    assert local_summary["job_kind"] == "local"
    assert local_summary["status"] == "completed"
    assert local_summary["result_kind"] == "no_candidates"
    assert client.get(f"/search-jobs/{local['job_id']}/candidates").json() == []
