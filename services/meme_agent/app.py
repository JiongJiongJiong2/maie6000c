"""Isolated local MVP: inspect candidates, edit blank templates, confirm and reuse."""

import io
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from services.retrieval.encoder import MODEL_VERSION, encode_image

from . import providers
from .editor import render_captions
from .library import Library
from .media import MAX_BYTES, MediaError, download_image, inspect_image
from .settings import AgentSettings, get_agent_settings

WEB_ROOT = Path(__file__).resolve().parents[2] / "web" / "studio"
MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}


class CaptionRequest(BaseModel):
    top_text: str = Field(default="", max_length=120)
    bottom_text: str = Field(default="", max_length=120)


class SaveRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)


def local_encoder(image):
    return encode_image(image)


local_encoder.model_id = MODEL_VERSION


def create_app(settings: AgentSettings | None = None, encoder=local_encoder) -> FastAPI:
    settings = settings or get_agent_settings()

    @asynccontextmanager
    async def lifespan(application):
        application.state.library = Library(settings.data_root, encoder)
        yield
        application.state.library.close()

    app = FastAPI(title="Meme search experiment v1", lifespan=lifespan)
    search_slots = threading.BoundedSemaphore(2)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # This edition has one shared local library and no user accounts.
        # Reject foreign Host/Origin to prevent browser requests from unrelated sites.
        from fastapi.responses import JSONResponse

        host = request.headers.get("host", "")
        try:
            hostname = urlsplit("http://" + host).hostname
        except ValueError:
            hostname = None
        if hostname not in {"localhost", "127.0.0.1", "[::1]", "::1", "testserver"}:
            return JSONResponse({"detail": "此版本仅允许本机访问。"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in {"http://" + host, "https://" + host}:
            return JSONResponse({"detail": "不允许跨站请求。"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    def library() -> Library:
        return app.state.library

    def get_item(ident: str):
        try:
            return library().get(ident)
        except KeyError:
            raise HTTPException(404, "候选不存在或已过期，请重新搜索。") from None

    def read_upload(upload: UploadFile) -> tuple[bytes, dict]:
        data = upload.file.read(MAX_BYTES + 1)
        try:
            return data, inspect_image(data)
        except MediaError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/studio/")

    @app.get("/studio/", include_in_schema=False)
    def studio():
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/studio/{filename}", include_in_schema=False)
    def studio_asset(filename: str):
        if filename not in {"styles.css", "app.js"}:
            raise HTTPException(404)
        return FileResponse(WEB_ROOT / filename)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "edition": "local-mvp"}

    @app.get("/api/config")
    def config():
        return {
            "planner_configured": bool(settings.deepseek_api_key),
            "web_search_configured": bool(settings.brave_api_key),
            "collection_count": len(library().list_saved()),
            "search_scope": "Imgflip 热门模板目录；可选 Brave 图片搜索（仅支持部分图片来源）",
        }

    @app.get("/api/library")
    def list_library():
        return {"items": library().list_saved()}

    @app.get("/api/media/{ident}")
    def media(ident: str):
        item = get_item(ident)
        path = library().media_path(ident)
        if not path.is_file():
            raise HTTPException(404, "图片文件已不可用。")
        return FileResponse(path, media_type=MIME[item["format"]])

    @app.post("/api/import")
    def import_image(
        image: UploadFile = File(),
        title: str = Form(default="", max_length=200),
        blank_template: bool = Form(default=False),
    ):
        data, info = read_upload(image)
        return library().add_candidate(
            data,
            {
                **info,
                "title": title.strip() or "导入图片",
                "provider": "upload",
                "source_url": None,
                "editable": blank_template and not info["animated"],
            },
        )

    @app.post("/api/candidates/{ident}/edit")
    def edit(ident: str, body: CaptionRequest):
        item = get_item(ident)
        if not item.get("editable") or item["animated"]:
            raise HTTPException(422, "请选择已确认的静态空白模板；此版本不支持去字。")
        if not (body.top_text.strip() or body.bottom_text.strip()):
            raise HTTPException(422, "请至少输入一段文字。")
        try:
            data = render_captions(
                library().media_path(ident),
                body.top_text,
                body.bottom_text,
                settings.meme_font_path,
            )
            info = inspect_image(data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return library().add_candidate(
            data,
            {
                **info,
                "title": item["title"] + " · 改字",
                "provider": "edit",
                "source_url": item.get("source_url"),
                "editable": False,
                "parent_id": ident,
                "caption": body.model_dump(),
                "query": item.get("query", ""),
                "tags": item.get("tags", []),
            },
        )

    @app.post("/api/candidates/{ident}/save")
    def save(ident: str, body: SaveRequest):
        get_item(ident)
        try:
            item, duplicate = library().save(ident, body.title)
        except (OSError, RuntimeError, ValueError, ImportError):
            raise HTTPException(503, "收藏索引未完成；请检查本地 CLIP 模型和存储后重试。") from None
        return {"item": item, "duplicate": duplicate}

    @app.post("/api/search")
    def search(
        query: str = Form(default="", max_length=500),
        image: UploadFile | None = File(None),
        scope: Literal["all", "library", "web"] = Form(default="all"),
    ):
        query = query.strip()
        if not query and image is None:
            raise HTTPException(422, "请填写描述或上传截图。")
        if not search_slots.acquire(blocking=False):
            raise HTTPException(429, "已有搜索进行中，请稍后重试。")
        try:
            return run_search(query, image, scope)
        finally:
            search_slots.release()

    def run_search(query, image, scope):
        candidates, trace, warnings = [], [], []
        if scope != "web":
            try:
                picture = None
                if image is not None:
                    data, _ = read_upload(image)
                    with Image.open(io.BytesIO(data)) as source:
                        picture = ImageOps.exif_transpose(source).convert("RGB")
                if library().list_saved():
                    candidates = library().search(query, picture)
                trace.append({"step": "收藏检索", "detail": f"找到 {len(candidates)} 个候选"})
            except (OSError, RuntimeError, ValueError, ImportError):
                warnings.append("本地图片索引暂不可用，请检查 CLIP 模型；可继续用文字搜索模板。")
        if scope != "library" and query:
            plan = providers.plan_query(query, settings=settings)
            warnings.extend(plan["warnings"])
            trace.append(
                {"step": "查询理解", "detail": f"{plan['planner']}：" + " / ".join(plan["queries"])}
            )
            sources = []
            for provider in (providers.search_templates, providers.search_web):
                try:
                    if provider is providers.search_web:
                        sources.extend(provider(plan, limit=4, settings=settings))
                    else:
                        sources.extend(provider(plan, limit=4))
                except providers.ProviderError as exc:
                    warnings.append(str(exc))
            unique = {s["image_url"]: s for s in sources}
            sources = list(unique.values())[:6]
            trace.append({"step": "联网来源", "detail": f"找到 {len(sources)} 个待验证图片地址"})

            def verify(source):
                try:
                    data = download_image(source["image_url"])
                    info = inspect_image(data)
                    item = library().add_candidate(
                        data,
                        {
                            **source,
                            **info,
                            "editable": source["editable"] and not info["animated"],
                            "query": query,
                            "tags": plan["queries"],
                        },
                    )
                    return item
                except (MediaError, OSError):
                    return None

            with ThreadPoolExecutor(max_workers=3) as executor:
                results = list(executor.map(verify, sources))
            verified = [r for r in results if r]
            candidates.extend(verified)
            if len(verified) != len(sources):
                warnings.append("部分候选无法下载、格式无效或来源不受支持，已跳过。")
            trace.append(
                {"step": "图片验证", "detail": f"{len(verified)} 张通过实际解码；尚未写入收藏索引"}
            )
            if not settings.brave_api_key:
                warnings.append("当前联网范围是 Imgflip 热门模板目录，并非全网图片搜索。")
        elif scope != "library" and image is not None:
            warnings.append("截图用于检索本地收藏；联网查找还需要填写画面描述。")
        seen = set()
        deduped = []
        for item in candidates:
            if item["sha256"] not in seen:
                seen.add(item["sha256"])
                deduped.append(item)
        return {"candidates": deduped, "trace": trace, "warnings": warnings}

    return app


app = create_app()
