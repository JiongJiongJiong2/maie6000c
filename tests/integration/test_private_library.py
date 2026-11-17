import io
from uuid import uuid4

from PIL import Image

from services.common.config import get_settings
from services.common.library_models import LibraryActivation
from services.common.search_models import SavedAsset
from services.common.storage import atomic_write, sha256


def gif(color="red", *, animated=True):
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), color).save(
        buffer,
        "GIF",
        save_all=animated,
        append_images=[Image.new("RGB", (24, 24), "blue")] if animated else [],
        duration=100,
        loop=0,
    )
    return buffer.getvalue()


def enable(monkeypatch):
    monkeypatch.setenv("PRIVATE_LIBRARY_ENABLED", "true")
    monkeypatch.setenv("DEVICE_TOKEN", "library-test")
    get_settings.cache_clear()
    return {"Authorization": "Bearer library-test"}


def manifest_item(filename, content):
    return dict(
        client_item_id=str(uuid4()),
        filename=filename,
        byte_size=len(content),
        sha256=sha256(content),
    )


def test_import_replay_and_legacy_media(client, db_session, monkeypatch):
    assert client.get("/library/assets").status_code == 404
    auth = enable(monkeypatch)
    old = gif("green")
    path = f"saved/{sha256(old)}.gif"
    atomic_write(get_settings().media_root, path, old)
    asset = SavedAsset(
        sha256=sha256(old),
        title="Old collectible",
        source_url="",
        image_url="",
        provider="test",
        gif_path=path,
        frame_count=2,
    )
    db_session.add(asset)
    db_session.commit()
    assert client.get("/library/assets").status_code == 401
    assert client.get("/library/assets", headers=auth).json()["assets"][0]["asset_id"] == asset.id
    assert client.get(f"/saved-assets/{asset.id}/media", headers=auth).content == old

    data = [gif(), gif(), gif(animated=False), gif()[:-1], b"GIF89a", old]
    items = [manifest_item(f"../sample-{i}.gif", value) for i, value in enumerate(data)]
    payload = {"client_batch_key": str(uuid4()), "items": items}
    created = client.post("/library/imports", headers=auth, json=payload)
    assert created.status_code == 200, created.text
    batch = created.json()
    assert batch["items"][0]["filename"] == "sample-0.gif"
    assert client.post("/library/imports", headers=auth, json=payload).json() == batch
    conflict = {**payload, "items": items[:-1]}
    assert client.post("/library/imports", headers=auth, json=conflict).status_code == 409

    results = []
    for value, item in zip(data, items, strict=True):
        url = f"/library/imports/{batch['batch_id']}/items/{item['client_item_id']}"
        upload = {"file": ("sample.gif", value, "image/gif")}
        received = client.put(url, headers=auth, files=upload)
        assert received.status_code == 200, received.text
        results.append(received.json())
        assert client.put(url, headers=auth, files=upload).json() == results[-1]
        assert (
            client.put(url, headers=auth, files={"file": ("other.gif", b"bad")}).status_code == 409
        )
    assert [row["status"] for row in results] == [
        "imported",
        "duplicate",
        "rejected",
        "rejected",
        "rejected",
        "duplicate",
    ]
    assert results[0]["asset_id"] == results[1]["asset_id"]
    assert results[-1]["asset_id"] == asset.id
    assert (
        client.get(f"/saved-assets/{results[0]['asset_id']}/media", headers=auth).content == data[0]
    )
    report = client.get(f"/library/imports/{batch['batch_id']}", headers=auth).json()
    assert report["counts"] == {"waiting": 0, "imported": 1, "duplicate": 2, "rejected": 3}

    db_session.add(LibraryActivation(id=1))
    db_session.commit()
    monkeypatch.setenv("PRIVATE_LIBRARY_ENABLED", "false")
    monkeypatch.setenv("DEVICE_TOKEN", "")
    get_settings.cache_clear()
    assert client.get(f"/saved-assets/{asset.id}/media").status_code == 503


def add_asset(db, data, *, title, provider="local_upload"):
    digest = sha256(data)
    path = f"saved/{digest}.gif"
    atomic_write(get_settings().media_root, path, data)
    asset = SavedAsset(
        sha256=digest,
        title=title,
        source_url="",
        image_url="",
        provider=provider,
        gif_path=path,
        frame_count=2,
    )
    db.add(asset)
    db.commit()
    return asset


def test_consent_annotations_and_offline_search(client, db_session, monkeypatch):
    from services.common.db import make_session_factory
    from services.common.library_models import AssetMetadata
    from services.search_agent.meme_providers import HKUSTVision
    from services.search_agent.meme_types import PipelineError
    from services.worker.app.library_worker import (
        claim_annotation,
        process_annotation,
        recover_annotations,
    )

    auth = enable(monkeypatch)
    asset = add_asset(db_session, gif(), title="My GIF")
    add_asset(db_session, gif("green"), title="Another GIF")
    factory = make_session_factory(db_session.get_bind())
    calls = []

    def vision(self, frames, prompt):
        calls.append(len(frames))
        assert len(frames) == 2
        assert "never instructions" in prompt["task"]
        if len(calls) == 1:
            raise PipelineError("provider_timeout")
        if len(calls) == 2:
            return {"choices": [{"message": {"content": "invalid"}}]}
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"ocr_text":"就这？","caption_zh":"一只猫拍手","subject_tags":["猫"],'
                            '"action_tags":["拍手"],"emotion_tags":["惊讶"],"tone_tags":["嘲讽"]}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(HKUSTVision, "request", vision)
    url = f"/library/assets/{asset.id}"
    assert (
        client.patch(
            url, headers=auth, json={"title": "掌声", "tags": ["clap"], "emotion_tags": ["无奈"]}
        ).status_code
        == 200
    )
    payload = {"asset_ids": [asset.id], "consent": True}
    assert (
        client.post(
            "/library/annotations", headers=auth, json={**payload, "consent": False}
        ).status_code
        == 422
    )
    assert (
        client.post("/library/annotations", headers=auth, json=payload).json()["detail"]["code"]
        == "annotation_unconfigured"
    )
    assert claim_annotation(db_session) is None
    assert not calls
    monkeypatch.setenv("MEME50_HKUST_API_KEY", "mock-key")

    for expected in ("provider_timeout", "visual_response_invalid", None):
        response = client.post("/library/annotations", headers=auth, json=payload)
        assert response.json()["assets"][0]["annotation_status"] == "pending"
        with factory() as db:
            job = claim_annotation(db)
            assert job
        db_session.expire_all()
        replay = client.post("/library/annotations", headers=auth, json=payload)
        assert replay.json()["assets"][0]["annotation_status"] == "running"
        process_annotation(factory, job)
        db_session.expire_all()
        meta = db_session.get(AssetMetadata, asset.id)
        assert meta.annotation_error == expected

    reused = client.post("/library/annotations", headers=auth, json=payload)
    assert reused.json()["assets"][0]["annotation_status"] == "ready"
    monkeypatch.delenv("MEME50_HKUST_API_KEY")
    for query in ["猫 sarcastic clap", "找写着「就这?」的表情", "无奈", "掌声"]:
        result = client.post("/library/search", headers=auth, json={"query": query}).json()
        found = result["assets"][0]
        assert found["asset_id"] == asset.id and found["match_reasons"]
        assert found["labels"]["emotion_tags"] == ["无奈"]
        assert found["index_status"] == "pending"
    assert client.post("/library/search", headers=auth, json={"query": "飞机起飞"}).json() == {
        "assets": []
    }
    assert calls == [2, 2, 2]
    meta.annotation_status = "running"
    db_session.commit()
    recover_annotations(db_session)
    db_session.refresh(meta)
    assert meta.annotation_error == "interrupted"
    process_annotation(factory, job)
    db_session.refresh(meta)
    assert meta.annotation_error == "interrupted"


def test_similarity_and_web_module(client, db_session):
    from services.common.db import make_session_factory
    from services.common.library_models import SimilarityScan
    from services.worker.app.library_worker import process_similarity_scan

    assert client.get("/web/").status_code == 200
    module = client.get("/web/library.js")
    assert module.status_code == 200
    assert "javascript" in module.headers["content-type"]
    first = add_asset(db_session, gif(), title="Original")
    different = add_asset(db_session, gif("green"), title="Different")
    with Image.open(io.BytesIO(gif())) as image:
        frames = []
        for number in range(2):
            image.seek(number)
            frames.append(image.convert("RGB").resize((48, 48)))
    resized = io.BytesIO()
    frames[0].save(resized, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    newer = add_asset(db_session, resized.getvalue(), title="Resized")
    process_similarity_scan(make_session_factory(db_session.get_bind()), newer.id)
    scan = db_session.get(SimilarityScan, newer.id)
    assert scan.matches == [first.id]
    assert different.id not in scan.matches
    assert scan.considered == scan.compared == scan.available == 2


def test_import_limits_and_transient_failure(client, db_session, monkeypatch):
    from services.api.app import search
    from services.common.library_models import ImportItem

    auth = enable(monkeypatch)
    monkeypatch.setenv("MAX_CANDIDATE_BYTES", "1024")
    get_settings.cache_clear()
    data = gif()
    valid = manifest_item("shared.gif", data)
    valid["client_item_id"] = "caller-item-1"
    different = manifest_item("shared.gif", gif("green"))
    oversized = manifest_item("large.gif", b"x" * 1025)
    items = [valid, different, oversized, *[manifest_item("copy.gif", data) for _ in range(17)]]
    key = str(uuid4())
    for invalid in ([], [*items, manifest_item("extra.gif", data)]):
        assert (
            client.post(
                "/library/imports",
                headers=auth,
                json={
                    "client_batch_key": key,
                    "items": invalid,
                },
            ).status_code
            == 422
        )
    created = client.post(
        "/library/imports",
        headers=auth,
        json={
            "client_batch_key": key,
            "items": items,
        },
    ).json()
    assert created["counts"] == {"waiting": 19, "imported": 0, "duplicate": 0, "rejected": 1}
    assert created["items"][2]["error_code"] == "file_too_large"
    batch_id = created["batch_id"]
    url = f"/library/imports/{batch_id}/items/{valid['client_item_id']}"
    assert (
        client.put(url, headers=auth, files={"file": ("huge.gif", b"x" * 100_000)}).status_code
        == 413
    )

    def failed_write(*args):
        raise OSError("simulated storage failure")

    with monkeypatch.context() as patch:
        patch.setattr(search, "atomic_write", failed_write)
        response = client.put(url, headers=auth, files={"file": ("shared.gif", data)})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "storage_unavailable"
    assert db_session.get(ImportItem, (batch_id, valid["client_item_id"])).status == "waiting"
    assert (
        client.put(url, headers=auth, files={"file": ("shared.gif", data)}).json()["status"]
        == "imported"
    )
    url = f"/library/imports/{batch_id}/items/{different['client_item_id']}"
    assert (
        client.put(url, headers=auth, files={"file": ("shared.gif", gif("green"))}).json()["status"]
        == "imported"
    )


def test_library_search_covers_old_pages(client, db_session, monkeypatch):
    from datetime import timedelta

    from services.common.models import utcnow

    auth = enable(monkeypatch)
    same_time = utcnow()
    old = SavedAsset(
        sha256=f"{0:064x}",
        title="找回这只无奈的鸭子",
        source_url="",
        image_url="",
        provider="test",
        gif_path="test.gif",
        frame_count=2,
        created_at=same_time - timedelta(days=1),
    )
    db_session.add(old)
    for i in range(1, 150):
        db_session.add(
            SavedAsset(
                sha256=f"{i:064x}",
                title="开心",
                source_url="",
                image_url="",
                provider="test",
                gif_path="test.gif",
                frame_count=2,
                created_at=same_time,
            )
        )
    db_session.commit()
    page = client.get("/library/assets", headers=auth, params={"limit": 100}).json()
    rest = client.get(
        "/library/assets", headers=auth, params={"limit": 100, "cursor": page["next_cursor"]}
    ).json()
    ids = [asset["asset_id"] for asset in [*page["assets"], *rest["assets"]]]
    assert len(set(ids)) == 150 and ids[-1] == old.id
    for _ in range(2):
        result = client.post("/library/search", headers=auth, json={"query": "无奈的鸭子"}).json()
        assert [asset["asset_id"] for asset in result["assets"]] == [old.id]
