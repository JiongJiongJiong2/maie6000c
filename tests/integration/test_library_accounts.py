import io
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from services.api.app.main import app
from services.common import db as database
from services.common.accounts import digest, issue_owner_setup, registry
from services.common.config import get_settings
from services.common.search_models import SavedAsset
from services.common.storage import atomic_write, sha256


def verify_account_libraries(engine):
    red = Image.new("RGB", (10, 10), "red")
    buf = io.BytesIO()
    red.save(buf, "GIF", save_all=True, append_images=[Image.new("RGB", red.size, "blue")])
    gif = buf.getvalue()
    checksum = sha256(gif)
    path = f"saved/{checksum}.gif"
    atomic_write(get_settings().media_root, path, gif)
    with database.make_session_factory(engine)() as db:
        old = SavedAsset(
            title="Original cat",
            sha256=checksum,
            source_url="",
            image_url="",
            provider="local_upload",
            gif_path=path,
            frame_count=2,
        )
        db.add(old)
        db.commit()
        old_id = old.id

    setup = issue_owner_setup()
    password = "test-library-password"
    bob = {"username": "2", "password": password}
    alice = {"username": "1", "password": password}
    with TestClient(app) as a, TestClient(app) as b, TestClient(app) as owner:
        assert (
            a.get("/library/assets", headers={"Authorization": "Bearer obsolete"}).status_code
            == 401
        )
        assert b.post("/auth/register", json=bob).status_code == 201
        response = a.post("/auth/register", json=alice)
        assert response.status_code == 201
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "Max-Age=" in response.headers["set-cookie"]
        assert a.get("/library/assets").json()["assets"] == []
        assert b.get(f"/saved-assets/{old_id}/media").status_code == 404
        assert b.post("/auth/register", json=bob).status_code == 409

        item = {
            "client_item_id": "file1",
            "filename": "new-dance.gif",
            "sha256": checksum,
            "byte_size": len(gif),
        }
        manifest = {"client_batch_key": str(uuid4()), "items": [item]}

        def upload(client):
            batch = client.post("/library/imports", json=manifest).json()["batch_id"]
            result = client.put(
                f"/library/imports/{batch}/items/file1",
                files={"file": ("new-dance.gif", gif, "image/gif")},
            ).json()
            assert result["status"] == "imported"
            return batch, result["asset_id"]

        batch, aid = upload(a)
        for path in [
            f"/library/imports/{batch}",
            f"/library/assets/{aid}",
            f"/saved-assets/{aid}/media",
        ]:
            assert b.get(path).status_code == 404
        assert b.post("/library/search", json={"query": "dance"}).json()["assets"] == []
        assert (
            b.post(
                "/library/assets/bulk-tags", json={"asset_ids": [aid], "tags": ["oops"]}
            ).status_code
            == 404
        )
        _, bid = upload(b)
        assert aid != bid and aid != old_id
        assert a.get(f"/saved-assets/{aid}/media").content == gif
        assert b.get(f"/saved-assets/{bid}/media").content == gif
        assert a.get("/library/assets", headers={"X-Library-Account": "2"}).status_code == 401

        original = {"username": "owner", "password": password, "owner_setup": setup}
        assert owner.post("/auth/register", json=original).status_code == 201
        assert [row["asset_id"] for row in owner.get("/library/assets").json()["assets"]] == [
            old_id
        ]
        assert owner.get(f"/saved-assets/{old_id}/media").content == gif
        assert issue_owner_setup() == ""
        assert b.post("/auth/register", json={**original, "username": "other"}).status_code == 409

        previous = a.cookies.get("memeretrieve_session")
        assert a.post("/auth/logout").status_code == 200
        assert (
            a.get(
                "/library/assets", headers={"Cookie": f"memeretrieve_session={previous}"}
            ).status_code
            == 401
        )
        assert a.post("/auth/login", json={**alice, "password": "incorrect"}).status_code == 401
        assert a.post("/auth/login", json=alice).status_code == 200
        assert [x["asset_id"] for x in a.get("/library/assets").json()["assets"]] == [aid]
        from services.common.accounts import sessions

        with engine.begin() as conn:
            conn.execute(
                sessions.update()
                .where(sessions.c.digest == digest(a.cookies.get("memeretrieve_session")))
                .values(expires=0)
            )
        assert a.get("/library/assets").status_code == 401


def test_private_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'accounts.db'}")
    monkeypatch.setenv("PRIVATE_LIBRARY_ENABLED", "true")
    monkeypatch.setenv("ACCOUNT_LOGIN_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(database, "_ENGINE", None)
    monkeypatch.setattr(database, "_SESSION_FACTORY", None)
    engine = database.get_engine()
    database.Base.metadata.create_all(engine)
    registry.create_all(engine)
    try:
        verify_account_libraries(engine)
    finally:
        engine.dispose()
