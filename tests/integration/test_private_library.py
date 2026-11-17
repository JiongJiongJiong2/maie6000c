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
