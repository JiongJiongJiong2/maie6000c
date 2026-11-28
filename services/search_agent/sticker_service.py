"""Thin internal HTTP service with no access to the account database or media store."""

from threading import BoundedSemaphore

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from services.common.sticker_web_models import MAX_SCREENSHOT_BYTES, WebStickerSearch
from services.common.storage import MediaError, validate_image

from .sticker_lookup import find_public_sticker

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
slots = BoundedSemaphore(2)


@app.get("/health/live", include_in_schema=False)
def live():
    return {"status": "ok"}


def run_lookup(data):
    try:
        validate_image(data)
        return find_public_sticker(data)
    finally:
        slots.release()


@app.post("/lookup", response_model=WebStickerSearch)
async def lookup(request: Request):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_SCREENSHOT_BYTES:
            raise HTTPException(413, "Screenshot exceeds 5 MB")
        data.extend(chunk)
    if not slots.acquire(blocking=False):
        return WebStickerSearch(state="busy")
    try:
        return await run_in_threadpool(run_lookup, bytes(data))
    except MediaError as exc:
        raise HTTPException(422, str(exc)) from exc
