import io
from datetime import timedelta
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select

from services.common.config import get_settings
from services.common.db import make_session_factory
from services.common.media import inspect_media, preview_bytes
from services.common.models import utcnow
from services.common.search_models import Candidate, SearchJob, SearchRequest
from services.common.storage import atomic_write
from services.search_agent.meme_types import PreparedMedia, RunnerEvent
from services.worker.app.meme_worker import process_meme_job


def media(fmt="PNG", animated=False):
    out = io.BytesIO()
    image = Image.new("RGB", (24, 18), "red")
    options = (
        dict(save_all=True, append_images=[Image.new("RGB", image.size, "blue")], duration=100)
        if animated
        else {}
    )
    image.save(out, format=fmt, **options)
    return out.getvalue()


def upload(client, fmt="PNG", animated=False, **extra):
    return client.post(
        "/search-requests",
        data={"client_submission_key": str(uuid4()), "search_profile": "meme50-v2", **extra},
        files={"image": ("random-name.bin", media(fmt, animated), "application/octet-stream")},
    )


@pytest.mark.parametrize(
    "fmt,animated",
    [
        ("PNG", False),
        ("JPEG", False),
        ("WEBP", False),
        ("GIF", False),
        ("GIF", True),
        ("WEBP", True),
        ("PNG", True),
    ],
)
def test_optional_description_direct_web_no_local_and_actual_decode(
    client, db_session, fmt, animated
):
    response = upload(client, fmt, animated)
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["search_profile"] == "meme50-v2" and accepted["target_count"] == 50
    request = db_session.get(SearchRequest, accepted["request_id"])
    jobs = list(db_session.scalars(select(SearchJob).where(SearchJob.request_id == request.id)))
    assert len(jobs) == 1 and jobs[0].job_kind == "web"
    assert request.input_metadata["format"] == fmt
    assert request.input_metadata["frame_count"] == (2 if animated else 1)
    state = client.get(f"/search-requests/{request.id}").json()
    assert state["local_job_id"] is None and state["contract_version"] == 2
    assert client.get(f"/search-jobs/{jobs[0].id}/results").status_code == 409


def test_missing_image_and_replay_conflict(client):
    assert (
        client.post(
            "/search-requests",
            data={"client_submission_key": "missing", "search_profile": "meme50-v2"},
        ).status_code
        == 422
    )
    key = str(uuid4())
    first = upload(client, client_submission_key=key, description=" 同一角色 ")
    replay = upload(client, client_submission_key=key, description="同一角色")
    assert first.json() == replay.json()
    assert upload(client, client_submission_key=key, description="生气").status_code == 409
    assert (
        upload(
            client, client_submission_key=key, target_count=49, description="同一角色"
        ).status_code
        == 409
    )


def test_fifty_stable_results_filters_and_integrity(client, db_session):
    accepted = upload(client).json()
    job = db_session.get(SearchJob, accepted["job_id"])
    job.status, job.started_at, job.finished_at = "completed", utcnow(), utcnow()
    job.stage, job.result_kind, job.result_count, job.result_revision = (
        "completed",
        "candidates",
        50,
        "frozen-revision",
    )
    root = get_settings().media_root
    for rank in range(1, 51):
        data = media("GIF", True) if rank % 2 == 0 else media()
        m = inspect_media(data)
        path = f"candidates/{job.id}/{rank}.{m.suffix}"
        atomic_write(root, path, data)
        db_session.add(
            Candidate(
                job_id=job.id,
                rank=rank,
                similarity_score=1 - rank / 100,
                source_url=f"https://example.net/{rank}",
                local_cache_path=path,
                media_sha256=m.sha256,
                frame_count=m.frame_count,
                media_format=m.format,
                mime_type=m.mime_type,
                media_kind=m.media_kind,
                width=m.width,
                height=m.height,
                byte_size=m.byte_size,
                content_group_id=str(rank),
                cache_expires_at=utcnow() + timedelta(days=1),
            )
        )
    db_session.commit()
    endpoint = f"/search-jobs/{job.id}/results"
    ids, cursor = [], None
    for expected in [20, 20, 10]:
        params = {"revision": "frozen-revision", "limit": 20}
        if cursor:
            params["cursor"] = cursor
        response = client.get(endpoint, params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page["items"]) == expected
        assert page["counts"] == {"static": 25, "animated": 25}
        ids += [x["candidate_id"] for x in page["items"]]
        cursor = page["next_cursor"]
    assert len(set(ids)) == 50 and cursor is None
    first = client.get(endpoint).json()
    assert (
        client.get(
            endpoint, params={"cursor": first["next_cursor"], "media_kind": "static"}
        ).status_code
        == 422
    )
    assert client.get(endpoint, params={"revision": "wrong"}).status_code == 409
    for kind in ["static", "animated"]:
        page = client.get(endpoint, params={"media_kind": kind, "limit": 50}).json()
        assert page["total"] == 25 and all(x["media_kind"] == kind for x in page["items"])
        item = page["items"][0]
        response = client.get(item["media_url"])
        assert response.status_code == 200 and response.headers["content-type"] == item["mime_type"]
        assert inspect_media(response.content).sha256 == item["sha256"]
        assert client.get(item["preview_url"]).headers["content-type"] == "image/png"
    static = first["items"][0]
    candidate = db_session.get(Candidate, static["candidate_id"])
    (root / candidate.local_cache_path).write_bytes(b"corrupt")
    assert client.get(static["media_url"]).status_code == 503


def test_worker_stream_drafts_final_and_missing_final(client, db_session, monkeypatch):
    monkeypatch.setenv("MEME50_VISION_PROVIDER", "hkust")
    monkeypatch.setenv("MEME50_HKUST_API_KEY", "controlled-school-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "controlled-deepseek-key")
    accepted = upload(client).json()
    job = db_session.get(SearchJob, accepted["job_id"])
    job.status, job.started_at = "running", utcnow()
    db_session.commit()
    factory = make_session_factory(db_session.get_bind())
    data = media()
    meta = inspect_media(data)
    from pathlib import Path

    def stream(payload, timeout):
        assert payload["settings"]["vision_provider"] == "hkust"
        assert "hkust_api_key" not in payload["settings"]
        assert "deepseek_api_key" not in payload["settings"]
        assert "controlled-deepseek-key" not in str(payload)
        assert "controlled-school-key" not in str(payload)
        work = Path(payload["work_dir"])
        atomic_write(work, "original.png", data)
        atomic_write(work, "preview.png", preview_bytes(data))
        item = PreparedMedia(
            key=meta.sha256,
            relative_path="original.png",
            preview_relative_path="preview.png",
            metadata=meta,
            source_url="https://example.org/source",
            media_url="https://cdn.example.org/image",
            provider="controlled-test",
            score=0.9,
            content_group_id="group1",
        )
        yield RunnerEvent(
            seq=1, type="analysis_ready", payload={"analysis": {"observations": ["test pixels"]}}
        )
        yield RunnerEvent(
            seq=2, type="candidate_ready", payload={"candidate": item.model_dump(mode="json")}
        )
        yield RunnerEvent(
            seq=3,
            type="final",
            payload={
                "status": "completed",
                "candidate_keys": [meta.sha256],
                "ledger": {"model_calls": 3},
                "stop_reason": "controlled_test",
            },
        )

    process_meme_job(job.id, factory=factory, event_stream=stream)
    db_session.expire_all()
    assert db_session.get(SearchJob, job.id).status == "completed"
    assert "hkust_api_key" not in db_session.get(SearchJob, job.id).configuration
    assert "deepseek_api_key" not in db_session.get(SearchJob, job.id).configuration
    assert client.get(f"/search-jobs/{job.id}/results").json()["total_all"] == 1
    # No final event must never be converted into success.
    second = upload(client).json()
    second_job = db_session.get(SearchJob, second["job_id"])
    second_job.status, second_job.started_at = "running", utcnow()
    db_session.commit()
    process_meme_job(second_job.id, factory=factory, event_stream=lambda *args: iter([]))
    db_session.expire_all()
    failed = db_session.get(SearchJob, second_job.id)
    assert failed.status == "failed" and failed.error_code == "runner_missing_final"
