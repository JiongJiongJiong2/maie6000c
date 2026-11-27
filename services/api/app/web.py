"""Serve the dependency-free W07 client without shadowing API routes."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from services.common.config import get_settings

router = APIRouter(include_in_schema=False)
WEB_ROOT = Path(__file__).resolve().parents[3] / "web"


@router.get("/web/")
def web_index(request: Request):
    if get_settings().account_login_enabled:
        account = getattr(request.state, "account", None)
        if not account:
            return sign_in_page()
        # The account name is restricted to ASCII letters, digits, hyphens, dots and underscores.
        html = (
            (WEB_ROOT / "index.html")
            .read_text()
            .replace('<html lang="en">', f'<html lang="en" data-account="{account.username}">')
        )
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-cache"})


@router.get("/web/sign-in")
def sign_in_page():
    return FileResponse(WEB_ROOT / "account.html", headers={"Cache-Control": "no-store"})


@router.get("/web/{asset}")
def web_asset(asset: str) -> FileResponse:
    # Expose only shipped browser assets, not tests, guides, or arbitrary paths.
    if asset not in {
        "styles.css",
        "app.js",
        "api.js",
        "store.js",
        "meme50.js",
        "library.js",
        "account.js",
        "account-folder.webp",
        "account-stickers.webp",
        "account-scraps.webp",
    }:
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(WEB_ROOT / asset, headers={"Cache-Control": "no-cache"})


@router.get("/web/fonts/{font}")
def library_font(font: str) -> FileResponse:
    if font not in {"cmunrm.woff", "cmunbx.woff", "OFL.txt"}:
        raise HTTPException(status_code=404, detail="Font not found")
    return FileResponse(WEB_ROOT / "fonts" / font)
