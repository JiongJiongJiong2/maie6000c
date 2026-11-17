from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from services.common.db import Base
from services.common.models import utcnow
from services.common.search_models import SavedAsset


class LibraryActivation(Base):
    __tablename__ = "library_activation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    __table_args__ = (CheckConstraint("id = 1"),)


class ImportBatch(Base):
    __tablename__ = "library_import_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_batch_key: Mapped[str] = mapped_column(String(128), unique=True)
    manifest_sha: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(16), server_default="upload")
    __table_args__ = (
        CheckConstraint("purpose IN ('upload', 'backup_restore')", name="ck_import_batch_purpose"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportItem(Base):
    __tablename__ = "library_import_items"
    batch_id: Mapped[str] = mapped_column(ForeignKey(ImportBatch.id), primary_key=True)
    client_item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(200))
    byte_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="waiting")
    asset_id: Mapped[str | None] = mapped_column(ForeignKey(SavedAsset.id))
    error_code: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        CheckConstraint("status IN ('waiting', 'imported', 'duplicate', 'rejected')"),
        CheckConstraint("(asset_id IS NOT NULL) = (status IN ('imported', 'duplicate'))"),
    )


class AssetMetadata(Base):
    __tablename__ = "library_asset_metadata"
    asset_id: Mapped[str] = mapped_column(ForeignKey(SavedAsset.id), primary_key=True)
    title: Mapped[str | None] = mapped_column(String(200))
    manual: Mapped[dict] = mapped_column(JSON, default=dict)
    annotation: Mapped[dict | None] = mapped_column(JSON)
    annotation_status: Mapped[str] = mapped_column(String(16), default="not_requested")
    annotation_attempt: Mapped[int] = mapped_column(Integer, default=0)
    annotation_version: Mapped[str | None] = mapped_column(String(200))
    annotation_sha: Mapped[str | None] = mapped_column(String(64))
    annotation_error: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        CheckConstraint(
            "annotation_status IN ('not_requested','pending','running','ready','failed')"
        ),
        Index("ix_library_annotation_queue", "annotation_status", "updated_at"),
    )


class SimilarityScan(Base):
    __tablename__ = "library_similarity_scans"
    asset_id: Mapped[str] = mapped_column(ForeignKey(SavedAsset.id), primary_key=True)
    matches: Mapped[list] = mapped_column(JSON)
    compared: Mapped[int] = mapped_column(Integer)
    considered: Mapped[int] = mapped_column(Integer)
    available: Mapped[int] = mapped_column(Integer)
