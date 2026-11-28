"""Public screenshot lookup in the registered catalog and on the web."""

from __future__ import annotations

import logging
import secrets
from io import BytesIO
from threading import Lock
from typing import Literal
from zipfile import ZipFile

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from prometheus_client import Counter
from starlette.concurrency import run_in_threadpool

from services.api.app.web import WEB_ROOT, sign_in_page, workspace_identity
from services.common.config import base_settings
from services.common.sticker_catalog import Catalog, Pack, find_packs, load_catalog, read_bounded
from services.common.sticker_web_models import (
    LOOKUP_SECONDS,
    MAX_SCREENSHOT_BYTES,
    WebStickerSearch,
)
from services.common.storage import MediaError, validate_image

router = APIRouter(prefix="/stickers", tags=["sticker packs"])
workspace_router = APIRouter(prefix="/web", include_in_schema=False)
DEMO_ROOT = WEB_ROOT.parent / "sticker_packs" / "demo"
VARIANT_COOKIE = "memeretrieve_sticker_view"
Variant = Literal["finder", "directory", "workspace"]
logger = logging.getLogger(__name__)
catalog_lock = Lock()
events = Counter(
    "sticker_pack_events_total", "Public sticker pack page and search events", ["variant", "event"]
)
claims = Counter(
    "sticker_pack_claims_total",
    "Acquisition requests from the public sticker catalog",
    ["variant", "pack", "channel"],
)


def catalog() -> Catalog:
    root = base_settings().sticker_pack_root or DEMO_ROOT
    try:
        with catalog_lock:
            return load_catalog(root.resolve())
    except (OSError, ValueError):
        logger.exception("sticker_pack_catalog_unavailable")
        raise HTTPException(503, "The sticker catalog is temporarily unavailable") from None


def public_pack(collection: Catalog, pack: Pack) -> dict:
    return {
        "id": pack.id,
        "name": pack.name,
        "publisher": pack.publisher,
        "creator": pack.creator,
        "description": pack.description,
        "color": pack.color,
        "stickers": [
            {
                "id": sticker.id,
                "name": sticker.name,
                "poster": f"/stickers/packs/{pack.id}/items/{sticker.id}/poster",
                "animation": (
                    f"/stickers/packs/{pack.id}/items/{sticker.id}/original"
                    if collection.stickers[pack.id, sticker.id].metadata.frame_count > 1
                    else None
                ),
            }
            for sticker in pack.stickers
        ],
        "channels": [{"id": channel.id, "label": channel.label} for channel in pack.channels]
        + ([{"id": "archive", "label": "Download sticker pack"}] if pack.archive else []),
    }


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def sticker_page(request: Request):
    return render_sticker_page(request)


@workspace_router.get("/stickers", response_class=HTMLResponse)
def workspace_sticker_page(request: Request):
    if base_settings().account_login_enabled and not getattr(request.state, "account", None):
        return sign_in_page()
    return render_sticker_page(request, workspace=True)


def render_sticker_page(request: Request, *, workspace: bool = False):
    variant = "finder"
    experiment = not workspace and base_settings().sticker_pack_experiment
    assigned = request.cookies.get(VARIANT_COOKIE)
    if experiment:
        variant = (
            assigned
            if assigned in {"finder", "directory"}
            else secrets.choice(("finder", "directory"))
        )
    html = (WEB_ROOT / "sticker-packs.html").read_text(encoding="utf-8")
    if workspace:
        html = workspace_identity(html, request).replace(
            '<body data-variant="finder">',
            '<body data-variant="finder" data-workspace-page="stickers">',
            1,
        )
    response = HTMLResponse(
        html.replace('data-variant="finder"', f'data-variant="{variant}"', 1),
        headers={"Cache-Control": "no-store", "Referrer-Policy": "same-origin"},
    )
    if experiment and variant != assigned:
        response.set_cookie(
            VARIANT_COOKIE,
            variant,
            max_age=30 * 86400,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
        )
    events.labels("workspace" if workspace else variant, "page_view").inc()
    return response


@router.get("/catalog")
def sticker_directory():
    collection = catalog()
    return {
        "demo": collection.manifest.demo,
        "example": "/stickers/example" if collection.example else None,
        "packs": [public_pack(collection, pack) for pack in collection.packs.values()],
    }


@router.get("/example", include_in_schema=False)
def sticker_example():
    example = catalog().example
    if example is None:
        raise HTTPException(404, "No example screenshot is available")
    path, mime_type = example
    return FileResponse(path, media_type=mime_type, headers={"X-Content-Type-Options": "nosniff"})


@router.post("/search")
async def sticker_search(request: Request, view: Literal["finder", "workspace"] = "finder"):
    # The raw request body stays in memory and never enters the search-job media store.
    data = bytearray()
    limit = min(base_settings().max_upload_bytes, MAX_SCREENSHOT_BYTES)
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise HTTPException(413, "Choose a screenshot smaller than 5 MB")
        data.extend(chunk)
    screenshot = bytes(data)
    try:
        matches = await run_in_threadpool(local_sticker_matches, screenshot)
    except MediaError as exc:
        raise HTTPException(422, str(exc)) from exc
    event = {0: "no_match", 1: "one_match"}.get(len(matches), "multiple_matches")
    events.labels(view, "search").inc()
    events.labels(view, event).inc()
    payload = {
        "matches": [
            {"packId": pack_id, "stickerId": sticker_id} for pack_id, sticker_id in matches
        ],
    }
    if not matches:
        web = await web_sticker_matches(screenshot)
        events.labels(view, "web_" + web.state).inc()
        payload["web"] = web.model_dump(mode="json")
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


def local_sticker_matches(data: bytes):
    try:
        collection = catalog()
    except HTTPException:
        # A temporarily unavailable catalog need not block public lookup.
        validate_image(data)
        return []
    return find_packs(collection, data)


async def web_sticker_matches(data: bytes) -> WebStickerSearch:
    endpoint = base_settings().sticker_lookup_url.rstrip("/")
    if endpoint:
        try:
            async with httpx.AsyncClient(
                trust_env=False, timeout=LOOKUP_SECONDS + 6, follow_redirects=False
            ) as client:
                response = await client.post(
                    endpoint + "/lookup",
                    content=data,
                    headers={"Content-Type": "application/octet-stream"},
                )
                response.raise_for_status()
                return WebStickerSearch.model_validate_json(response.content)
        except (httpx.HTTPError, ValueError):
            logger.warning("sticker_lookup_unavailable")
    return WebStickerSearch(state="unavailable")


@router.get("/packs/{pack_id}/items/{sticker_id}/{rendition}", include_in_schema=False)
def sticker_media(pack_id: str, sticker_id: str, rendition: Literal["poster", "original"]):
    item = catalog().stickers.get((pack_id, sticker_id))
    if item is None:
        raise HTTPException(404, "Sticker not found")
    headers = {"X-Content-Type-Options": "nosniff"}
    if rendition == "poster":
        return Response(item.poster, media_type="image/png", headers=headers)
    return FileResponse(item.path, media_type=item.metadata.mime_type, headers=headers)


@router.post("/packs/{pack_id}/claim/{channel_id}", include_in_schema=False)
def claim_sticker_pack(pack_id: str, channel_id: str, view: Variant = "finder"):
    collection = catalog()
    pack = collection.packs.get(pack_id)
    if pack is None:
        raise HTTPException(404, "Sticker pack not found")
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    channel = next((channel for channel in pack.channels if channel.id == channel_id), None)
    if channel:
        response = RedirectResponse(str(channel.url), status_code=303, headers=headers)
    elif channel_id == "archive" and pack.archive:
        with BytesIO() as output:
            with ZipFile(output, "w") as archive:
                for sticker in pack.stickers:
                    media = collection.stickers[pack.id, sticker.id]
                    archive.writestr(
                        f"{sticker.id}.{media.metadata.suffix}",
                        read_bounded(media.path, media.metadata.byte_size),
                    )
            archive_bytes = output.getvalue()
        headers["Content-Disposition"] = f'attachment; filename="{pack.id}.zip"'
        response = Response(archive_bytes, media_type="application/zip", headers=headers)
    else:
        raise HTTPException(404, "Claim channel not found")
    claims.labels(view, pack_id, channel_id).inc()
    return response
