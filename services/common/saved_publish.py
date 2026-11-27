"""Coordinate publication and orphan cleanup for a content-addressed saved GIF."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_saved_digest(db: Session, digest: str) -> None:
    if db.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(bytes.fromhex(digest[:16]), "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
