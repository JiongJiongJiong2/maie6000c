"""Serve the dependency-free W07 client without shadowing API routes."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(include_in_schema=False)
WEB_ROOT = Path(__file__).resolve().parents[3] / "web"


@router.get("/web/")
def web_index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-cache"})


@router.get("/web/{asset}")
def web_asset(asset: str) -> FileResponse:
    # Expose only shipped browser assets, not tests, guides, or arbitrary paths.
    media_types = {
        "styles.css": "text/css",
        "app.js": "text/javascript",
        "api.js": "text/javascript",
        "store.js": "text/javascript",
        "meme50.js": "text/javascript",
        "share.js": "text/javascript",
        "whatsapp-import.html": "text/html",
        "whatsapp-import.js": "text/javascript",
        "whatsapp-demo-pack.json": "application/json",
    }
    if asset not in media_types or not (WEB_ROOT / asset).is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    # Windows registry associations can identify .js as text/plain, which browsers
    # reject for ES modules. These shipped assets have known content types.
    media_type = media_types[asset]
    return FileResponse(
        WEB_ROOT / asset, media_type=media_type, headers={"Cache-Control": "no-cache"}
    )
