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
    if asset not in {"styles.css", "app.js", "api.js", "store.js"}:
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(WEB_ROOT / asset, headers={"Cache-Control": "no-cache"})
