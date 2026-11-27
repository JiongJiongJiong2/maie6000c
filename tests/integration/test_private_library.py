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
                            '{"ocr_text":"就这？","caption_zh":"一只猫拍手",'
                            '"caption_en":"A cat claps.","subject_tags":["猫"],'
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
        assert found["caption_en"] == "A cat claps."
        assert found["match_reasons_en"]
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


def test_backup_round_trip_into_clean_library(client, db_session, monkeypatch, tmp_path):
    from zipfile import ZipFile

    from services.api.app.main import app
    from services.common.db import Base, get_db, make_engine, make_session_factory
    from services.common.library_models import AssetMetadata

    auth = enable(monkeypatch)

    def send_batch(key, files):
        manifest = [manifest_item(name, data) for name, data in files]
        result = client.post(
            "/library/imports", headers=auth, json={"client_batch_key": key, "items": manifest}
        )
        assert result.status_code == 200, result.text
        batch_id = result.json()["batch_id"]
        for entry, (name, data) in zip(manifest, files, strict=True):
            item_id = entry["client_item_id"]
            sent = client.put(
                f"/library/imports/{batch_id}/items/{item_id}",
                headers=auth,
                files={"file": (name, data)},
            )
            assert sent.status_code == 200, sent.text
        return client.get(f"/library/imports/{batch_id}", headers=auth).json()

    originals = [("same-name.gif", gif((i * 7, 20, 80))) for i in range(28)]
    source_batches = [
        send_batch("source-1", originals[:20]),
        send_batch("source-2", [*originals[20:], originals[0], ("broken.gif", b"GIF89a")]),
    ]
    assert [batch["counts"] for batch in source_batches] == [
        {"imported": 20, "duplicate": 0, "rejected": 0, "waiting": 0},
        {"imported": 8, "duplicate": 1, "rejected": 1, "waiting": 0},
    ]
    ids = [
        item["asset_id"]
        for batch in source_batches
        for item in batch["items"]
        if item["status"] == "imported"
    ]
    assert len(ids) == 28
    applied = client.post(
        "/library/assets/bulk-tags",
        headers=auth,
        json={"asset_ids": ids, "tags": ["项目", "备份", "项目"]},
    )
    assert applied.json() == {"updated": 28}
    edited = client.patch(
        f"/library/assets/{ids[0]}", headers=auth, json={"title": "手工标题", "ocr_text": "原文"}
    )
    assert edited.status_code == 200
    meta = db_session.get(AssetMetadata, ids[0])
    meta.annotation = {
        "ocr_text": "AI 原文",
        "caption_zh": "描述",
        "subject_tags": [],
        "action_tags": [],
        "emotion_tags": ["好奇"],
        "version": "hkust/demo/test",
        "sha256": sha256(originals[0][1]),
        "sampled_frames": [{"frame_index": 1, "time_ms": 100}],
    }
    meta.annotation_version = meta.annotation["version"]
    meta.annotation_sha = meta.annotation["sha256"]
    meta.annotation_status = "ready"
    db_session.commit()
    filtered = client.get(
        "/library/assets",
        headers=auth,
        params={
            "tag": "备份",
            "title": "手工",
            "state": "ai:ready",
        },
    ).json()
    assert [item["asset_id"] for item in filtered["assets"]] == [ids[0]]
    assert client.get(f"/library/assets/{ids[0]}", headers=auth).json()["title"] == "手工标题"

    payload = {
        "asset_ids": ids,
        "profile": "original_zip",
        "include_manual": True,
        "include_annotations": True,
    }
    assert client.post("/library/exports", json=payload).status_code == 401
    exported = client.post("/library/exports", headers=auth, json=payload)
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(exported.content)) as archive:
        import json

        manifest = json.loads(archive.read("manifest.json"))
        assert len(manifest["assets"]) == 28
        files = {entry["sha256"]: archive.read(entry["path"]) for entry in manifest["assets"]}
        assert set(archive.namelist()) == {
            "manifest.json",
            *[f"assets/{digest}.gif" for digest in files],
        }
        assert files == {sha256(data): data for _, data in originals}
    primary = next(entry for entry in manifest["assets"] if entry["title"] == "手工标题")
    assert primary["manual"]["tags"] == ["项目", "备份"]
    assert primary["annotation"]["sampled_frames"] == [{"frame_index": 1, "time_ms": 100}]

    engine = make_engine(f"sqlite:///{tmp_path / 'backup-destination.db'}")
    Base.metadata.create_all(engine)
    previous = app.dependency_overrides[get_db]
    with make_session_factory(engine)() as dest:
        app.dependency_overrides[get_db] = lambda: dest
        try:
            monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "backup-destination-media"))
            get_settings.cache_clear()
            assert not client.get("/library/assets", headers=auth).json()["assets"]
            restore_files = [(f"{digest}.gif", data) for digest, data in files.items()]
            batches = [restore_files[:20], restore_files[20:]]
            first = send_batch("restore-1", batches[0])
            assert first["counts"]["imported"] == 20
            absent = sha256(batches[1][0][1])
            request = {"manifest": manifest, "uploaded_sha256": list(files)}
            partial = client.post("/library/restores/metadata", headers=auth, json=request)
            assert partial.status_code == 200, partial.text
            assert sum(item["status"] == "restored" for item in partial.json()["items"]) == 20
            assert (
                next(item for item in partial.json()["items"] if item["sha256"] == absent)[
                    "error_code"
                ]
                == "backup_asset_missing"
            )
            assert send_batch("restore-2", batches[1])["counts"]["imported"] == 8
            restored = client.post("/library/restores/metadata", headers=auth, json=request)
            assert all(item["status"] == "restored" for item in restored.json()["items"])
            assert client.post("/library/restores/metadata", headers=auth, json=request).json() == (
                restored.json()
            )
            by_digest = {item["sha256"]: item["asset_id"] for item in restored.json()["items"]}
            for digest, asset_id in by_digest.items():
                asset = client.get(f"/library/assets/{asset_id}", headers=auth).json()
                response = client.get(asset["media_url"], headers=auth)
                assert response.content == files[digest]
                assert asset["frame_count"] == 2
                assert asset["manual"]["tags"] == ["项目", "备份"]
            asset_id = by_digest[primary["sha256"]]
            restored_primary = client.get(f"/library/assets/{asset_id}", headers=auth).json()
            assert restored_primary["ocr_text"] == "原文"
            assert restored_primary["annotation_status"] == "ready"
            assert restored_primary["annotation_result_version"] == "hkust/demo/test"
            assert send_batch("restore-repeat", batches[1])["counts"]["duplicate"] == 8
            assert len(client.get("/library/assets?limit=100", headers=auth).json()["assets"]) == 28
        finally:
            app.dependency_overrides[get_db] = previous
    engine.dispose()


def backup_projection(items):
    return {
        "version": 1,
        "profile": "original_zip",
        "assets": [
            {
                "sha256": item["sha256"],
                "byte_size": item["byte_size"],
                "path": f"assets/{item['sha256']}.gif",
            }
            for item in items
        ],
    }


def test_restore_uses_stored_purpose_for_manifest_and_body(client, monkeypatch):
    from services.api.app.library import file_limit

    auth = enable(monkeypatch)
    monkeypatch.setenv("MAX_CANDIDATE_BYTES", str(11 * 1024**2))
    get_settings.cache_clear()
    ordinary_limit = 10 * 1024**2
    restore_limit = 11 * 1024**2
    assert file_limit("upload") == ordinary_limit
    body = gif()
    # Legal GIF comment sub-blocks keep the complete animation intact.
    remaining = restore_limit - len(body) - 3
    comment = bytearray(b"\x21\xfe")
    while remaining:
        count = min(255, remaining - 1)
        assert count
        comment.extend(bytes([count]) + b"x" * count)
        remaining -= count + 1
    large = body[:-1] + comment + b"\x00;"
    assert len(large) == restore_limit
    entries = [
        manifest_item("large.gif", large),
        {**manifest_item("over.gif", b"over"), "byte_size": restore_limit + 1},
        {**manifest_item("ordinary-boundary.gif", b"boundary"), "byte_size": ordinary_limit},
    ]

    for item in entries:
        item["filename"] = f"{item['sha256']}.gif"

    def create(key, purpose=None):
        payload = {"client_batch_key": key, "items": entries}
        if purpose is not None:
            payload["purpose"] = purpose
        if purpose == "backup_restore":
            payload["backup"] = backup_projection(entries)
        return client.post("/library/imports", headers=auth, json=payload)

    ordinary = create("ordinary").json()
    backup = create("restore", "backup_restore").json()
    assert ordinary["purpose"] == "upload"
    assert [i["status"] for i in ordinary["items"]] == ["rejected", "rejected", "waiting"]
    assert [i["status"] for i in backup["items"]] == ["waiting", "rejected", "waiting"]
    assert create("ordinary", "upload").json() == ordinary
    assert create("ordinary", "backup_restore").status_code == 409
    assert create("restore").status_code == 409

    def upload(batch, data):
        path = f"/library/imports/{batch['batch_id']}/items/{entries[0]['client_item_id']}"
        return client.put(path, headers=auth, files={"file": ("large.gif", data)})

    assert upload(ordinary, large).status_code == 413
    assert upload(backup, large + b"x").status_code == 413
    assert upload(backup, large + b"x" * (17 * 1024)).status_code == 413
    saved = upload(backup, large).json()
    assert saved["status"] == "imported"
    assert upload(backup, large).json() == saved
    assert (
        upload(create("restore-again", "backup_restore").json(), large).json()["asset_id"]
        == saved["asset_id"]
    )


def test_backup_manifest_binding_and_legacy_replay(client, db_session, monkeypatch):
    import copy
    import json

    from sqlalchemy import select

    from services.common.library_models import ImportBatch, ImportItem

    auth = enable(monkeypatch)
    data = gif()
    items = [manifest_item("a.gif", data), manifest_item("b.gif", gif("green"))]
    for item in items:
        item["filename"] = f"{item['sha256']}.gif"
    payload = {
        "client_batch_key": "bound",
        "purpose": "backup_restore",
        "items": items,
        "backup": backup_projection(items),
    }

    def create(body):
        return client.post("/library/imports", headers=auth, json=body)

    def without_backup(body):
        body.pop("backup")

    missing = copy.deepcopy(payload)
    without_backup(missing)
    assert create(missing).json()["detail"]["code"] == "backup_manifest_required"
    for change in [
        lambda p: p["backup"].update(version=True),
        lambda p: p["backup"].update(version=2),
        lambda p: p["backup"].update(profile="other"),
        lambda p: p["backup"]["assets"].append(p["backup"]["assets"][0]),
        lambda p: p["backup"]["assets"][0].update(path="../foo.gif"),
        lambda p: p["items"][0].update(filename="../" + p["items"][0]["filename"]),
        lambda p: p["backup"]["assets"].pop(),
        lambda p: p["items"].pop(),
        lambda p: p["backup"]["assets"][0].update(sha256="0" * 64),
        lambda p: p["backup"]["assets"][0].update(byte_size=999),
    ]:
        invalid = copy.deepcopy(payload)
        change(invalid)
        response = create(invalid)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "backup_manifest_invalid"
    assert not list(db_session.scalars(select(ImportBatch)))
    assert not list(db_session.scalars(select(ImportItem)))

    first = create(payload).json()
    reordered = copy.deepcopy(payload)
    reordered["items"].reverse()
    reordered["backup"]["assets"].reverse()
    assert create(reordered).json() == first
    assert create(missing).status_code == 409
    assert create({**payload, "purpose": "upload"}).status_code == 409
    assert (
        create({**payload, "items": items[:1], "backup": backup_projection(items[:1])}).status_code
        == 409
    )

    # Seed exactly the digest and row shape written by e015921.
    for purpose in ("upload", "backup_restore"):
        old = {**items[0], "filename": "legacy.gif"}
        batch_id = str(uuid4())
        key = f"legacy-{purpose}"
        db_session.add(
            ImportBatch(
                id=batch_id,
                client_batch_key=key,
                purpose=purpose,
                manifest_sha=sha256(json.dumps([old], sort_keys=True).encode()),
            )
        )
        db_session.flush()
        db_session.add(ImportItem(batch_id=batch_id, position=0, **old))
        db_session.commit()
        original = {"client_batch_key": key, "items": [old]}
        if purpose == "backup_restore":
            original["purpose"] = purpose
        assert create(original).json()["batch_id"] == batch_id
        changed = {**original, "items": [{**old, "byte_size": len(data) + 1}]}
        assert create(changed).status_code == 409
        path = f"/library/imports/{batch_id}/items/{old['client_item_id']}"
        assert (
            client.put(path, headers=auth, files={"file": ("legacy.gif", data[:-1])}).status_code
            == 409
        )
        exact = client.put(path, headers=auth, files={"file": ("legacy.gif", data)})
        assert exact.json()["status"] in {"imported", "duplicate"}
        assert create(original).json()["items"][0] == exact.json()
