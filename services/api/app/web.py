"""Serve the dependency-free W07 client without shadowing API routes."""

from html import escape
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import HttpUrl, ValidationError

from services.common.config import get_settings

router = APIRouter(include_in_schema=False)
WEB_ROOT = Path(__file__).resolve().parents[3] / "web"


def browser_page(filename: str, username: str | None = None):
    settings = get_settings()
    html = (WEB_ROOT / filename).read_text(encoding="utf-8")
    attributes = []
    if filename == "account.html" and settings.beta_invite_required:
        attributes.append("data-invite-required")
    if filename == "index.html" and settings.public_beta_enabled:
        attributes.append("data-local-first")
    if filename == "index.html" and not settings.online_search_enabled:
        attributes.append("data-online-disabled")
    if username:
        attributes.append(f'data-account="{escape(username, quote=True)}"')
    if attributes:
        html = html.replace('<html lang="en"', f'<html {" ".join(attributes)} lang="en"', 1)
    if settings.beta_feedback_url:
        try:
            url = HttpUrl(settings.beta_feedback_url)
        except ValidationError:
            url = None
        if url and url.scheme == "https" and not url.username and not url.password:
            html = html.replace("data-beta-feedback hidden", "data-beta-feedback").replace(
                "data-feedback-link", f'href="{escape(str(url), quote=True)}"'
            )
    cache = "no-store" if filename == "account.html" or username else "no-cache"
    return HTMLResponse(html, headers={"Cache-Control": cache})


@router.get("/web/")
def web_index(request: Request):
    if get_settings().account_login_enabled:
        account = getattr(request.state, "account", None)
        if not account:
            return sign_in_page()
        return browser_page("index.html", account.username)
    return browser_page("index.html")


@router.get("/web/sign-in")
def sign_in_page():
    return browser_page("account.html")


@router.get("/web/{asset}")
def web_asset(asset: str) -> FileResponse:
    # Expose only shipped browser assets, not tests, guides, or arbitrary paths.
    media_types = {
        "styles.css": "text/css",
        "app.js": "text/javascript",
        "api.js": "text/javascript",
        "store.js": "text/javascript",
        "meme50.js": "text/javascript",
        "account.js": "text/javascript",
        "library.js": "text/javascript",
        "account-folder.webp": "image/webp",
        "account-stickers.webp": "image/webp",
        "account-scraps.webp": "image/webp",
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


@router.get("/web/fonts/{font}")
def library_font(font: str) -> FileResponse:
    if font not in {"cmunrm.woff", "cmunbx.woff", "OFL.txt"}:
        raise HTTPException(status_code=404, detail="Font not found")
    return FileResponse(WEB_ROOT / "fonts" / font)
