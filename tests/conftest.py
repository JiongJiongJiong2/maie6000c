from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import app
from services.common.db import Base, get_db, make_engine, make_session_factory
from services.common.config import get_settings


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch, request):
    if request.node.get_closest_marker("smoke") is not None:
        yield
        return
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("REFERENCE_ROOT", str(tmp_path / "reference"))
    monkeypatch.setenv("MODEL_CACHE_ROOT", str(tmp_path / "models"))
    monkeypatch.setenv("DEVICE_TOKEN", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def db_session(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_engine(database_url)
    testing_session_factory = make_session_factory(engine)

    Base.metadata.create_all(bind=engine)
    session = testing_session_factory()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
