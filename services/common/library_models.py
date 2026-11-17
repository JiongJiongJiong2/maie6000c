from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportItem(Base):
    __tablename__ = "library_import_items"
    batch_id: Mapped[str] = mapped_column(ForeignKey(ImportBatch.id), primary_key=True)
    client_item_id: Mapped[str] = mapped_column(String(36), primary_key=True)
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
