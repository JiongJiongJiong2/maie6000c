from contextlib import nullcontext
from pathlib import Path

from services.common.config import get_settings


def test_create_case_enqueues_job(client):
    response = client.post(
        "/cases",
        json={
            "title": "Cannot login",
            "description": "User cannot access the dashboard after password reset.",
        },
    )

    assert response.status_code == 201
    data = response.json()

    assert data["case"]["status"] == "queued"
    assert data["job"]["status"] == "pending"

    case_id = data["case"]["id"]
    get_case = client.get(f"/cases/{case_id}")

    assert get_case.status_code == 200
    assert get_case.json()["title"] == "Cannot login"


def test_health_ready(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_ready_only_writes_to_mutable_storage(client, monkeypatch):
    checked_directories: list[Path] = []

    def check_writeable_directory(*, dir):
        checked_directories.append(Path(dir))
        return nullcontext()

    monkeypatch.setattr(
        "services.api.app.main.tempfile.TemporaryFile",
        check_writeable_directory,
    )

    response = client.get("/health/ready")

    settings = get_settings()
    assert response.status_code == 200
    assert settings.reference_root not in checked_directories
    assert set(checked_directories) == {
        settings.media_root / "inputs",
        settings.media_root / "candidates",
        settings.model_cache_root,
    }
