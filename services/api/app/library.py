from __future__ import annotations

import heapq
import json
import unicodedata
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import BaseModel, Field, StrictBool, StringConstraints, model_validator
from sqlalchemy import select, text, tuple_
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import UploadFile

from services.api.app.library_rank import prepare_query, rank
from services.api.app.search import Database, authorize, fail, publish_saved_gif
from services.common.config import get_settings
from services.common.library_metadata import MetadataEdit, annotation_version, effective_labels
from services.common.library_models import (
    AssetMetadata,
    ImportBatch,
    ImportItem,
    LibraryActivation,
    SimilarityScan,
)
from services.common.models import utcnow
from services.common.search_models import SavedAsset
from services.common.storage import MediaError, sha256, validate_image
from services.search_agent.meme_types import MemeSettings


def require_library(response: Response) -> None:
    if not get_settings().private_library_enabled:
        raise fail(404, "library_disabled", "Private library is disabled")
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/library", dependencies=[Depends(require_library), Depends(authorize)])
Key = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^\S+$")]


def file_limit() -> int:
    return min(10 * 1024 * 1024, get_settings().max_candidate_bytes)


ItemKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class ManifestItem(BaseModel):
    client_item_id: ItemKey
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
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit + 16 * 1024:
            raise fail(413, "file_too_large", "Multipart body exceeds the upload limit")
        body.extend(chunk)

    async def receive():
        return {"type": "http.request", "body": bytes(body), "more_body": False}

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
    client_item_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,128}$")],
    db: Database,
    data: Annotated[bytes, Depends(bounded_file)],
) -> dict:
    item = db.scalar(
        select(ImportItem)
        .where(ImportItem.batch_id == str(batch_id), ImportItem.client_item_id == client_item_id)
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
        try:
            db.flush()
        except SQLAlchemyError as exc:
            db.rollback()
            raise fail(503, "database_unavailable", "GIF could not be published") from exc
        item.asset_id = asset.id
        item.status = "imported" if created else "duplicate"
    commit(db)
    return item_receipt(item)


def asset_card(
    asset: SavedAsset, metadata: AssetMetadata | None = None, scan: SimilarityScan | None = None
) -> dict:
    annotation = (metadata.annotation or {}) if metadata else {}
    manual = metadata.manual if metadata else {}
    labels = effective_labels(manual, annotation)
    return {
        "asset_id": asset.id,
        "title": (metadata.title if metadata else None) or asset.title,
        "frame_count": asset.frame_count,
        "media_url": f"/saved-assets/{asset.id}/media",
        "index_status": asset.index_status,
        "annotation_status": metadata.annotation_status if metadata else "not_requested",
        "annotation_error": metadata.annotation_error if metadata else None,
        "annotation_version": metadata.annotation_version if metadata else None,
        "sampled_frames": annotation.get("sampled_frames", []),
        "annotation_result_version": annotation.get("version"),
        "caption_zh": annotation.get("caption_zh", ""),
        "ocr_text": manual.get("ocr_text", annotation.get("ocr_text", "")),
        "ocr_uncertain": "ocr_text" not in manual and annotation.get("ocr_uncertain", False),
        "tags": list(
            dict.fromkeys(
                [
                    *manual.get("tags", []),
                    *(tag for category in labels.values() for tag in category),
                ]
            )
        ),
        "manual": manual,
        "labels": labels,
        "possible_duplicates": scan.matches if scan else [],
        "similarity_coverage": {
            "considered": scan.considered,
            "compared": scan.compared,
            "available": scan.available,
        }
        if scan
        else None,
    }


def asset_rows():
    return (
        select(SavedAsset, AssetMetadata, SimilarityScan)
        .outerjoin(AssetMetadata, AssetMetadata.asset_id == SavedAsset.id)
        .outerjoin(SimilarityScan, SimilarityScan.asset_id == SavedAsset.id)
        .order_by(SavedAsset.created_at.desc(), SavedAsset.id.desc())
    )


@router.get("/assets")
def list_assets(
    db: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=90)] = None,
) -> dict:
    statement = asset_rows()
    if cursor:
        try:
            timestamp, asset_id = cursor.split("|", 1)
            after = (datetime.fromisoformat(timestamp), str(UUID(asset_id)))
        except ValueError as exc:
            raise fail(422, "invalid_cursor", "Invalid library cursor") from exc
        statement = statement.where(tuple_(SavedAsset.created_at, SavedAsset.id) < after)
    assets = list(db.execute(statement.limit(limit + 1)))
    page = assets[:limit]
    next_cursor = None
    if len(assets) > limit:
        next_cursor = f"{page[-1][0].created_at.isoformat()}|{page[-1][0].id}"
    return {"assets": [asset_card(*row) for row in page], "next_cursor": next_cursor}


def activate_library(db: Database) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(41298, 0)"))
    if db.get(LibraryActivation, 1) is None:
        db.add(LibraryActivation(id=1))
    commit(db)


def lock_asset(db: Database, asset_id: UUID) -> SavedAsset:
    asset = db.scalar(select(SavedAsset).where(SavedAsset.id == str(asset_id)).with_for_update())
    if asset is None:
        raise fail(404, "asset_not_found", "Saved GIF not found")
    return asset


def metadata_for_edit(db: Database, asset: SavedAsset) -> AssetMetadata:
    metadata = db.scalar(
        select(AssetMetadata).where(AssetMetadata.asset_id == asset.id).with_for_update()
    )
    if metadata is None:
        metadata = AssetMetadata(asset_id=asset.id)
        db.add(metadata)
        db.flush()
    return metadata


@router.patch("/assets/{asset_id}")
def edit_asset(asset_id: UUID, payload: MetadataEdit, db: Database) -> dict:
    asset = lock_asset(db, asset_id)
    metadata = metadata_for_edit(db, asset)
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes:
        metadata.title = changes.pop("title")
    manual = dict(metadata.manual)
    for category, value in changes.items():
        if value is None:
            manual.pop(category, None)
        else:
            manual[category] = value
    metadata.manual = manual
    commit(db)
    return asset_card(asset, metadata, db.get(SimilarityScan, asset.id))


class AnnotationRequest(BaseModel):
    asset_ids: list[UUID] = Field(min_length=1, max_length=20)
    consent: StrictBool


@router.post("/annotations")
def request_annotations(payload: AnnotationRequest, db: Database) -> dict:
    if not payload.consent:
        raise fail(422, "annotation_consent_required", "Explicit AI consent is required")
    settings = MemeSettings()
    if not settings.hkust_api_key.strip():
        raise fail(503, "annotation_unconfigured", "The vision gateway is not configured")
    version = annotation_version(settings.hkust_model)
    result = []
    for asset_id in sorted(set(payload.asset_ids)):
        asset = lock_asset(db, asset_id)
        metadata = metadata_for_edit(db, asset)
        if metadata.annotation_status not in {"pending", "running"} and (
            metadata.annotation_status != "ready"
            or metadata.annotation_sha != asset.sha256
            or metadata.annotation_version != version
        ):
            metadata.annotation_status = "pending"
            metadata.annotation_version = version
            metadata.annotation_sha = asset.sha256
            metadata.annotation_error = None
            metadata.updated_at = utcnow()
        result.append({"asset_id": asset.id, "annotation_status": metadata.annotation_status})
    commit(db)
    return {"assets": result}


class LibraryQuery(BaseModel):
    query: str = Field(max_length=200)
    limit: int = Field(default=10, ge=1, le=50)


@router.post("/search")
def search_library(payload: LibraryQuery, db: Database) -> dict:
    statement = asset_rows()
    prepared = prepare_query(payload.query)
    if not prepared[0]:
        return {"assets": [asset_card(*row) for row in db.execute(statement.limit(payload.limit))]}
    top = []
    for asset, metadata, scan in db.execute(statement.execution_options(yield_per=50)):
        manual = metadata.manual if metadata else {}
        annotation = (metadata.annotation or {}) if metadata else {}
        title = (metadata.title if metadata else None) or asset.title
        score, reasons = rank(prepared, title, manual, annotation)
        if any(score):
            key = (*score, asset.created_at, asset.id)
            result = (key, {**asset_card(asset, metadata, scan), "match_reasons": reasons})
            if len(top) < payload.limit:
                heapq.heappush(top, result)
            else:
                heapq.heappushpop(top, result)
    return {"assets": [value for _, value in sorted(top, reverse=True)]}
