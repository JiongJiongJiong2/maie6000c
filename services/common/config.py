from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import os
import re

from sqlalchemy.engine import make_url
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from pythonjsonlogger.json import JsonFormatter


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/maie6000c"
    ai_service_url: str = "http://ai:8100"
    worker_poll_seconds: float = 2.0
    worker_request_timeout_seconds: float = 20.0
    media_root: Path = Path("data/media")
    reference_root: Path = Path("data/reference")
    model_cache_root: Path = Path("data/models")
    account_login_enabled: bool = False
    vector_backend: Literal["npz", "pgvector"] = "npz"
    device_token: str = ""
    telegram_api_id: int = Field(default=0, ge=0)
    telegram_api_hash: SecretStr = SecretStr("")
    discord_bot_token: SecretStr = SecretStr("")
    discord_sticker_guild_id: str = Field(default="", pattern=r"^(|[0-9]{17,20})$")
    discord_sticker_guild_name: str = Field(default="", max_length=100)
    discord_sticker_accounts: set[str] = Field(default_factory=set)
    private_library_enabled: bool = False
    enable_demo_library: bool = False
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_candidate_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    media_retention_days: int = Field(default=7, ge=1)
    retrieval_timeout_seconds: float = Field(default=120.0, gt=0)
    web_search_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    web_search_call_timeout_seconds: float = Field(default=12.0, gt=0, le=60)
    web_search_max_downloads: int = Field(default=6, ge=0, le=6)
    saved_index_timeout_seconds: float = Field(default=300.0, gt=0, le=600)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def base_settings() -> Settings:
    return Settings()


# The server selects the workspace from a verified session or the worker queue.
_workspace = ContextVar("workspace", default="public")


def validated_workspace(name: str) -> str:
    if name != "public" and not re.fullmatch(r"acct_[a-f0-9]{32}", name):
        raise ValueError("Invalid account workspace")
    return name


@contextmanager
def use_workspace(name: str):
    token = _workspace.set(validated_workspace(name))
    try:
        yield
    finally:
        _workspace.reset(token)


def get_settings() -> Settings:
    settings = base_settings()
    name = _workspace.get()
    if name == "public":
        return settings
    media = settings.media_root / "accounts" / name
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite":
        url = url.set(database=str(media / "library.sqlite3"))
    else:
        url = url.update_query_dict({"options": f"-csearch_path={name}"})
    return settings.model_copy(
        update={
            "media_root": media,
            "database_url": url.render_as_string(hide_password=False),
        }
    )


get_settings.cache_clear = base_settings.cache_clear


def worker_environment():
    if _workspace.get() == "public":
        return None  # Let existing workers and operator overrides inherit the process environment.
    settings = get_settings()
    return {
        **os.environ,
        "DATABASE_URL": settings.database_url,
        "MEDIA_ROOT": str(settings.media_root),
    }


class ServiceJsonFormatter(JsonFormatter):
    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:
        super().add_fields(log_record, record, message_dict)
        if "service" not in log_record:
            parts = record.name.split(".")
            log_record["service"] = parts[1] if len(parts) > 1 and parts[0] == "services" else "app"


def configure_logging() -> None:
    if getattr(configure_logging, "_configured", False):
        return

    settings = get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(
        ServiceJsonFormatter("%(asctime)s %(levelname)s %(service)s %(name)s %(message)s")
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    configure_logging._configured = True  # type: ignore[attr-defined]
