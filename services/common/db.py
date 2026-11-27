from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy.pool import NullPool

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from services.common.config import base_settings, get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(database_url: str) -> dict:
    kwargs: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return kwargs


def make_engine(database_url: str):
    return create_engine(database_url, **_engine_kwargs(database_url))


def make_session_factory(engine):
    return sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )


_ENGINE = None
_SESSION_FACTORY = None


@lru_cache(maxsize=128)
def workspace_engine(url: str):
    # Idle accounts do not hold PostgreSQL connections.
    return create_engine(url, poolclass=NullPool, **_engine_kwargs(url))


def get_engine():
    global _ENGINE
    if get_settings().database_url != base_settings().database_url:
        return workspace_engine(get_settings().database_url)
    if _ENGINE is None:
        _ENGINE = make_engine(get_settings().database_url)
    return _ENGINE


def get_session_factory():
    global _SESSION_FACTORY
    if get_settings().database_url != base_settings().database_url:
        return make_session_factory(get_engine())
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = make_session_factory(get_engine())
    return _SESSION_FACTORY


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
