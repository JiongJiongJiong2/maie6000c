"""Optional example screenshots from the actual local corpus, never canned search results."""

from __future__ import annotations

import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.search import authorize
from services.common.config import get_settings
from services.common.db import get_db
from services.common.search_models import ReferenceAsset
from services.common.storage import contained_path


def require_demo():
    if not get_settings().enable_demo_library:
        raise HTTPException(status_code=404, detail="Example library is not enabled")


router = APIRouter(dependencies=[Depends(authorize), Depends(require_demo)])


@router.get("/demo-library")
def library(db: Session = Depends(get_db)):
    assets = db.scalars(select(ReferenceAsset).order_by(ReferenceAsset.title).limit(24))
    return {
        "examples": [
            {
                "id": asset.id,
                "title": asset.title,
                "screenshot_url": f"/demo-library/{asset.id}/screenshot",
            }
            for asset in assets
        ]
    }


@router.get("/demo-library/{asset_id}/screenshot")
def screenshot(asset_id: UUID, db: Session = Depends(get_db)):
    asset = db.get(ReferenceAsset, str(asset_id))
    if asset is None:
        raise HTTPException(status_code=404, detail="Example not found")
    path = contained_path(get_settings().reference_root, asset.gif_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Example media is unavailable")
    with Image.open(path) as gif:
        gif.seek(gif.n_frames // 3)
        rgba = gif.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        image = Image.alpha_composite(background, rgba).convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    return Response(
        buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"}
    )
