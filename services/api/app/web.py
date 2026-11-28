"""Serve the dependency-free W07 client without shadowing API routes."""

from html import escape
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from services.api.app.sticker_integrations import can_add_discord_sticker, can_create_signal_pack
from services.common.config import get_settings

router = APIRouter(include_in_schema=False)
WEB_ROOT = Path(__file__).resolve().parents[3] / "web"


@router.get("/web/")
def web_index(request: Request):
    settings = get_settings()
    attributes = ['lang="en"']
    if settings.account_login_enabled:
        account = getattr(request.state, "account", None)
        if not account:
            return sign_in_page()
        # The account name is restricted to ASCII letters, digits, hyphens, dots and underscores.
        attributes.append(f'data-account="{account.username}"')
    if can_add_discord_sticker(request):
        attributes.append('data-discord-stickers="true"')
        if guild_name := settings.discord_sticker_guild_name.strip():
            attributes.append(f'data-discord-guild-name="{escape(guild_name)}"')
    if can_create_signal_pack(request):
        attributes.append('data-signal-stickers="true"')
    if len(attributes) > 1:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        html = html.replace('<html lang="en">', f'<html {" ".join(attributes)}>', 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-cache"})


@router.get("/web/sign-in")
def sign_in_page():
    return FileResponse(WEB_ROOT / "account.html", headers={"Cache-Control": "no-store"})


@router.get("/web/{asset}")
def web_asset(asset: str) -> FileResponse:
    # Expose only shipped browser assets, not tests, guides, or arbitrary paths.
    media_types = {
        "styles.css": "text/css",
        "app.js": "text/javascript",
        "crop.js": "text/javascript",
        "api.js": "text/javascript",
        "store.js": "text/javascript",
        "meme50.js": "text/javascript",
        "account.js": "text/javascript",
        "library.js": "text/javascript",
        "account-folder.webp": "image/webp",
        "account-stickers.webp": "image/webp",
        "account-scraps.webp": "image/webp",
        "share.js": "text/javascript",
        "telegram.js": "text/javascript",
        "sticker-integrations.js": "text/javascript",
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
