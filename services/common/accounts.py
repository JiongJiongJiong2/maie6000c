"""Account registry in the deployment database; private data lives in each workspace."""

import hashlib
import secrets
from time import time
from uuid import uuid4

from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, select, text

from services.common.config import use_workspace, validated_workspace
from services.common.db import Base, get_engine, get_session_factory

registry = MetaData()
accounts = Table(
    "library_accounts",
    registry,
    Column("username", String(64), primary_key=True),
    Column("password_hash", String(192), nullable=False),
    Column("workspace", String(40), nullable=False, unique=True),
)
sessions = Table(
    "library_sessions",
    registry,
    Column("digest", String(64), primary_key=True),
    Column("username", ForeignKey(accounts.c.username), nullable=False),
    Column("expires", Integer, nullable=False, index=True),
)
owner_setup = Table(
    "library_owner_setup",
    registry,
    Column("id", Integer, primary_key=True),
    Column("digest", String(64), nullable=False),
    Column("expires", Integer, nullable=False),
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def workspaces():
    with get_session_factory()() as db:
        return [
            "public",
            *db.scalars(
                select(accounts.c.workspace)
                .where(accounts.c.workspace != "public")
                .order_by(accounts.c.workspace)
            ),
        ]


def provision_workspace(db, name):
    from services.common.library_models import LibraryActivation
    from services.common.search_models import ReferenceAsset
    from services.common.storage import prepare_storage

    validated_workspace(name)
    with use_workspace(name):
        prepare_storage()
        if db.get_bind().dialect.name == "postgresql":
            # DDL, registration and the initial session commit atomically.
            conn = db.connection()
            conn.exec_driver_sql(f'CREATE SCHEMA "{name}"')
            conn.exec_driver_sql(f'SET LOCAL search_path TO "{name}"')
            Base.metadata.create_all(conn, checkfirst=False)
            conn.execute(LibraryActivation.__table__.insert().values(id=1))
            conn.exec_driver_sql(
                "INSERT INTO reference_assets SELECT * FROM public.reference_assets"
            )
            conn.exec_driver_sql(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
            )
            conn.exec_driver_sql("INSERT INTO alembic_version SELECT * FROM public.alembic_version")
            conn.exec_driver_sql("SET LOCAL search_path TO public")
        else:
            # SQLite is used by the local browser and integration test harnesses.
            refs = db.execute(select(ReferenceAsset.__table__)).mappings().all()
            with get_engine().begin() as conn:
                Base.metadata.create_all(conn)
                conn.execute(LibraryActivation.__table__.insert().values(id=1))
                if refs:
                    conn.execute(ReferenceAsset.__table__.insert(), [dict(r) for r in refs])


def issue_owner_setup():
    """Local operator command. The secret travels in a URL fragment, never in server access logs."""
    with get_session_factory()() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(6000, 81)"))
        if db.scalar(select(accounts.c.username).where(accounts.c.workspace == "public")):
            return ""
        from services.common.search_models import SavedAsset, SearchRequest

        if not (
            db.scalar(select(SavedAsset.id).limit(1))
            or db.scalar(select(SearchRequest.id).limit(1))
        ):
            return ""
        secret = secrets.token_urlsafe(32)
        db.execute(owner_setup.delete())
        db.execute(
            owner_setup.insert().values(id=1, digest=digest(secret), expires=int(time()) + 1800)
        )
        db.commit()
        return secret


def new_workspace():
    return "acct_" + uuid4().hex


if __name__ == "__main__":
    print(issue_owner_setup())
