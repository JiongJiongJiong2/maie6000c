from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import select, text, tuple_
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import UploadFile

from services.api.app.search import Database, authorize, fail, publish_saved_gif
from services.common.config import get_settings
from services.common.library_models import ImportBatch, ImportItem, LibraryActivation
from services.common.search_models import SavedAsset
from services.common.storage import MediaError, sha256, validate_image


def require_library() -> None:
    if not get_settings().private_library_enabled:
        raise fail(404, "library_disabled", "Private library is disabled")


router = APIRouter(prefix="/library", dependencies=[Depends(require_library), Depends(authorize)])
Key = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^\S+$")]


def file_limit() -> int:
    return min(10 * 1024 * 1024, get_settings().max_candidate_bytes)


class ManifestItem(BaseModel):
    client_item_id: UUID
    filename: str = Field(min_length=1, max_length=1024)
    byte_size: int = Field(ge=0, le=2**31 - 1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Manifest(BaseModel):
    client_batch_key: Key
    items: list[ManifestItem] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_items(self):
        if len({item.client_item_id for item in self.items}) != len(self.items):
            raise ValueError("File IDs must be unique within a batch")
        return self


def display_name(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return (
        "".join(c for c in name if not unicodedata.category(c).startswith("C")).strip()[:200]
        or "GIF"
    )


def commit(db: Database) -> None:
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise fail(503, "database_unavailable", "Library changes could not be committed") from exc


def item_receipt(item: ImportItem) -> dict:
    return {
        name: getattr(item, name)
        for name in (
            "client_item_id",
            "filename",
            "byte_size",
            "sha256",
            "status",
            "asset_id",
            "error_code",
        )
    }


def batch_receipt(db: Database, batch: ImportBatch) -> dict:
    items = [
        item_receipt(item)
        for item in db.scalars(
            select(ImportItem).where(ImportItem.batch_id == batch.id).order_by(ImportItem.position)
        )
    ]
    return {
        "batch_id": batch.id,
        "items": items,
        "counts": {
            status: sum(item["status"] == status for item in items)
            for status in ("waiting", "imported", "duplicate", "rejected")
        },
    }


@router.post("/imports")
def create_import(payload: Manifest, db: Database) -> dict:
    rows = [item.model_dump(mode="json") for item in payload.items]
    for row in rows:
        row["filename"] = display_name(row["filename"])
    normalized = sorted(rows, key=lambda row: row["client_item_id"])
    digest = sha256(json.dumps(normalized, sort_keys=True).encode())
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(41298, hashtext(:key))"),
            {"key": payload.client_batch_key},
        )
    batch = db.scalar(
        select(ImportBatch).where(ImportBatch.client_batch_key == payload.client_batch_key)
    )
    if batch is not None:
        if batch.manifest_sha != digest:
            raise fail(409, "import_key_conflict", "Batch key already binds a different manifest")
        return batch_receipt(db, batch)
    batch = ImportBatch(
        id=str(uuid4()), client_batch_key=payload.client_batch_key, manifest_sha=digest
    )
    db.add(batch)
    db.flush()
    for position, row in enumerate(rows):
        oversized = row["byte_size"] > file_limit()
        db.add(
            ImportItem(
                batch_id=batch.id,
                position=position,
                **row,
                status="rejected" if oversized else "waiting",
                error_code="file_too_large" if oversized else None,
            )
        )
    commit(db)
    return batch_receipt(db, batch)


@router.get("/imports/{batch_id}")
def read_import(batch_id: UUID, db: Database) -> dict:
    batch = db.get(ImportBatch, str(batch_id))
    if batch is None:
        raise fail(404, "import_not_found", "Batch not found")
    return batch_receipt(db, batch)


async def bounded_file(request: Request) -> bytes:
    limit = file_limit()
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "multipart/form-data":
        raise fail(415, "multipart_required", "Upload a multipart file")
    received = 0

    async def receive():
        nonlocal received
        message = await request.receive()
        received += len(message.get("body", b""))
        if received > limit + 16 * 1024:
            raise fail(413, "file_too_large", "Multipart body exceeds the upload limit")
        return message

    # Keep the parser's spool and close uploaded files on an interrupted body.
    bounded = Request(request.scope, receive)
    async with bounded.form(max_files=1, max_fields=0) as form:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise fail(422, "file_required", "Expected one multipart field named file")
        data = await upload.read(limit + 1)
    if len(data) > limit:
        raise fail(413, "file_too_large", "GIF exceeds the upload limit")
    return data


@router.put("/imports/{batch_id}/items/{client_item_id}")
def upload_item(
    batch_id: UUID,
    client_item_id: UUID,
    db: Database,
    data: Annotated[bytes, Depends(bounded_file)],
) -> dict:
    item = db.scalar(
        select(ImportItem)
        .where(
            ImportItem.batch_id == str(batch_id), ImportItem.client_item_id == str(client_item_id)
        )
        .with_for_update()
    )
    if item is None:
        raise fail(404, "item_not_found", "Import item not found")
    if len(data) != item.byte_size or sha256(data) != item.sha256:
        raise fail(409, "file_mismatch", "File differs from the batch manifest")
    if item.status != "waiting":
        return item_receipt(item)

    try:
        if not item.filename.lower().endswith(".gif") or not data.rstrip(b"\0").endswith(b";"):
            raise MediaError("Expected a complete GIF")
        frames = validate_image(data, animated_gif=True)
    except MediaError:
        item.status = "rejected"
        item.error_code = "invalid_animated_gif"
    else:
        asset, created = publish_saved_gif(
            db, data, frame_count=frames, title=item.filename, provider="local_upload"
        )
        db.flush()
        item.asset_id = asset.id
        item.status = "imported" if created else "duplicate"
    commit(db)
    return item_receipt(item)


def asset_card(asset: SavedAsset) -> dict:
    return {
        "asset_id": asset.id,
        "title": asset.title,
        "frame_count": asset.frame_count,
        "media_url": f"/saved-assets/{asset.id}/media",
        "index_status": asset.index_status,
        "annotation_status": "not_requested",
        "tags": [],
    }


@router.get("/assets")
def list_assets(
    db: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=90)] = None,
) -> dict:
    statement = select(SavedAsset).order_by(SavedAsset.created_at.desc(), SavedAsset.id.desc())
    if cursor:
        try:
            timestamp, asset_id = cursor.split("|", 1)
            after = (datetime.fromisoformat(timestamp), str(UUID(asset_id)))
        except ValueError as exc:
            raise fail(422, "invalid_cursor", "Invalid library cursor") from exc
        statement = statement.where(tuple_(SavedAsset.created_at, SavedAsset.id) < after)
    assets = list(db.scalars(statement.limit(limit + 1)))
    page = assets[:limit]
    next_cursor = None
    if len(assets) > limit:
        next_cursor = f"{page[-1].created_at.isoformat()}|{page[-1].id}"
    return {"assets": [asset_card(asset) for asset in page], "next_cursor": next_cursor}


def activate_library(db: Database) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(41298, 0)"))
    if db.get(LibraryActivation, 1) is None:
        db.add(LibraryActivation(id=1))
    commit(db)
