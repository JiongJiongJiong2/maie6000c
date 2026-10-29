from __future__ import annotations

import argparse
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select

from services.common.db import get_session_factory
from services.common.search_models import ReferenceAsset
from services.common.storage import read_gif, sha256


class AssetEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reference_asset_id: UUID
    title: str = Field(min_length=1, max_length=200)
    source_reference: str = Field(min_length=1)
    permission_note: str = Field(min_length=1)
    gif_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    corpus_version: str = Field(min_length=1, max_length=100)
    assets: list[AssetEntry] = Field(min_length=1)


def import_manifest(path: Path) -> int:
    manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    ids = [asset.reference_asset_id for asset in manifest.assets]
    if len(set(ids)) != len(ids):
        raise ValueError("Manifest contains duplicate reference_asset_id values")
    checksums = [asset.sha256 for asset in manifest.assets]
    if len(set(checksums)) != len(checksums):
        raise ValueError("Manifest contains duplicate GIF checksums")
    frame_counts = []
    for entry in manifest.assets:
        data, frames = read_gif(entry.gif_path)
        if sha256(data) != entry.sha256:
            raise ValueError(f"GIF checksum mismatch: {entry.reference_asset_id}")
        frame_counts.append(frames)

    with get_session_factory()() as db:
        batch_size = 400
        for offset in range(0, len(manifest.assets), batch_size):
            entries = manifest.assets[offset : offset + batch_size]
            batch_frames = frame_counts[offset : offset + batch_size]
            ids_in_batch = [str(entry.reference_asset_id) for entry in entries]
            checksums_in_batch = [entry.sha256 for entry in entries]
            existing_assets = db.scalars(
                select(ReferenceAsset).where(
                    or_(
                        ReferenceAsset.id.in_(ids_in_batch),
                        ReferenceAsset.sha256.in_(checksums_in_batch),
                    )
                )
            ).all()
            assets_by_id = {asset.id: asset for asset in existing_assets}
            owners_by_checksum = {asset.sha256: asset.id for asset in existing_assets}

            for entry, frames in zip(entries, batch_frames, strict=True):
                asset_id = str(entry.reference_asset_id)
                fields = {
                    "sha256": entry.sha256,
                    "title": entry.title,
                    "source_reference": entry.source_reference,
                    "permission_note": entry.permission_note,
                    "gif_path": entry.gif_path,
                    "frame_count": frames,
                    "corpus_version": manifest.corpus_version,
                }
                existing = assets_by_id.get(asset_id)
                if existing is not None:
                    if any(
                        getattr(existing, key) != value
                        for key, value in fields.items()
                        if key != "corpus_version"
                    ):
                        raise ValueError(
                            f"Existing reference asset differs: {entry.reference_asset_id}"
                        )
                    existing.corpus_version = manifest.corpus_version
                else:
                    checksum_owner = owners_by_checksum.get(entry.sha256)
                    if checksum_owner is not None:
                        raise ValueError(
                            f"GIF checksum already belongs to reference asset {checksum_owner}"
                        )
                    db.add(ReferenceAsset(id=asset_id, **fields))
        db.commit()
    return len(manifest.assets)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and import a permitted GIF corpus manifest"
    )
    parser.add_argument("manifest", type=Path)
    arguments = parser.parse_args()
    count = import_manifest(arguments.manifest)
    print(f"Validated {count} reference assets")


if __name__ == "__main__":
    main()
