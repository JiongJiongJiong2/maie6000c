import hashlib
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


class Library:
    def __init__(self, root: Path, encoder):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.files = self.root / "media"
        self.files.mkdir(exist_ok=True)
        self.encoder = encoder
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.root / "library.sqlite3"), check_same_thread=False)
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, sha TEXT, metadata TEXT, "
            "saved INTEGER DEFAULT 0, vector BLOB, dim INTEGER, model TEXT)"
        )
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS saved_sha ON items(sha) WHERE saved=1")
        parents = {
            json.loads(row[0]).get("parent_id")
            for row in self.db.execute("SELECT metadata FROM items WHERE saved=1")
        }
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        for ident, metadata in self.db.execute(
            "SELECT id,metadata FROM items WHERE saved=0"
        ).fetchall():
            if ident not in parents and json.loads(metadata).get("created_at", "") < cutoff:
                self.db.execute("DELETE FROM items WHERE id=?", (ident,))
                if re.fullmatch(r"[0-9a-f]{32}", ident):
                    (self.files / ident).unlink(missing_ok=True)
        self.db.commit()

    def close(self):
        with self.lock:
            self.db.close()

    def _model(self):
        return str(
            getattr(
                self.encoder,
                "model_id",
                getattr(self.encoder, "__qualname__", type(self.encoder).__name__),
            )
        )

    def _public(self, row):
        item = json.loads(row[2])
        item.update(id=row[0], sha256=row[1], saved=bool(row[3]), media_url="/api/media/" + row[0])
        return item

    def add_candidate(self, data: bytes, metadata: dict) -> dict:
        allowed = (
            "title",
            "source_url",
            "provider",
            "format",
            "width",
            "height",
            "frames",
            "animated",
            "editable",
            "parent_id",
            "caption",
            "query",
            "tags",
        )
        meta = {k: metadata[k] for k in allowed if k in metadata}
        meta.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        ident = uuid.uuid4().hex
        digest = hashlib.sha256(data).hexdigest()
        with self.lock:
            path = self.files / ident
            try:
                with path.open("xb") as output:
                    output.write(data)
                self.db.execute(
                    "INSERT INTO items(id,sha,metadata) VALUES(?,?,?)",
                    (ident, digest, json.dumps(meta, ensure_ascii=False)),
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                path.unlink(missing_ok=True)
                raise
        return self.get(ident)

    def get(self, ident: str) -> dict:
        with self.lock:
            row = self.db.execute(
                "SELECT id,sha,metadata,saved FROM items WHERE id=?", (ident,)
            ).fetchone()
            if row is None:
                raise KeyError(ident)
            return self._public(row)

    def media_path(self, ident: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", ident):
            raise KeyError(ident)
        self.get(ident)
        return self.files / ident

    def _encode(self, image):
        vector = np.asarray(
            self.encoder(ImageOps.exif_transpose(image).convert("RGB")), dtype=np.float32
        ).reshape(-1)
        norm = np.linalg.norm(vector)
        if not vector.size or not np.isfinite(vector).all() or not np.isfinite(norm) or norm == 0:
            raise ValueError("Encoder returned an invalid image vector")
        return vector / norm

    def save(self, ident: str, title: str | None = None):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                return self._save_locked(ident, title)
            except Exception:
                self.db.rollback()
                raise

    def _save_locked(self, ident, title):
        item = self.get(ident)
        existing = self.db.execute(
            "SELECT id FROM items WHERE sha=? AND saved=1 ORDER BY rowid LIMIT 1", (item["sha256"],)
        ).fetchone()
        if existing:
            self.db.commit()
            return self.get(existing[0]), True
        with Image.open(self.media_path(ident)) as image:
            image.seek(0)
            vector = self._encode(image)
        meta = json.loads(
            self.db.execute("SELECT metadata FROM items WHERE id=?", (ident,)).fetchone()[0]
        )
        if title is not None:
            meta["title"] = title
        model = self._model()
        self.db.execute(
            "UPDATE items SET metadata=?, saved=1, vector=?, dim=?, model=? WHERE id=?",
            (
                json.dumps(meta, ensure_ascii=False),
                vector.tobytes(),
                vector.size,
                str(model),
                ident,
            ),
        )
        self.db.commit()
        return self.get(ident), False

    def list_saved(self):
        with self.lock:
            return [
                self._public(row)
                for row in self.db.execute(
                    "SELECT id,sha,metadata,saved FROM items WHERE saved=1 ORDER BY rowid DESC"
                ).fetchall()
            ]

    def search(self, query: str = "", image=None, limit: int = 8):
        with self.lock:
            vector = self._encode(image) if image is not None else None
            rows = self.db.execute(
                "SELECT id,sha,metadata,saved,vector,dim,model FROM items "
                "WHERE saved=1 ORDER BY rowid DESC"
            ).fetchall()
            results = []
            terms = query.casefold().split()
            for row in rows:
                item = self._public(row)
                if vector is not None:
                    if row[6] != self._model():
                        continue
                    stored = np.frombuffer(row[4], dtype=np.float32)
                    if stored.size != vector.size:
                        continue
                    score = float(np.dot(vector, stored))
                else:
                    haystack = json.dumps(
                        {k: item.get(k, "") for k in ("title", "query", "tags", "caption")},
                        ensure_ascii=False,
                    ).casefold()
                    score = sum(haystack.count(term) for term in terms)
                    if terms and not score:
                        continue
                item["score"] = score
                results.append(item)
            return sorted(results, key=lambda x: x["score"], reverse=True)[: max(0, limit)]
