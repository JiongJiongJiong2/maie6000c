import io

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from services.meme_agent.app import create_app
from services.meme_agent.settings import AgentSettings


def image_bytes(animated=False):
    out = io.BytesIO()
    image = Image.new("RGB", (180, 180), "red")
    if animated:
        image.save(
            out,
            format="GIF",
            save_all=True,
            append_images=[Image.new("RGB", image.size, "blue")],
            duration=100,
            loop=0,
        )
    else:
        image.save(out, format="PNG")
    return out.getvalue()


def encode(image):
    return np.array([1, 2, 3], dtype=np.float32)


def settings(tmp_path):
    return AgentSettings(
        data_root=tmp_path, deepseek_api_key="secret-test", brave_api_key="", _env_file=None
    )


def upload(client, data=None, blank=True):
    return client.post(
        "/api/import",
        files={"image": ("test.png", data or image_bytes(), "image/png")},
        data={"title": "猫", "blank_template": str(blank).lower()},
    )


def test_workflow_and_restart(tmp_path):
    with TestClient(create_app(settings(tmp_path), encode)) as client:
        assert "secret-test" not in client.get("/api/config").text
        base = upload(client).json()
        assert not base["saved"] and client.get("/api/library").json()["items"] == []
        result = client.post(
            f"/api/candidates/{base['id']}/edit", json={"top_text": "HELLO", "bottom_text": ""}
        )
        assert result.status_code == 200, result.text
        edited = result.json()
        assert edited["format"] == "PNG" and edited["parent_id"] == base["id"]
        assert (
            client.post(
                f"/api/candidates/{edited['id']}/edit", json={"top_text": "again"}
            ).status_code
            == 422
        )
        saved = client.post(f"/api/candidates/{edited['id']}/save", json={}).json()
        assert saved["item"]["saved"] and not saved["duplicate"]
        assert client.post(f"/api/candidates/{edited['id']}/save", json={}).json()["duplicate"]
    with TestClient(create_app(settings(tmp_path), encode)) as client:
        assert len(client.get("/api/library").json()["items"]) == 1
        result = client.post("/api/search", data={"query": "猫", "scope": "library"})
        assert result.status_code == 200 and result.json()["candidates"][0]["id"] == edited["id"]


def test_invalid_requests_and_origin(tmp_path):
    with TestClient(create_app(settings(tmp_path), encode)) as client:
        assert upload(client, b"not an image").status_code == 422
        for item in (upload(client, blank=False).json(), upload(client, image_bytes(True)).json()):
            assert (
                client.post(
                    f"/api/candidates/{item['id']}/edit", json={"top_text": "x"}
                ).status_code
                == 422
            )
        assert client.post("/api/candidates/missing/save", json={}).status_code == 404
        assert (
            client.get("/api/health", headers={"origin": "https://evil.example"}).status_code == 403
        )
        assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403


def test_missing_model_does_not_save(tmp_path):
    def broken(image):
        raise RuntimeError("unavailable")

    with TestClient(create_app(settings(tmp_path), broken)) as client:
        item = upload(client).json()
        result = client.post(f"/api/candidates/{item['id']}/save", json={})
        assert result.status_code == 503
        assert client.get("/api/library").json()["items"] == []
