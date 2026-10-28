from __future__ import annotations

import io
import json
import sqlite3
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import event, func, select

from services.common import reference_assets
from services.common.config import get_settings
from services.common.db import make_session_factory
from services.common.search_models import ReferenceAsset
from services.common.storage import atomic_write, prepare_storage, sha256


def test_manifest_validation_idempotency_and_versioning(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(
        reference_assets,
        "get_session_factory",
        lambda: make_session_factory(db_session.get_bind()),
    )
    prepare_storage()
    output = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(
        output,
        "GIF",
        save_all=True,
        append_images=[Image.new("RGB", (4, 4), "blue")],
        duration=100,
    )
    data = output.getvalue()
    atomic_write(get_settings().reference_root, "test.gif", data)
    asset_id = str(uuid4())
    manifest = {
        "corpus_version": "v1",
        "assets": [
            {
                "reference_asset_id": asset_id,
                "title": "Generated GIF",
                "source_reference": "generated",
                "permission_note": "Test generated",
                "gif_path": "test.gif",
                "sha256": sha256(data),
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert reference_assets.import_manifest(path) == 1
    assert reference_assets.import_manifest(path) == 1
    manifest["corpus_version"] = "v2"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert reference_assets.import_manifest(path) == 1
    db_session.expire_all()
    assert db_session.get(ReferenceAsset, asset_id).corpus_version == "v2"
    assert db_session.scalar(select(func.count()).select_from(ReferenceAsset)) == 1
    duplicate_content = json.loads(json.dumps(manifest))
    duplicate_content["assets"][0]["reference_asset_id"] = str(uuid4())
    path.write_text(json.dumps(duplicate_content), encoding="utf-8")
    with pytest.raises(ValueError, match="already belongs to reference asset"):
        reference_assets.import_manifest(path)
    assert db_session.scalar(select(func.count()).select_from(ReferenceAsset)) == 1

    manifest["assets"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        reference_assets.import_manifest(path)


def test_invalid_manifest_is_rejected_before_opening_database(
    monkeypatch,
    tmp_path,
):
    prepare_storage()
    output = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(
        output,
        "GIF",
        save_all=True,
        append_images=[Image.new("RGB", (4, 4), "blue")],
        duration=100,
    )
    data = output.getvalue()
    atomic_write(get_settings().reference_root, "valid.gif", data)
    atomic_write(get_settings().reference_root, "invalid.gif", data)
    manifest = {
        "corpus_version": "v1",
        "assets": [
            {
                "reference_asset_id": str(uuid4()),
                "title": "First GIF",
                "source_reference": "generated",
                "permission_note": "Test generated",
                "gif_path": "valid.gif",
                "sha256": sha256(data),
            },
            {
                "reference_asset_id": str(uuid4()),
                "title": "Second GIF",
                "source_reference": "generated",
                "permission_note": "Test generated",
                "gif_path": "invalid.gif",
                "sha256": "0" * 64,
            },
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def database_must_not_be_opened():
        raise AssertionError("Database session opened before manifest preflight completed")

    monkeypatch.setattr(reference_assets, "get_session_factory", database_must_not_be_opened)
    with pytest.raises(ValueError, match="checksum mismatch"):
        reference_assets.import_manifest(path)
    manifest["assets"][1]["sha256"] = manifest["assets"][0]["sha256"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate GIF checksums"):
        reference_assets.import_manifest(path)


def test_manifest_import_queries_existing_assets_per_batch(
    db_session,
    monkeypatch,
    tmp_path,
):
    engine = db_session.get_bind()
    monkeypatch.setattr(
        reference_assets,
        "get_session_factory",
        lambda: make_session_factory(engine),
    )
    assets = []
    for index in range(401):
        gif_path = f"synthetic-{index}.gif"
        data = gif_path.encode("ascii")
        assets.append(
            {
                "reference_asset_id": str(uuid4()),
                "title": f"Generated GIF {index}",
                "source_reference": "generated",
                "permission_note": "Test generated",
                "gif_path": gif_path,
                "sha256": sha256(data),
            }
        )
    monkeypatch.setattr(
        reference_assets,
        "read_gif",
        lambda gif_path: (str(gif_path).encode("ascii"), 2),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"corpus_version": "batch-v1", "assets": assets}),
        encoding="utf-8",
    )
    catalog_selects = []

    def count_catalog_selects(connection, _cursor, statement, _parameters, _context, _many):
        del _cursor, _parameters, _context, _many
        if statement.lstrip().lower().startswith("select") and "reference_assets" in statement:
            connection.connection.driver_connection.setlimit(
                sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER,
                999,
            )
            catalog_selects.append(statement)

    event.listen(engine, "before_cursor_execute", count_catalog_selects)
    try:
        assert reference_assets.import_manifest(manifest_path) == 401
    finally:
        event.remove(engine, "before_cursor_execute", count_catalog_selects)

    assert len(catalog_selects) == 2
    assert db_session.scalar(select(func.count()).select_from(ReferenceAsset)) == 401


def test_checksum_conflict_in_later_batch_rolls_back_earlier_batches(
    db_session,
    monkeypatch,
    tmp_path,
):
    engine = db_session.get_bind()
    monkeypatch.setattr(
        reference_assets,
        "get_session_factory",
        lambda: make_session_factory(engine),
    )
    existing_data = b"existing catalog asset"
    db_session.add(
        ReferenceAsset(
            id=str(uuid4()),
            sha256=sha256(existing_data),
            title="Existing asset",
            source_reference="generated",
            permission_note="Test generated",
            gif_path="existing.gif",
            frame_count=2,
            corpus_version="v1",
        )
    )
    db_session.commit()

    assets = []
    for index in range(401):
        gif_path = f"synthetic-{index}.gif"
        data = existing_data if index == 400 else gif_path.encode("ascii")
        assets.append(
            {
                "reference_asset_id": str(uuid4()),
                "title": f"Generated GIF {index}",
                "source_reference": "generated",
                "permission_note": "Test generated",
                "gif_path": gif_path,
                "sha256": sha256(data),
            }
        )
    def read_synthetic_gif(gif_path):
        data = (
            b"existing catalog asset"
            if gif_path == "synthetic-400.gif"
            else str(gif_path).encode()
        )
        return data, 2

    monkeypatch.setattr(reference_assets, "read_gif", read_synthetic_gif)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"corpus_version": "batch-v2", "assets": assets}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="already belongs to reference asset"):
        reference_assets.import_manifest(manifest_path)

    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(ReferenceAsset)) == 1
