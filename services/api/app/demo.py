"""Optional example screenshots from the actual local corpus, never canned search results."""

from __future__ import annotations

import io
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.search import authorize
from services.common.config import get_settings
from services.common.db import get_db
from services.common.reference_assets import Manifest
from services.common.search_models import ReferenceAsset
from services.common.storage import MediaError, contained_path, read_gif, sha256
from services.retrieval.public_fetch import FetchError, valid_url


def require_demo():
    if not get_settings().enable_demo_library:
        raise HTTPException(status_code=404, detail="Example library is not enabled")


router = APIRouter(dependencies=[Depends(authorize), Depends(require_demo)])


def available_assets(db: Session, asset_id: UUID | None = None) -> list[ReferenceAsset]:
    root = get_settings().reference_root
    statement = select(ReferenceAsset)
    if asset_id is not None:
        statement = statement.where(ReferenceAsset.id == str(asset_id))
    try:
        raw = (root / "manifest.json").read_bytes()
    except FileNotFoundError:
        # Older, manually registered installations only have the database catalog.
        entries = None
    else:
        manifest = Manifest.model_validate_json(raw)
        entries = {str(entry.reference_asset_id): entry for entry in manifest.assets}
        statement = statement.where(ReferenceAsset.corpus_version == manifest.corpus_version)
    available = []
    for asset in db.scalars(statement.order_by(ReferenceAsset.title, ReferenceAsset.id)):
        if entries is not None:
            entry = entries.get(asset.id)
            if entry is None or (entry.sha256, entry.gif_path) != (asset.sha256, asset.gif_path):
                continue
        try:
            path = contained_path(root, asset.gif_path)
        except MediaError:
            continue
        if path.is_file():
            available.append(asset)
    return available


def public_attribution(asset: ReferenceAsset) -> dict:
    try:
        valid_url(asset.source_reference)
    except FetchError:
        return {"source_reference": None, "permission_note": None}
    # Older manually imported notes can contain storage locations.
    note = asset.permission_note
    prose = re.sub(r"https?://\S+", "", note)
    if re.search(r"file:|[A-Za-z]:[\\/]|\\\\|(?:^|[\s(])(?:/|\.{1,2}/)\S+", prose):
        note = None
    return {"source_reference": asset.source_reference, "permission_note": note}


@router.get("/demo-library")
def library(db: Session = Depends(get_db)):
    assets = available_assets(db)
    featured = [asset for asset in assets if asset.gif_path.startswith("eval-examples/")]
    regular = [asset for asset in assets if not asset.gif_path.startswith("eval-examples/")]
    return {
        "examples": [
            {
                "id": asset.id,
                "title": asset.title,
                "screenshot_url": f"/demo-library/{asset.id}/screenshot",
                **public_attribution(asset),
            }
            for asset in [*featured, *regular[:24]]
        ]
    }


@router.get("/demo-library/{asset_id}/screenshot")
def screenshot(asset_id: UUID, db: Session = Depends(get_db)):
    assets = available_assets(db, asset_id)
    if not assets:
        raise HTTPException(status_code=404, detail="Example not found")
    asset = assets[0]
    try:
        data, _ = read_gif(asset.gif_path)
    except (MediaError, OSError):
        raise HTTPException(status_code=404, detail="Example media is unavailable") from None
    if sha256(data) != asset.sha256:
        raise HTTPException(status_code=404, detail="Example media has changed")
    with Image.open(io.BytesIO(data)) as gif:
        gif.seek(gif.n_frames // 3)
        rgba = gif.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        image = Image.alpha_composite(background, rgba).convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    return Response(
        buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"}
    )
