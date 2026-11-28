"""Optional derived PostgreSQL index. Saved GIFs and NPZ remain authoritative."""

from __future__ import annotations

import argparse
import logging
import math

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from services.common.config import get_settings
from services.common.db import get_engine, get_session_factory
from services.common.search_models import SavedAsset

logger = logging.getLogger(__name__)
VECTOR_TABLES = {
    "saved_vector_versions",
    "saved_frame_vectors",
    "reference_vector_generations",
    "reference_frame_vectors",
}
DIMENSIONS = 512
SCORE_MARGIN = 4e-6


def _extension_schema(connection):
    name = connection.scalar(
        text(
            "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
            "WHERE e.extname = 'vector'"
        )
    )
    return connection.dialect.identifier_preparer.quote_schema(name) if name else None


def _ensure_extension_schema(connection):
    schema = _extension_schema(connection)
    if schema:
        return schema
    available = connection.scalar(
        text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    )
    if not available:
        return None
    connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    return _extension_schema(connection)


def provision_vector_tables(connection) -> bool:
    """Provision the current workspace without requiring the extension in ordinary deployments."""
    if connection.dialect.name != "postgresql":
        return False
    try:
        with connection.begin_nested():
            schema = _ensure_extension_schema(connection)
            if not schema:
                return False
            connection.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS saved_vector_versions (
                    asset_id VARCHAR(36) NOT NULL REFERENCES saved_assets(id) ON DELETE CASCADE,
                    index_version VARCHAR(100) NOT NULL,
                    media_sha256 VARCHAR(64) NOT NULL,
                    expected_frames SMALLINT NOT NULL CHECK (expected_frames BETWEEN 1 AND 8),
                    PRIMARY KEY (asset_id, index_version)
                )
                """
            )
            connection.exec_driver_sql(
                f"""
                CREATE TABLE IF NOT EXISTS saved_frame_vectors (
                    asset_id VARCHAR(36) NOT NULL,
                    index_version VARCHAR(100) NOT NULL,
                    frame_no INTEGER NOT NULL CHECK (frame_no >= 0),
                    embedding {schema}.vector({DIMENSIONS}) NOT NULL,
                    PRIMARY KEY (asset_id, index_version, frame_no),
                    FOREIGN KEY (asset_id, index_version)
                        REFERENCES saved_vector_versions(asset_id, index_version) ON DELETE CASCADE
                )
                """
            )
            return True
    except SQLAlchemyError:
        logger.warning("pgvector_provision_unavailable")
        return False


def provision_reference_tables(connection) -> bool:
    if connection.dialect.name != "postgresql":
        return False
    try:
        with connection.begin_nested():
            if connection.scalar(text("SELECT current_schema()")) != "public":
                return False
            schema = _ensure_extension_schema(connection)
            if not schema:
                return False
            connection.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS public.reference_vector_generations (
                    id SMALLINT PRIMARY KEY CHECK (id = 1),
                    manifest_sha256 VARCHAR(64) NOT NULL,
                    corpus_version VARCHAR(100) NOT NULL,
                    model_version VARCHAR(100) NOT NULL,
                    index_format INTEGER NOT NULL,
                    frame_count INTEGER NOT NULL CHECK (frame_count > 0)
                )
                """
            )
            connection.exec_driver_sql(
                f"""
                CREATE TABLE IF NOT EXISTS public.reference_frame_vectors (
                    generation_id SMALLINT NOT NULL
                        REFERENCES public.reference_vector_generations(id) ON DELETE CASCADE,
                    asset_id VARCHAR(36) NOT NULL
                        REFERENCES public.reference_assets(id) ON DELETE CASCADE,
                    media_sha256 VARCHAR(64) NOT NULL,
                    frame_no INTEGER NOT NULL CHECK (frame_no >= 0),
                    embedding {schema}.vector({DIMENSIONS}) NOT NULL,
                    PRIMARY KEY (generation_id, asset_id, frame_no)
                )
                """
            )
            return True
    except SQLAlchemyError:
        logger.warning("pgvector_reference_provision_unavailable")
        return False


def provision() -> bool:
    """Initialize an existing deployment after enabling pgvector."""
    from services.common.accounts import workspaces
    from services.common.config import use_workspace

    with use_workspace("public"), get_engine().connect() as conn:
        if conn.dialect.name != "postgresql":
            return False
        # The registry is always read from the base workspace.
        names = workspaces()
    for name in names:
        with use_workspace(name), get_engine().begin() as conn:
            if not provision_vector_tables(conn):
                return False
            if name == "public" and not provision_reference_tables(conn):
                return False
    return True


def _vector_literal(values) -> str:
    values = tuple(float(value) for value in values)
    if len(values) != DIMENSIONS or not all(math.isfinite(value) for value in values):
        raise ValueError("Invalid vector")
    if not math.isclose(sum(value * value for value in values), 1.0, rel_tol=1e-6):
        raise ValueError("Vector is not normalized")
    return "[" + ",".join(map(str, values)) + "]"


def store_asset_vectors(asset, version, frames, vectors) -> bool:
    """Mirror an already validated NPZ generation after all frame rows commit together."""
    if get_settings().vector_backend != "pgvector":
        return False
    from services.retrieval.saved_index import frame_numbers, identity

    try:
        with get_session_factory()() as db:
            if db.get_bind().dialect.name != "postgresql":
                return False
            schema = _extension_schema(db.connection())
            if not schema:
                return False
            current = db.scalar(
                select(SavedAsset).where(SavedAsset.id == asset.id).with_for_update()
            )
            frame_numbers_expected = list(map(int, frame_numbers(asset.frame_count)))
            if (
                not current
                or current.sha256 != asset.sha256
                or current.frame_count != asset.frame_count
                or current.index_status not in {"running", "ready"}
                or (current.index_status == "ready" and current.index_version != version)
                or version != identity(current)[1]
                or list(map(int, frames)) != frame_numbers_expected
                or len(vectors) != len(frame_numbers_expected)
            ):
                return False
            common = {"asset": current.id, "version": version}
            # This child only touches the proved generation in the active workspace.
            db.execute(
                text(
                    "DELETE FROM saved_vector_versions "
                    "WHERE asset_id = :asset AND index_version = :version"
                ),
                common,
            )
            db.execute(
                text(
                    "INSERT INTO saved_vector_versions "
                    "(asset_id, index_version, media_sha256, expected_frames) "
                    "VALUES (:asset, :version, :sha, :count)"
                ),
                dict(common, sha=current.sha256, count=len(frames)),
            )
            db.execute(
                text(
                    "INSERT INTO saved_frame_vectors "
                    "(asset_id, index_version, frame_no, embedding) "
                    f"VALUES (:asset, :version, :frame, CAST(:embedding AS {schema}.vector))"
                ),
                [
                    dict(common, frame=int(frame), embedding=_vector_literal(vector))
                    for frame, vector in zip(frames, vectors, strict=True)
                ],
            )
            db.commit()
        return True
    except (SQLAlchemyError, TypeError, ValueError):
        logger.warning("pgvector_mirror_unavailable", extra={"asset_id": asset.id})
        return False


_ELIGIBLE = """
    FROM saved_assets AS asset
    JOIN saved_vector_versions AS version
      ON version.asset_id = asset.id AND version.index_version = asset.index_version
     AND version.media_sha256 = asset.sha256
     AND version.expected_frames = LEAST(asset.frame_count, 8)
    JOIN saved_frame_vectors AS frame
      ON frame.asset_id = version.asset_id AND frame.index_version = version.index_version
    WHERE asset.index_status = 'ready'
"""


def _exact_frame_ranks(connection, schema, eligible, query, top_k, minimum):
    distance = f"frame.embedding OPERATOR({schema}.<=>) CAST(:query AS {schema}.vector)"
    score = f"MAX(1 - ({distance}))"
    rows = connection.execute(
        text(
            f"SELECT asset.id, {score} AS score "
            + eligible
            + f" GROUP BY asset.id HAVING {score} >= :minimum "
            + 'ORDER BY score DESC, asset.id COLLATE "C" LIMIT :limit'
        ),
        {
            "query": _vector_literal(query),
            "minimum": minimum - SCORE_MARGIN,
            "limit": top_k + 1,
        },
    ).all()
    # pgvector and NumPy round their dot products differently at score boundaries.
    if any(abs(value - minimum) <= SCORE_MARGIN for _, value in rows) or any(
        abs(a[1] - b[1]) <= SCORE_MARGIN for a, b in zip(rows, rows[1:])
    ):
        return None
    return [
        {"reference_asset_id": asset_id, "score": min(1.0, max(-1.0, score))}
        for asset_id, score in rows[:top_k]
    ]


def rank_saved_vectors(query, top_k, minimum) -> list[dict] | None:
    """Return complete exact saved ranks, or None for a complete NPZ fallback."""
    if get_settings().vector_backend != "pgvector":
        return None
    from services.retrieval.saved_index import (
        INVALID_INDEX,
        frame_numbers,
        identity,
        read_saved_gif,
    )

    try:
        with get_session_factory()() as db:
            if db.get_bind().dialect.name != "postgresql":
                return None
            # Coverage and scoring must see the same set while the index worker is publishing.
            connection = db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            schema = _extension_schema(connection)
            if not schema:
                return None
            assets = {
                asset.id: asset
                for asset in db.scalars(
                    select(SavedAsset).where(
                        SavedAsset.index_status == "ready", SavedAsset.index_version.is_not(None)
                    )
                )
            }
            if not assets:
                return []
            coverage = dict(
                connection.execute(
                    text(
                        "SELECT asset.id, array_agg(frame.frame_no ORDER BY frame.frame_no) "
                        + _ELIGIBLE
                        + " GROUP BY asset.id"
                    )
                ).all()
            )
            if set(coverage) != set(assets) or any(
                asset.index_version != identity(asset)[1]
                or coverage[asset.id] != list(map(int, frame_numbers(asset.frame_count)))
                for asset in assets.values()
            ):
                return None
            matches = _exact_frame_ranks(connection, schema, _ELIGIBLE, query, top_k, minimum)
            for item in matches or []:
                read_saved_gif(assets[item["reference_asset_id"]])
            return matches
    except (SQLAlchemyError, TypeError, *INVALID_INDEX):
        logger.warning("pgvector_read_fallback")
        return None


_REFERENCE_RANKABLE = """
    FROM public.reference_assets AS asset
    JOIN public.reference_frame_vectors AS frame
      ON frame.asset_id = asset.id AND frame.media_sha256 = asset.sha256
    WHERE frame.generation_id = 1
"""


def _reference_manifest_frames(connection, manifest):
    from services.retrieval.saved_index import frame_numbers

    hashes = {str(entry.reference_asset_id): entry.sha256 for entry in manifest.assets}
    if len(hashes) != len(manifest.assets):
        return None
    rows = connection.execute(
        text(
            "SELECT id, sha256, frame_count FROM public.reference_assets "
            "WHERE corpus_version = :version AND id = ANY(CAST(:assets AS varchar[]))"
        ),
        {"version": manifest.corpus_version, "assets": list(hashes)},
    ).all()
    if len(rows) != len(hashes) or any(hashes[asset_id] != sha for asset_id, sha, _ in rows):
        return None
    return hashes, {asset_id: list(map(int, frame_numbers(count))) for asset_id, _, count in rows}


def mirror_reference_vectors(manifest, manifest_digest, asset_ids, frame_numbers, vectors) -> bool:
    if get_settings().vector_backend != "pgvector":
        return False
    from services.retrieval.engine import INDEX_FORMAT, MODEL_VERSION

    try:
        with get_session_factory()() as db:
            if db.get_bind().dialect.name != "postgresql":
                return False
            conn = db.connection()
            if conn.scalar(text("SELECT current_schema()")) != "public":
                return False
            schema = _extension_schema(conn)
            expected = _reference_manifest_frames(conn, manifest) if schema else None
            if expected is None:
                return False
            hashes, expected_frames = expected
            supplied_frames = {}
            for asset_id, frame in zip(asset_ids, frame_numbers, strict=True):
                supplied_frames.setdefault(str(asset_id), []).append(int(frame))
            if {k: sorted(v) for k, v in supplied_frames.items()} != expected_frames:
                return False
            db.execute(text("SELECT pg_advisory_xact_lock(6000, 84)"))
            db.execute(text("DELETE FROM public.reference_vector_generations WHERE id = 1"))
            db.execute(
                text(
                    "INSERT INTO public.reference_vector_generations "
                    "(id, manifest_sha256, corpus_version, model_version, "
                    "index_format, frame_count) "
                    "VALUES (1, :digest, :corpus, :model, :format, :count)"
                ),
                dict(
                    digest=manifest_digest,
                    corpus=manifest.corpus_version,
                    model=MODEL_VERSION,
                    format=INDEX_FORMAT,
                    count=len(frame_numbers),
                ),
            )
            db.execute(
                text(
                    "INSERT INTO public.reference_frame_vectors "
                    "(generation_id, asset_id, media_sha256, frame_no, embedding) "
                    f"VALUES (1, :asset, :sha, :frame, CAST(:embedding AS {schema}.vector))"
                ),
                [
                    dict(
                        asset=str(asset),
                        sha=hashes[str(asset)],
                        frame=int(frame),
                        embedding=_vector_literal(vector),
                    )
                    for asset, frame, vector in zip(asset_ids, frame_numbers, vectors, strict=True)
                ],
            )
            db.commit()
        return True
    except (SQLAlchemyError, TypeError, ValueError):
        logger.warning("pgvector_reference_mirror_unavailable")
        return False


def rank_reference_vectors(query, top_k, minimum, manifest, manifest_digest) -> list[dict] | None:
    if get_settings().vector_backend != "pgvector":
        return None
    from services.retrieval.engine import INDEX_FORMAT, MODEL_VERSION

    try:
        with get_session_factory()() as db:
            if db.get_bind().dialect.name != "postgresql":
                return None
            conn = db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            schema = _extension_schema(conn)
            if not schema:
                return None
            active = conn.execute(
                text(
                    "SELECT manifest_sha256, corpus_version, model_version, index_format, "
                    "frame_count "
                    "FROM public.reference_vector_generations WHERE id = 1"
                )
            ).one_or_none()
            if not active or active[:4] != (
                manifest_digest,
                manifest.corpus_version,
                MODEL_VERSION,
                INDEX_FORMAT,
            ):
                return None
            expected = _reference_manifest_frames(conn, manifest)
            if expected is None:
                return None
            _, expected_frames = expected
            coverage = dict(
                conn.execute(
                    text(
                        "SELECT asset.id, array_agg(frame.frame_no ORDER BY frame.frame_no) "
                        + _REFERENCE_RANKABLE
                        + " GROUP BY asset.id"
                    )
                ).all()
            )
            if coverage != expected_frames or active.frame_count != sum(
                map(len, coverage.values())
            ):
                return None
            return _exact_frame_ranks(conn, schema, _REFERENCE_RANKABLE, query, top_k, minimum)
    except (SQLAlchemyError, TypeError, ValueError):
        logger.warning("pgvector_reference_read_fallback")
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["provision"])
    parser.parse_args()
    if not provision():
        raise SystemExit("pgvector is unavailable; NPZ remains usable")


if __name__ == "__main__":
    main()
